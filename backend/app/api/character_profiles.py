from __future__ import annotations

from pathlib import Path
import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import save_config, settings
from app.db.session import get_db
from app.models.character import Message
from app.character.profiles import (
    _safe_profile_id,
    active_profile,
    apply_profile_to_config,
    ensure_profile_migration,
    list_profiles,
    load_trait_library,
    profile_path,
    profile_public,
    profiles_dir,
    read_profile,
    write_profile,
    add_trait_to_library,
)
from app.schemas.character_profile import (
    CharacterProfileBase,
    CharacterProfileCreate,
    CharacterProfilePublic,
    CharacterProfileUpdate,
    CharacterTraitLibrary,
    TraitOption,
)

router = APIRouter()

_PICTURE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _picture_dir() -> Path:
    path = profiles_dir(settings) / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_profile_pictures(profile_id: str) -> None:
    safe_id = _safe_profile_id(profile_id)
    # Versioned snapshots are intentionally retained: old chat messages point
    # at them so changing or deleting a profile does not break its history.
    for path in _picture_dir().glob(f"{safe_id}.*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def _ensure_migration() -> None:
    ensure_profile_migration(settings)


def _merge_profile_update(
    current: CharacterProfileBase,
    update_data: dict[str, object],
) -> CharacterProfileBase:
    """Merge and validate a partial profile update, including nested fields."""

    update_data = dict(update_data)
    appearance_update = update_data.get("appearance")
    if isinstance(appearance_update, dict):
        merged_appearance = current.appearance.model_dump()
        merged_appearance.update(appearance_update)
        update_data["appearance"] = merged_appearance
    merged_data = current.model_dump()
    merged_data.update(update_data)
    return CharacterProfileBase.model_validate(merged_data)


async def _update_character_message_names(
    db: AsyncSession,
    profile_id: str,
    character_name: str,
) -> int:
    """Update the persona label stored on historical assistant messages.

    Message identity is keyed by ``character_profile_id`` rather than the
    display name.  That means renaming one profile cannot accidentally rename
    messages produced by another profile with a similar name.  We copy the
    JSON metadata before assigning it so SQLAlchemy's JSON column reliably
    detects the change on SQLite as well as other supported databases.
    """

    result = await db.execute(select(Message))
    changed = 0
    for message in result.scalars().all():
        metadata = message.metadata_ if isinstance(message.metadata_, dict) else {}
        if metadata.get("character_profile_id") != profile_id:
            continue
        if metadata.get("character_name") == character_name:
            continue
        updated_metadata = dict(metadata)
        updated_metadata["character_name"] = character_name
        message.metadata_ = updated_metadata
        changed += 1
    return changed


@router.get("/character-profiles", response_model=list[CharacterProfilePublic])
async def list_character_profiles() -> list[CharacterProfilePublic]:
    _ensure_migration()
    return [profile_public(profile_id, profile, settings) for profile_id, profile, _ in list_profiles(settings)]


@router.get("/character-profiles/{profile_id}", response_model=CharacterProfilePublic)
async def get_character_profile(profile_id: str) -> CharacterProfilePublic:
    _ensure_migration()
    try:
        profile = read_profile(profile_id, settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Character profile not found") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Markdown profile: {exc}") from exc
    return profile_public(_safe_profile_id(profile_id), profile, settings)


def _serve_picture(safe_id: str, picture_id: str | None = None) -> FileResponse:
    if picture_id is not None and (not picture_id.isalnum() or len(picture_id) > 32):
        raise HTTPException(status_code=404, detail="Character profile picture not found")
    for extension, media_type in _PICTURE_TYPES.items():
        filename = f"{safe_id}-{picture_id}{extension}" if picture_id else f"{safe_id}{extension}"
        path = _picture_dir() / filename
        if path.exists():
            return FileResponse(path, media_type=media_type)
    raise HTTPException(status_code=404, detail="Character profile picture not found")


@router.get("/character-profiles/{profile_id}/picture")
async def get_character_profile_picture(profile_id: str) -> FileResponse:
    """Serve a profile's current or legacy uploaded picture."""
    _ensure_migration()
    safe_id = _safe_profile_id(profile_id)
    try:
        profile = read_profile(safe_id, settings)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Character profile not found") from exc

    if not profile.profile_picture.startswith("/api/character-profiles/"):
        raise HTTPException(status_code=404, detail="This profile does not have an uploaded picture")
    return _serve_picture(safe_id)


@router.get("/character-profiles/{profile_id}/picture/{picture_id}")
async def get_versioned_character_profile_picture(profile_id: str, picture_id: str) -> FileResponse:
    """Serve an immutable picture snapshot referenced by an older message."""
    _ensure_migration()
    safe_id = _safe_profile_id(profile_id)
    return _serve_picture(safe_id, picture_id)


@router.post("/character-profiles", response_model=CharacterProfilePublic, status_code=201)
async def create_character_profile(req: CharacterProfileCreate) -> CharacterProfilePublic:
    _ensure_migration()
    profile_id = _safe_profile_id(req.id or req.name)
    if profile_path(profile_id, settings).exists():
        raise HTTPException(status_code=409, detail="A character profile with that ID already exists")
    profile = req.model_dump(exclude={"id"})
    from app.schemas.character_profile import CharacterProfileBase

    value = CharacterProfileBase.model_validate(profile)
    write_profile(profile_id, value, settings)
    return profile_public(profile_id, value, settings)


@router.put("/character-profiles/{profile_id}", response_model=CharacterProfilePublic)
async def update_character_profile(
    profile_id: str,
    req: CharacterProfileUpdate,
    db: AsyncSession = Depends(get_db),
) -> CharacterProfilePublic:
    _ensure_migration()
    safe_id = _safe_profile_id(profile_id)
    try:
        current = read_profile(safe_id, settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Character profile not found") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Markdown profile: {exc}") from exc

    update_data = req.model_dump(exclude_none=True)
    if update_data.get("profile_picture") == "" and current.profile_picture.startswith("/api/character-profiles/"):
        _remove_profile_pictures(safe_id)
    # model_copy(update=...) intentionally skips validation. That leaves
    # nested appearance payloads as plain dictionaries, and applying the
    # profile then fails when it accesses profile.appearance.height.
    # Merge through the full profile schema so nested fields are reconstructed
    # as AppearanceProfile and malformed edits return a useful 422.
    try:
        updated = _merge_profile_update(current, update_data)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid character profile data: {exc}") from exc
    write_profile(safe_id, updated, settings)
    if current.name != updated.name:
        # Keep historical chat labels in sync with a renamed persona.  This
        # runs for both the active profile and profiles renamed from the
        # profile selector, while leaving other characters' histories intact.
        await _update_character_message_names(db, safe_id, updated.name)
    if settings.character.profile_id == safe_id:
        apply_profile_to_config(updated, settings, safe_id)
        save_config(settings)
    return profile_public(safe_id, updated, settings)


@router.post("/character-profiles/{profile_id}/picture", response_model=CharacterProfilePublic)
async def upload_character_profile_picture(
    profile_id: str,
    file: UploadFile = File(...),
) -> CharacterProfilePublic:
    """Store a small profile image beside the Markdown profile."""
    _ensure_migration()
    safe_id = _safe_profile_id(profile_id)
    try:
        current = read_profile(safe_id, settings)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Character profile not found") from exc

    extension = Path(file.filename or "").suffix.lower()
    if extension not in _PICTURE_TYPES:
        raise HTTPException(status_code=415, detail="Use a PNG, JPG, WEBP, or GIF image")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Profile pictures must be 5 MB or smaller")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded picture is empty")

    picture_id = str(int(time.time() * 1000))
    target = _picture_dir() / f"{safe_id}-{picture_id}{extension}"
    target.write_bytes(content)
    # Versioned URLs keep old chat messages tied to the image they saw.
    picture_url = f"/api/character-profiles/{safe_id}/picture/{picture_id}"
    updated = current.model_copy(update={"profile_picture": picture_url})
    write_profile(safe_id, updated, settings)
    if settings.character.profile_id == safe_id:
        apply_profile_to_config(updated, settings, safe_id)
        save_config(settings)
    return profile_public(safe_id, updated, settings)


@router.delete("/character-profiles/{profile_id}")
async def delete_character_profile(profile_id: str) -> dict[str, bool]:
    _ensure_migration()
    safe_id = _safe_profile_id(profile_id)
    if settings.character.profile_id == safe_id:
        raise HTTPException(status_code=409, detail="Apply another profile before deleting the active profile")
    path = profile_path(safe_id, settings)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Character profile not found")
    path.unlink()
    _remove_profile_pictures(safe_id)
    return {"ok": True}


@router.post("/character-profiles/{profile_id}/apply", response_model=CharacterProfilePublic)
async def apply_character_profile(profile_id: str) -> CharacterProfilePublic:
    _ensure_migration()
    safe_id = _safe_profile_id(profile_id)
    try:
        profile = read_profile(safe_id, settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Character profile not found") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid Markdown profile: {exc}") from exc
    apply_profile_to_config(profile, settings, safe_id)
    save_config(settings)
    return profile_public(safe_id, profile, settings)


@router.get("/character-trait-library", response_model=CharacterTraitLibrary)
async def get_character_trait_library(query: str = Query(default="", max_length=120)) -> CharacterTraitLibrary:
    _ensure_migration()
    return load_trait_library(settings, query=query.strip())


@router.post("/character-trait-library", response_model=CharacterTraitLibrary)
async def add_character_trait(option: TraitOption) -> CharacterTraitLibrary:
    _ensure_migration()
    category = "dere" if option.category.lower() == "dere" else "personality"
    return add_trait_to_library(option, category, settings)
