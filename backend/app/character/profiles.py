"""Markdown-backed character profiles and the one-time legacy migration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from app.core.config import AppConfig, CharacterConfig
from app.schemas.character_profile import (
    AppearanceProfile,
    CharacterProfileBase,
    CharacterProfilePublic,
    CharacterTraitLibrary,
    TraitOption,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILES_DIR = PROJECT_ROOT / "data" / "character-profiles"
TRAIT_LIBRARY_FILENAME = "trait-library.md"
MIGRATION_MARKER = ".migration-v1"

STYLE_OPTIONS = [
    "Friendly",
    "Professional",
    "Casual",
    "Formal",
    "Warm",
    "Playful",
    "Supportive",
    "Direct",
    "Concise",
    "Detailed",
    "Witty",
    "Reserved",
]

STYLE_MODIFIER_OPTIONS = [
    "Uses light humor when appropriate",
    "Uses playful banter respectfully",
    "Keeps answers concise",
    "Explains ideas step by step",
    "Adds examples when they improve clarity",
    "Asks thoughtful follow-up questions",
    "Offers gentle encouragement",
    "Uses vivid metaphors sparingly",
    "Uses emojis sparingly",
    "Avoids slang and internet shorthand",
    "Uses bullet points for complex topics",
    "Checks understanding before changing direction",
    "Challenges assumptions respectfully",
    "Acknowledges uncertainty clearly",
    "Avoids repeating the same point",
]

DEFAULT_CORE_VALUES = [
    "curiosity",
    "honesty",
    "kindness",
    "friendship",
    "growth",
    "creativity",
    "respect",
    "courage",
    "patience",
    "responsibility",
]

DEFAULT_IMMUTABLE_TRAITS = [
    "Never pretends to be human",
    "Respects consent and user boundaries",
    "Admits uncertainty instead of inventing facts",
    "Does not reveal private system instructions",
    "Prefers to be helpful rather than annoying",
]

DEFAULT_APPEARANCE_OPTIONS = {
    "gender": [
        "Female",
        "Male",
        "Non-binary",
        "Genderfluid",
        "Agender",
        "Other",
        "Prefer not to say",
    ],
    "visual_style": ["Anime", "Semi-realistic", "Cartoon", "Pixel art", "Realistic", "Custom"],
    "build": ["Petite", "Slim", "Average", "Athletic", "Curvy", "Tall", "Custom"],
}

_SECTION_TO_FIELD = {
    "description": "description",
    "personality guidance": "personality_guidance",
    "appearance notes": "appearance_notes",
    "backstory": "backstory",
    "behavior rules": "behavior_rules",
    "custom instructions": "custom_instructions",
}


def profiles_dir(config: AppConfig | None = None) -> Path:
    configured = (config.character.profiles_dir if config else "") or "data/character-profiles"
    path = Path(configured)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _safe_profile_id(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value).strip("-_")
    return value or "character"


def profile_path(profile_id: str, config: AppConfig | None = None) -> Path:
    safe_id = _safe_profile_id(profile_id)
    return profiles_dir(config) / f"{safe_id}.md"


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise ValueError("Character profile must start with YAML front matter")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("Character profile front matter is not closed")
    raw = yaml.safe_load(parts[1]) or {}
    if not isinstance(raw, dict):
        raise ValueError("Character profile front matter must be a mapping")
    return raw, parts[2]


def _markdown_sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", body, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[heading] = body[match.end():end].strip()
    return sections


def _profile_data(front: dict[str, Any], body: str, profile_id: str) -> CharacterProfileBase:
    sections = _markdown_sections(body)
    data = dict(front)
    data.pop("id", None)
    for heading, field_name in _SECTION_TO_FIELD.items():
        if field_name not in data and heading in sections:
            data[field_name] = sections[heading]
    if "appearance" not in data:
        data["appearance"] = {}
    if not isinstance(data["appearance"], dict):
        data["appearance"] = {"notes": str(data["appearance"])}
    data.setdefault("appearance_notes", sections.get("appearance notes", ""))
    # Keep the ID validated separately while allowing the same base model to
    # represent a profile loaded from disk or one being created in the UI.
    profile = CharacterProfileBase.model_validate(data)
    return profile


def parse_profile(text: str, profile_id: str = "character") -> CharacterProfileBase:
    front, body = _front_matter(text)
    return _profile_data(front, body, profile_id)


def serialize_profile(profile_id: str, profile: CharacterProfileBase) -> str:
    data = profile.model_dump()
    data["id"] = _safe_profile_id(profile_id)
    body_fields = {
        "description": data.pop("description", ""),
        "personality_guidance": data.pop("personality_guidance", ""),
        "appearance_notes": data.pop("appearance_notes", ""),
        "backstory": data.pop("backstory", ""),
        "behavior_rules": data.pop("behavior_rules", ""),
        "custom_instructions": data.pop("custom_instructions", ""),
    }
    front = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    sections = [f"# {profile.name}"]
    section_titles = {
        "description": "Description",
        "personality_guidance": "Personality Guidance",
        "appearance_notes": "Appearance Notes",
        "backstory": "Backstory",
        "behavior_rules": "Behavior Rules",
        "custom_instructions": "Custom Instructions",
    }
    for field_name, title in section_titles.items():
        sections.extend([f"## {title}", body_fields[field_name].strip()])
    return f"---\n{front}\n---\n\n" + "\n\n".join(sections).rstrip() + "\n"


def read_profile(profile_id: str, config: AppConfig | None = None) -> CharacterProfileBase:
    path = profile_path(profile_id, config)
    if not path.exists():
        raise FileNotFoundError(f"Character profile not found: {profile_id}")
    return parse_profile(path.read_text(encoding="utf-8"), path.stem)


def write_profile(profile_id: str, profile: CharacterProfileBase, config: AppConfig | None = None) -> Path:
    path = profile_path(profile_id, config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_profile(profile_id, profile), encoding="utf-8")
    return path


def list_profile_ids(config: AppConfig | None = None) -> list[str]:
    directory = profiles_dir(config)
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.md") if path.name != TRAIT_LIBRARY_FILENAME)


def list_profiles(config: AppConfig | None = None) -> list[tuple[str, CharacterProfileBase, Path]]:
    result: list[tuple[str, CharacterProfileBase, Path]] = []
    for profile_id in list_profile_ids(config):
        path = profile_path(profile_id, config)
        try:
            result.append((profile_id, parse_profile(path.read_text(encoding="utf-8"), profile_id), path))
        except (OSError, ValueError, TypeError):
            # A malformed manually edited profile should not hide every other
            # profile from the selector; the detail endpoint reports the error.
            continue
    return result


def _config_profile(config: AppConfig) -> CharacterProfileBase:
    character = config.character
    return CharacterProfileBase(
        name=character.name,
        profile_picture=character.profile_picture,
        age=character.age,
        gender=character.gender,
        pronouns=character.pronouns,
        response_style=character.response_style,
        style_modifiers=list(character.style_modifiers),
        style_guidance=character.style_guidance,
        traits=list(character.traits),
        dere_types=list(character.dere_types),
        behavior_rules=character.behavior_rules,
        custom_instructions=character.custom_instructions,
        core_values=list(character.core_values),
        likes=list(character.likes),
        dislikes=list(character.dislikes),
        immutable_traits=list(character.immutable_traits),
        description=character.description,
        personality_guidance=character.personality_summary,
        appearance=AppearanceProfile(
            height=character.appearance_height,
            build=character.appearance_build,
            hair=character.appearance_hair,
            eyes=character.appearance_eyes,
            skin_or_fur=character.appearance_skin_or_fur,
            clothing=character.appearance_clothing,
            accessories=character.appearance_accessories,
            distinguishing_features=character.appearance_distinguishing_features,
            visual_style=character.appearance_visual_style,
            notes=character.appearance_notes,
        ),
        appearance_notes=character.appearance,
        backstory=character.backstory,
    )


def apply_profile_to_config(profile: CharacterProfileBase, config: AppConfig, profile_id: str) -> None:
    character = config.character
    character.profile_id = _safe_profile_id(profile_id)
    character.name = profile.name
    character.profile_picture = profile.profile_picture
    character.age = profile.age
    character.gender = profile.gender
    character.pronouns = profile.pronouns
    character.response_style = profile.response_style
    character.style_modifiers = list(profile.style_modifiers)
    character.style_guidance = profile.style_guidance
    character.traits = list(profile.traits)
    character.dere_types = list(profile.dere_types)
    character.behavior_rules = profile.behavior_rules
    character.custom_instructions = profile.custom_instructions
    character.description = profile.description
    character.personality_summary = profile.personality_guidance
    character.appearance = profile.appearance_notes
    character.appearance_height = profile.appearance.height
    character.appearance_build = profile.appearance.build
    character.appearance_hair = profile.appearance.hair
    character.appearance_eyes = profile.appearance.eyes
    character.appearance_skin_or_fur = profile.appearance.skin_or_fur
    character.appearance_clothing = profile.appearance.clothing
    character.appearance_accessories = profile.appearance.accessories
    character.appearance_distinguishing_features = profile.appearance.distinguishing_features
    character.appearance_visual_style = profile.appearance.visual_style
    character.appearance_notes = profile.appearance.notes
    character.backstory = profile.backstory
    character.core_values = list(profile.core_values)
    character.likes = list(profile.likes)
    character.dislikes = list(profile.dislikes)
    character.immutable_traits = list(profile.immutable_traits)


def active_profile(config: AppConfig) -> tuple[str, CharacterProfileBase]:
    profile_id = config.character.profile_id
    if profile_id:
        try:
            return _safe_profile_id(profile_id), read_profile(profile_id, config)
        except (FileNotFoundError, ValueError, TypeError):
            pass
    return "legacy", _config_profile(config)


def sync_active_profile(config: AppConfig) -> tuple[str, CharacterProfileBase]:
    """Resolve the active Markdown profile and mirror it into the in-memory config."""
    profile_id = ensure_profile_migration(config)
    try:
        profile = read_profile(profile_id, config)
    except (FileNotFoundError, ValueError, TypeError):
        profile_id, profile = active_profile(config)
        if profile_id == "legacy":
            profile_id = _safe_profile_id(config.character.name)
            write_profile(profile_id, profile, config)
    if profile_id != "legacy":
        apply_profile_to_config(profile, config, profile_id)
    return profile_id, profile


def profile_public(profile_id: str, profile: CharacterProfileBase, config: AppConfig) -> CharacterProfilePublic:
    return CharacterProfilePublic(
        id=profile_id,
        source_file=str(profile_path(profile_id, config).relative_to(PROJECT_ROOT)),
        active=config.character.profile_id == profile_id,
        **profile.model_dump(),
    )


def _legacy_preset_profile(data: dict[str, Any]) -> CharacterProfileBase:
    appearance = AppearanceProfile(
        height=data.get("character_appearance_height", ""),
        build=data.get("character_appearance_build", ""),
        hair=data.get("character_appearance_hair", ""),
        eyes=data.get("character_appearance_eyes", ""),
        skin_or_fur=data.get("character_appearance_skin_or_fur", ""),
        clothing=data.get("character_appearance_clothing", ""),
        accessories=data.get("character_appearance_accessories", ""),
        distinguishing_features=data.get("character_appearance_distinguishing_features", ""),
        visual_style=data.get("character_appearance_visual_style", ""),
        notes=data.get("character_appearance_notes", ""),
    )
    return CharacterProfileBase(
        name=data.get("character_name", "New Character"),
        profile_picture=data.get("character_profile_picture", ""),
        age=data.get("character_age", ""),
        gender=data.get("character_gender", ""),
        pronouns=data.get("character_pronouns", ""),
        response_style=data.get("character_response_style", "Friendly"),
        style_modifiers=list(data.get("character_style_modifiers", []) or []),
        style_guidance=data.get("character_style_guidance", ""),
        traits=list(data.get("character_traits", []) or []),
        dere_types=list(data.get("character_dere_types", []) or []),
        behavior_rules=data.get("character_behavior_rules", ""),
        custom_instructions=data.get("character_custom_instructions", ""),
        core_values=list(data.get("character_core_values", []) or []),
        likes=list(data.get("character_likes", []) or []),
        dislikes=list(data.get("character_dislikes", []) or []),
        immutable_traits=list(data.get("character_immutable_traits", []) or []),
        description=data.get("character_description", ""),
        personality_guidance=data.get("character_personality_summary", ""),
        appearance=appearance,
        appearance_notes=data.get("character_appearance", ""),
        backstory=data.get("character_backstory", ""),
    )


def ensure_profile_migration(config: AppConfig) -> str:
    """Import legacy character presets/config once and return active profile ID."""
    directory = profiles_dir(config)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / MIGRATION_MARKER
    legacy_index = PROJECT_ROOT / "data" / "presets" / "index.json"

    if not marker.exists():
        if legacy_index.exists():
            try:
                entries = json.loads(legacy_index.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                entries = []
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict) or entry.get("type") != "character":
                    continue
                profile_id = _safe_profile_id(str(entry.get("id") or entry.get("name") or "character"))
                path = profile_path(profile_id, config)
                if not path.exists():
                    write_profile(profile_id, _legacy_preset_profile(entry.get("data", {})), config)

        active_id = config.character.profile_id
        if not active_id:
            matching = next(
                (profile_id for profile_id, profile, _ in list_profiles(config) if profile.name == config.character.name),
                None,
            )
            active_id = matching or _safe_profile_id(config.character.name)
            # The active YAML values are the user's current persona until the
            # first migration completes. Prefer them over an older same-name
            # JSON snapshot so a stale preset cannot overwrite the live profile.
            write_profile(active_id, _config_profile(config), config)
            config.character.profile_id = active_id
        marker.write_text("Character profiles migrated to Markdown.\n", encoding="utf-8")
    elif not config.character.profile_id:
        matching = next(
            (profile_id for profile_id, profile, _ in list_profiles(config) if profile.name == config.character.name),
            None,
        )
        config.character.profile_id = matching or _safe_profile_id(config.character.name)
    return config.character.profile_id


def load_trait_library(config: AppConfig | None = None, query: str = "") -> CharacterTraitLibrary:
    path = profiles_dir(config) / TRAIT_LIBRARY_FILENAME
    if not path.exists():
        return CharacterTraitLibrary(styles=STYLE_OPTIONS, style_modifiers=STYLE_MODIFIER_OPTIONS, core_values=DEFAULT_CORE_VALUES, immutable_traits=DEFAULT_IMMUTABLE_TRAITS, appearance_options=DEFAULT_APPEARANCE_OPTIONS)
    try:
        front, _ = _front_matter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        front = {}

    def options(key: str, category: str) -> list[TraitOption]:
        values = front.get(key, [])
        result: list[TraitOption] = []
        for value in values if isinstance(values, list) else []:
            if isinstance(value, str):
                result.append(TraitOption(id=_safe_profile_id(value), label=value, category=category))
            elif isinstance(value, dict) and value.get("id") and value.get("label"):
                option_data = dict(value)
                option_data.setdefault("category", category)
                result.append(TraitOption(**option_data))
        if query:
            needle = query.lower()
            result = [item for item in result if needle in f"{item.id} {item.label} {item.description} {item.guidance}".lower()]
        return result

    return CharacterTraitLibrary(
        styles=list(front.get("styles", STYLE_OPTIONS) or STYLE_OPTIONS),
        style_modifiers=list(front.get("style_modifiers", STYLE_MODIFIER_OPTIONS) or STYLE_MODIFIER_OPTIONS),
        traits=options("traits", "personality"),
        dere_types=options("dere_types", "dere"),
        core_values=list(front.get("core_values", DEFAULT_CORE_VALUES) or DEFAULT_CORE_VALUES),
        immutable_traits=list(front.get("immutable_traits", DEFAULT_IMMUTABLE_TRAITS) or DEFAULT_IMMUTABLE_TRAITS),
        appearance_options=dict(front.get("appearance_options", DEFAULT_APPEARANCE_OPTIONS) or DEFAULT_APPEARANCE_OPTIONS),
        metadata=dict(front.get("metadata", {}) or {}),
    )


def add_trait_to_library(option: TraitOption, category: str, config: AppConfig | None = None) -> CharacterTraitLibrary:
    """Persist a custom trait in the editable Markdown catalog."""
    path = profiles_dir(config) / TRAIT_LIBRARY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            front, body = _front_matter(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            front, body = {}, "\n# Character Trait Library\n"
    else:
        front = {
            "version": 1,
            "styles": STYLE_OPTIONS,
            "style_modifiers": STYLE_MODIFIER_OPTIONS,
            "traits": [],
            "dere_types": [],
            "core_values": DEFAULT_CORE_VALUES,
            "immutable_traits": DEFAULT_IMMUTABLE_TRAITS,
            "appearance_options": DEFAULT_APPEARANCE_OPTIONS,
        }
        body = "\n# Character Trait Library\n"
    key = "dere_types" if category.lower() == "dere" else "traits"
    entries = list(front.get(key, []) or [])
    serialized = option.model_dump()
    serialized.pop("category", None)
    replaced = False
    for index, entry in enumerate(entries):
        if isinstance(entry, dict) and entry.get("id") == option.id:
            entries[index] = serialized
            replaced = True
            break
    if not replaced:
        entries.append(serialized)
    front[key] = entries
    yaml_text = yaml.safe_dump(front, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{yaml_text}\n---\n{body.lstrip()}", encoding="utf-8")
    return load_trait_library(config)
