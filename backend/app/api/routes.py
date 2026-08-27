from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import random
import re
import shutil
import tempfile
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import edge_tts
import httpx
from faster_whisper import WhisperModel
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.integrations import router as integrations_router
from app.api.character_profiles import _update_character_message_names
from app.avatar.actions import choose_avatar_action
from app.character.prompt import build_messages
from app.character.profiles import (
    _legacy_preset_profile,
    _safe_profile_id,
    apply_profile_to_config,
    read_profile,
    sync_active_profile,
    write_profile,
)
from app.character.service import load_character_state
from app.core.config import save_config, settings
from app.db.session import get_db
from app.integrations.spotify import (
    SpotifyError,
    spotify_controller,
)
from app.llm.base import ChatMessage, LLMResponse
from app.llm.models import (
    accept_license as accept_llm_model_license,
    catalog_model as llm_catalog_model,
    download_status as llm_download_status,
    license_accepted as llm_license_accepted,
    list_models as list_local_llm_models,
    start_download as start_llm_download,
)
from app.llm.openai_compatible import create_llm_provider
from app.tools import create_tool_registry, route_tool_request, run_tool_conversation
from app.tools.discord import parse_discord_voice_command
from app.stt_runtime import (
    NEMO_MODELS,
    SIDECAR_URL,
    accept_license,
    license_accepted,
    model_status,
    nemo_model,
    nemo_model_path,
    nemo_download_status,
    nemo_install_status,
    nemo_sidecar,
    start_nemo_download,
)
from app.models.character import (
    Conversation,
    EmotionalState,
    Goal,
    Memory,
    Message,
    Skill,
)
from app.memory.context import VoiceContextPack, assemble_voice_context
from app.schemas.chat import (
    CharacterPublic,
    ChatRequest,
    ChatResponse,
    ConversationPublic,
    GoalCreate,
    GoalPublic,
    MemoryCreate,
    MemoryPublic,
    MessagePublic,
    FishAudioKeyUpdate,
    OpenRouterKeyUpdate,
    ProactiveChatRequest,
    SettingsResponse,
    SettingsUpdate,
    SkillCreate,
    SkillPublic,
    SkillUpdate,
    StatusResponse,
    TTSRequest,
    WSMessage,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Master presets selected on chat channels are request-scoped. The settings
# object is shared by the existing engine factories, so serialize scoped
# requests while temporarily overlaying a resolved bundle and restore the
# exact global draft afterwards. This keeps channel presets isolated from the
# settings editor and avoids two channels racing their engine selection.
_channel_runtime_lock = asyncio.Lock()
_channel_runtime_active: ContextVar[bool] = ContextVar("channel_runtime_active", default=False)

# Reference recordings are project assets, not pointers to arbitrary files in
# a user's Downloads folder.  Keeping one canonical directory means a cloned
# voice remains usable after the original sample is moved or deleted.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
VOICE_REFERENCE_DIR = PROJECT_ROOT / "tools" / "zonos" / "reference_voices"
VOICE_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _openrouter_env_file() -> Path:
    """Return the project backend .env file used by the Windows launcher."""

    return PROJECT_ROOT / "backend" / ".env"


def _persist_openrouter_api_key(env_name: str, api_key: str) -> None:
    """Persist an OpenRouter key without ever putting it in YAML or presets."""

    name = (env_name or "OPENROUTER_API_KEY").strip()
    value = (api_key or "").strip()
    if not ENV_NAME_PATTERN.fullmatch(name):
        raise HTTPException(status_code=422, detail="API key environment name is invalid")
    if not value:
        raise HTTPException(status_code=422, detail="API key cannot be empty")
    if any(char in value for char in "\r\n"):
        raise HTTPException(status_code=422, detail="API key contains an invalid newline")

    env_path = _openrouter_env_file()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = existing.splitlines(keepends=True)
    assignment = f"{name}={value}\n"
    key_pattern = re.compile(rf"^\s*{re.escape(name)}\s*=")
    replaced = False
    output: list[str] = []
    for line in lines:
        if key_pattern.match(line):
            if not replaced:
                output.append(assignment)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and not output[-1].endswith(("\n", "\r")):
            output.append("\n")
        output.append(assignment)
    env_path.write_text("".join(output), encoding="utf-8")
    # Make the key available immediately for model search and TTS requests;
    # a restart is still needed by other processes, as with all .env edits.
    os.environ[name] = value


@dataclass(frozen=True)
class GeneratedAudio:
    """Engine output before it is wrapped for HTTP or desktop playback."""

    data: bytes
    media_type: str
    filename: str


def _resolve_reference_file(reference: str) -> Path | None:
    """Resolve a reference path from either the project or current process."""

    raw = str(reference or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    candidates = [candidate] if candidate.is_absolute() else [PROJECT_ROOT / candidate, Path.cwd() / candidate]
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.is_file():
            return resolved
    return None


def _is_project_voice_file(path: Path) -> bool:
    try:
        path.resolve().relative_to(VOICE_REFERENCE_DIR.resolve())
        return True
    except ValueError:
        return False


def _safe_voice_filename(filename: str) -> tuple[str, str]:
    source = Path(filename or "uploaded_voice.wav")
    extension = source.suffix.lower()
    if extension not in VOICE_AUDIO_EXTENSIONS:
        extension = ".wav"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", source.stem).strip("._") or "uploaded_voice"
    return stem, extension


def _store_voice_bytes(filename: str, content: bytes) -> Path:
    """Store uploaded reference bytes durably and avoid replacing old voices."""

    VOICE_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    stem, extension = _safe_voice_filename(filename)
    target = VOICE_REFERENCE_DIR / f"{stem}{extension}"
    if target.exists():
        existing = target.read_bytes()
        if existing == content:
            return target.resolve()
        digest = hashlib.sha256(content).hexdigest()[:10]
        target = VOICE_REFERENCE_DIR / f"{stem}_{digest}{extension}"
    target.write_bytes(content)
    return target.resolve()


def _ensure_project_voice_reference(reference: str | None) -> str | None:
    """Copy an external reference recording into the project and return it."""

    # Keep an explicitly empty field empty. This matters for presets that use
    # the engine's built-in/default voice and avoids changing their JSON shape
    # from ``""`` to ``null`` during a save or apply operation.
    if reference is None:
        return None
    if not str(reference).strip():
        return reference
    resolved = _resolve_reference_file(reference)
    if resolved is None:
        # Built-in Edge voice IDs and legacy missing paths are identifiers, not
        # files we can copy. Preserve them so existing compatibility behavior
        # remains intact.
        return reference
    if _is_project_voice_file(resolved):
        return str(resolved)

    VOICE_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    stem, extension = _safe_voice_filename(resolved.name)
    target = VOICE_REFERENCE_DIR / f"{stem}{extension}"
    if target.exists():
        try:
            if target.stat().st_size == resolved.stat().st_size and hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(resolved.read_bytes()).digest():
                return str(target.resolve())
        except OSError:
            pass
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()[:10]
        target = VOICE_REFERENCE_DIR / f"{stem}_{digest}{extension}"
    if not target.exists():
        shutil.copy2(resolved, target)
    return str(target.resolve())


def _adopt_project_voice_reference(reference: str | None) -> str | None:
    """Normalize a voice reference and persist the durable path when needed."""

    normalized = _ensure_project_voice_reference(reference)
    if normalized and normalized != reference:
        settings.tts.voice_ref = normalized
        if not _channel_runtime_active.get():
            try:
                save_config(settings)
            except OSError as exc:
                # The copied asset is still safe even if config persistence is
                # temporarily unavailable; the next settings read retries it.
                logger.warning("Could not persist project voice reference path: %s", exc)
    return normalized

router.include_router(integrations_router)


# Local TTS engines run in their own processes.  Keep the selected engine in
# the API process so a model is released only when an actual TTS request uses a
# different engine (changing a setting alone does not interrupt active audio).
_tts_engine_lock = asyncio.Lock()
_last_tts_engine: str | None = None


async def _unload_tts_service(url: str, name: str) -> None:
    """Best-effort unload request; a stopped optional engine is not an error."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=0.8)) as client:
            response = await client.post(f"{url.rstrip('/')}/unload")
            if response.status_code >= 400:
                logger.warning("%s unload endpoint returned HTTP %s", name, response.status_code)
    except Exception as exc:
        logger.debug("%s is not available for unload: %s", name, exc)


async def _prepare_tts_engine(engine: str) -> None:
    """Unload non-selected local TTS models before generating new audio.

    This is intentionally called from the generation path rather than the
    settings endpoint.  Selecting a new engine does not evict a model until
    the user actually sends a message and TTS is requested.
    """
    global _last_tts_engine
    selected = (engine or "edge-tts").strip().lower()
    if selected not in {"zonos", "indextts", "edge-tts", "openrouter"}:
        selected = "edge-tts"

    async with _tts_engine_lock:
        # Always clear the other local engine.  This also cleans up a model
        # left behind by a previous backend process whose tracking state was
        # lost during a restart.
        targets: list[tuple[str, str]] = []
        if selected != "zonos":
            targets.append((settings.tts.zonos_url, "Zonos"))
        if selected != "indextts":
            targets.append((settings.tts.indextts_url, "Index-TTS"))
        if selected in {"edge-tts", "openrouter"}:
            # Cloud engines do not keep a local model resident.
            targets = [
                (settings.tts.zonos_url, "Zonos"),
                (settings.tts.indextts_url, "Index-TTS"),
            ]

        if _last_tts_engine != selected or _last_tts_engine is None:
            logger.info(
                "Selecting TTS engine %s%s; unloading non-selected local engines",
                selected,
                f" from {_last_tts_engine}" if _last_tts_engine else "",
            )
            await asyncio.gather(
                *(_unload_tts_service(url, name) for url, name in targets),
                return_exceptions=True,
            )
        _last_tts_engine = selected


def _character_message_metadata(state) -> dict[str, str]:
    """Snapshot the active persona on each assistant message.

    Conversations can continue after switching Markdown profiles. Keeping this
    small identity snapshot in message metadata lets the UI render old replies
    with the character that actually produced them.
    """
    return {
        "character_profile_id": state.profile_id,
        "character_name": state.name,
        "character_profile_picture": state.profile_picture,
    }

# Emotion keywords and the deltas they trigger
_EMOTION_KEYWORDS: dict[str, dict[str, float]] = {
    # --- Happiness / joy ---
    r"\bhapp(?:y|ier|ily)\b":              {"happiness": 0.05, "sadness": -0.03},
    r"\bjoy(?:ful|ous)?\b":                {"happiness": 0.05, "excitement": 0.03},
    r"\bfun\b":                            {"happiness": 0.03, "excitement": 0.03},
    r"\blove\b":                           {"happiness": 0.05, "sadness": -0.03},
    r"\bthank(?:s|ful|you)\b":             {"happiness": 0.03},
    r"\bgreat\b":                          {"happiness": 0.04, "excitement": 0.02},
    r"\bnice\b":                           {"happiness": 0.03},
    r"\bwonderful\b":                      {"happiness": 0.05, "excitement": 0.03},
    r"\bawesome\b":                        {"happiness": 0.04, "excitement": 0.04},
    r"\bperfect\b":                        {"happiness": 0.04, "confidence": 0.02},
    r"\bglad\b":                           {"happiness": 0.04},
    r"\bsmile\b":                          {"happiness": 0.03},
    r"\bcheer(?:ful|ful|s|ing)?\b":        {"happiness": 0.04, "excitement": 0.02},
    r"\bdelight(?:ed|ful)?\b":             {"happiness": 0.05},
    r"\bpleased\b":                        {"happiness": 0.04},
    r"\bthankful\b":                       {"happiness": 0.04},
    r"\bappreciate\b":                     {"happiness": 0.03},
    r"\bador(?:e|ing)\b":                  {"happiness": 0.05},
    r"\bmiss(?:ing)?\b":                   {"happiness": 0.02, "sadness": 0.03},

    # --- Excitement ---
    r"\bexcited\b":                        {"excitement": 0.05, "sadness": -0.03},
    r"\bamazing\b":                        {"excitement": 0.05, "happiness": 0.03},
    r"\bincredible\b":                     {"excitement": 0.04, "happiness": 0.03},
    r"\bwow\b":                            {"excitement": 0.04, "surprise": 0.03},
    r"\byes\b":                            {"excitement": 0.03, "happiness": 0.02},
    r"\bcan.?t wait\b":                    {"excitement": 0.05},
    r"\bl(?:ets|et'?s) go\b":             {"excitement": 0.05},
    r"\bhype\b":                           {"excitement": 0.05},

    # --- Sadness ---
    r"\bsad(?:ly)?\b":                     {"sadness": 0.05, "happiness": -0.03},
    r"\bsorry\b":                          {"sadness": 0.03, "frustration": 0.02},
    r"\bunfortunate(?:ly)?\b":             {"sadness": 0.04},
    r"\bsigh\b":                           {"sadness": 0.04},
    r"\bdepressed\b":                      {"sadness": 0.06, "happiness": -0.04},
    r"\bmiss(?:ing)?\b":                   {"sadness": 0.04, "happiness": -0.02},
    r"\btears?\b":                         {"sadness": 0.04},
    r"\bheartbroken\b":                    {"sadness": 0.06},
    r"\bgloomy\b":                         {"sadness": 0.04},
    r"\bmelanchol(?:y|ic)\b":              {"sadness": 0.05},
    r"\blonely\b":                         {"sadness": 0.05},
    r"\bwistful\b":                        {"sadness": 0.03},
    r"\bdisappoint(?:ed|ment)\b":          {"sadness": 0.04, "frustration": 0.02},

    # --- Anger ---
    r"\bangr(?:y|ier)\b":                  {"anger": 0.05, "happiness": -0.03},
    r"\bfurious\b":                        {"anger": 0.06},
    r"\bhate\b":                           {"anger": 0.05, "happiness": -0.04},
    r"\bmad\b":                            {"anger": 0.04},
    r"\bunacceptable\b":                   {"anger": 0.04},
    r"\brage\b":                           {"anger": 0.06},
    r"\boutraged\b":                       {"anger": 0.06},

    # --- Fear ---
    r"\bscare[dt]\b":                      {"fear": 0.05, "confidence": -0.03},
    r"\bafraid\b":                         {"fear": 0.05, "confidence": -0.03},
    r"\bworried?\b":                       {"fear": 0.04, "confidence": -0.03},
    r"\bterrified\b":                      {"fear": 0.06},
    r"\bnervous\b":                        {"fear": 0.04, "confidence": -0.02},
    r"\banxious\b":                        {"fear": 0.04, "confidence": -0.02},
    r"\bpanic\b":                          {"fear": 0.06},
    r"\bdread\b":                          {"fear": 0.05},

    # --- Curiosity ---
    r"\bcuriou(?:s|sly)\b":               {"curiosity": 0.05, "frustration": -0.02},
    r"\bwonder(?:ing|s)?\b":              {"curiosity": 0.04},
    r"\bhmm+\b":                           {"curiosity": 0.03},
    r"\bhuh\??\b":                         {"curiosity": 0.03},
    r"\bwhat if\b":                        {"curiosity": 0.04},
    r"\btell me\b":                        {"curiosity": 0.03},
    r"\bexplain\b":                        {"curiosity": 0.03},
    r"\bcurious\b":                        {"curiosity": 0.05},

    # --- Confidence ---
    r"\bconfiden(?:t|ce)\b":               {"confidence": 0.05, "fear": -0.03},
    r"\bdefinitely\b":                     {"confidence": 0.04},
    r"\babsolutely\b":                     {"confidence": 0.04},
    r"\bwill do\b":                        {"confidence": 0.03},
    r"\bgot this\b":                       {"confidence": 0.04},
    r"\bno problem\b":                     {"confidence": 0.03, "happiness": 0.02},
    r"\bsure\b":                           {"confidence": 0.02},

    # --- Frustration ---
    r"\bfrustrate[dt]\b":                  {"frustration": 0.05, "confidence": -0.03},
    r"\bannoy(?:ed|ing)\b":                {"frustration": 0.04, "happiness": -0.02},
    r"\bugh+\b":                           {"frustration": 0.05},
    r"\bargh\b":                           {"frustration": 0.05},
    r"\bwhy\b.*\b(?:can.?t|won.?t|doesn.?t|isn.?t)\b": {"frustration": 0.04},
    r"\bstupid\b":                         {"frustration": 0.05, "anger": 0.03},
    r"\buseless\b":                        {"frustration": 0.04, "anger": 0.02},
    r"\bnot working\b":                    {"frustration": 0.05},
    r"\bbroken\b":                         {"frustration": 0.04},
    r"\bimpossible\b":                     {"frustration": 0.05, "fear": 0.02},
    r"\bdisgust(?:ed|ing)?\b":             {"frustration": 0.04, "happiness": -0.03},
    r"\bgross\b":                          {"frustration": 0.03},
    r"\bhorrible\b":                       {"frustration": 0.04, "sadness": 0.02},
    r"\bterrible\b":                       {"frustration": 0.04, "sadness": 0.02},
}

# ============================================================================
# HIGH-INTENSITY expressive triggers — these produce STRONG visible reactions
# on Live2D (laughing face, crying face, etc.) and strong TTS emotion weights.
# Deltas are 3-5x larger than the subtle keywords above.
# ============================================================================
_EXPRESSIVE_TRIGGERS: list[tuple[str, str, dict[str, float]]] = [
    # (regex_pattern, emotion_label_for_live2d, zonos_deltas)
    # --- Laughter (happiness 0.7+) ---
    (r"\b(?:lmao|rofl|lol|lmfao)\b",                     "laughing",  {"happiness": 0.25, "excitement": 0.10, "sadness": -0.15}),
    (r"\bhaha+(?:ha)?\b",                                 "laughing",  {"happiness": 0.20, "excitement": 0.08, "sadness": -0.10}),
    (r"\bheh(?:e+h*)?\b",                                 "laughing",  {"happiness": 0.15, "excitement": 0.05}),
    (r"\b(?:ahah+|ahaha+)\b",                             "laughing",  {"happiness": 0.22, "excitement": 0.10, "sadness": -0.12}),
    (r"\bchuckle\b",                                      "laughing",  {"happiness": 0.12, "excitement": 0.03}),
    (r"\bgiggles?\b",                                     "laughing",  {"happiness": 0.15, "excitement": 0.05, "sadness": -0.08}),
    (r"\bsnicker(?:s|ing)?\b",                            "laughing",  {"happiness": 0.12, "excitement": 0.04}),
    (r"\bcackl(?:e|es|ing)\b",                            "laughing",  {"happiness": 0.18, "excitement": 0.08}),
    (r"\bha!\b",                                          "laughing",  {"happiness": 0.15, "excitement": 0.05}),

    # --- Crying / deep sadness (sadness 0.7+) ---
    (r"\b(?:cry|crying|cried)\b",                         "crying",    {"sadness": 0.25, "happiness": -0.15, "other": 0.05}),
    (r"\b(?:sob|sobbing|sobs)\b",                         "crying",    {"sadness": 0.30, "happiness": -0.15}),
    (r"\b(?:weep|weeping|weeps)\b",                       "crying",    {"sadness": 0.25, "happiness": -0.12}),
    (r"\btears?\b",                                       "sadness",   {"sadness": 0.15, "happiness": -0.08}),
    (r"\bheartbroken\b",                                  "crying",    {"sadness": 0.28, "happiness": -0.15}),
    (r"\bwailing\b",                                      "crying",    {"sadness": 0.25, "anger": 0.05}),
    (r"\b\\*sob\\*\b|\(\*sob\*\)",                        "crying",    {"sadness": 0.30, "happiness": -0.15}),
    (r"\b\\*cry\\*\b|\(\*cry\*\)",                        "crying",    {"sadness": 0.28, "happiness": -0.15}),

    # --- Shock / surprise (surprise 0.7+) ---
    (r"\b(?:omg|oh my god|oh my gosh)\b",                 "shocked",   {"surprise": 0.25, "fear": 0.08, "excitement": 0.05}),
    (r"\b(?:whaat|whaaat|wtaf|wtf)\b",                   "shocked",   {"surprise": 0.25, "anger": 0.05}),
    (r"\bno way\b",                                       "shocked",   {"surprise": 0.20, "happiness": 0.08}),
    (r"\b(?:yikes|eek)\b",                                "shocked",   {"surprise": 0.15, "fear": 0.10}),
    (r"\bunbelievable\b",                                 "shocked",   {"surprise": 0.22, "happiness": 0.05}),
    (r"\bwhat\?\?|\bwhat!\b",                             "shocked",   {"surprise": 0.20, "frustration": 0.05}),

    # --- Yelling / intense anger (anger 0.7+) ---
    (r"\b(?:goddamn|god damn|dammit|damn)\b",             "yelling",   {"anger": 0.18, "frustration": 0.12, "happiness": -0.10}),
    (r"\b(?:shut up|shut it)\b",                          "yelling",   {"anger": 0.20, "frustration": 0.10}),
    (r"\b(?:bullshit|bs)\b",                              "yelling",   {"anger": 0.18, "frustration": 0.12}),
    (r"\b(?:idiot|moron|dumbass)\b",                      "yelling",   {"anger": 0.20, "frustration": 0.10}),
    (r"\b(?:hate you|hate this)\b",                       "yelling",   {"anger": 0.25, "sadness": 0.05, "happiness": -0.15}),
    (r"\b(?:enough!|stop it!)\b",                         "yelling",   {"anger": 0.18, "frustration": 0.12}),

    # --- Deep fear / panic (fear 0.7+) ---
    (r"\b(?:help|help me)\b",                             "panicking", {"fear": 0.22, "sadness": 0.08}),
    (r"\b(?:no no no|nononono)\b",                        "panicking", {"fear": 0.25, "anger": 0.05}),
    (r"\b(?:terrified|horror)\b",                         "panicking", {"fear": 0.25, "surprise": 0.10}),
    (r"\b(?:run|get out|escape)\b",                       "panicking", {"fear": 0.20, "excitement": 0.08}),

    # --- Blushing / flustered (happiness 0.5+ with tere) ---
    (r"\b(?:blush|blushing|fluster(?:ed)?)\b",           "blushing",  {"happiness": 0.15, "excitement": 0.08, "surprise": 0.05}),
    (r"\b(?:kyaa|kyaaa)\b",                               "blushing",  {"happiness": 0.18, "excitement": 0.10, "surprise": 0.08}),
    (r"\b(?:ehehe|ehhehe)\b",                             "blushing",  {"happiness": 0.12, "excitement": 0.05}),
    (r"\bshy\b",                                          "blushing",  {"happiness": 0.10, "excitement": 0.05, "fear": 0.03}),

    # --- Confident / smug (confidence 0.7+) ---
    (r"\b(?:heh|heh)\b.*\b(?:easy|simple|trivial)\b",    "smug",      {"confidence": 0.20, "happiness": 0.10, "frustration": -0.10}),
    (r"\btold you\b",                                     "smug",      {"confidence": 0.18, "happiness": 0.08}),
    (r"\bas expected\b",                                  "smug",      {"confidence": 0.15, "happiness": 0.05}),
    (r"\bpiece of cake\b",                                "smug",      {"confidence": 0.18, "happiness": 0.10}),
    (r"\bsee\?\b",                                        "smug",      {"confidence": 0.12, "happiness": 0.05}),
]

# Map expressive labels to Live2D face preset overrides (intensity modifiers)
_EXPRESSIVE_FACE_MODIFIERS: dict[str, dict[str, float]] = {
    "laughing":  {"mouthOpen": 0.7, "mouthForm": 1.0, "mouthSize": 0.85, "eyeLOpen": 0.35, "eyeROpen": 0.35, "browLY": 0.3, "browRY": 0.3, "tereo": 0.5},
    "crying":    {"mouthOpen": 0.3, "mouthForm": -0.6, "mouthSize": 0.4, "eyeLOpen": 0.55, "eyeROpen": 0.55, "browLY": -0.5, "browRY": -0.5, "browLAngle": -0.4, "browRAngle": 0.4, "tereo": 0, "angleY": -0.1},
    "shocked":   {"mouthOpen": 0.8, "mouthForm": 0, "mouthSize": 0.7, "eyeLOpen": 1.0, "eyeROpen": 1.0, "browLY": 0.7, "browRY": 0.7, "tereo": 0, "angleY": 0.05},
    "yelling":   {"mouthOpen": 0.9, "mouthForm": -0.3, "mouthSize": 0.8, "eyeLOpen": 0.6, "eyeROpen": 0.6, "browLY": -0.7, "browRY": -0.7, "browLAngle": -0.5, "browRAngle": 0.5, "tereo": 0, "angleY": -0.05},
    "panicking": {"mouthOpen": 0.5, "mouthForm": -0.4, "mouthSize": 0.5, "eyeLOpen": 1.0, "eyeROpen": 1.0, "eyeBallY": 0.3, "browLY": 0.8, "browRY": 0.8, "tereo": 0, "angleX": 0.1, "angleY": 0.1},
    "blushing":  {"mouthOpen": 0.15, "mouthForm": 0.7, "mouthSize": 0.55, "eyeLOpen": 0.7, "eyeROpen": 0.7, "browLY": 0.2, "browRY": 0.2, "tereo": 0.8, "angleX": -0.1, "angleZ": 0.1},
    "smug":      {"mouthOpen": 0, "mouthForm": 0.6, "mouthSize": 0.5, "eyeLOpen": 0.8, "eyeROpen": 0.65, "eyeBallX": 0.15, "browLY": 0.25, "browRY": 0.1, "browLAngle": 0.1, "browRAngle": -0.15, "tereo": 0.2, "angleX": 0.08, "angleZ": -0.05},
}

# Negation prefixes — if a keyword is preceded by these, flip the polarity
_NEGATION_PREFIXES = r"(?:not|no|never|don'?t|doesn'?t|didn'?t|won'?t|can'?t|couldn'?t|wouldn'?t|shouldn'?t|isn'?t|aren'?t|wasn'?t|weren'?t|hardly|barely|scarcely|without)\s+"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _update_emotions_from_text(text: str, es: EmotionalState) -> str | None:
    """Nudge emotion values based on keywords found in the LLM response.

    Negation-aware: if a keyword is preceded by not/no/don't/etc., the delta
    polarity is flipped (positive becomes negative and vice versa).

    Also processes high-intensity expressive triggers (laughing, crying, etc.)
    which produce much stronger emotion shifts.

    Returns the expressive_label if a high-intensity trigger was matched, else None.
    """
    lower = text.lower()
    for pattern, deltas in _EMOTION_KEYWORDS.items():
        for match in re.finditer(pattern, lower):
            # Check if this match is preceded by a negation
            start = match.start()
            prefix = lower[max(0, start - 30):start]
            negated = bool(re.search(_NEGATION_PREFIXES, prefix))
            for attr, delta in deltas.items():
                if negated:
                    delta = -delta  # flip polarity
                current = getattr(es, attr)
                setattr(es, attr, _clamp(current + delta))

    # Process high-intensity expressive triggers (bigger deltas, label for Live2D)
    expressive_label = None
    for pattern, label, deltas in _EXPRESSIVE_TRIGGERS:
        if re.search(pattern, lower):
            expressive_label = label
            for attr, delta in deltas.items():
                current = getattr(es, attr)
                setattr(es, attr, _clamp(current + delta))
            break  # only the first (strongest) match

    return expressive_label


def _emotion_values(es: EmotionalState | None) -> dict[str, float]:
    """Serialize current adaptive emotion state for the semantic avatar API."""
    if es is None:
        return {}
    return {
        "happiness": es.happiness,
        "excitement": es.excitement,
        "sadness": es.sadness,
        "anger": es.anger,
        "fear": es.fear,
        "curiosity": es.curiosity,
        "confidence": es.confidence,
        "frustration": es.frustration,
    }


def _dominant_emotion(values: dict[str, float], fallback: str = "curiosity") -> str:
    return max(values, key=values.get) if values else fallback


async def _run_spotify_action(action: str, args: dict[str, object]) -> tuple[dict[str, object] | None, str | None]:
    """Run an action while converting setup/API failures into safe tool output."""

    if not spotify_controller.is_authenticated():
        return None, "Spotify is not connected yet. Open Settings → Integrations → Spotify and connect your account."
    try:
        result = await spotify_controller.execute_action(action, args)
    except SpotifyError as exc:
        return None, f"Spotify couldn't complete that: {exc}"
    return result, None


_SPOTIFY_CONFIRMATION_STYLES = (
    "Direct: state the result immediately, with no preamble or closing wish.",
    "Dry and playful: use one brief understated character remark after the exact result.",
    "Minimal: use the fewest natural words possible while naming the exact result.",
    "Teasing: give the exact result with one short, harmless tease and no generic encouragement.",
    "Announcer-like: present the exact result crisply as a now-playing update.",
    "Casual: answer as if replying to a friend, without a greeting or sign-off.",
)

_SPOTIFY_STOCK_PHRASES = (
    "oh it looks like",
    "it looks like we",
    "we re currently enjoying",
    "still grooving to",
    "hope you re enjoying",
    "hope you enjoy",
    "hope you re vibing",
    "hope you like it",
    "glad you re enjoying",
    "great choice",
    "excellent choice",
)


def _normalize_spotify_wording(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _recent_assistant_replies(messages: list[ChatMessage], limit: int = 8) -> list[str]:
    replies = [message.content.strip() for message in messages if message.role == "assistant" and message.content.strip()]
    return replies[-limit:]


def _spotify_response_is_repetitive(candidate: str, recent_replies: list[str]) -> bool:
    """Reject stock music filler and openings copied from recent turns."""

    normalized = _normalize_spotify_wording(candidate)
    if not normalized:
        return True
    if any(phrase in normalized for phrase in _SPOTIFY_STOCK_PHRASES):
        return True

    candidate_words = normalized.split()
    for prior in recent_replies:
        prior_words = _normalize_spotify_wording(prior).split()
        if not prior_words:
            continue
        shared_prefix_length = 0
        for candidate_word, prior_word in zip(candidate_words[:5], prior_words[:5]):
            if candidate_word != prior_word:
                break
            shared_prefix_length += 1
        if shared_prefix_length >= 3:
            return True
        candidate_opening = " ".join(candidate_words[:8])
        prior_opening = " ".join(prior_words[:8])
        if candidate_opening and prior_opening and SequenceMatcher(
            None,
            candidate_opening,
            prior_opening,
        ).ratio() >= 0.8:
            return True
    return False


def _varied_spotify_status_fallback(
    messages: list[ChatMessage],
    result: dict[str, object] | None,
    *,
    model: str | None,
) -> LLMResponse | None:
    """Guarantee grounded variety if a small model repeats rejected wording."""

    item = (result or {}).get("item") or {}
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return None
    title = str(item["name"]).strip()
    artists = ", ".join(str(value).strip() for value in (item.get("artists") or []) if str(value).strip())
    attribution = f" by {artists}" if artists else ""
    if (result or {}).get("is_playing"):
        templates = (
            f"Now playing: “{title}”{attribution}.",
            f"That’s “{title}”{attribution} on Spotify right now.",
            f"You’re hearing “{title}”{f' from {artists}' if artists else ''}.",
            f"On right now: “{title}”{f' — {artists}' if artists else ''}.",
            f"Spotify’s current track is “{title}”{attribution}.",
            f"The track playing is “{title}”{attribution}.",
        )
    else:
        templates = (
            f"“{title}”{attribution} is paused right now.",
            f"Spotify is paused on “{title}”{attribution}.",
            f"The paused track is “{title}”{attribution}.",
            f"You have “{title}”{attribution} paused.",
        )

    recent_replies = _recent_assistant_replies(messages)
    start = len(recent_replies) % len(templates)
    for offset in range(len(templates)):
        content = templates[(start + offset) % len(templates)]
        if not _spotify_response_is_repetitive(content, recent_replies):
            return LLMResponse(content=content, model=model or "spotify", finish_reason="stop")
    return LLMResponse(content=templates[start], model=model or "spotify", finish_reason="stop")


def _varied_spotify_action_fallback(
    messages: list[ChatMessage],
    action: str,
    result: dict[str, object] | None,
    *,
    model: str | None,
) -> LLMResponse | None:
    """Return a grounded, non-stock fallback for actions with a track name."""

    if action != "save_current":
        return None
    item = (result or {}).get("saved_track") or (result or {}).get("item") or {}
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return None
    title = str(item["name"]).strip()
    artists = ", ".join(str(value).strip() for value in (item.get("artists") or []) if str(value).strip())
    attribution = f" by {artists}" if artists else ""
    templates = (
        f"Saved “{title}”{attribution} to your Liked Songs.",
        f"“{title}”{attribution} is now in your Spotify Liked Songs.",
        f"Liked: “{title}”{attribution}.",
        f"Added “{title}”{attribution} to your saved tracks.",
    )
    recent_replies = _recent_assistant_replies(messages)
    start = len(recent_replies) % len(templates)
    for offset in range(len(templates)):
        content = templates[(start + offset) % len(templates)]
        if not _spotify_response_is_repetitive(content, recent_replies):
            return LLMResponse(content=content, model=model or "spotify", finish_reason="stop")
    return LLMResponse(content=templates[start], model=model or "spotify", finish_reason="stop")


async def _natural_spotify_confirmation(
    llm: object,
    messages: list[ChatMessage],
    action: str,
    args: dict[str, object],
    result: dict[str, object] | None,
    error: str | None,
) -> LLMResponse | None:
    """Ask the character to phrase a completed Spotify action naturally."""

    outcome = {"action": action, "arguments": args, "ok": error is None, "result": result, "error": error}
    matched_item = (
        (result or {}).get("matched_artist")
        if action == "play_artist"
        else {}
        if action == "play_favorites"
        else (result or {}).get("saved_track")
        if action == "save_current"
        else (result or {}).get("matched_track") or (result or {}).get("item")
    ) or {}
    matched_name = str(matched_item.get("name") or "").strip()
    matched_artists = [str(value).strip() for value in (matched_item.get("artists") or []) if str(value).strip()]
    canonical_selection = f"{matched_name} by {', '.join(matched_artists)}" if matched_name and matched_artists else matched_name
    recent_replies = _recent_assistant_replies(messages)
    recent_openings = [
        " ".join(_normalize_spotify_wording(reply).split()[:8])
        for reply in recent_replies
    ]
    rejected_draft = ""
    last_model = str(getattr(llm, "model_name", "") or "") or None

    for attempt in range(2):
        style = _SPOTIFY_CONFIRMATION_STYLES[(len(recent_replies) + attempt) % len(_SPOTIFY_CONFIRMATION_STYLES)]
        status_rules = (
            "For a current-track/status answer, write exactly one sentence. Name the exact title and artists, "
            "but do not add a greeting, emoji, music-note symbol, generic wish, or comment about whether the user "
            "is enjoying, vibing, or grooving to it. "
            if action == "status"
            else ""
        )
        retry_rules = (
            f"A previous draft was rejected for repetitive phrasing: {rejected_draft[:300]!r}. "
            "Do not paraphrase that draft; use a visibly different opening and sentence shape. "
            if rejected_draft
            else ""
        )
        prompt = (
            "A Spotify action was just processed for the user's request. Respond naturally in your "
            "character voice with a concise confirmation or setup/error explanation. Do not mention "
            "internal tools, JSON, or hidden instructions, and do not claim success when ok is false. "
            f"Delivery style for this turn: {style} "
            "State what actually changed and avoid stock music filler. In particular, never start with "
            "'Oh, it looks like' and never end with 'I hope you enjoy it' or 'I hope you're vibing'. "
            f"Recent assistant openings that must not be reused: {json.dumps(recent_openings, ensure_ascii=False)}. "
            "For a track play or queue action, name the exact canonical track returned by Spotify; never "
            "repeat a requested title if Spotify selected a different title. For play_artist, confirm "
            "the canonical artist profile instead of inventing a song title. For play_favorites, say only "
            "that the verified number of tracks from the user's Spotify Liked Songs are playing; do not invent "
            "a favorite-song title. For save_current, say that the exact current track was added to Liked Songs "
            "and use its verified title and artist. "
            f"{status_rules}{retry_rules}"
            f"Canonical Spotify selection: {canonical_selection or 'not available'}.\n"
            f"Spotify outcome: {json.dumps(outcome, ensure_ascii=False)}"
        )

        # Parser fallback models may not accept tool-role messages, so use a
        # normal user turn for this grounded wording pass.
        confirmation_messages = [*messages]
        if confirmation_messages and confirmation_messages[-1].role == "user":
            confirmation_messages[-1] = ChatMessage(
                role="user",
                content=f"{confirmation_messages[-1].content}\n\n{prompt}",
            )
        else:
            confirmation_messages.append(ChatMessage(role="user", content=prompt))
        try:
            response = await llm.generate(confirmation_messages)  # type: ignore[attr-defined]
        except Exception:
            continue
        last_model = response.model or last_model
        if not response.content.strip():
            continue
        if not _spotify_confirmation_is_grounded(response, action, result):
            rejected_draft = response.content
            continue
        if _spotify_response_is_repetitive(response.content, recent_replies):
            rejected_draft = response.content
            continue
        return response

    if action == "status" and error is None:
        return _varied_spotify_status_fallback(messages, result, model=last_model)
    if action == "save_current" and error is None:
        return _varied_spotify_action_fallback(messages, action, result, model=last_model)
    return None


def _spotify_confirmation_is_grounded(
    response: LLMResponse | None,
    action: str,
    result: dict[str, object] | None,
) -> bool:
    """Prevent a tool-followup from claiming the requested track was played."""

    if response is None or not response.content.strip():
        return False
    normalized_response = re.sub(r"[^a-z0-9]+", " ", response.content.lower()).strip()
    if action == "play_favorites":
        return bool(re.search(r"\b(?:liked|saved|favorite|favourite)\b", normalized_response))
    if action == "save_current" and not re.search(
        r"\b(?:saved|save|liked|like|favorited|favourite|favorite|added)\b",
        normalized_response,
    ):
        return False
    action_terms: dict[str, tuple[str, ...]] = {
        "play": ("play", "playing", "started", "resumed", "resume"),
        "play_artist": ("play", "playing", "started", "start"),
        "queue": ("queue", "queued", "added", "add", "line", "up next"),
        "pause": ("pause", "paused"),
        "resume": ("play", "playing", "started", "resumed", "resume"),
        "next": ("skip", "skipped", "next"),
        "previous": ("back", "previous", "prev", "rewind"),
        "volume": ("volume",),
        "volume_relative": ("volume",),
        "shuffle": ("shuffle",),
        "repeat": ("repeat",),
        "toggle": ("playback", "resumed", "paused"),
    }
    if action in action_terms and not any(
        re.search(rf"\b{re.escape(term)}\b", normalized_response)
        for term in action_terms[action]
    ):
        return False
    if action == "queue" and re.search(
        r"\b(?:replac(?:ed|e)|removed|deleted|playing\s+now|now\s+playing)\b",
        normalized_response,
    ):
        # Queueing does not replace or start the current track. Reject a
        # fluent but false summary and use the verified deterministic text.
        return False
    if action in {"play", "play_artist", "resume"} and re.search(
        r"\b(?:queued|queue|added\s+to\s+(?:the\s+)?queue)\b",
        normalized_response,
    ):
        return False
    if action == "pause" and re.search(r"\b(?:playing|resumed|started)\b", normalized_response):
        return False
    item = (
        (result or {}).get("matched_artist")
        if action == "play_artist"
        else (result or {}).get("saved_track")
        if action == "save_current"
        else (result or {}).get("matched_track") or (result or {}).get("item")
    ) or {}
    name = str(item.get("name") or "").strip() if isinstance(item, dict) else ""
    if action == "status" and not name:
        # If Spotify reports no current item, the model may explain that state
        # in its own words. There is no title to ground in that case.
        return True
    if not name:
        return True
    normalized_name = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    return bool(normalized_name and normalized_name in normalized_response)


_MASTER_REFERENCE_KEYS = {
    "llm_preset_id",
    "tts_preset_id",
    "avatar_preset_id",
    "stt_preset_id",
    "whisper_preset_id",
    "character_profile_id",
}


def _resolve_master_runtime(preset_id: str) -> tuple[dict[str, object], str | None]:
    """Resolve a master bundle without applying or persisting it."""

    requested = str(preset_id or "").strip()
    if not requested:
        return {}, None
    presets = _load_presets()
    preset = next((item for item in presets if str(item.get("id") or "") == requested), None)
    if not preset or str(preset.get("type") or "").lower() != "master":
        raise ValueError(f"Channel master preset not found: {requested}")

    master_data = preset.get("data") if isinstance(preset.get("data"), dict) else {}
    resolved: dict[str, object] = {
        key: value for key, value in master_data.items() if key not in _MASTER_REFERENCE_KEYS
    }
    # A channel bundle with no avatar component intentionally renders the orb
    # instead of inheriting the global Live2D model.
    resolved["_channel_avatar_specified"] = bool(
        master_data.get("avatar_preset_id") or "avatar_model" in master_data
    )
    for reference_key in (
        "llm_preset_id",
        "tts_preset_id",
        "avatar_preset_id",
        "stt_preset_id",
        "whisper_preset_id",
    ):
        child_id = master_data.get(reference_key)
        if not child_id:
            continue
        child = next((item for item in presets if str(item.get("id") or "") == str(child_id)), None)
        if child and str(child.get("type") or "").lower() in {"llm", "tts", "avatar", "stt", "whisper"}:
            child_data = child.get("data")
            if isinstance(child_data, dict):
                resolved.update(child_data)
    return resolved, str(master_data.get("character_profile_id") or "").strip() or None


def _apply_channel_runtime(data: dict[str, object], character_profile_id: str | None) -> None:
    """Overlay resolved master data on the shared config for one request."""

    if character_profile_id:
        profile = read_profile(character_profile_id, settings)
        apply_profile_to_config(profile, settings, _safe_profile_id(character_profile_id))

    llm_map = {
        "llm_provider": "provider",
        "llm_model": "model",
        "llm_base_url": "base_url",
        "llm_temperature": "temperature",
        "llm_max_tokens": "max_tokens",
    }
    for field_name, attr_name in llm_map.items():
        if field_name in data:
            setattr(settings.llm, attr_name, data[field_name])

    tts_map = {
        "tts_engine": "engine", "tts_voice_ref": "voice_ref", "tts_language": "language",
        "tts_happiness": "happiness", "tts_sadness": "sadness", "tts_disgust": "disgust",
        "tts_fear": "fear", "tts_surprise": "surprise", "tts_anger": "anger",
        "tts_other": "other", "tts_neutral": "neutral", "tts_speaking_rate": "speaking_rate",
        "tts_pitch_std": "pitch_std", "tts_fmax": "fmax", "tts_vq_score": "vq_score",
        "tts_dnsmos_ovrl": "dnsmos_ovrl", "tts_cfg_scale": "cfg_scale", "tts_seed": "seed",
        "tts_seed_mode": "seed_mode", "tts_emotion_mode": "emotion_mode", "tts_voice_gender": "voice_gender",
        "tts_openrouter_base_url": "openrouter_base_url", "tts_openrouter_api_key_env": "openrouter_api_key_env",
        "tts_openrouter_model": "openrouter_model", "tts_openrouter_voice": "openrouter_voice",
        "tts_openrouter_response_format": "openrouter_response_format", "tts_openrouter_speed": "openrouter_speed",
        "tts_fish_audio_base_url": "fish_audio_base_url", "tts_fish_audio_api_key_env": "fish_audio_api_key_env",
    }
    for field_name, attr_name in tts_map.items():
        if field_name in data:
            value = data[field_name]
            if field_name == "tts_voice_ref":
                value = _ensure_project_voice_reference(value if value is not None else "")
            setattr(settings.tts, attr_name, value)

    stt_map = {
        "stt_provider": "provider", "stt_model": "model", "stt_device": "device",
        "stt_compute_type": "compute_type", "stt_beam_size": "beam_size", "stt_language": "language",
        "stt_vad_filter": "vad_filter", "stt_temperature": "temperature",
        "stt_streaming_enabled": "streaming_enabled", "stt_stream_chunk_ms": "stream_chunk_ms",
        "stt_stream_language": "stream_language", "stt_fallback_enabled": "fallback_enabled",
        "stt_sidecar_port": "sidecar_port",
    }
    for field_name, attr_name in stt_map.items():
        if field_name in data:
            setattr(settings.stt, attr_name, data[field_name])
    if "stt_provider" not in data and "stt_model" in data:
        settings.stt.provider = "nemo_speech" if str(data["stt_model"]).startswith("nemotron-") else "faster_whisper"

    avatar_map = {
        "avatar_provider": "provider",
        "avatar_model": "model",
        "avatar_smart_expressions": "smart_expressions",
        "avatar_idle_preset": "idle_preset",
        "avatar_idle_intensity": "idle_intensity",
    }
    for field_name, attr_name in avatar_map.items():
        if field_name in data:
            setattr(settings.avatar, attr_name, data[field_name])
    if not bool(data.get("_channel_avatar_specified", False)):
        settings.avatar.model = ""
    if "memory_max_short_term" in data:
        settings.memory.max_short_term_messages = data["memory_max_short_term"]
    if "memory_retrieval_top_k" in data:
        settings.memory.retrieval_top_k = data["memory_retrieval_top_k"]
    if "message_mode" in data:
        settings.message_mode = data["message_mode"]


@asynccontextmanager
async def _channel_runtime_scope(master_preset_id: str | None):
    """Use a channel bundle for a request, then restore the global draft."""

    async with _channel_runtime_lock:
        snapshot = settings.model_copy(deep=True)
        runtime_token = _channel_runtime_active.set(bool(master_preset_id))
        try:
            if master_preset_id:
                data, character_profile_id = _resolve_master_runtime(master_preset_id)
                _apply_channel_runtime(data, character_profile_id)
            yield
        finally:
            # Preserve object identity because other modules imported the
            # shared ``settings`` instance at module load time.
            for field_name in snapshot.__class__.model_fields:
                setattr(settings, field_name, getattr(snapshot, field_name))
            _channel_runtime_active.reset(runtime_token)


async def _process_chat(db: AsyncSession, req: ChatRequest) -> ChatResponse:
    async with _channel_runtime_scope(req.master_preset_id):
        return await _process_chat_inner(db, req)


async def _process_chat_inner(db: AsyncSession, req: ChatRequest) -> ChatResponse:
    """Shared chat logic used by both REST and WebSocket handlers."""
    state = await load_character_state(db)
    llm = create_llm_provider()
    add_log("info", "chat", f"Received message ({len(req.message)} chars)")

    # Get or create conversation
    if req.conversation_id:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.id == req.conversation_id)
            .options(selectinload(Conversation.messages))
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(character_id=state.id)
            db.add(conversation)
            await db.flush()
    else:
        conversation = Conversation(character_id=state.id)
        db.add(conversation)
        await db.flush()

    # Load recent history
    history_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    )
    past = history_result.scalars().all()
    is_live_voice = req.source in {"web_voice", "discord_voice", "voice_brain"}
    voice_context: VoiceContextPack | None = None
    if is_live_voice:
        voice_context = await assemble_voice_context(
            db,
            character_id=state.id,
            conversation_messages=past,
            current_text=req.message,
            session_id=req.voice_session_id,
        )
        history = list(voice_context.history)
    else:
        max_short_term = settings.memory.max_short_term_messages
        history = [
            ChatMessage(role=m.role, content=m.content) for m in past[-max_short_term:]
        ]

    # Store user message
    user_msg = Message(
        conversation_id=conversation.id,
        role="user",
        content=req.message,
        metadata_={
            "source": req.source,
            **({"voice_session_id": req.voice_session_id} if req.voice_session_id else {}),
        },
    )
    db.add(user_msg)
    await db.flush()

    history.append(ChatMessage(role="user", content=req.message))

    if is_live_voice and req.voice_session_id:
        try:
            from app.agent.voice_brain import voice_brain

            await voice_brain.heartbeat(
                req.voice_session_id,
                phase="processing",
                conversation_id=conversation.id,
                persist=False,
            )
            await voice_brain.publish_event(
                req.voice_session_id,
                "user_spoke",
                source=req.source,
                priority=65,
                payload={"text": req.message[:1200]},
                db_session=db,
            )
        except KeyError:
            # A voice request remains usable when a client reconnect races its
            # session-open request; it simply misses this perception event.
            pass

    # Load active memories and goals for prompt injection
    if voice_context is not None:
        memories = list(voice_context.memories)
    else:
        mem_result = await db.execute(
            select(Memory)
            .where(Memory.character_id == state.id)
            .order_by(Memory.importance.desc(), Memory.created_at.desc())
            .limit(settings.memory.retrieval_top_k)
        )
        memories = [m.content for m in mem_result.scalars().all()]

    goal_result = await db.execute(
        select(Goal)
        .where(Goal.character_id == state.id, Goal.status == "active")
        .order_by(Goal.priority.desc())
        .limit(10)
    )
    goals = [f"{g.title}: {g.description}" if g.description else g.title for g in goal_result.scalars().all()]

    spotify_enabled = settings.integrations.spotify.enabled
    tool_registry = create_tool_registry()
    parsed_command = spotify_controller.parse_command(req.message)
    if parsed_command is None:
        # Short follow-ups (for example, "make it fifty") need the preceding
        # turn to establish what "it" refers to. Keep this narrow and only
        # promote the phrase when recent messages clearly mention volume.
        parsed_command = spotify_controller.parse_contextual_command(
            req.message,
            [message.content for message in history[-6:]],
        )
    # Keep integration guidance out of ordinary conversational turns. Small
    # local models are more likely to reinterpret a short STT transcript as a
    # song request when they see the Spotify tool directory in every prompt.
    route_wake = tool_registry.looks_actionable(req.message) or (
        spotify_enabled and parsed_command is not None
    )
    messages = build_messages(
        state,
        history,
        extra_memories=memories or None,
        current_goals=goals or None,
        tool_guidance=tool_registry.guidance() if route_wake else None,
        conversation_summary=voice_context.summary if voice_context else None,
        open_loops=voice_context.open_loops if voice_context else None,
        situational_context=req.situational_context,
        internal_state=voice_context.internal_state if voice_context else None,
    )

    response: LLMResponse | None = None
    tools_used: list[str] = []
    discord_command = parse_discord_voice_command(req.message)
    required_tool = None
    required_arguments: dict[str, object] | None = None
    initial_tool_call = None
    initial_tool_model: str | None = None
    route_status = "skipped"
    if route_wake:
        try:
            semantic_route = await route_tool_request(llm, req.message, tool_registry)
            route_status = semantic_route.status
            if semantic_route.status == "selected" and semantic_route.call is not None:
                initial_tool_call = semantic_route.call
                initial_tool_model = semantic_route.model
                if initial_tool_call.name.startswith("spotify_"):
                    if parsed_command is not None:
                        parsed_name, parsed_arguments = spotify_controller.tool_from_action(*parsed_command)
                        # Explicit artist-collection wording is more specific
                        # than a small model choosing the generic track tool.
                        if {
                            initial_tool_call.name,
                            parsed_name,
                        } == {"spotify_play", "spotify_play_artist"}:
                            initial_tool_call = initial_tool_call.model_copy(
                                update={"name": parsed_name, "arguments": dict(parsed_arguments)}
                            )
                        # Liked Songs is not a search query. If a small model
                        # incorrectly selects the generic play tool for
                        # “play my favorite songs”, force the registered
                        # favorites tool so it cannot invent a title.
                        elif parsed_name == "spotify_play_favorites":
                            initial_tool_call = initial_tool_call.model_copy(
                                update={"name": parsed_name, "arguments": dict(parsed_arguments)}
                            )
                        # Favoriting the current track is a write to Liked
                        # Songs, not a request to play the existing favorites
                        # library or search for a track title. Keep the
                        # explicit parser intent when a small router picks a
                        # neighboring Spotify tool.
                        elif parsed_name == "spotify_save_current":
                            initial_tool_call = initial_tool_call.model_copy(
                                update={"name": parsed_name, "arguments": dict(parsed_arguments)}
                            )
                    grounded = spotify_controller.arguments_for_tool_request(
                        initial_tool_call.name,
                        req.message,
                    )
                    if grounded is not None:
                        initial_tool_call = initial_tool_call.model_copy(
                            update={"arguments": grounded}
                        )
        except Exception as exc:
            # A routing failure must never execute anything. The conservative
            # parser below remains available for explicit Spotify commands.
            route_status = "failed"
            add_log("warning", "tools", f"Semantic tool routing failed: {exc}")

    # The parser is a compatibility safety net, not the primary decision
    # maker. It only takes over when the semantic router did not select a real
    # registered call.
    if spotify_enabled and parsed_command is not None:
        required_tool, required_arguments = spotify_controller.tool_from_action(*parsed_command)
        if initial_tool_call is not None and initial_tool_call.name != required_tool:
            # A parser-grounded Spotify intent is safer than a neighboring
            # semantic choice (for example, status instead of volume). Keep
            # the model for phrasing, but force the actual requested action.
            initial_tool_call = initial_tool_call.model_copy(
                update={"name": required_tool, "arguments": dict(required_arguments or {})}
            )

    # Keep explicit Discord voice controls reliable with small local models
    # that ignore native function calls. These phrases are narrow and
    # self-targeted, so grounding them here cannot affect another participant.
    discord_enabled = bool(settings.integrations.discord.enabled)
    discord_client_enabled = discord_enabled and str(settings.integrations.discord.mode or "client").lower() == "client"
    if discord_client_enabled and discord_command is not None:
        discord_tool_name, discord_arguments = discord_command
        if initial_tool_call is None:
            required_tool, required_arguments = discord_tool_name, discord_arguments
        elif initial_tool_call.name.startswith("discord_"):
            initial_tool_call = initial_tool_call.model_copy(
                update={"name": discord_tool_name, "arguments": dict(discord_arguments)}
            )

    if not spotify_enabled:
        # Still recognize a Spotify-shaped request so the user receives setup
        # guidance instead of an unrelated character answer.
        spotify_reply = await spotify_controller.handle_chat_message(req.message, enabled=False)
        if spotify_reply is not None:
            response = LLMResponse(content=spotify_reply, model="spotify", finish_reason="stop")
            add_log("info", "spotify", f"Spotify request blocked while disabled ({req.message[:80]!r})")

    if response is None and route_status in {"none", "skipped", "failed"} and required_tool is None:
        # ``skipped`` means the wake gate found no action language at all;
        # ``none`` means the semantic router explicitly chose no action;
        # ``failed`` means routing was unavailable. In all three cases, do not
        # send the full tool directory to the conversational model, otherwise
        # a short/ambiguous STT transcript (for example a person's name) can
        # be hallucinated into a Spotify search.
        safe_messages = list(messages)
        if safe_messages and safe_messages[0].role == "system":
            safe_messages[0] = safe_messages[0].model_copy(
                update={
                    "content": (
                        f"{safe_messages[0].content}\n\n"
                        "External-action guard: no verified external tool is being run for this turn. "
                        "Do not claim that you played, queued, changed, sent, joined, or otherwise "
                        "completed an external action. If the user appears to request one, ask for a "
                        "clear action request instead of pretending it happened."
                    )
                }
            )
        response = await llm.generate(safe_messages)

    if response is None:
        definitions = tool_registry.definitions()
        add_log(
            "info",
            "llm",
            f"Sending {len(messages)} messages with {len(definitions)} available tools ({llm.provider_name})",
        )
        try:
            tool_run = await run_tool_conversation(
                llm,
                messages,
                tool_registry,
                required_tool=required_tool,
                required_arguments=required_arguments,
                initial_call=initial_tool_call,
                initial_model=initial_tool_model,
            )
        except Exception as exc:
            # The deterministic Spotify parser is intentionally the final
            # compatibility layer for typo-heavy STT and servers that cannot
            # perform either native or prompt-protocol function calls.
            if not (
                (spotify_enabled and parsed_command is not None)
                or (discord_client_enabled and discord_command is not None and required_tool)
            ):
                raise
            if discord_client_enabled and discord_command is not None and required_tool:
                # If the conversational wording turn fails, execute the
                # already-grounded, validated local tool once rather than
                # turning a clear self-control request into a 503.
                execution = await tool_registry.execute(
                    ToolCall(
                        id="call_controller_discord_fallback_1",
                        name=required_tool,
                        arguments=dict(required_arguments or {}),
                        source="controller",
                    )
                )
                tools_used = [required_tool]
                if execution.ok:
                    result_payload = execution.result if isinstance(execution.result, dict) else {}
                    response = LLMResponse(
                        content=str(result_payload.get("confirmation") or "Discord voice state updated."),
                        model="discord",
                        finish_reason="tool_result",
                    )
                else:
                    response = LLMResponse(
                        content=execution.error or "Discord could not change Neuro's voice state.",
                        model="discord",
                        finish_reason="tool_error",
                    )
                add_log("warning", "discord", f"Deterministic voice-control fallback after tool-loop failure: {exc}")
                # Skip the Spotify fallback below.
                parsed_command = None
            else:
                action, args = parsed_command
                # Parser fallback still executed a real registered tool. Keep
                # its name in the response so web, Live Mode, and Discord all
                # render the same tool-use indicator.
                tools_used = [spotify_controller.tool_from_action(action, args)[0]]
                result, error = await _run_spotify_action(action, args)
                fallback_text = error or spotify_controller.format_action_response(action, args, result or {})
                natural = (
                    await _natural_spotify_confirmation(llm, messages, action, args, result, error)
                    if error is None
                    else None
                )
                response = natural or LLMResponse(content=fallback_text, model="spotify", finish_reason="stop")
                spotify_controller.set_ai_control_mode("parser_fallback")
                add_log("warning", "spotify", f"Parser fallback after tool-loop failure: {exc}")
        else:
            tools_used = list(
                dict.fromkeys(execution.call.name for execution in tool_run.executions)
            )
            spotify_executions = [
                item for item in tool_run.executions if item.call.name.startswith("spotify_")
            ]
            spotify_execution = next((item for item in spotify_executions if not item.ok), None)
            if spotify_execution is None:
                spotify_execution = next(
                    (item for item in spotify_executions if item.call.name in {"spotify_play", "spotify_play_artist", "spotify_queue"}),
                    spotify_executions[0] if spotify_executions else None,
                )
            if spotify_execution is not None:
                spotify_controller.set_ai_control_mode("tool_calling")
                if not spotify_execution.ok:
                    response = LLMResponse(
                        content=spotify_execution.error or "Spotify could not complete that action.",
                        model=tool_run.response.model or initial_tool_model or llm.model_name,
                        finish_reason="tool_error",
                    )
                else:
                    outcome = spotify_execution.result if isinstance(spotify_execution.result, dict) else {}
                    action = str(outcome.get("action") or "status")
                    result = outcome.get("data") if isinstance(outcome.get("data"), dict) else {}
                    # Give the character a dedicated, normal-temperature turn
                    # to phrase the completed action. The deterministic text
                    # remains only as a safety fallback if that generation
                    # fails or omits a required canonical track.
                    natural = await _natural_spotify_confirmation(
                        llm,
                        messages,
                        action,
                        outcome.get("arguments") if isinstance(outcome.get("arguments"), dict) else {},
                        result,
                        None,
                    )
                    if natural is not None:
                        response = natural
                    elif _spotify_confirmation_is_grounded(tool_run.response, action, result):
                        response = tool_run.response
                    else:
                        response = LLMResponse(
                            content=str(outcome.get("confirmation") or "Spotify completed the action."),
                            model=tool_run.response.model or initial_tool_model or llm.model_name,
                            finish_reason="stop",
                        )
                add_log("info", "spotify", f"Tool loop handled {spotify_execution.call.name}")
            elif discord_command is not None or any(
                item.call.name == "discord_speak_voice" for item in tool_run.executions
            ):
                discord_executions = [
                    item
                    for item in tool_run.executions
                    if item.call.name in {"discord_set_mute", "discord_set_deafen", "discord_speak_voice"}
                ]
                if any(item.call.name == "discord_speak_voice" for item in discord_executions):
                    # A model may attempt to repeat the call after receiving
                    # the tool result. Prefer the first successful playback so
                    # a blocked duplicate cannot hide the audio that already
                    # played or produce a false failure confirmation.
                    discord_execution = next(
                        (item for item in discord_executions if item.ok),
                        discord_executions[-1] if discord_executions else None,
                    )
                else:
                    discord_execution = discord_executions[-1] if discord_executions else None
                if discord_execution is not None:
                    if not discord_execution.ok:
                        response = LLMResponse(
                            content=discord_execution.error or "Discord could not change Neuro's voice state.",
                            model=tool_run.response.model or initial_tool_model or llm.model_name,
                            finish_reason="tool_error",
                        )
                    elif discord_execution.call.name == "discord_speak_voice":
                        # The tool result is authoritative. Never surface a
                        # model-generated "Sure, I said ..." as proof of
                        # playback when the voice tool did not run.
                        result_payload = discord_execution.result if isinstance(discord_execution.result, dict) else {}
                        response = LLMResponse(
                            content=str(result_payload.get("confirmation") or "The sentence was spoken in the Discord voice call."),
                            model=tool_run.response.model or initial_tool_model or llm.model_name,
                            finish_reason="tool_result",
                        )
                    elif not tool_run.response.content.strip():
                        result_payload = discord_execution.result if isinstance(discord_execution.result, dict) else {}
                        response = LLMResponse(
                            content=str(result_payload.get("confirmation") or "Discord voice state updated."),
                            model=tool_run.response.model or initial_tool_model or llm.model_name,
                            finish_reason="tool_result",
                        )
                    else:
                        response = tool_run.response
                    add_log("info", "discord", f"Tool loop handled {discord_execution.call.name}")
                else:
                    response = tool_run.response
            elif spotify_enabled and parsed_command is not None:
                action, args = parsed_command
                # The semantic model returned without a tool call, but this
                # recognized parser path still performed the Spotify action.
                tools_used = [spotify_controller.tool_from_action(action, args)[0]]
                result, error = await _run_spotify_action(action, args)
                fallback_text = error or spotify_controller.format_action_response(action, args, result or {})
                natural = (
                    await _natural_spotify_confirmation(llm, messages, action, args, result, error)
                    if error is None
                    else None
                )
                response = natural or LLMResponse(content=fallback_text, model="spotify", finish_reason="stop")
                spotify_controller.set_ai_control_mode("parser_fallback")
                add_log("info", "spotify", f"Parser handled uncalled Spotify intent ({req.message[:80]!r})")
            else:
                response = tool_run.response
            if route_status == "failed" and not tool_run.executions:
                response = LLMResponse(
                    content=(
                        "I understood that as a possible external action, but I couldn't safely "
                        "select an available tool. Please rephrase the action."
                    ),
                    model=tool_run.response.model or llm.model_name,
                    finish_reason="tool_route_failed",
                )
    add_log("info", "llm", f"Response received ({len(response.content)} chars)")

    # Update emotion state from response text
    expressive_label = None
    emotional_state: EmotionalState | None = None
    if state.emotion is not None:
        es_result = await db.execute(
            select(EmotionalState).where(EmotionalState.character_id == state.id)
        )
        emotional_state = es_result.scalar_one_or_none()
        if emotional_state is not None:
            expressive_label = _update_emotions_from_text(response.content, emotional_state)

    emotion_values = _emotion_values(emotional_state)
    emotion = _dominant_emotion(emotion_values, state.emotion.dominant())
    avatar_action = choose_avatar_action(
        text=response.content,
        emotion=emotion,
        expressive_label=expressive_label,
        emotion_values=emotion_values,
    )
    assistant_msg = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=response.content,
        emotion=emotion,
        metadata_={
            "model": response.model or llm.model_name,
            "avatar_action": avatar_action,
            "tools_used": tools_used,
            "context_mode": "hierarchical_voice" if voice_context else "short_term",
            "context_estimated_tokens": voice_context.estimated_tokens if voice_context else None,
            "retrieved_memory_count": len(voice_context.memories) if voice_context else len(memories),
            "conversation_summary_used": bool(voice_context and voice_context.summary),
            **_character_message_metadata(state),
        },
    )
    db.add(assistant_msg)
    conversation.updated_at = datetime.now(timezone.utc)
    await db.commit()
    add_log("info", "chat", f"Conversation updated: {conversation.id}")

    if is_live_voice and req.voice_session_id:
        try:
            from app.agent.voice_brain import voice_brain

            await voice_brain.note_completed_turn(
                req.voice_session_id,
                conversation_id=conversation.id,
                role="user",
                text=req.message,
            )
            await voice_brain.note_completed_turn(
                req.voice_session_id,
                conversation_id=conversation.id,
                role="assistant",
                text=response.content,
            )
            await voice_brain.heartbeat(
                req.voice_session_id,
                phase="listening",
                conversation_id=conversation.id,
            )
        except KeyError:
            pass

    return ChatResponse(
        message_id=assistant_msg.id,
        conversation_id=conversation.id,
        content=response.content,
        emotion=emotion,
        expressive_label=expressive_label,
        avatar_action=avatar_action,
        model=response.model or llm.model_name,
        tools_used=tools_used,
        character_profile_id=state.profile_id,
        character_name=state.name,
        character_profile_picture=state.profile_picture,
        created_at=assistant_msg.created_at,
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status", response_model=StatusResponse)
async def status(db: AsyncSession = Depends(get_db)) -> StatusResponse:
    state = await load_character_state(db)
    llm = create_llm_provider()

    # Latest conversation
    result = await db.execute(
        select(Conversation)
        .where(Conversation.character_id == state.id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    conv = result.scalar_one_or_none()
    msg_count = 0
    if conv:
        count_result = await db.execute(
            select(Message).where(Message.conversation_id == conv.id)
        )
        msg_count = len(count_result.scalars().all())

    return StatusResponse(
        character=CharacterPublic(
            id=state.id,
            profile_id=state.profile_id,
            name=state.name,
            profile_picture=state.profile_picture,
            description=state.description,
            personality=state.personality.traits,
            emotion={
                "happiness": state.emotion.happiness,
                "excitement": state.emotion.excitement,
                "sadness": state.emotion.sadness,
                "anger": state.emotion.anger,
                "fear": state.emotion.fear,
                "curiosity": state.emotion.curiosity,
                "confidence": state.emotion.confidence,
                "frustration": state.emotion.frustration,
            },
            dominant_emotion=state.emotion.dominant(),
            model_provider=llm.provider_name,
            model_name=llm.model_name,
        ),
        conversation_id=conv.id if conv else None,
        message_count=msg_count,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, db: AsyncSession = Depends(get_db)) -> ChatResponse:
    try:
        return await _process_chat(db, req)
    except Exception as e:
        logger.exception("Chat request failed")
        add_log("error", "chat", f"Chat request failed: {e}")
        raise HTTPException(status_code=503, detail=f"LLM server error: {e}")


@router.post("/chat/voice", response_model=ChatResponse)
async def chat_voice(
    file: UploadFile,
    conversation_id: str | None = None,
    master_preset_id: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Send a voice message — transcribe audio then process as chat."""
    audio_bytes = await file.read()
    add_log("info", "voice", f"Voice message received ({len(audio_bytes)} bytes)")

    try:
        # STT should use the channel bundle too, but only for this request.
        async with _channel_runtime_scope(master_preset_id):
            transcribed = await _transcribe_audio(audio_bytes, file.filename or "voice.webm")
    except Exception as e:
        add_log("error", "voice", f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

    if not transcribed.strip():
        raise HTTPException(status_code=400, detail="Could not transcribe audio")

    add_log("info", "voice", f"Transcribed: {transcribed[:80]}")

    req = ChatRequest(message=transcribed, conversation_id=conversation_id, master_preset_id=master_preset_id)
    try:
        return await _process_chat(db, req)
    except Exception as e:
        logger.exception("Voice chat processing failed")
        add_log("error", "voice", f"Voice chat failed: {e}")
        raise HTTPException(status_code=503, detail=f"LLM server error: {e}")


async def _transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe audio bytes using Whisper."""
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)
    try:
        whisper = _get_whisper()
        segments, _ = whisper.transcribe(str(tmp_path), beam_size=5)
        return " ".join(seg.text.strip() for seg in segments)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


@router.post("/chat/proactive", response_model=ChatResponse)
async def chat_proactive(
    req: ProactiveChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    async with _channel_runtime_scope(req.master_preset_id):
        return await _chat_proactive_inner(req, db)


async def _chat_proactive_inner(
    req: ProactiveChatRequest,
    db: AsyncSession,
) -> ChatResponse:
    """AI-initiated proactive message — the AI speaks on its own during silence."""
    state = await load_character_state(db)
    llm = create_llm_provider()

    # Get or create conversation
    if req.conversation_id:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.id == req.conversation_id)
            .options(selectinload(Conversation.messages))
        )
        conversation = result.scalar_one_or_none()
    else:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.character_id == state.id)
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        conversation = result.scalar_one_or_none()

    if conversation is None:
        # No conversation yet — use greeting trigger
        req.trigger = "greeting"

    # Load recent history. Autonomous live voice uses the same hierarchical
    # context pack as user-driven voice turns, including summary/open loops.
    history: list[ChatMessage] = []
    past: list[Message] = []
    if conversation:
        history_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
        )
        past = list(history_result.scalars().all())

    # Build a proactive prompt based on trigger type
    trigger_prompts = {
        "silence": (
            "The user has been quiet for a while. Say something natural to keep the conversation going. "
            "You could ask a question, share a thought, make an observation, or comment on something from earlier. "
            "Be natural and conversational — don't force it."
        ),
        "emotion_change": (
            "You're feeling a shift in your mood. Express this naturally in a short message. "
            "Don't explain that your emotion changed — just let it come through in what you say."
        ),
        "greeting": (
            "This is the start of a conversation. Greet the user warmly and naturally. "
            "Introduce yourself briefly and ask how they're doing or what's on their mind."
        ),
    }

    proactive_instruction = req.agent_instruction or trigger_prompts.get(req.trigger, trigger_prompts["silence"])

    voice_context: VoiceContextPack | None = None
    if req.voice_session_id:
        voice_context = await assemble_voice_context(
            db,
            character_id=state.id,
            conversation_messages=past,
            current_text=proactive_instruction,
            session_id=req.voice_session_id,
        )
        history = list(voice_context.history)
    else:
        max_short_term = settings.memory.max_short_term_messages
        history = [ChatMessage(role=m.role, content=m.content) for m in past[-max_short_term:]]

    # Load memories and goals
    if voice_context is not None:
        memories = list(voice_context.memories)
    else:
        mem_result = await db.execute(
            select(Memory)
            .where(Memory.character_id == state.id)
            .order_by(Memory.importance.desc(), Memory.created_at.desc())
            .limit(settings.memory.retrieval_top_k)
        )
        memories = [m.content for m in mem_result.scalars().all()]

    goal_result = await db.execute(
        select(Goal)
        .where(Goal.character_id == state.id, Goal.status == "active")
        .order_by(Goal.priority.desc())
        .limit(10)
    )
    goals = [f"{g.title}: {g.description}" if g.description else g.title for g in goal_result.scalars().all()]

    messages = build_messages(
        state,
        history,
        extra_memories=memories or None,
        current_goals=goals or None,
        conversation_summary=voice_context.summary if voice_context else None,
        open_loops=voice_context.open_loops if voice_context else None,
        situational_context=req.situational_context,
        internal_state=voice_context.internal_state if voice_context else None,
        agent_instruction=proactive_instruction,
    )
    add_log("info", "llm", f"Proactive chat ({req.trigger}): sending {len(messages)} messages to LLM")
    try:
        response = await llm.generate(messages)
    except Exception as exc:
        # Keep proactive failures consistent with normal chat failures.  The
        # Live Mode client can then surface a useful service error instead of
        # receiving an opaque 500 response when the local model is unavailable
        # or still switching.
        logger.exception("Proactive chat request failed")
        add_log("error", "chat", f"Proactive chat request failed: {exc}")
        raise HTTPException(status_code=503, detail=f"LLM server error: {exc}") from exc
    add_log("info", "llm", f"Proactive response ({len(response.content)} chars)")

    # Update emotion state and emit the same semantic avatar contract as a
    # normal chat reply.
    expressive_label = None
    emotional_state: EmotionalState | None = None
    if state.emotion is not None:
        es_result = await db.execute(
            select(EmotionalState).where(EmotionalState.character_id == state.id)
        )
        emotional_state = es_result.scalar_one_or_none()
        if emotional_state is not None:
            expressive_label = _update_emotions_from_text(response.content, emotional_state)

    emotion_values = _emotion_values(emotional_state)
    emotion = _dominant_emotion(emotion_values, state.emotion.dominant())
    avatar_action = choose_avatar_action(
        text=response.content,
        emotion=emotion,
        expressive_label=expressive_label,
        emotion_values=emotion_values,
    )

    # Store the proactive message
    if conversation:
        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=response.content,
            emotion=emotion,
            metadata_={
                "model": response.model or llm.model_name,
                "proactive": True,
                "trigger": req.trigger,
                "voice_brain_session_id": req.voice_session_id,
                "voice_surface": req.surface,
                "context_mode": "hierarchical_voice" if voice_context else "short_term",
                "context_estimated_tokens": voice_context.estimated_tokens if voice_context else None,
                "retrieved_memory_count": len(voice_context.memories) if voice_context else len(memories),
                "conversation_summary_used": bool(voice_context and voice_context.summary),
                "avatar_action": avatar_action,
                **_character_message_metadata(state),
            },
        )
        db.add(assistant_msg)
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return ChatResponse(
            message_id=assistant_msg.id,
            conversation_id=conversation.id,
            content=response.content,
            emotion=emotion,
            expressive_label=expressive_label,
            avatar_action=avatar_action,
            model=response.model or llm.model_name,
            character_profile_id=state.profile_id,
            character_name=state.name,
            character_profile_picture=state.profile_picture,
            created_at=assistant_msg.created_at,
        )
    else:
        # No conversation — create one
        conversation = Conversation(character_id=state.id)
        db.add(conversation)
        await db.flush()

        assistant_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=response.content,
            emotion=emotion,
            metadata_={
                "model": response.model or llm.model_name,
                "proactive": True,
                "trigger": req.trigger,
                "voice_brain_session_id": req.voice_session_id,
                "voice_surface": req.surface,
                "context_mode": "hierarchical_voice" if voice_context else "short_term",
                "context_estimated_tokens": voice_context.estimated_tokens if voice_context else None,
                "retrieved_memory_count": len(voice_context.memories) if voice_context else len(memories),
                "conversation_summary_used": bool(voice_context and voice_context.summary),
                "avatar_action": avatar_action,
                **_character_message_metadata(state),
            },
        )
        db.add(assistant_msg)
        conversation.updated_at = datetime.now(timezone.utc)
        await db.commit()

        return ChatResponse(
            message_id=assistant_msg.id,
            conversation_id=conversation.id,
            content=response.content,
            emotion=emotion,
            expressive_label=expressive_label,
            avatar_action=avatar_action,
            model=response.model or llm.model_name,
            character_profile_id=state.profile_id,
            character_name=state.name,
            character_profile_picture=state.profile_picture,
            created_at=assistant_msg.created_at,
        )


@router.get("/conversations", response_model=list[ConversationPublic])
async def list_conversations(db: AsyncSession = Depends(get_db)) -> list[ConversationPublic]:
    state = await load_character_state(db)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.character_id == state.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    out = []
    for c in convs:
        count_result = await db.execute(
            select(Message).where(Message.conversation_id == c.id)
        )
        count = len(count_result.scalars().all())
        out.append(ConversationPublic(
            id=c.id,
            title=c.title,
            message_count=count,
            created_at=c.created_at,
            updated_at=c.updated_at,
        ))
    return out


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessagePublic])
async def get_conversation_messages(
    conversation_id: str, db: AsyncSession = Depends(get_db)
) -> list[MessagePublic]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return [
        MessagePublic(
            id=m.id,
            role=m.role,
            content=m.content,
            emotion=m.emotion,
            avatar_action=m.metadata_.get("avatar_action") if m.metadata_ else None,
            model=m.metadata_.get("model") if m.metadata_ else None,
            tools_used=m.metadata_.get("tools_used", []) if m.metadata_ else [],
            character_profile_id=m.metadata_.get("character_profile_id") if m.metadata_ else None,
            character_name=m.metadata_.get("character_name") if m.metadata_ else None,
            character_profile_picture=m.metadata_.get("character_profile_picture") if m.metadata_ else None,
            created_at=m.created_at,
        )
        for m in result.scalars().all()
    ]


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            try:
                data = await websocket.receive_json()
                msg = WSMessage.model_validate(data)
            except ValidationError as e:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Invalid message format: {e.error_count()} error(s)"},
                })
                continue
            except Exception as e:
                logger.warning("Failed to parse WebSocket message: %s", e)
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "Could not parse message"},
                })
                continue

            if msg.type == "chat":
                from app.db.session import AsyncSessionLocal

                try:
                    async with AsyncSessionLocal() as db:
                        req = ChatRequest(
                            message=msg.data.get("message", ""),
                            conversation_id=msg.data.get("conversation_id"),
                            master_preset_id=msg.data.get("master_preset_id"),
                        )
                        result = await _process_chat(db, req)
                        await websocket.send_json({
                            "type": "chat_response",
                            "data": {
                                "message_id": result.message_id,
                                "conversation_id": result.conversation_id,
                                "content": result.content,
                                "emotion": result.emotion,
                                "expressive_label": result.expressive_label,
                                "avatar_action": result.avatar_action,
                                "model": result.model,
                                "tools_used": result.tools_used,
                                "character_profile_id": result.character_profile_id,
                                "character_name": result.character_name,
                                "character_profile_picture": result.character_profile_picture,
                            },
                        })
                except Exception as e:
                    logger.exception("WebSocket chat failed")
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": f"Chat error: {e}"},
                    })

            elif msg.type == "ping":
                await websocket.send_json({"type": "pong", "data": {}})

    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# TTS endpoint (Zonos primary, Index-TTS alternative, edge-tts fallback)
# ---------------------------------------------------------------------------

# Map simple voice names to edge-tts voice IDs (fallback)
_VOICE_MAP: dict[str, str] = {
    "default": "en-US-AnaNeural",
    "female": "en-US-AnaNeural",
    "male": "en-US-GuyNeural",
    "british": "en-GB-SoniaNeural",
    "anime": "ja-JP-NanamiNeural",
    "ana": "en-US-AnaNeural",
    "jenny": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "sonia": "en-GB-SoniaNeural",
    "nanami": "ja-JP-NanamiNeural",
    "guy": "en-US-GuyNeural",
    "ryan": "en-GB-RyanNeural",
    "christopher": "en-US-ChristopherNeural",
    "keita": "ja-JP-KeitaNeural",
    "onokami": "en-US-AnaNeural",
}

# Regex for emoji detection (covers all common emoji ranges)
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed characters
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # ZWJ
    "]+",
    flags=re.UNICODE,
)


def _clean_for_tts(text: str) -> str:
    """Strip emojis and normalize pauses for natural speech."""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\.{2,}", ",", text)
    text = re.sub(r"…+", ",", text)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"^[\s]*[-•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _compute_smart_emotions(state: CharacterState, text: str) -> dict[str, Any]:
    """Compute normalized emotion weights for Zonos from live character state and text tone.

    Also detects high-intensity expressive triggers and amplifies the dominant
    emotion accordingly so TTS voice and Live2D face are strongly expressive.
    Returns dict with emotion weights AND an optional "expressive_label" key.
    """
    emo = state.emotion
    lower = text.lower()

    # Base from live character state
    happiness = emo.happiness * 0.7 + (0.3 if emo.excitement > 0.5 else 0.0)
    sadness = emo.sadness * 0.8
    fear = emo.fear * 0.8
    surprise = emo.excitement * 0.5 + (0.3 if emo.curiosity > 0.6 else 0.0)
    anger = max(emo.anger, emo.frustration * 0.7)

    # Amplify dominant emotion
    dominant = emo.dominant() if hasattr(emo, "dominant") else "happiness"
    if dominant == "happiness":
        happiness = max(happiness, 0.65)
    elif dominant == "sadness":
        sadness = max(sadness, 0.6)
    elif dominant in ("anger", "frustration"):
        anger = max(anger, 0.55)
    elif dominant == "excitement":
        happiness = max(happiness, 0.5)
        surprise = max(surprise, 0.4)
    elif dominant == "fear":
        fear = max(fear, 0.5)
    elif dominant == "curiosity":
        surprise = max(surprise, 0.35)
        happiness = max(happiness, 0.3)

    # --- Text-driven tone modifiers ---
    # Punctuation emphasis
    if "!" in text:
        if anger > 0.3:
            anger = min(1.0, anger + 0.15)
        else:
            happiness = min(1.0, happiness + 0.15)
            surprise = min(1.0, surprise + 0.1)
    if "?" in text:
        surprise = min(1.0, surprise + 0.15)
    if "..." in text:
        sadness = min(1.0, sadness + 0.1)

    # Extended sadness keywords (from text)
    sadness_words = ["sorry", "sad", "sigh", "unfortunate", "apologize",
                     "depressed", "lonely", "miss", "heartbroken", "gloomy",
                     "tears", "cry", "disappointed", "wistful", "melancholy"]
    if any(k in lower for k in sadness_words):
        sadness = min(1.0, sadness + 0.15)

    # Extended frustration keywords
    frustration_words = ["ugh", "argh", "stupid", "useless", "broken",
                         "not working", "impossible", "hate", "disgusting",
                         "horrible", "terrible", "annoying"]
    if any(k in lower for k in frustration_words):
        anger = min(1.0, anger + 0.12)

    # Disgust — reactive, not dead
    disgust_words = ["disgust", "gross", "yuck", "eww", "nasty", "repulsive",
                     "sickening", "revolting", "vile", "icky"]
    disgust = 0.02  # baseline
    if any(k in lower for k in disgust_words):
        disgust = min(0.5, disgust + 0.25)

    # Confidence boost
    confidence_words = ["definitely", "absolutely", "will do", "got this",
                        "no problem", "sure", "confident", "certain"]
    if any(k in lower for k in confidence_words):
        happiness = min(1.0, happiness + 0.1)

    # Curiosity boost
    curiosity_words = ["wonder", "hmm", "huh", "what if", "tell me",
                       "explain", "curious", "interesting"]
    if any(k in lower for k in curiosity_words):
        surprise = min(1.0, surprise + 0.1)

    # Surprise boost
    surprise_words = ["wow", "omg", "whoa", "no way", "incredible",
                      "unbelievable", "shocking"]
    if any(k in lower for k in surprise_words):
        surprise = min(1.0, surprise + 0.15)

    # Excessive exclamation marks = heightened state
    excl_count = text.count("!")
    if excl_count >= 3:
        happiness = min(1.0, happiness + 0.1)
        surprise = min(1.0, surprise + 0.05)

    # ALL CAPS words (shouting) — boost anger or excitement
    caps_words = [w for w in text.split() if w.isupper() and len(w) > 2]
    if len(caps_words) >= 2:
        if anger > 0.3:
            anger = min(1.0, anger + 0.15)
        else:
            excitement = min(1.0, happiness + 0.1)

    # ============================================================================
    # HIGH-INTENSITY expressive triggers — amplify the dominant emotion strongly
    # so TTS voice and Live2D face are visibly/audibly expressive
    # ============================================================================
    expressive_label = None
    for pattern, label, deltas in _EXPRESSIVE_TRIGGERS:
        if re.search(pattern, lower):
            expressive_label = label
            for attr, delta in deltas.items():
                if attr == "happiness":
                    happiness = min(1.0, max(0.0, happiness + delta))
                elif attr == "sadness":
                    sadness = min(1.0, max(0.0, sadness + delta))
                elif attr == "fear":
                    fear = min(1.0, max(0.0, fear + delta))
                elif attr == "surprise":
                    surprise = min(1.0, max(0.0, surprise + delta))
                elif attr == "anger":
                    anger = min(1.0, max(0.0, anger + delta))
                elif attr == "disgust":
                    disgust = min(1.0, max(0.0, disgust + delta))
                elif attr == "excitement":
                    # excitement maps to happiness + surprise in Zonos
                    happiness = min(1.0, max(0.0, happiness + delta * 0.6))
                    surprise = min(1.0, max(0.0, surprise + delta * 0.4))
            break  # only apply the first (strongest) matching trigger

    # Neutral weight balances the distribution
    total_active = happiness + sadness + fear + surprise + anger + disgust
    neutral = max(0.05, 1.0 - (total_active * 0.6))
    other = max(0.02, 0.15 - (total_active * 0.1))  # reactive, not dead

    return {
        "happiness": round(min(1.0, max(0.0, happiness)), 3),
        "sadness": round(min(1.0, max(0.0, sadness)), 3),
        "disgust": round(min(1.0, max(0.0, disgust)), 3),
        "fear": round(min(1.0, max(0.0, fear)), 3),
        "surprise": round(min(1.0, max(0.0, surprise)), 3),
        "anger": round(min(1.0, max(0.0, anger)), 3),
        "other": round(min(1.0, max(0.0, other)), 3),
        "neutral": round(min(1.0, max(0.05, neutral)), 3),
        "expressive_label": expressive_label,
    }


async def _tts_zonos(clean_text: str, req: TTSRequest) -> GeneratedAudio | None:
    """Try Zonos TTS (primary engine). Returns reusable audio bytes."""
    import httpx

    await _prepare_tts_engine("zonos")
    zonos_url = settings.tts.zonos_url
    request_voice_ref = getattr(req, "voice_ref", None)
    if request_voice_ref:
        # A one-off request reference should not silently replace the user's
        # saved voice preference; it is still copied for durable inference.
        voice_ref = _ensure_project_voice_reference(request_voice_ref)
    else:
        voice_ref = _adopt_project_voice_reference(settings.tts.voice_ref or None)
    seed = (
        random.randint(0, 2**31 - 1)
        if settings.tts.seed_mode == "random"
        else settings.tts.seed
    )

    is_smart = (
        settings.tts.emotion_mode == "smart"
        if getattr(req, "smart_emotions", None) is None
        else req.smart_emotions
    )

    if is_smart:
        try:
            from app.db.session import async_session_factory
            async with async_session_factory() as session:
                character_state = await load_character_state(session)
                emotions = _compute_smart_emotions(character_state, clean_text)
        except Exception:
            emotions = {
                "happiness": 0.35, "sadness": 0.05, "disgust": 0.02,
                "fear": 0.02, "surprise": 0.1, "anger": 0.02,
                "other": 0.05, "neutral": 0.39,
            }
        happiness = emotions["happiness"]
        sadness = emotions["sadness"]
        disgust = emotions["disgust"]
        fear = emotions["fear"]
        surprise = emotions["surprise"]
        anger = emotions["anger"]
        other = emotions["other"]
        neutral = emotions["neutral"]
    else:
        happiness = settings.tts.happiness
        sadness = settings.tts.sadness
        disgust = settings.tts.disgust
        fear = settings.tts.fear
        surprise = settings.tts.surprise
        anger = settings.tts.anger
        other = settings.tts.other
        neutral = settings.tts.neutral

    payload = {
        "text": clean_text,
        "language": settings.tts.language,
        "happiness": happiness,
        "sadness": sadness,
        "disgust": disgust,
        "fear": fear,
        "surprise": surprise,
        "anger": anger,
        "other": other,
        "neutral": neutral,
        "speaking_rate": settings.tts.speaking_rate,
        "pitch_std": settings.tts.pitch_std,
        "fmax": settings.tts.fmax,
        "vq_score": settings.tts.vq_score,
        "dnsmos_ovrl": settings.tts.dnsmos_ovrl,
        "cfg_scale": settings.tts.cfg_scale,
        "seed": seed,
    }
    if voice_ref:
        payload["voice_ref"] = voice_ref

    try:
        # Local Zonos generation can legitimately take 20–60 seconds on the
        # first request while the model warms up. Do not replace a valid cloned
        # voice with Edge/Index fallback just because the read timeout is too
        # short for local inference.
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=1.0)) as client:
            resp = await client.post(f"{zonos_url}/tts", json=payload)
            if resp.status_code == 200:
                return GeneratedAudio(resp.content, "audio/wav", "tts.wav")
    except Exception as e:
        logger.warning(f"Zonos TTS unavailable ({e}), trying fallback...")
    return None


async def _tts_indextts(clean_text: str, voice: str) -> GeneratedAudio | None:
    """Try Index-TTS (alternative engine). Returns reusable audio bytes."""
    import httpx

    await _prepare_tts_engine("indextts")
    indextts_url = settings.tts.indextts_url
    voice_ref = _adopt_project_voice_reference(settings.tts.voice_ref or None)

    payload = {"text": clean_text, "lang": "EN", "duration_factor": 1.0}
    if voice_ref:
        payload["voice_ref"] = voice_ref

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=1.0)) as client:
            resp = await client.post(f"{indextts_url}/tts", json=payload)
            if resp.status_code == 200:
                return GeneratedAudio(resp.content, "audio/wav", "tts.wav")
    except Exception as e:
        logger.warning(f"Index-TTS unavailable ({e}), trying fallback...")
    return None


_VOICE_MAP: dict[str, str] = {
    # Direct Azure / Edge-TTS Voice Identifiers
    "en-us-ananeural": "en-US-AnaNeural",
    "en-us-jennyneural": "en-US-JennyNeural",
    "en-gb-sonianeural": "en-GB-SoniaNeural",
    "ja-jp-nanamineural": "ja-JP-NanamiNeural",
    "en-us-guyneural": "en-US-GuyNeural",
    "en-gb-ryanneural": "en-GB-RyanNeural",
    "en-us-arianeural": "en-US-AriaNeural",
    "en-us-ericneural": "en-US-EricNeural",
    "en-us-christopherneural": "en-US-ChristopherNeural",
    "en-gb-libbyneural": "en-GB-LibbyNeural",

    # Preset Aliases & Names
    "ana": "en-US-AnaNeural",
    "jenny": "en-US-JennyNeural",
    "sonia": "en-GB-SoniaNeural",
    "nanami": "ja-JP-NanamiNeural",
    "guy": "en-US-GuyNeural",
    "ryan": "en-GB-RyanNeural",

    # Zonos Character Mappings
    "aiko": "en-US-AnaNeural",
    "seraphina": "en-US-JennyNeural",
    "rei": "en-GB-SoniaNeural",
    "luna": "ja-JP-NanamiNeural",
    "ren": "en-US-GuyNeural",
    "kael": "en-GB-RyanNeural",
    "onokami": "en-US-AnaNeural",

    # Index-TTS Reference WAV Mappings
    "voices/female_sweet.wav": "en-US-AnaNeural",
    "voices/female_warm.wav": "en-US-JennyNeural",
    "voices/female_energetic.wav": "ja-JP-NanamiNeural",
    "voices/female_refined.wav": "en-GB-SoniaNeural",
    "voices/male_hero.wav": "en-US-GuyNeural",
    "voices/male_deep.wav": "en-GB-RyanNeural",

    "yuna": "en-US-AnaNeural",
    "maya": "en-US-JennyNeural",
    "chika": "ja-JP-NanamiNeural",
    "elena": "en-GB-SoniaNeural",
    "alex": "en-US-GuyNeural",
    "marcus": "en-GB-RyanNeural",
}


def _format_rate_pitch(
    speaking_rate: float | None = None,
    pitch_std: float | None = None,
    happiness: float | None = None,
    sadness: float | None = None,
    anger: float | None = None,
) -> tuple[str, str]:
    rate_val = speaking_rate if speaking_rate is not None else settings.tts.speaking_rate
    pitch_val = pitch_std if pitch_std is not None else settings.tts.pitch_std
    hap = happiness if happiness is not None else settings.tts.happiness
    sad = sadness if sadness is not None else settings.tts.sadness
    ang = anger if anger is not None else settings.tts.anger

    # Rate percentage
    rate_pct = 0
    if rate_val is not None:
        if rate_val > 5.0:
            rate_pct = int((rate_val - 15.0) / 15.0 * 100)
        else:
            rate_pct = int((rate_val - 1.0) * 100)
    rate_pct = max(-50, min(50, rate_pct))
    rate_str = f"{rate_pct:+d}%"

    # Pitch Hz
    pitch_hz = 0
    if pitch_val is not None:
        if pitch_val > 10.0:
            pitch_hz = int((pitch_val - 45.0) * 0.75)
        else:
            pitch_hz = int((pitch_val - 1.0) * 25.0)

    if (hap or 0) > 0.3:
        pitch_hz += int(hap * 14)
    if (ang or 0) > 0.3:
        pitch_hz += int(ang * 18)
    if (sad or 0) > 0.3:
        pitch_hz -= int(sad * 16)

    pitch_hz = max(-45, min(45, pitch_hz))
    pitch_str = f"{pitch_hz:+d}Hz"

    return rate_str, pitch_str


def _resolve_edge_voice(voice: str | None) -> str:
    """Resolve voice string, voice_ref, or gender keyword into a valid Edge-TTS neural voice."""
    raw = voice or settings.tts.voice_ref or settings.tts.engine or "default"
    v = str(raw).strip()
    v_lower = v.lower()

    if v_lower in _VOICE_MAP:
        return _VOICE_MAP[v_lower]

    # Check substring matches in _VOICE_MAP
    for key, mapped_voice in _VOICE_MAP.items():
        if key in v_lower:
            return mapped_voice

    # Valid Azure/Edge neural voice ID format (e.g., 'en-US-JennyNeural')
    if "neural" in v_lower and "-" in v:
        return v

    # Male voice detection
    if any(k in v_lower for k in ["male", "guy", "ryan", "hero", "deep", "ren", "kael", "boy", "man", "alex", "marcus"]):
        if any(k in v_lower for k in ["british", "ryan", "uk", "kael", "marcus"]):
            return "en-GB-RyanNeural"
        return "en-US-GuyNeural"

    # Female voice detection
    if any(k in v_lower for k in ["british", "sonia", "uk", "rei", "elena"]):
        return "en-GB-SoniaNeural"
    if any(k in v_lower for k in ["nanami", "anime", "japan", "ja", "luna", "chika"]):
        return "ja-JP-NanamiNeural"
    if any(k in v_lower for k in ["jenny", "warm", "maya", "seraphina"]):
        return "en-US-JennyNeural"
    if any(k in v_lower for k in ["aria", "story"]):
        return "en-US-AriaNeural"

    return "en-US-AnaNeural"


async def _tts_edge(clean_text: str, voice: str | None = None, req: TTSRequest | None = None) -> GeneratedAudio:
    """Edge-TTS generation with full voice, rate, and pitch synthesis."""
    voice_id = _resolve_edge_voice(voice)
    rate_str, pitch_str = _format_rate_pitch(
        speaking_rate=getattr(req, "speaking_rate", None),
        pitch_std=getattr(req, "pitch_std", None),
        happiness=getattr(req, "happiness", None),
        sadness=getattr(req, "sadness", None),
        anger=getattr(req, "anger", None),
    )
    try:
        communicate = edge_tts.Communicate(clean_text, voice_id, rate=rate_str, pitch=pitch_str)
        audio_chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        if not audio_chunks:
            # Fallback to plain communicate
            communicate = edge_tts.Communicate(clean_text, voice_id)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
        if not audio_chunks:
            raise HTTPException(status_code=500, detail="Edge-TTS generated empty audio")
        audio_data = b"".join(audio_chunks)
        return GeneratedAudio(audio_data, "audio/mpeg", "tts.mp3")
    except Exception as e:
        logger.error(f"Edge-TTS generation error with voice {voice_id}: {e}")
        raise HTTPException(status_code=500, detail=f"TTS generation error: {e}")


async def _tts_openrouter(clean_text: str, req: TTSRequest) -> GeneratedAudio:
    """Generate speech through OpenRouter's OpenAI-compatible speech API.

    This is deliberately a direct hosted-provider option.  It never falls
    back to a local engine when selected, so a missing key or provider error
    is visible instead of silently producing a different voice.
    """
    await _prepare_tts_engine("openrouter")
    cfg = settings.tts
    key_env = (cfg.openrouter_api_key_env or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
    api_key = os.environ.get(key_env, "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"OpenRouter TTS is selected but {key_env} is not set in the backend environment",
        )

    model = (getattr(req, "openrouter_model", None) or cfg.openrouter_model).strip()
    voice = (getattr(req, "openrouter_voice", None) or cfg.openrouter_voice or "").strip()
    response_format = (
        getattr(req, "openrouter_response_format", None)
        or cfg.openrouter_response_format
        or "mp3"
    ).strip().lower()
    # OpenRouter documents MP3 and PCM output. The shared web/Discord TTS
    # path expects a self-describing browser/decodeable file, so keep MP3 as
    # the safe format instead of handing raw PCM to an audio player.
    if response_format != "mp3":
        raise HTTPException(status_code=422, detail="OpenRouter TTS response format must be mp3")
    requested_speed = getattr(req, "openrouter_speed", None)
    speed = float(requested_speed if requested_speed is not None else cfg.openrouter_speed)
    speed = min(4.0, max(0.25, speed))

    payload = {
        "input": clean_text,
        "model": model,
        "response_format": response_format,
        "speed": speed,
    }
    if voice:
        payload["voice"] = voice
    base_url = (cfg.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "AI VTuber",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            response = await client.post(f"{base_url}/audio/speech", headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("OpenRouter TTS request failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"OpenRouter TTS request failed: {exc}") from exc

    if response.status_code >= 400:
        detail = "OpenRouter rejected the TTS request"
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or detail)
            elif error:
                detail = str(error)
        except Exception:
            if response.text.strip():
                detail = response.text.strip()[:500]
        raise HTTPException(status_code=502, detail=detail)
    if not response.content:
        raise HTTPException(status_code=502, detail="OpenRouter returned empty TTS audio")

    return GeneratedAudio(response.content, "audio/mpeg", "tts-openrouter.mp3")


async def _generate_tts_audio(req: TTSRequest) -> GeneratedAudio:
    """Generate reusable TTS bytes using the same engine/fallback path as the web UI."""
    clean_text = _clean_for_tts(req.text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="No speakable text after cleaning")

    engine = req.engine or settings.tts.engine
    active_voice = req.voice_ref or req.voice or settings.tts.voice_ref

    # Hosted OpenRouter speech is explicit and does not silently switch to a
    # local voice if the provider is unavailable.
    if engine == "openrouter":
        return await _tts_openrouter(clean_text, req)

    # Try requested local engine first, then the existing fallback chain.
    if engine == "zonos":
        result = await _tts_zonos(clean_text, req)
        if result:
            return result
        # Fallback to indextts then edge-tts
        result = await _tts_indextts(clean_text, active_voice)
        if result:
            return result
        await _prepare_tts_engine("edge-tts")
        return await _tts_edge(clean_text, active_voice, req)

    elif engine == "indextts":
        result = await _tts_indextts(clean_text, active_voice)
        if result:
            return result
        # Fallback to zonos then edge-tts
        result = await _tts_zonos(clean_text, req)
        if result:
            return result
        await _prepare_tts_engine("edge-tts")
        return await _tts_edge(clean_text, active_voice, req)

    else:  # edge-tts (or unknown)
        await _prepare_tts_engine("edge-tts")
        return await _tts_edge(clean_text, active_voice, req)


@router.post("/tts")
async def text_to_speech(req: TTSRequest) -> StreamingResponse:
    """Generate speech audio for the browser."""

    async with _channel_runtime_scope(req.master_preset_id):
        audio = await _generate_tts_audio(req)
    return StreamingResponse(
        io.BytesIO(audio.data),
        media_type=audio.media_type,
        headers={"Content-Disposition": f"attachment; filename={audio.filename}"},
    )


# ---------------------------------------------------------------------------
# TTS voice management endpoints
# ---------------------------------------------------------------------------

@router.get("/tts/voices")
async def list_tts_voices() -> dict:
    """List available reference voices from all TTS engines."""
    import httpx

    # OpenRouter voices are provider/model-specific and are intentionally
    # user-configurable rather than guessed from local voice catalogs.
    voices: dict[str, list] = {"zonos": [], "indextts": [], "edge": [], "openrouter": []}

    # Zonos voices
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.tts.zonos_url}/voices")
            if resp.status_code == 200:
                voices["zonos"] = resp.json().get("voices", [])
    except Exception:
        pass

    # Index-TTS voices
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.tts.indextts_url}/voices")
            if resp.status_code == 200:
                voices["indextts"] = resp.json().get("voices", [])
    except Exception:
        pass

    # Edge-TTS voices (static map)
    voices["edge"] = [{"name": k, "path": v} for k, v in _VOICE_MAP.items()]

    return voices


@router.post("/tts/upload-voice")
async def upload_tts_voice(file: UploadFile) -> dict:
    """Upload a reference audio file for voice cloning."""
    import httpx

    # Read the upload once so the same bytes can be sent to a running Zonos
    # service and retained by the local fallback when the service is offline.
    content = await file.read()
    filename = Path(file.filename or "uploaded_voice.wav").name
    if not content:
        raise HTTPException(status_code=400, detail="Reference audio file is empty")

    # Persist the sample before contacting an optional engine. The returned
    # project path is what presets/configuration store; the engine's own copy
    # is only an optimization and is never the source of truth.
    project_path = _store_voice_bytes(filename, content)

    # Try Zonos server first
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {"file": (filename, content, file.content_type)}
            resp = await client.post(f"{settings.tts.zonos_url}/upload-voice", files=files)
            if resp.status_code == 200:
                # Return the project-owned path to the editor as a draft; the
                # active config changes only when the user explicitly saves.
                service_response = resp.json()
                return {
                    "path": str(project_path),
                    "name": project_path.name,
                    "service_path": service_response.get("path"),
                }
    except httpx.ConnectError:
        pass

    # Fallback: the project copy is already durable and ready to use.
    return {"path": str(project_path), "name": project_path.name}


@router.get("/tts/settings")
async def get_tts_settings() -> dict:
    """Get current TTS configuration."""
    project_voice_ref = _ensure_project_voice_reference(settings.tts.voice_ref)
    if project_voice_ref and project_voice_ref != settings.tts.voice_ref:
        settings.tts.voice_ref = project_voice_ref
    return {
        "engine": settings.tts.engine,
        "voice_ref": project_voice_ref or settings.tts.voice_ref,
        "language": settings.tts.language,
        "happiness": settings.tts.happiness,
        "sadness": settings.tts.sadness,
        "disgust": settings.tts.disgust,
        "fear": settings.tts.fear,
        "surprise": settings.tts.surprise,
        "anger": settings.tts.anger,
        "other": settings.tts.other,
        "neutral": settings.tts.neutral,
        "speaking_rate": settings.tts.speaking_rate,
        "pitch_std": settings.tts.pitch_std,
        "fmax": settings.tts.fmax,
        "vq_score": settings.tts.vq_score,
        "dnsmos_ovrl": settings.tts.dnsmos_ovrl,
        "cfg_scale": settings.tts.cfg_scale,
        "seed": settings.tts.seed,
        "seed_mode": settings.tts.seed_mode,
        "voice_gender": settings.tts.voice_gender,
        "openrouter_base_url": settings.tts.openrouter_base_url,
        "openrouter_api_key_env": settings.tts.openrouter_api_key_env,
        "openrouter_model": settings.tts.openrouter_model,
        "openrouter_voice": settings.tts.openrouter_voice,
        "openrouter_response_format": settings.tts.openrouter_response_format,
        "openrouter_speed": settings.tts.openrouter_speed,
        "fish_audio_base_url": settings.tts.fish_audio_base_url,
        "fish_audio_api_key_env": settings.tts.fish_audio_api_key_env,
    }


@router.post("/tts/settings")
async def update_tts_settings(req: SettingsUpdate) -> dict:
    """Update TTS configuration."""
    tts_fields = {
        "tts_engine": "engine", "tts_voice_ref": "voice_ref", "tts_language": "language",
        "tts_happiness": "happiness", "tts_sadness": "sadness", "tts_disgust": "disgust",
        "tts_fear": "fear", "tts_surprise": "surprise", "tts_anger": "anger",
        "tts_other": "other", "tts_neutral": "neutral",
        "tts_speaking_rate": "speaking_rate", "tts_pitch_std": "pitch_std",
        "tts_fmax": "fmax", "tts_vq_score": "vq_score",
        "tts_dnsmos_ovrl": "dnsmos_ovrl", "tts_cfg_scale": "cfg_scale",
        "tts_seed": "seed", "tts_seed_mode": "seed_mode", "tts_voice_gender": "voice_gender",
        "tts_openrouter_base_url": "openrouter_base_url", "tts_openrouter_api_key_env": "openrouter_api_key_env",
        "tts_openrouter_model": "openrouter_model", "tts_openrouter_voice": "openrouter_voice",
        "tts_openrouter_response_format": "openrouter_response_format", "tts_openrouter_speed": "openrouter_speed",
        "tts_fish_audio_base_url": "fish_audio_base_url", "tts_fish_audio_api_key_env": "fish_audio_api_key_env",
    }
    for field_name, attr_name in tts_fields.items():
        value = getattr(req, field_name, None)
        if value is not None:
            if field_name == "tts_voice_ref":
                value = _ensure_project_voice_reference(value)
            setattr(settings.tts, attr_name, value)
    return await get_tts_settings()


@router.get("/tts/openrouter/key-status")
async def get_openrouter_key_status() -> dict:
    """Return only whether the configured OpenRouter key exists."""

    env_name = (settings.tts.openrouter_api_key_env or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
    value = os.environ.get(env_name, "").strip()
    return {
        "configured": bool(value),
        "env_name": env_name,
        "masked": f"••••{value[-4:]}" if len(value) >= 4 else ("••••" if value else ""),
    }


@router.post("/tts/openrouter/key")
async def save_openrouter_key(req: OpenRouterKeyUpdate) -> dict:
    """Store a key in backend/.env and return a non-secret status summary."""

    env_name = (req.env_name or settings.tts.openrouter_api_key_env or "OPENROUTER_API_KEY").strip()
    _persist_openrouter_api_key(env_name, req.api_key)
    if settings.tts.openrouter_api_key_env != env_name:
        settings.tts.openrouter_api_key_env = env_name
        save_config(settings)
    return await get_openrouter_key_status()


@router.get("/tts/fish/key-status")
async def get_fish_audio_key_status() -> dict:
    """Return whether a Fish Audio directory-search key is configured."""

    env_name = (settings.tts.fish_audio_api_key_env or "FISH_AUDIO_API_KEY").strip() or "FISH_AUDIO_API_KEY"
    value = os.environ.get(env_name, "").strip()
    return {
        "configured": bool(value),
        "env_name": env_name,
        "masked": f"••••{value[-4:]}" if len(value) >= 4 else ("••••" if value else ""),
    }


@router.post("/tts/fish/key")
async def save_fish_audio_key(req: FishAudioKeyUpdate) -> dict:
    """Store the Fish Audio lookup key in backend/.env, never in settings."""

    env_name = (req.env_name or settings.tts.fish_audio_api_key_env or "FISH_AUDIO_API_KEY").strip()
    _persist_openrouter_api_key(env_name, req.api_key)
    if settings.tts.fish_audio_api_key_env != env_name:
        settings.tts.fish_audio_api_key_env = env_name
        save_config(settings)
    return await get_fish_audio_key_status()


@router.get("/tts/fish/voices")
async def list_fish_audio_voices(
    q: str | None = None,
    page: int = 1,
    page_size: int = 24,
    licensed: bool | None = None,
) -> dict:
    """Search Fish Audio voice models and return safe metadata for the UI.

    Fish Audio's model directory requires a Fish API token.  This endpoint is
    intentionally separate from OpenRouter model search: the returned
    ``_id`` is the Fish voice/reference ID that can be entered into an
    OpenRouter provider which supports Fish voice IDs.
    """

    key_env = (settings.tts.fish_audio_api_key_env or "FISH_AUDIO_API_KEY").strip() or "FISH_AUDIO_API_KEY"
    api_key = os.environ.get(key_env, "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"Fish Audio voice search requires {key_env} in the backend environment",
        )
    try:
        bounded_page = max(1, int(page))
        bounded_page_size = min(100, max(1, int(page_size)))
    except (TypeError, ValueError):
        bounded_page, bounded_page_size = 1, 24
    params: dict[str, str | int | bool] = {
        "page_number": bounded_page,
        "page_size": bounded_page_size,
        "sort_by": "score",
    }
    query = (q or "").strip()
    if query:
        params["title"] = query[:120]
    if licensed is not None:
        params["licensed"] = licensed
    base_url = (settings.tts.fish_audio_base_url or "https://api.fish.audio").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.get(f"{base_url}/model", headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Fish Audio voice search failed: {exc}") from exc
    if response.status_code in {401, 403}:
        raise HTTPException(status_code=401, detail="Fish Audio rejected the API key")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="Fish Audio rate limit reached; try again shortly")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Fish Audio voice search failed ({response.status_code})")
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Fish Audio returned invalid voice metadata") from exc
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        raw_items = []
    voices: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        voice_id = str(item.get("_id") or item.get("id") or "").strip()
        if not voice_id:
            continue
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        voices.append({
            "id": voice_id,
            "title": str(item.get("title") or voice_id),
            "description": str(item.get("description") or ""),
            "author": str(author.get("nickname") or author.get("_id") or ""),
            "tags": [str(tag) for tag in (item.get("tags") or []) if tag is not None],
            "languages": [str(language) for language in (item.get("languages") or []) if language is not None],
            "visibility": str(item.get("visibility") or ""),
            "licensed": bool(item.get("licensed", False)),
            "like_count": item.get("like_count", 0),
            "url": f"https://fish.audio/model/{voice_id}",
        })
    return {
        "voices": voices,
        "total": payload.get("total") if isinstance(payload, dict) else len(voices),
        "has_more": bool(payload.get("has_more", False)) if isinstance(payload, dict) else False,
        "page": bounded_page,
        "page_size": bounded_page_size,
    }


@router.get("/tts/openrouter/models")
async def list_openrouter_tts_models(q: str | None = None, limit: int = 100) -> dict:
    """Fetch searchable speech-model metadata from OpenRouter.

    This intentionally uses the configured OpenRouter key and endpoint only;
    it does not add a direct Fish Audio TTS provider. Fish community voice
    references are provider-specific and are not always included in
    OpenRouter's model metadata.
    """
    key_env = (settings.tts.openrouter_api_key_env or "OPENROUTER_API_KEY").strip() or "OPENROUTER_API_KEY"
    api_key = os.environ.get(key_env, "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"OpenRouter model search requires {key_env} in the backend environment",
        )
    try:
        bounded_limit = min(1000, max(1, int(limit)))
    except (TypeError, ValueError):
        bounded_limit = 100
    params: dict[str, str | int] = {
        "output_modalities": "speech",
        "limit": bounded_limit,
    }
    query = (q or "").strip()
    if query:
        params["q"] = query[:120]
    base_url = (settings.tts.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "http://localhost:5173",
        "X-Title": "AI VTuber",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            response = await client.get(f"{base_url}/models", headers=headers, params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"OpenRouter model search failed: {exc}") from exc
    if response.status_code >= 400:
        detail = "OpenRouter rejected the model search request"
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or detail)
            elif error:
                detail = str(error)
        except Exception:
            if response.text.strip():
                detail = response.text.strip()[:500]
        raise HTTPException(status_code=502, detail=detail)
    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="OpenRouter returned invalid model metadata") from exc
    raw_models = body.get("data", []) if isinstance(body, dict) else body
    models: list[dict[str, object]] = []
    for item in raw_models if isinstance(raw_models, list) else []:
        if not isinstance(item, dict):
            continue
        architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        voices = item.get("supported_voices")
        if not isinstance(voices, list):
            voices = []
        models.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "canonical_slug": str(item.get("canonical_slug") or item.get("id") or ""),
            "description": str(item.get("description") or ""),
            "supported_voices": [str(voice) for voice in voices if voice is not None],
            "output_modalities": architecture.get("output_modalities", []),
            "prompt_price": pricing.get("prompt"),
            "completion_price": pricing.get("completion"),
            "context_length": item.get("context_length"),
        })
    return {"query": query, "models": models, "total_count": body.get("total_count", len(models)) if isinstance(body, dict) else len(models)}


# ---------------------------------------------------------------------------
# STT endpoint (faster-whisper, local GPU/CPU with model library & downloader)
# ---------------------------------------------------------------------------

WHISPER_MODELS_CATALOG = [
    {
        "id": "tiny",
        "name": "Whisper Tiny (Multi-lingual)",
        "params": "39M",
        "size_mb": 75,
        "vram_mb": 350,
        "relative_speed": "32x",
        "wer": "10.2%",
        "description": "Ultra-fast, lowest memory usage. Ideal for instant voice commands.",
    },
    {
        "id": "tiny.en",
        "name": "Whisper Tiny (English-only)",
        "params": "39M",
        "size_mb": 75,
        "vram_mb": 350,
        "relative_speed": "32x",
        "wer": "9.8%",
        "description": "Specialized English model with low compute overhead.",
    },
    {
        "id": "base",
        "name": "Whisper Base (Multi-lingual)",
        "params": "74M",
        "size_mb": 145,
        "vram_mb": 500,
        "relative_speed": "16x",
        "wer": "8.1%",
        "description": "Balanced speed and accuracy. Excellent default companion choice.",
    },
    {
        "id": "base.en",
        "name": "Whisper Base (English-only)",
        "params": "74M",
        "size_mb": 145,
        "vram_mb": 500,
        "relative_speed": "16x",
        "wer": "7.6%",
        "description": "Optimized English baseline for conversation.",
    },
    {
        "id": "small",
        "name": "Whisper Small (Multi-lingual)",
        "params": "244M",
        "size_mb": 480,
        "vram_mb": 1020,
        "relative_speed": "6x",
        "wer": "5.8%",
        "description": "High accuracy multi-language model for accurate speech.",
    },
    {
        "id": "small.en",
        "name": "Whisper Small (English-only)",
        "params": "244M",
        "size_mb": 480,
        "vram_mb": 1020,
        "relative_speed": "6x",
        "wer": "5.4%",
        "description": "Crisp recognition for English dialogue and stream audio.",
    },
    {
        "id": "medium",
        "name": "Whisper Medium (Multi-lingual)",
        "params": "769M",
        "size_mb": 1530,
        "vram_mb": 2600,
        "relative_speed": "2x",
        "wer": "4.2%",
        "description": "Near-human accuracy across dozens of languages.",
    },
    {
        "id": "medium.en",
        "name": "Whisper Medium (English-only)",
        "params": "769M",
        "size_mb": 1530,
        "vram_mb": 2600,
        "relative_speed": "2x",
        "wer": "3.9%",
        "description": "Exceptional English precision with background noise rejection.",
    },
    {
        "id": "distil-large-v3",
        "name": "Distil-Whisper Large v3",
        "params": "756M",
        "size_mb": 1510,
        "vram_mb": 2400,
        "relative_speed": "6x",
        "wer": "3.8%",
        "description": "Distilled architecture: 6x faster with Large-v3 level accuracy.",
    },
    {
        "id": "large-v3",
        "name": "Whisper Large v3 (Studio)",
        "params": "1550M",
        "size_mb": 3100,
        "vram_mb": 4500,
        "relative_speed": "1x",
        "wer": "3.2%",
        "description": "State of the art benchmark for studio speech recognition.",
    },
    {
        "id": "large-v3-turbo",
        "name": "Whisper Large v3 Turbo",
        "params": "809M",
        "size_mb": 1620,
        "vram_mb": 2200,
        "relative_speed": "8x",
        "wer": "3.3%",
        "description": "Latest turbo architecture. Studio accuracy at high speed.",
    },
]


def _is_whisper_downloaded(model_id: str) -> bool:
    import os
    import glob
    hf_home = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface/hub")
    clean_id = model_id.replace("/", "--")
    patterns = [
        f"{hf_home}/models--Systran--faster-whisper-{clean_id}*",
        f"{hf_home}/models--Systran--faster-distil-whisper-{clean_id}*",
        f"{hf_home}/models--openai--whisper-{clean_id}*",
        f"{hf_home}/models--Systran--{clean_id}*",
        f"{hf_home}/models--*{clean_id}*",
    ]
    for p in patterns:
        if glob.glob(p):
            return True
    return False


def _setup_cuda_dlls() -> None:
    """Register CUDA runtime DLL directories on Windows for CTranslate2."""
    import sys
    import os
    if sys.platform != "win32":
        return
    venv_dir = os.path.dirname(sys.executable)
    site_packages = os.path.normpath(os.path.join(venv_dir, "..", "Lib", "site-packages"))
    if not os.path.exists(site_packages):
        site_packages = os.path.normpath(os.path.join(venv_dir, "Lib", "site-packages"))

    if os.path.exists(site_packages):
        for root, _, files in os.walk(site_packages):
            if any(f.lower().endswith(".dll") for f in files) and "nvidia" in root.lower():
                try:
                    os.add_dll_directory(root)
                except Exception:
                    pass
                if root not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")


_setup_cuda_dlls()


_whisper_instance: WhisperModel | None = None
_whisper_instance_key: str = ""


def _unload_whisper() -> None:
    """Release the previous CTranslate2 model before a model/provider switch."""
    global _whisper_instance, _whisper_instance_key
    if _whisper_instance is None:
        return
    try:
        del _whisper_instance
    except Exception:
        pass
    _whisper_instance = None
    _whisper_instance_key = ""
    try:
        import gc
        gc.collect()
    except Exception:
        pass


def _get_whisper() -> WhisperModel:
    global _whisper_instance, _whisper_instance_key
    model_name = settings.stt.model or "base"
    # Nemotron is served by the native sidecar. If the sidecar is unavailable,
    # use a known Faster-Whisper compatibility model instead of passing a
    # Nemotron ID to CTranslate2.
    if str(model_name).startswith("nemotron-"):
        model_name = "distil-large-v3"
    device = settings.stt.device

    if device == "auto" or not device:
        import ctranslate2
        device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"

    compute_type = settings.stt.compute_type or "float16"
    if device == "cuda" and compute_type == "int8":
        compute_type = "float16"
    elif device == "cpu" and compute_type == "float16":
        compute_type = "int8"

    target_id = "Systran/faster-distil-whisper-large-v3" if model_name == "distil-large-v3" else model_name
    key = f"{target_id}:{device}:{compute_type}"

    if _whisper_instance is None or _whisper_instance_key != key:
        if _whisper_instance is not None:
            _unload_whisper()
        try:
            _whisper_instance = WhisperModel(target_id, device=device, compute_type=compute_type)
            _whisper_instance_key = key
            add_log("info", "stt", f"Loaded Whisper model '{model_name}' on {device} ({compute_type})")
        except Exception as e:
            logger.warning(f"Could not load Whisper model '{model_name}' on {device}: {e}. Falling back to CPU int8...")
            _whisper_instance = WhisperModel(target_id, device="cpu", compute_type="int8")
            _whisper_instance_key = f"{target_id}:cpu:int8"

    return _whisper_instance


@router.get("/stt/models")
async def list_stt_models() -> list[dict]:
    """List Nemotron and legacy Faster-Whisper models with runtime metadata."""
    result = []
    for m in NEMO_MODELS:
        result.append({
            **m,
            **model_status(m["id"]),
            "runtime_installation": nemo_install_status(),
            "is_active": settings.stt.model == m["id"],
        })
    for m in WHISPER_MODELS_CATALOG:
        is_dl = _is_whisper_downloaded(m["id"])
        result.append({
            **m,
            "provider": "faster_whisper",
            "runtime": "faster-whisper / CTranslate2",
            "streaming": False,
            "languages": "Multilingual" if ".en" not in m["id"] else "English",
            "license": "MIT",
            "license_url": "https://github.com/SYSTRAN/faster-whisper",
            "source_url": "https://huggingface.co/Systran",
            "license_accepted": True,
            "ready": is_dl,
            "downloaded": is_dl,
            "is_active": settings.stt.model == m["id"],
        })
    return result


@router.get("/stt/models/{model_id}/license")
async def get_stt_license(model_id: str) -> dict:
    model = nemo_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="License is only required for Nemotron models")
    return {
        "model": model_id,
        "license": model["license"],
        "license_url": model["license_url"],
        "source_url": model["source_url"],
        "accepted": license_accepted(model_id),
        "text": f"This model is distributed under the {model['license']}. Review the official terms before downloading or using it.",
    }


@router.post("/stt/models/{model_id}/license/accept")
async def accept_stt_license(model_id: str, req: dict | None = None) -> dict:
    try:
        return accept_license(model_id, str((req or {}).get("revision") or "main"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/stt/models/download")
async def download_stt_model(req: dict) -> dict:
    """Download an official model into the local cache."""
    import asyncio
    model_id = req.get("model", "base")
    nemo = nemo_model(model_id)
    if nemo:
        if not license_accepted(model_id, str(req.get("revision") or "main")):
            raise HTTPException(status_code=403, detail="Accept the model license before downloading")
        try:
            download = await start_nemo_download(model_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        add_log("info", "stt", f"Nemotron model '{model_id}' download {download['status']}")
        return {
            "status": download["status"],
            "model": model_id,
            "message": f"Downloading {nemo['filename']} in background",
            "download": download,
            "runtime_installation": nemo_install_status(),
        }

    target_id = "Systran/faster-distil-whisper-large-v3" if model_id == "distil-large-v3" else model_id
    add_log("info", "stt", f"Triggered download for Whisper model '{model_id}'...")

    def _download():
        try:
            WhisperModel(target_id, device="cpu", compute_type="int8")
            add_log("info", "stt", f"Whisper model '{model_id}' downloaded successfully.")
        except Exception as e:
            add_log("error", "stt", f"Failed downloading Whisper model '{model_id}': {e}")

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _download)
    return {"status": "downloading", "model": model_id, "message": f"Downloading {model_id} in background"}


@router.get("/stt/models/{model_id}/download-status")
async def get_stt_model_download_status(model_id: str) -> dict:
    """Return real byte progress/errors for a managed Nemotron download."""
    if not nemo_model(model_id):
        raise HTTPException(status_code=404, detail="Download progress is available for Nemotron models")
    return nemo_download_status(model_id)


@router.get("/stt/runtime")
async def stt_runtime_status() -> dict:
    """Return the actual selected runtime, readiness and CUDA diagnostics."""
    configured_provider = settings.stt.provider or ("nemo_speech" if str(settings.stt.model).startswith("nemotron-") else "faster_whisper")
    if configured_provider == "nemo_speech":
        status = await nemo_sidecar.runtime(settings.stt.model)
        status["configured_provider"] = configured_provider
        status["fallback_enabled"] = settings.stt.fallback_enabled
        status["fallback_active"] = not status.get("ready", False) and settings.stt.fallback_enabled
        status["chunk_ms"] = settings.stt.stream_chunk_ms
        return status

    try:
        import ctranslate2
        cuda_count = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda_count = 0
    return {
        "provider": "faster_whisper",
        "configured_provider": configured_provider,
        "model": settings.stt.model,
        "device": "cuda" if cuda_count > 0 and settings.stt.device != "cpu" else "cpu",
        "cuda_devices": cuda_count,
        "compute_type": settings.stt.compute_type,
        "ready": _whisper_instance is not None,
        "streaming": False,
        "fallback_enabled": settings.stt.fallback_enabled,
    }


async def _transcribe_with_nemo(audio_bytes: bytes, filename: str) -> dict[str, Any]:
    """Use the native sidecar for a batch-compatible transcription request."""
    nemo_sidecar.port = int(settings.stt.sidecar_port or 8092)
    ready = await nemo_sidecar.ensure(settings.stt.model, settings.stt.stream_chunk_ms)
    if not ready:
        raise RuntimeError(nemo_sidecar.error or "NeMo-Speech.cpp is not ready")
    language = settings.stt.stream_language or settings.stt.language or "auto"
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data = {"language": language, "model": settings.stt.model}
    sidecar_url = f"http://127.0.0.1:{settings.stt.sidecar_port or 8092}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=3.0)) as client:
        response = await client.post(f"{sidecar_url}/v1/audio/transcriptions", files=files, data=data)
        response.raise_for_status()
        payload = response.json()
    text = str(payload.get("text") or payload.get("transcript") or "").strip()
    return {
        "text": text,
        "language": payload.get("language") or language,
        "probability": payload.get("confidence"),
        "duration": payload.get("duration"),
        "runtime": "nemo-speech.cpp",
        "model": settings.stt.model,
    }


@router.post("/stt")
async def speech_to_text(
    file: UploadFile,
    master_preset_id: str | None = Form(default=None),
) -> dict[str, Any]:
    """Transcribe audio using the selected runtime with explicit fallback."""

    async with _channel_runtime_scope(master_preset_id):
        return await _speech_to_text_inner(file)


async def _speech_to_text_inner(file: UploadFile) -> dict[str, Any]:
    audio_bytes = await file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    configured_provider = settings.stt.provider or ("nemo_speech" if str(settings.stt.model).startswith("nemotron-") else "faster_whisper")
    if configured_provider == "nemo_speech":
        try:
            return await _transcribe_with_nemo(audio_bytes, file.filename or "audio.wav")
        except Exception as exc:
            if not settings.stt.fallback_enabled:
                raise HTTPException(status_code=503, detail=f"NeMo-Speech.cpp unavailable: {exc}") from exc
            logger.warning("NeMo-Speech.cpp unavailable; using Faster-Whisper fallback: %s", exc)

    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)

    try:
        model = _get_whisper()
        lang = None if settings.stt.language == "auto" else settings.stt.language
        try:
            segments, info = model.transcribe(
                str(tmp_path),
                language=lang,
                beam_size=settings.stt.beam_size or 5,
                vad_filter=settings.stt.vad_filter,
                temperature=settings.stt.temperature or 0.0,
            )
            text_parts = [seg.text.strip() for seg in segments if seg.text]
        except Exception as transcribe_err:
            err_str = str(transcribe_err).lower()
            if any(k in err_str for k in ["cublas", "cuda", "not found", "failed to load", "cudnn"]):
                logger.warning(f"CUDA execution failed ({transcribe_err}), falling back to CPU int8...")
                cpu_fallback_id = settings.stt.model or "base"
                if str(cpu_fallback_id).startswith("nemotron-"):
                    cpu_fallback_id = "distil-large-v3"
                cpu_target = "Systran/faster-distil-whisper-large-v3" if cpu_fallback_id == "distil-large-v3" else cpu_fallback_id
                cpu_model = WhisperModel(cpu_target, device="cpu", compute_type="int8")
                segments, info = cpu_model.transcribe(
                    str(tmp_path),
                    language=lang,
                    beam_size=settings.stt.beam_size or 5,
                    vad_filter=settings.stt.vad_filter,
                    temperature=settings.stt.temperature or 0.0,
                )
                text_parts = [seg.text.strip() for seg in segments if seg.text]
            else:
                raise transcribe_err

        text = " ".join(text_parts).strip()

        return {
            "text": text if text else "No speech detected in audio.",
            "language": getattr(info, "language", settings.stt.language or "en"),
            "language_probability": round(float(getattr(info, "language_probability", 1.0)), 3),
            "duration": round(float(getattr(info, "duration", 0.0)), 2),
        }
    except Exception as e:
        logger.error(f"STT transcription error: {e}")
        raise HTTPException(status_code=500, detail=f"Whisper transcription failed: {e}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


@router.websocket("/ws/stt-stream")
async def stt_stream(websocket: WebSocket) -> None:
    """Normalize NeMo-Speech.cpp realtime events for Live Mode.

    The browser only sees the stable ``ready/partial/final/status/error``
    vocabulary.  If the optional native runtime is absent, the error includes
    the configured fallback state so the UI can switch to batch STT.
    """
    await websocket.accept()
    sidecar_ws = None
    receiver: asyncio.Task | None = None
    try:
        first = await websocket.receive_json()
        if str(first.get("type") or first.get("event")) != "start":
            await websocket.send_json({"type": "error", "message": "The first stream message must be start"})
            await websocket.close(code=1003)
            return
        model_id = str(first.get("model") or settings.stt.model)
        if not nemo_model(model_id):
            await websocket.send_json({"type": "error", "message": "Realtime streaming requires a Nemotron model"})
            await websocket.close(code=1003)
            return
        chunk_ms = int(first.get("chunk_ms") or settings.stt.stream_chunk_ms or 320)
        if chunk_ms not in (80, 160, 320, 560, 1120):
            chunk_ms = 320
        await websocket.send_json({"type": "status", "status": "loading", "model": model_id})
        nemo_sidecar.port = int(settings.stt.sidecar_port or 8092)
        if not await nemo_sidecar.ensure(model_id, chunk_ms):
            await websocket.send_json({
                "type": "error",
                "message": nemo_sidecar.error or "NeMo-Speech.cpp is not ready",
                "fallback_available": settings.stt.fallback_enabled,
            })
            await websocket.close(code=1013)
            return

        import websockets
        sidecar_ws = await websockets.connect(
            f"ws://127.0.0.1:{settings.stt.sidecar_port or 8092}/v1/realtime",
            open_timeout=5,
            close_timeout=2,
            max_size=None,
        )
        await sidecar_ws.send(json.dumps({
            "type": "session.update",
            "sample_rate": int(first.get("sample_rate") or 16000),
            "language": str(first.get("language") or settings.stt.stream_language or "auto"),
            "chunk_ms": chunk_ms,
        }))
        await websocket.send_json({
            "type": "ready",
            "model": model_id,
            "device": nemo_sidecar.device,
            "sample_rate": 16000,
            "chunk_ms": chunk_ms,
            "runtime": "nemo-speech.cpp",
        })

        async def relay_sidecar() -> None:
            assert sidecar_ws is not None
            async for message in sidecar_ws:
                if isinstance(message, bytes):
                    continue
                try:
                    event = json.loads(message)
                except (TypeError, ValueError):
                    continue
                event_type = str(event.get("type") or event.get("event") or "").lower()
                text = str(event.get("text") or event.get("transcript") or event.get("delta") or "")
                # NeMo-Speech.cpp names its terminal realtime event
                # ``conversation.item.input_audio_transcription.completed``;
                # normalize that alongside providers that use ``final`` or an
                # explicit boolean so Live Mode forwards only finalized text
                # to the LLM.
                is_final = bool(
                    event.get("is_final")
                    or event.get("final")
                    or "final" in event_type
                    or "completed" in event_type
                )
                if text:
                    await websocket.send_json({
                        "type": "final" if is_final else "partial",
                        "text": text,
                        "language": event.get("language") or first.get("language") or "auto",
                        "duration": event.get("duration"),
                    })
                elif event_type in {"endpoint", "speech_end", "utterance_end"}:
                    await websocket.send_json({"type": "status", "status": "endpointing"})

        receiver = asyncio.create_task(relay_sidecar())
        while True:
            incoming = await websocket.receive()
            if incoming.get("type") == "websocket.disconnect":
                break
            if incoming.get("bytes") is not None:
                await sidecar_ws.send(incoming["bytes"])
                continue
            raw = incoming.get("text")
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            command = str(message.get("type") or message.get("event") or "")
            if command == "flush":
                await websocket.send_json({"type": "status", "status": "endpointing"})
                await sidecar_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                await sidecar_ws.send(json.dumps({"type": "flush"}))
            elif command == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("STT streaming connection failed: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if receiver:
            receiver.cancel()
        if sidecar_ws is not None:
            try:
                await sidecar_ws.close()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------

@router.get("/memories", response_model=list[MemoryPublic])
async def list_memories(
    memory_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MemoryPublic]:
    state = await load_character_state(db)
    q = select(Memory).where(Memory.character_id == state.id)
    if memory_type:
        q = q.where(Memory.memory_type == memory_type)
    q = q.order_by(Memory.importance.desc(), Memory.created_at.desc()).limit(100)
    result = await db.execute(q)
    return [MemoryPublic.model_validate(m, from_attributes=True) for m in result.scalars().all()]


@router.post("/memories", response_model=MemoryPublic)
async def create_memory(
    req: MemoryCreate, db: AsyncSession = Depends(get_db)
) -> MemoryPublic:
    state = await load_character_state(db)
    mem = Memory(
        character_id=state.id,
        memory_type=req.memory_type,
        content=req.content,
        importance=req.importance,
        pinned=req.pinned,
        source=req.source,
        tags=req.tags,
    )
    db.add(mem)
    await db.commit()
    return MemoryPublic.model_validate(mem, from_attributes=True)


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Memory).where(Memory.id == memory_id))
    mem = result.scalar_one_or_none()
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    await db.delete(mem)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Goal endpoints
# ---------------------------------------------------------------------------

@router.get("/goals", response_model=list[GoalPublic])
async def list_goals(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[GoalPublic]:
    state = await load_character_state(db)
    q = select(Goal).where(Goal.character_id == state.id)
    if status:
        q = q.where(Goal.status == status)
    q = q.order_by(Goal.priority.desc(), Goal.created_at.desc()).limit(50)
    result = await db.execute(q)
    return [GoalPublic.model_validate(g, from_attributes=True) for g in result.scalars().all()]


@router.post("/goals", response_model=GoalPublic)
async def create_goal(
    req: GoalCreate, db: AsyncSession = Depends(get_db)
) -> GoalPublic:
    state = await load_character_state(db)
    goal = Goal(
        character_id=state.id,
        title=req.title,
        description=req.description,
        priority=req.priority,
    )
    db.add(goal)
    await db.commit()
    return GoalPublic.model_validate(goal, from_attributes=True)


@router.patch("/goals/{goal_id}", response_model=GoalPublic)
async def update_goal(
    goal_id: str, status: str | None = None, db: AsyncSession = Depends(get_db)
) -> GoalPublic:
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    if status:
        goal.status = status
        if status == "completed":
            goal.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return GoalPublic.model_validate(goal, from_attributes=True)


@router.delete("/goals/{goal_id}")
async def delete_goal(goal_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Goal).where(Goal.id == goal_id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.delete(goal)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Skill endpoints
# ---------------------------------------------------------------------------

@router.get("/skills", response_model=list[SkillPublic])
async def list_skills(db: AsyncSession = Depends(get_db)) -> list[SkillPublic]:
    state = await load_character_state(db)
    result = await db.execute(
        select(Skill)
        .where(Skill.character_id == state.id)
        .order_by(Skill.proficiency.desc())
    )
    return [SkillPublic.model_validate(s, from_attributes=True) for s in result.scalars().all()]


@router.post("/skills", response_model=SkillPublic)
async def create_skill(
    req: SkillCreate, db: AsyncSession = Depends(get_db)
) -> SkillPublic:
    state = await load_character_state(db)
    skill = Skill(
        character_id=state.id,
        name=req.name,
        description=req.description,
        proficiency=req.proficiency,
    )
    db.add(skill)
    await db.commit()
    return SkillPublic.model_validate(skill, from_attributes=True)


@router.patch("/skills/{skill_id}", response_model=SkillPublic)
async def update_skill(
    skill_id: str, req: SkillUpdate, db: AsyncSession = Depends(get_db)
) -> SkillPublic:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if req.proficiency is not None:
        skill.proficiency = req.proficiency
    if req.description is not None:
        skill.description = req.description
    skill.last_used = datetime.now(timezone.utc)
    await db.commit()
    return SkillPublic.model_validate(skill, from_attributes=True)


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Skill).where(Skill.id == skill_id))
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    await db.delete(skill)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=SettingsResponse)
async def get_settings(*, persist_migrations: bool = True) -> SettingsResponse:
    profile_id, profile = sync_active_profile(settings)
    project_voice_ref = _ensure_project_voice_reference(settings.tts.voice_ref)
    if project_voice_ref and project_voice_ref != settings.tts.voice_ref:
        # Migrate legacy/external references the first time settings are read,
        # so a later restart still points at the durable project copy.
        settings.tts.voice_ref = project_voice_ref
        if persist_migrations:
            try:
                save_config(settings)
            except OSError as exc:
                logger.warning("Could not persist migrated TTS reference path: %s", exc)
    return SettingsResponse(
        character_profile_id=profile_id,
        character_name=profile.name,
        character_profile_picture=profile.profile_picture,
        character_age=profile.age,
        character_gender=profile.gender,
        character_pronouns=profile.pronouns,
        character_description=profile.description,
        character_appearance=profile.appearance_notes,
        character_appearance_height=profile.appearance.height,
        character_appearance_build=profile.appearance.build,
        character_appearance_hair=profile.appearance.hair,
        character_appearance_eyes=profile.appearance.eyes,
        character_appearance_skin_or_fur=profile.appearance.skin_or_fur,
        character_appearance_clothing=profile.appearance.clothing,
        character_appearance_accessories=profile.appearance.accessories,
        character_appearance_distinguishing_features=profile.appearance.distinguishing_features,
        character_appearance_visual_style=profile.appearance.visual_style,
        character_appearance_notes=profile.appearance.notes,
        character_personality_summary=profile.personality_guidance,
        character_response_style=profile.response_style,
        character_style_modifiers=profile.style_modifiers,
        character_style_guidance=profile.style_guidance,
        character_traits=profile.traits,
        character_dere_types=profile.dere_types,
        character_behavior_rules=profile.behavior_rules,
        character_custom_instructions=profile.custom_instructions,
        character_backstory=profile.backstory,
        character_core_values=profile.core_values,
        character_likes=profile.likes,
        character_dislikes=profile.dislikes,
        character_immutable_traits=profile.immutable_traits,
        user_name=settings.user.name,
        user_age=settings.user.age,
        user_height=settings.user.height,
        user_gender=settings.user.gender,
        user_pronouns=settings.user.pronouns,
        user_location=settings.user.location,
        user_occupation=settings.user.occupation,
        user_bio=settings.user.bio,
        user_hobbies=settings.user.hobbies,
        user_interests=settings.user.interests,
        user_favorite_games=settings.user.favorite_games,
        user_favorite_anime=settings.user.favorite_anime,
        user_dislikes=settings.user.dislikes,
        user_notes=settings.user.notes,
        llm_provider=settings.llm.provider,
        llm_model=settings.llm.model,
        llm_base_url=settings.llm.base_url,
        llm_temperature=settings.llm.temperature,
        llm_max_tokens=settings.llm.max_tokens,
        avatar_provider=settings.avatar.provider,
        avatar_model=settings.avatar.model,
        avatar_smart_expressions=settings.avatar.smart_expressions,
        avatar_idle_preset=settings.avatar.idle_preset,
        avatar_idle_intensity=settings.avatar.idle_intensity,
        memory_max_short_term=settings.memory.max_short_term_messages,
        memory_retrieval_top_k=settings.memory.retrieval_top_k,
        message_mode=settings.message_mode,
        tts_engine=settings.tts.engine,
        tts_voice_ref=project_voice_ref or settings.tts.voice_ref,
        tts_language=settings.tts.language,
        tts_happiness=settings.tts.happiness,
        tts_sadness=settings.tts.sadness,
        tts_disgust=settings.tts.disgust,
        tts_fear=settings.tts.fear,
        tts_surprise=settings.tts.surprise,
        tts_anger=settings.tts.anger,
        tts_other=settings.tts.other,
        tts_neutral=settings.tts.neutral,
        tts_speaking_rate=settings.tts.speaking_rate,
        tts_pitch_std=settings.tts.pitch_std,
        tts_fmax=settings.tts.fmax,
        tts_vq_score=settings.tts.vq_score,
        tts_dnsmos_ovrl=settings.tts.dnsmos_ovrl,
        tts_cfg_scale=settings.tts.cfg_scale,
        tts_seed=settings.tts.seed,
        tts_seed_mode=settings.tts.seed_mode,
        tts_emotion_mode=settings.tts.emotion_mode,
        tts_voice_gender=settings.tts.voice_gender,
        tts_openrouter_base_url=settings.tts.openrouter_base_url,
        tts_openrouter_api_key_env=settings.tts.openrouter_api_key_env,
        tts_openrouter_model=settings.tts.openrouter_model,
        tts_openrouter_voice=settings.tts.openrouter_voice,
        tts_openrouter_response_format=settings.tts.openrouter_response_format,
        tts_openrouter_speed=settings.tts.openrouter_speed,
        tts_fish_audio_base_url=settings.tts.fish_audio_base_url,
        tts_fish_audio_api_key_env=settings.tts.fish_audio_api_key_env,
        stt_provider=settings.stt.provider,
        stt_model=settings.stt.model,
        stt_device=settings.stt.device,
        stt_compute_type=settings.stt.compute_type,
        stt_beam_size=settings.stt.beam_size,
        stt_language=settings.stt.language,
        stt_vad_filter=settings.stt.vad_filter,
        stt_temperature=settings.stt.temperature,
        stt_streaming_enabled=settings.stt.streaming_enabled,
        stt_stream_chunk_ms=settings.stt.stream_chunk_ms,
        stt_stream_language=settings.stt.stream_language,
        stt_fallback_enabled=settings.stt.fallback_enabled,
        stt_sidecar_port=settings.stt.sidecar_port,
    )


@router.get("/models/gguf")
async def list_gguf_models() -> list[dict]:
    """List available GGUF model files."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    gguf_dir = project_root / "assets" / "models" / "gguf"
    if not gguf_dir.exists():
        return []
    models = []
    for f in sorted(gguf_dir.glob("*.gguf")):
        size_gb = f.stat().st_size / (1024 ** 3)
        models.append({
            "name": f.stem,
            "filename": f.name,
            "size_gb": round(size_gb, 2),
        })
    return models


@router.get("/llm/models")
async def list_llm_models() -> list[dict]:
    """List managed LLM downloads alongside manually copied GGUF files."""
    return list_local_llm_models()


@router.get("/llm/models/{model_id}/license")
async def get_llm_model_license(model_id: str) -> dict:
    model = llm_catalog_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="License information is available for managed download models only")
    return {
        "model": model_id,
        "license": model["license"],
        "license_url": model["license_url"],
        "source_url": model["source_url"],
        "official_source_url": model["official_source_url"],
        "requires_hf_access": model["requires_hf_access"],
        "accepted": llm_license_accepted(model_id),
        "text": (
            "This GGUF is a llama.cpp-compatible conversion of the linked official model. "
            f"Review and accept the {model['license']} before downloading."
        ),
    }


@router.post("/llm/models/{model_id}/license/accept")
async def accept_llm_model_license_endpoint(model_id: str) -> dict:
    try:
        return accept_llm_model_license(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/llm/models/download")
async def download_llm_model(req: dict) -> dict:
    """Start or resume a tracked GGUF download for the local llama.cpp runtime."""
    model_id = str(req.get("model") or "")
    model = llm_catalog_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Unknown managed local LLM model")
    if not llm_license_accepted(model_id):
        raise HTTPException(status_code=403, detail=f"Accept the {model['license']} before downloading this model")
    try:
        download = await start_llm_download(model_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    add_log("info", "llm", f"Local LLM '{model_id}' download {download['status']}")
    return {
        "status": download["status"],
        "model": model_id,
        "message": f"Downloading {model['filename']} in the background",
        "download": download,
    }


@router.get("/llm/models/{model_id}/download-status")
async def get_llm_model_download_status(model_id: str) -> dict:
    if not llm_catalog_model(model_id):
        raise HTTPException(status_code=404, detail="Download progress is available for managed LLM models only")
    return llm_download_status(model_id)


def _get_gpu_telemetry() -> dict:
    import shutil
    import subprocess
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.check_output(
                [
                    smi,
                    "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=1.5,
            ).strip()
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 5:
                return {
                    "name": parts[0],
                    "total_vram_mb": int(parts[1]),
                    "used_vram_mb": int(parts[2]),
                    "free_vram_mb": int(parts[3]),
                    "utilization_pct": int(parts[4]),
                    "temperature_c": int(parts[5]) if len(parts) > 5 else None,
                    "available": True,
                }
        except Exception:
            pass
    return {
        "name": "Integrated / CPU",
        "total_vram_mb": 0,
        "used_vram_mb": 0,
        "free_vram_mb": 0,
        "utilization_pct": 0,
        "temperature_c": None,
        "available": False,
    }


@router.get("/telemetry")
async def get_hardware_telemetry(
    llm_model: str | None = None,
    llm_provider: str | None = None,
    tts_engine: str | None = None,
    stt_model: str | None = None,
    stt_provider: str | None = None,
    stt_device: str | None = None,
    stt_compute_type: str | None = None,
) -> dict:
    """Return live hardware telemetry using optional settings-page drafts.

    Settings editing is intentionally draft-based.  Query overrides let the
    cards preview the selected model/engine immediately without persisting a
    change or pretending an unsaved model is already loaded in VRAM.
    """
    gpu = _get_gpu_telemetry()

    # Active LLM calculations
    llm_name = llm_model or settings.llm.model or "gemma-3-12b-it-Q4_K_M.gguf"
    llm_lower = llm_name.lower()

    # Calculate model size and compute specs
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    # Model names can come from a draft query; only use the filename portion
    # when resolving local telemetry metadata.
    gguf_path = project_root / "assets" / "models" / "gguf" / Path(llm_name).name

    if gguf_path.exists():
        file_size_gb = round(gguf_path.stat().st_size / (1024 ** 3), 2)
    elif "12b" in llm_lower or "gemma-3" in llm_lower:
        file_size_gb = 7.62
    elif "14b" in llm_lower:
        file_size_gb = 9.20
    elif "7b" in llm_lower or "8b" in llm_lower or "9b" in llm_lower:
        file_size_gb = 5.40
    elif "3b" in llm_lower or "2b" in llm_lower or "1b" in llm_lower:
        file_size_gb = 2.30
    elif "32b" in llm_lower or "33b" in llm_lower:
        file_size_gb = 19.50
    elif "70b" in llm_lower:
        file_size_gb = 42.00
    else:
        file_size_gb = 6.00

    if "minitron" in llm_lower or "mistral-nemo" in llm_lower:
        est_vram = round(file_size_gb + 0.8, 1)
        est_tps = 70
        gpu_load = 68
        arch = "Mistral-NeMo-Minitron (8B Dense)"
    elif "gemma-2" in llm_lower and "2b" in llm_lower:
        est_vram = round(file_size_gb + 0.5, 1)
        est_tps = 115
        gpu_load = 42
        arch = "Gemma 2 (2B Dense)"
    elif "70b" in llm_lower:
        est_vram = round(file_size_gb + 2.5, 1)
        est_tps = 12
        gpu_load = 99
        arch = "Llama-3 (70B MoE/Dense)"
    elif "32b" in llm_lower:
        est_vram = round(file_size_gb + 1.8, 1)
        est_tps = 22
        gpu_load = 96
        arch = "Qwen 2.5 (32B Dense)"
    elif "14b" in llm_lower:
        est_vram = round(file_size_gb + 1.2, 1)
        est_tps = 38
        gpu_load = 88
        arch = "Qwen 2.5 (14B Dense)"
    elif "12b" in llm_lower or "gemma-3" in llm_lower:
        est_vram = round(file_size_gb + 1.0, 1)
        est_tps = 48
        gpu_load = 76
        arch = "Gemma 3 Architecture (12B)"
    elif "7b" in llm_lower or "8b" in llm_lower or "9b" in llm_lower:
        est_vram = round(file_size_gb + 0.8, 1)
        est_tps = 72
        gpu_load = 64
        arch = "Qwen 2.5 / Gemma 2 (7B-9B)"
    elif "3b" in llm_lower or "2b" in llm_lower or "1b" in llm_lower:
        est_vram = round(file_size_gb + 0.5, 1)
        est_tps = 115
        gpu_load = 42
        arch = "Llama 3.2 / Gemma (Compact)"
    else:
        est_vram = round(file_size_gb * 1.15, 1)
        est_tps = max(20, round(320 / max(1.0, file_size_gb)))
        gpu_load = min(95, max(35, round(file_size_gb * 8.5)))
        arch = "GGUF Quantized LLM"

    llm_telemetry = {
        "model_name": llm_name,
        "architecture": arch,
        "file_size_gb": file_size_gb,
        "vram_allocated_gb": est_vram,
        "tokens_per_sec": est_tps,
        "gpu_load_pct": gpu_load,
        "context_window": settings.llm.max_tokens or 2048,
        "provider": llm_provider or settings.llm.provider,
    }

    # Active TTS calculations
    selected_tts_engine = tts_engine or settings.tts.engine or "zonos"
    if selected_tts_engine == "zonos":
        tts_telemetry = {
            "engine": "zonos",
            "name": "Zonos Transformer v0.1",
            "vram_allocated_gb": 2.1,
            "vram_allocated_mb": 2150,
            "device": "CUDA:0 (RTX 5070)" if gpu["available"] else "CPU",
            "speed_multiplier": "3.4x Realtime",
            "latency_ms": 175,
            "sample_rate": "44.1 kHz",
            "precision": "BFloat16 / FP16",
            "specs": ["44.1kHz Hi-Fi", "Port 8091", "Smart Mood"],
        }
    elif selected_tts_engine == "indextts":
        tts_telemetry = {
            "engine": "indextts",
            "name": "Index-TTS v2.5",
            "vram_allocated_gb": 1.6,
            "vram_allocated_mb": 1580,
            "device": "CUDA:0 (RTX 5070)" if gpu["available"] else "CPU",
            "speed_multiplier": "4.8x Realtime",
            "latency_ms": 135,
            "sample_rate": "24.0 kHz",
            "precision": "FP16",
            "specs": ["24kHz Neural", "Port 8090", "Audio Latents"],
        }
    elif selected_tts_engine == "openrouter":
        tts_telemetry = {
            "engine": "openrouter",
            "name": "OpenRouter hosted speech",
            "model": settings.tts.openrouter_model,
            "vram_allocated_gb": 0.0,
            "vram_allocated_mb": 0,
            "device": "OpenRouter Cloud API",
            "speed_multiplier": "Provider dependent",
            "latency_ms": 0,
            "sample_rate": "Provider output",
            "precision": "Hosted neural audio",
            "specs": ["No local VRAM", "OpenAI-compatible speech API", settings.tts.openrouter_response_format.upper()],
        }
    else:  # edge-tts
        tts_telemetry = {
            "engine": "edge-tts",
            "name": "Microsoft Edge-TTS Neural",
            "vram_allocated_gb": 0.0,
            "vram_allocated_mb": 0,
            "device": "Cloud Azure CDN",
            "speed_multiplier": "14.2x Cloud",
            "latency_ms": 85,
            "sample_rate": "24.0 kHz",
            "precision": "Cloud Neural Stream",
            "specs": ["0 MB VRAM", "Cloud CDN", "Low Latency"],
        }

    # Active STT calculations
    stt_model_name = stt_model or settings.stt.model or "base"
    stt_meta = nemo_model(stt_model_name) or next((m for m in WHISPER_MODELS_CATALOG if m["id"] == stt_model_name), WHISPER_MODELS_CATALOG[2])
    selected_stt_device = stt_device or settings.stt.device
    selected_stt_provider = stt_provider or settings.stt.provider
    selected_stt_compute_type = stt_compute_type or settings.stt.compute_type
    is_cuda_stt = (selected_stt_device != "cpu" and gpu["available"])
    stt_device_display = "CUDA:0 (RTX 5070)" if is_cuda_stt else "CPU (Multi-threaded)"
    stt_is_nemo = bool(nemo_model(stt_model_name) and selected_stt_provider == "nemo_speech")

    stt_telemetry = {
        "model": stt_model_name,
        "name": stt_meta["name"],
        "params": stt_meta["params"],
        "provider": selected_stt_provider,
        "runtime": "NeMo-Speech.cpp" if stt_is_nemo else "Faster-Whisper / CTranslate2",
        "vram_allocated_mb": stt_meta["vram_mb"] if is_cuda_stt else 0,
        "vram_allocated_gb": round(stt_meta["vram_mb"] / 1024, 2) if is_cuda_stt else 0.0,
        "device": "CUDA:0 (RTX 5070)" if stt_is_nemo and is_cuda_stt else stt_device_display,
        "compute_type": selected_stt_compute_type or ("float16" if is_cuda_stt else "int8"),
        "speed_multiplier": "Realtime streaming" if stt_is_nemo else f"{stt_meta['relative_speed']} Realtime",
        "latency_per_sec": f"{settings.stt.stream_chunk_ms} ms chunks" if stt_is_nemo else ("~28 ms/s" if is_cuda_stt else "~110 ms/s"),
        "beam_size": settings.stt.beam_size or 5,
        "vad_filter": settings.stt.vad_filter,
        "language": settings.stt.stream_language if stt_is_nemo else (settings.stt.language or "en"),
        "wer": stt_meta["wer"],
        "specs": [f"Beam {settings.stt.beam_size or 5}", f"VAD {'ON' if settings.stt.vad_filter else 'OFF'}", f"{stt_meta['params']} params"] + (["Realtime PCM16", f"Chunk {settings.stt.stream_chunk_ms} ms"] if stt_is_nemo else []),
    }

    return {
        "gpu": gpu,
        "llm": llm_telemetry,
        "tts": tts_telemetry,
        "stt": stt_telemetry,
    }


_LOG_BUFFER: list[dict] = []


def add_log(level: str, source: str, message: str) -> None:
    from datetime import datetime, timezone
    _LOG_BUFFER.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "source": source,
        "message": message,
    })
    if len(_LOG_BUFFER) > 500:
        _LOG_BUFFER.pop(0)


@router.get("/logs")
async def get_logs(limit: int = 100, level: str | None = None, source: str | None = None) -> list[dict]:
    """Return recent log entries."""
    logs = list(reversed(_LOG_BUFFER))
    if level:
        logs = [l for l in logs if l["level"] == level]
    if source:
        logs = [l for l in logs if l["source"] == source]
    return logs[:limit]


@router.delete("/logs")
async def clear_logs() -> dict:
    """Clear all log entries."""
    _LOG_BUFFER.clear()
    return {"ok": True}


@router.post("/settings")
async def update_settings(
    req: SettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Update all settings and persist to config.yaml."""
    # Character
    profile_id, profile = sync_active_profile(settings)
    profile_name_before = profile.name
    profile_switched = False
    if req.character_profile_id and req.character_profile_id != profile_id:
        try:
            profile_id = req.character_profile_id
            profile = read_profile(profile_id, settings)
            profile_switched = True
        except (FileNotFoundError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=404, detail="Character profile not found") from exc

    character_updates: dict[str, object] = {}
    character_map = {
        "character_name": "name", "character_profile_picture": "profile_picture",
        "character_age": "age", "character_gender": "gender",
        "character_pronouns": "pronouns", "character_description": "description",
        "character_personality_summary": "personality_guidance", "character_backstory": "backstory",
        "character_response_style": "response_style", "character_style_modifiers": "style_modifiers",
        "character_style_guidance": "style_guidance", "character_traits": "traits",
        "character_dere_types": "dere_types", "character_core_values": "core_values",
        "character_likes": "likes", "character_dislikes": "dislikes",
        "character_immutable_traits": "immutable_traits", "character_behavior_rules": "behavior_rules",
        "character_custom_instructions": "custom_instructions",
    }
    for request_name, profile_name in character_map.items():
        value = getattr(req, request_name, None)
        if value is not None:
            character_updates[profile_name] = value

    appearance = profile.appearance
    appearance_updates = appearance.model_dump()
    appearance_map = {
        "character_appearance_height": "height", "character_appearance_build": "build",
        "character_appearance_hair": "hair", "character_appearance_eyes": "eyes",
        "character_appearance_skin_or_fur": "skin_or_fur", "character_appearance_clothing": "clothing",
        "character_appearance_accessories": "accessories",
        "character_appearance_distinguishing_features": "distinguishing_features",
        "character_appearance_visual_style": "visual_style", "character_appearance_notes": "notes",
    }
    for request_name, appearance_name in appearance_map.items():
        value = getattr(req, request_name, None)
        if value is not None:
            appearance_updates[appearance_name] = value
    if req.character_appearance is not None:
        character_updates["appearance_notes"] = req.character_appearance
    if appearance_updates != appearance.model_dump():
        from app.schemas.character_profile import AppearanceProfile
        character_updates["appearance"] = AppearanceProfile.model_validate(appearance_updates)
    if character_updates or profile_switched:
        profile = profile.model_copy(update=character_updates)
        apply_profile_to_config(profile, settings, profile_id)
        write_profile(profile_id, profile, settings)
        if profile.name != profile_name_before:
            await _update_character_message_names(db, profile_id, profile.name)
    # User
    user_str_fields = {
        "user_name": "name", "user_age": "age", "user_height": "height",
        "user_gender": "gender", "user_pronouns": "pronouns", "user_location": "location",
        "user_occupation": "occupation", "user_bio": "bio", "user_notes": "notes",
    }
    for field_name, attr_name in user_str_fields.items():
        val = getattr(req, field_name, None)
        if val is not None:
            setattr(settings.user, attr_name, val)
    user_list_fields = {
        "user_hobbies": "hobbies", "user_interests": "interests",
        "user_favorite_games": "favorite_games", "user_favorite_anime": "favorite_anime",
        "user_dislikes": "dislikes",
    }
    for field_name, attr_name in user_list_fields.items():
        val = getattr(req, field_name, None)
        if val is not None:
            setattr(settings.user, attr_name, val)
    # LLM
    if req.llm_provider is not None:
        settings.llm.provider = req.llm_provider
    if req.llm_model is not None:
        settings.llm.model = req.llm_model
    if req.llm_base_url is not None:
        settings.llm.base_url = req.llm_base_url
    if req.llm_temperature is not None:
        settings.llm.temperature = req.llm_temperature
    if req.llm_max_tokens is not None:
        settings.llm.max_tokens = req.llm_max_tokens
    # Avatar
    if req.avatar_provider is not None:
        settings.avatar.provider = req.avatar_provider
    if req.avatar_model is not None:
        settings.avatar.model = req.avatar_model
    if req.avatar_smart_expressions is not None:
        settings.avatar.smart_expressions = req.avatar_smart_expressions
    if req.avatar_idle_preset is not None:
        settings.avatar.idle_preset = req.avatar_idle_preset
    if req.avatar_idle_intensity is not None:
        settings.avatar.idle_intensity = req.avatar_idle_intensity
    # Memory
    if req.memory_max_short_term is not None:
        settings.memory.max_short_term_messages = req.memory_max_short_term
    if req.memory_retrieval_top_k is not None:
        settings.memory.retrieval_top_k = req.memory_retrieval_top_k
    # Message mode
    if req.message_mode is not None:
        settings.message_mode = req.message_mode
    # TTS
    tts_fields = {
        "tts_engine": "engine", "tts_voice_ref": "voice_ref", "tts_language": "language",
        "tts_happiness": "happiness", "tts_sadness": "sadness", "tts_disgust": "disgust",
        "tts_fear": "fear", "tts_surprise": "surprise", "tts_anger": "anger",
        "tts_other": "other", "tts_neutral": "neutral",
        "tts_speaking_rate": "speaking_rate", "tts_pitch_std": "pitch_std",
        "tts_fmax": "fmax", "tts_vq_score": "vq_score",
        "tts_dnsmos_ovrl": "dnsmos_ovrl", "tts_cfg_scale": "cfg_scale",
        "tts_seed": "seed", "tts_seed_mode": "seed_mode", "tts_emotion_mode": "emotion_mode",
        "tts_voice_gender": "voice_gender",
        "tts_openrouter_base_url": "openrouter_base_url", "tts_openrouter_api_key_env": "openrouter_api_key_env",
        "tts_openrouter_model": "openrouter_model", "tts_openrouter_voice": "openrouter_voice",
        "tts_openrouter_response_format": "openrouter_response_format", "tts_openrouter_speed": "openrouter_speed",
        "tts_fish_audio_base_url": "fish_audio_base_url", "tts_fish_audio_api_key_env": "fish_audio_api_key_env",
    }
    for field_name, attr_name in tts_fields.items():
        value = getattr(req, field_name, None)
        if value is not None:
            setattr(settings.tts, attr_name, value)

    # STT / streaming Nemotron (legacy Whisper fields stay compatible)
    stt_fields = {
        "stt_provider": "provider", "stt_model": "model", "stt_device": "device", "stt_compute_type": "compute_type",
        "stt_beam_size": "beam_size", "stt_language": "language", "stt_vad_filter": "vad_filter",
        "stt_temperature": "temperature", "stt_streaming_enabled": "streaming_enabled",
        "stt_stream_chunk_ms": "stream_chunk_ms", "stt_stream_language": "stream_language",
        "stt_fallback_enabled": "fallback_enabled", "stt_sidecar_port": "sidecar_port",
    }
    for field_name, attr_name in stt_fields.items():
        value = getattr(req, field_name, None)
        if value is not None:
            setattr(settings.stt, attr_name, value)
    if req.stt_provider is None and req.stt_model is not None:
        settings.stt.provider = "nemo_speech" if str(req.stt_model).startswith("nemotron-") else "faster_whisper"

    # A settings change is a safe point to release a locally owned runtime.
    # The next request will load only the newly selected backend/model.
    if req.stt_provider is not None or req.stt_model is not None or req.stt_device is not None or req.stt_compute_type is not None:
        if settings.stt.provider != "faster_whisper":
            _unload_whisper()
        if settings.stt.provider != "nemo_speech":
            await nemo_sidecar.stop()

    # Persist to config.yaml
    from app.core.config import save_config
    save_config(settings)

    return await get_settings()


# ---------------------------------------------------------------------------
# Presets endpoints
# ---------------------------------------------------------------------------

import json
import uuid

_PRESETS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "presets"
SUPPORTED_PRESET_TYPES = {"master", "user", "llm", "tts", "avatar", "stt"}
PRESET_TYPE_ALIASES = {"whisper": "stt"}

# User presets are intentionally scoped to the user profile. Older snapshots
# may contain a full settings dump, so this allowlist also protects applying a
# legacy preset from changing character or engine configuration.
USER_PRESET_FIELDS = {
    "user_name", "user_age", "user_height", "user_gender", "user_pronouns",
    "user_location", "user_occupation", "user_bio", "user_hobbies",
    "user_interests", "user_favorite_games", "user_favorite_anime",
    "user_dislikes", "user_notes",
}


def _normalize_preset_type(value: object) -> str:
    requested = str(value or "").strip().lower()
    return PRESET_TYPE_ALIASES.get(requested, requested)


def _normalize_preset_voice_reference(data: object) -> object:
    if not isinstance(data, dict) or "tts_voice_ref" not in data:
        return data
    normalized = dict(data)
    normalized["tts_voice_ref"] = _ensure_project_voice_reference(normalized.get("tts_voice_ref"))
    return normalized


def _load_presets() -> list[dict]:
    _PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    index_file = _PRESETS_DIR / "index.json"
    if not index_file.exists():
        return []
    with index_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_presets(presets: list[dict]) -> None:
    _PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    index_file = _PRESETS_DIR / "index.json"
    with index_file.open("w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)


@router.get("/presets")
async def list_presets() -> list[dict]:
    # Markdown personas are exposed through /character-profiles. JSON presets
    # include master bundles, the user profile, and engine-specific presets.
    exposed: list[dict] = []
    for preset in _load_presets():
        normalized_type = _normalize_preset_type(preset.get("type"))
        if normalized_type in SUPPORTED_PRESET_TYPES:
            # Normalize the response without rewriting legacy JSON on disk.
            exposed.append({**preset, "type": normalized_type})
    return exposed


@router.post("/presets")
async def create_preset(req: dict) -> dict:
    preset_type = _normalize_preset_type(req.get("type", "llm"))
    if preset_type not in SUPPORTED_PRESET_TYPES:
        raise HTTPException(
            status_code=422,
            detail="Preset type must be one of: master, user, llm, tts, avatar, stt (Whisper).",
        )
    preset = {
        "id": str(uuid.uuid4())[:8],
        "name": req.get("name", "Unnamed"),
        "type": preset_type,
        "data": _normalize_preset_voice_reference(req.get("data", {})),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    presets = _load_presets()
    presets.append(preset)
    _save_presets(presets)
    add_log("info", "preset", f"Created preset '{preset['name']}' ({preset['type']})")
    return preset


@router.put("/presets/{preset_id}")
async def update_preset(preset_id: str, req: dict) -> dict:
    presets = _load_presets()
    for p in presets:
        if p["id"] == preset_id:
            p["name"] = req.get("name", p["name"])
            p["data"] = _normalize_preset_voice_reference(req.get("data", p["data"]))
            _save_presets(presets)
            add_log("info", "preset", f"Updated preset '{p['name']}'")
            return p
    raise HTTPException(status_code=404, detail="Preset not found")


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: str) -> dict:
    presets = _load_presets()
    preset = next((p for p in presets if p["id"] == preset_id), None)
    presets = [p for p in presets if p["id"] != preset_id]
    _save_presets(presets)
    if preset:
        add_log("info", "preset", f"Deleted preset '{preset['name']}'")
    return {"ok": True}


@router.get("/presets/{preset_id}/resolve", response_model=SettingsResponse)
async def resolve_preset(preset_id: str) -> SettingsResponse:
    """Preview a preset's resolved settings without changing global config."""

    preset = next((item for item in _load_presets() if item.get("id") == preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if str(preset.get("type") or "").lower() != "master":
        raise HTTPException(status_code=422, detail="Only master presets can be resolved for a channel")
    try:
        async with _channel_runtime_scope(preset_id):
            return await get_settings(persist_migrations=False)
    except (FileNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Channel master preset could not be resolved") from exc


@router.post("/presets/{preset_id}/apply")
async def apply_preset(preset_id: str) -> SettingsResponse:
    """Apply a preset's data to the live settings and persist."""
    presets = _load_presets()
    preset = next((p for p in presets if p["id"] == preset_id), None)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")

    data = preset.get("data", {})
    if not isinstance(data, dict):
        data = {}
    if preset.get("type") == "user":
        data = {key: value for key, value in data.items() if key in USER_PRESET_FIELDS}

    # A master preset stores references to one engine preset per subsystem and
    # an optional Markdown persona. Resolve those references into the same
    # settings payload used by legacy JSON snapshots, so applying a bundle is
    # atomic from the UI's perspective while each child preset stays editable.
    if preset.get("type") == "master":
        master_data = data if isinstance(data, dict) else {}
        resolved_data: dict = {
            key: value for key, value in master_data.items()
            if key not in {"llm_preset_id", "tts_preset_id", "avatar_preset_id", "stt_preset_id", "whisper_preset_id", "character_profile_id"}
        }
        for reference_key in ("llm_preset_id", "tts_preset_id", "avatar_preset_id", "stt_preset_id", "whisper_preset_id"):
            child_id = master_data.get(reference_key)
            if not child_id:
                continue
            child = next((item for item in _load_presets() if item.get("id") == child_id), None)
            if child and child.get("type") in {"llm", "tts", "avatar", "stt", "whisper"}:
                resolved_data.update(child.get("data") or {})

        character_profile_id = master_data.get("character_profile_id")
        if character_profile_id:
            try:
                profile = read_profile(str(character_profile_id), settings)
            except (FileNotFoundError, ValueError, TypeError) as exc:
                raise HTTPException(status_code=404, detail="Master preset character profile not found") from exc
            apply_profile_to_config(profile, settings, _safe_profile_id(str(character_profile_id)))
        data = resolved_data

    # Character presets are now Markdown profiles. Keep this legacy endpoint
    # working for older clients by materializing the JSON snapshot as a profile
    # and applying that profile through the same path as the new API.
    if preset.get("type") == "character":
        profile_id = _safe_profile_id(str(preset.get("id") or preset.get("name") or "character"))
        profile = _legacy_preset_profile(data)
        write_profile(profile_id, profile, settings)
        apply_profile_to_config(profile, settings, profile_id)
        from app.core.config import save_config
        save_config(settings)
        return await get_settings()

    # Apply character settings. Character profiles are Markdown-backed, but
    # older master/JSON presets can still contain character fields. Restore
    # every supported persona field when it is present so switching presets
    # does not silently drop response styles, modifiers, traits, or guidance.
    char_map = {
        "character_name": "name", "character_profile_picture": "profile_picture",
        "character_age": "age", "character_gender": "gender",
        "character_pronouns": "pronouns", "character_description": "description",
        "character_personality_summary": "personality_guidance", "character_backstory": "backstory",
        "character_response_style": "response_style", "character_style_modifiers": "style_modifiers",
        "character_style_guidance": "style_guidance", "character_traits": "traits",
        "character_dere_types": "dere_types", "character_behavior_rules": "behavior_rules",
        "character_custom_instructions": "custom_instructions", "character_core_values": "core_values",
        "character_likes": "likes", "character_dislikes": "dislikes",
        "character_immutable_traits": "immutable_traits",
    }
    profile_id, active_profile = sync_active_profile(settings)
    profile_updates: dict[str, object] = {}
    for field_name, attr_name in char_map.items():
        if field_name in data:
            profile_updates[attr_name] = data[field_name]
    appearance = active_profile.appearance
    appearance_updates = appearance.model_dump()
    appearance_map = {
        "character_appearance_height": "height", "character_appearance_build": "build",
        "character_appearance_hair": "hair", "character_appearance_eyes": "eyes",
        "character_appearance_skin_or_fur": "skin_or_fur", "character_appearance_clothing": "clothing",
        "character_appearance_accessories": "accessories",
        "character_appearance_distinguishing_features": "distinguishing_features",
        "character_appearance_visual_style": "visual_style", "character_appearance_notes": "notes",
    }
    for field_name, appearance_name in appearance_map.items():
        if field_name in data:
            appearance_updates[appearance_name] = data[field_name]
    if "character_appearance" in data:
        profile_updates["appearance_notes"] = data["character_appearance"]
    if appearance_updates != appearance.model_dump():
        from app.schemas.character_profile import AppearanceProfile
        profile_updates["appearance"] = AppearanceProfile.model_validate(appearance_updates)
    if profile_updates:
        updated_profile = active_profile.model_copy(update=profile_updates)
        apply_profile_to_config(updated_profile, settings, profile_id)
        write_profile(profile_id, updated_profile, settings)
    # Apply LLM settings
    if "llm_provider" in data:
        settings.llm.provider = data["llm_provider"]
    if "llm_model" in data:
        settings.llm.model = data["llm_model"]
    if "llm_base_url" in data:
        settings.llm.base_url = data["llm_base_url"]
    if "llm_temperature" in data:
        settings.llm.temperature = data["llm_temperature"]
    if "llm_max_tokens" in data:
        settings.llm.max_tokens = data["llm_max_tokens"]
    # Apply TTS settings
    tts_map = {
        "tts_engine": "engine", "tts_voice_ref": "voice_ref", "tts_language": "language",
        "tts_happiness": "happiness", "tts_sadness": "sadness", "tts_disgust": "disgust",
        "tts_fear": "fear", "tts_surprise": "surprise", "tts_anger": "anger",
        "tts_other": "other", "tts_neutral": "neutral",
        "tts_speaking_rate": "speaking_rate", "tts_pitch_std": "pitch_std",
        "tts_fmax": "fmax", "tts_vq_score": "vq_score",
        "tts_dnsmos_ovrl": "dnsmos_ovrl", "tts_cfg_scale": "cfg_scale",
        "tts_seed": "seed", "tts_seed_mode": "seed_mode", "tts_emotion_mode": "emotion_mode",
        "tts_voice_gender": "voice_gender",
        "tts_openrouter_base_url": "openrouter_base_url", "tts_openrouter_api_key_env": "openrouter_api_key_env",
        "tts_openrouter_model": "openrouter_model", "tts_openrouter_voice": "openrouter_voice",
        "tts_openrouter_response_format": "openrouter_response_format", "tts_openrouter_speed": "openrouter_speed",
        "tts_fish_audio_base_url": "fish_audio_base_url", "tts_fish_audio_api_key_env": "fish_audio_api_key_env",
    }
    for field_name, attr_name in tts_map.items():
        if field_name in data:
            value = data[field_name]
            if field_name == "tts_voice_ref":
                value = _ensure_project_voice_reference(value)
            setattr(settings.tts, attr_name, value)

    # Apply STT / streaming Nemotron settings
    stt_map = {
        "stt_provider": "provider", "stt_model": "model", "stt_device": "device", "stt_compute_type": "compute_type",
        "stt_beam_size": "beam_size", "stt_language": "language", "stt_vad_filter": "vad_filter",
        "stt_temperature": "temperature", "stt_streaming_enabled": "streaming_enabled",
        "stt_stream_chunk_ms": "stream_chunk_ms", "stt_stream_language": "stream_language",
        "stt_fallback_enabled": "fallback_enabled", "stt_sidecar_port": "sidecar_port",
    }
    for field_name, attr_name in stt_map.items():
        if field_name in data:
            setattr(settings.stt, attr_name, data[field_name])
    if "stt_provider" not in data and "stt_model" in data:
        settings.stt.provider = "nemo_speech" if str(data["stt_model"]).startswith("nemotron-") else "faster_whisper"

    if any(key in data for key in ("stt_provider", "stt_model", "stt_device", "stt_compute_type")):
        if settings.stt.provider != "faster_whisper":
            _unload_whisper()
        if settings.stt.provider != "nemo_speech":
            await nemo_sidecar.stop()

    # Apply User profile settings
    user_map = {
        "user_name": "name", "user_age": "age", "user_height": "height",
        "user_gender": "gender", "user_pronouns": "pronouns", "user_location": "location",
        "user_occupation": "occupation", "user_bio": "bio", "user_notes": "notes",
    }
    for field_name, attr_name in user_map.items():
        if field_name in data:
            setattr(settings.user, attr_name, data[field_name])

    user_list_fields = {
        "user_hobbies": "hobbies", "user_interests": "interests",
        "user_favorite_games": "favorite_games", "user_favorite_anime": "favorite_anime",
        "user_dislikes": "dislikes",
    }
    for field_name, attr_name in user_list_fields.items():
        if field_name in data:
            setattr(settings.user, attr_name, data[field_name])

    # Apply Avatar, Memory, Message mode
    if "avatar_provider" in data:
        settings.avatar.provider = data["avatar_provider"]
    if "avatar_model" in data:
        settings.avatar.model = data["avatar_model"]
    if "avatar_smart_expressions" in data:
        settings.avatar.smart_expressions = bool(data["avatar_smart_expressions"])
    if "avatar_idle_preset" in data:
        settings.avatar.idle_preset = str(data["avatar_idle_preset"])
    if "avatar_idle_intensity" in data:
        settings.avatar.idle_intensity = float(data["avatar_idle_intensity"])
    if "memory_max_short_term" in data:
        settings.memory.max_short_term_messages = data["memory_max_short_term"]
    if "memory_retrieval_top_k" in data:
        settings.memory.retrieval_top_k = data["memory_retrieval_top_k"]
    if "message_mode" in data:
        settings.message_mode = data["message_mode"]

    from app.core.config import save_config
    save_config(settings)

    return await get_settings()
