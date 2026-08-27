from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from app.core.paths import data_root, resource_root

# Load the project-local backend .env explicitly.  The Windows launcher
# currently starts uvicorn from ``backend/``, but resolving this path here
# also keeps secrets available when the server is started from the project
# root (or by an IDE/service).  ``override=False`` is the dotenv default, so
# an already-exported environment variable still wins over the file.
_PROJECT_ROOT = resource_root()
load_dotenv(data_root() / ".env")
load_dotenv(_PROJECT_ROOT / "backend" / ".env")
load_dotenv()


class CharacterConfig(BaseModel):
    # Markdown profile identity. Legacy fields remain as a fallback for older
    # installations until the profile migration has completed.
    profile_id: str = ""
    profiles_dir: str = "data/character-profiles"
    name: str = "Aiko"
    profile_picture: str = ""
    age: str = ""
    gender: str = ""
    pronouns: str = ""
    description: str = ""
    appearance: str = ""
    appearance_height: str = ""
    appearance_build: str = ""
    appearance_hair: str = ""
    appearance_eyes: str = ""
    appearance_skin_or_fur: str = ""
    appearance_clothing: str = ""
    appearance_accessories: str = ""
    appearance_distinguishing_features: str = ""
    appearance_visual_style: str = ""
    appearance_notes: str = ""
    personality_summary: str = ""
    response_style: str = "Friendly"
    style_modifiers: list[str] = Field(default_factory=list)
    style_guidance: str = ""
    traits: list[str] = Field(default_factory=list)
    dere_types: list[str] = Field(default_factory=list)
    behavior_rules: str = ""
    custom_instructions: str = ""
    backstory: str = ""
    core_values: list[str] = Field(default_factory=list)
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    immutable_traits: list[str] = Field(default_factory=list)


class UserConfig(BaseModel):
    """Information about the human user — separate from the AI character."""
    name: str = "You"
    age: str = ""
    height: str = ""
    gender: str = ""
    pronouns: str = ""
    location: str = ""
    occupation: str = ""
    bio: str = ""
    hobbies: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    favorite_games: list[str] = Field(default_factory=list)
    favorite_anime: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    notes: str = ""


class LLMConfig(BaseModel):
    provider: str = "openai_compatible"
    # 8080 is commonly claimed by Chromium/Discord remote debugging on
    # Windows. Keep the project-owned llama.cpp router on a collision-free
    # dedicated port.
    base_url: str = "http://127.0.0.1:8081/v1"
    model: str = "local-model"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.85
    max_tokens: int = 1024


class SpeculativeConfig(BaseModel):
    """Optional llama.cpp speculative decoding settings."""

    enabled: bool = False
    type: str = "draft-simple"
    draft_model: str = ""
    max_draft_tokens: int = 3


class LLMPerformanceConfig(BaseModel):
    """Runtime knobs for the local llama.cpp server."""

    flash_attention: str = "auto"  # auto | on | off
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    prompt_cache: bool = True
    speculative: SpeculativeConfig = Field(default_factory=SpeculativeConfig)


class TTSPerformanceConfig(BaseModel):
    """Safe, capability-detected acceleration settings for local TTS."""

    attention: str = "auto"  # auto | flash | eager
    dtype: str = "auto"  # auto | bf16 | fp16 | fp32
    torch_compile: str = "auto"  # auto | on | off
    cuda_graphs: str = "auto"  # auto | on | off
    fused_kernels: str = "auto"  # auto | on | off
    warmup: bool = True
    deepspeed: bool = False


class PerformanceConfig(BaseModel):
    """Cross-service inference acceleration profile."""

    llm: LLMPerformanceConfig = Field(default_factory=LLMPerformanceConfig)
    tts: TTSPerformanceConfig = Field(default_factory=TTSPerformanceConfig)


class DatabaseConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///./data/character.db"


class MemoryConfig(BaseModel):
    max_short_term_messages: int = 30
    retrieval_top_k: int = 8
    # Voice conversations use a hierarchical context pack instead of simply
    # dumping the last N rows into the model. These are approximate input
    # token budgets and intentionally leave room for model output/tools.
    context_budget_tokens: int = Field(default=12000, ge=2048, le=262144)
    recent_history_tokens: int = Field(default=6200, ge=512, le=196608)
    memory_tokens: int = Field(default=2600, ge=256, le=65536)
    summary_tokens: int = Field(default=1400, ge=128, le=32768)
    retrieval_candidates: int = Field(default=256, ge=8, le=10000)
    summary_trigger_messages: int = Field(default=20, ge=4, le=500)


class VoiceBrainConfig(BaseModel):
    """Autonomous executive controller used only by live voice surfaces."""

    enabled: bool = True
    tick_seconds: float = Field(default=5.0, ge=0.5, le=300.0)
    min_silence_seconds: float = Field(default=45.0, ge=5.0, le=7200.0)
    min_speak_cooldown_seconds: float = Field(default=75.0, ge=5.0, le=7200.0)
    soft_max_silence_seconds: float = Field(default=240.0, ge=15.0, le=21600.0)
    hard_max_silence_seconds: float = Field(default=600.0, ge=30.0, le=43200.0)
    max_proactive_turns_per_hour: int = Field(default=8, ge=0, le=120)
    decision_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    decision_max_tokens: int = Field(default=420, ge=128, le=4096)
    minimum_speak_confidence: float = Field(default=0.58, ge=0.0, le=1.0)
    event_ttl_seconds: float = Field(default=900.0, ge=30.0, le=86400.0)
    max_pending_events: int = Field(default=64, ge=8, le=4096)
    reflection_enabled: bool = True
    auto_memory_enabled: bool = True
    evaluator_enabled: bool = False
    # Autonomous side effects are deny-by-default. Future game adapters can
    # opt specific capabilities in (for example ``minecraft.move``) without
    # making Spotify/Discord/OBS actions implicitly autonomous.
    allowed_autonomous_capabilities: list[str] = Field(default_factory=list)


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )


class AvatarConfig(BaseModel):
    provider: str = "live2d"
    model: str = "/live2d/shizuku_ja/runtime/shizuku.model3.json"
    smart_expressions: bool = True
    idle_preset: str = "dynamic"
    idle_intensity: float = Field(default=1.0, ge=0.25, le=2.0)


class TTSConfig(BaseModel):
    engine: str = "zonos"  # zonos | indextts | edge-tts | openrouter
    zonos_url: str = "http://127.0.0.1:8091"
    indextts_url: str = "http://127.0.0.1:8090"
    # OpenRouter-hosted speech. Keep the key out of config.yaml; the value is
    # read from this environment variable at request time.
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key_env: str = "OPENROUTER_API_KEY"
    openrouter_model: str = "fish-audio/s2.1-pro-free:free"
    # Empty lets the selected OpenRouter provider choose its documented
    # default. Set a provider-specific voice ID only when the model supports
    # one (voice names are not portable between TTS models).
    openrouter_voice: str = ""
    openrouter_response_format: str = "mp3"
    openrouter_speed: float = Field(default=1.0, ge=0.25, le=4.0)
    # Fish Audio is used only as an authenticated voice-directory lookup for
    # the hosted OpenRouter Fish model.  The secret itself stays in .env.
    fish_audio_base_url: str = "https://api.fish.audio"
    fish_audio_api_key_env: str = "FISH_AUDIO_API_KEY"
    voice_ref: str = "tools/zonos/reference_voices/onokami.wav"  # project-owned reference audio for voice cloning
    language: str = "en-us"
    # Zonos emotion params
    happiness: float = 0.1
    sadness: float = 0.05
    disgust: float = 0.05
    fear: float = 0.05
    surprise: float = 0.05
    anger: float = 0.05
    other: float = 0.1
    neutral: float = 0.2
    # Zonos audio quality params
    speaking_rate: float = 15.0
    pitch_std: float = 45.0
    fmax: float = 24000.0
    vq_score: float = 0.78
    dnsmos_ovrl: float = 4.0
    cfg_scale: float = 2.0
    seed: int = 420
    seed_mode: str = "fixed"  # fixed | random
    emotion_mode: str = "smart"  # smart | manual
    voice_gender: int = 50  # -100 masculine .. +100 feminine voice preference


class STTConfig(BaseModel):
    # provider is intentionally separate from model so older Whisper presets
    # remain valid while Nemotron can be selected as the streaming backend.
    provider: str = "nemo_speech"  # nemo_speech | faster_whisper
    model: str = "nemotron-3.5-asr-streaming-0.6b"
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "float16"  # float16 | int8 | float32 | int8_float16
    beam_size: int = 5
    language: str = "auto"  # en | ja | es | fr | de | auto
    vad_filter: bool = True
    temperature: float = 0.0
    streaming_enabled: bool = True
    stream_chunk_ms: int = 320
    stream_language: str = "auto"
    fallback_enabled: bool = True
    sidecar_port: int = 8092


class DiscordConfig(BaseModel):
    enabled: bool = False
    mode: str = "client"  # client | bot
    build: str = "stable"  # stable | canary | ptb
    bot_token: str = ""  # stored in .env as DISCORD_BOT_TOKEN
    channel_id: str = ""  # default speaking channel for AI-initiated messages
    voice_channel_id: str = ""  # voice channel to join
    command_prefix: str = "ai!"
    status_text: str = "Listening..."
    # Server scope
    server_id: str = ""  # restrict to a specific Discord server
    # Voice auto-join
    auto_join_voice: bool = False  # join voice channel on bot start
    # If idle, join the current voice channel of an eligible message author.
    # An active voice session stays locked to its current channel.
    join_message_author_voice: bool = False
    live_join_enabled: bool = False  # allow manual/on-demand live joins
    live_join_follow_author: bool = False  # explicit join requests prefer the author's current voice channel
    join_method: str = "manual"  # manual | population
    voice_channel_mode: str = "specific"  # specific | biggest | lowest | above | below
    voice_channel_threshold: int = 0  # user count threshold for above/below modes
    # Channel filtering
    channel_mode: str = "all"  # all | allowlist | blocklist
    channel_list: list[str] = Field(default_factory=list)  # channel IDs for allowlist/blocklist
    allowed_user_ids: list[str] = Field(default_factory=list)  # empty means any non-bot user
    auto_reply: bool = True  # reply to ordinary messages in eligible channels
    typing_indicator: bool = True  # show Discord typing while the AI is generating
    # New explicit routing control. ``None`` keeps older YAML files
    # backwards-compatible; the runtime helper derives the legacy behavior
    # from auto_reply when this field was not saved yet.
    respond_to_every_message: bool | None = None
    # Bridge mode (Equicord plugin)
    bridge_user_id: str = ""  # Discord user ID of the account running Equicord


class DiscordVoiceOutputConfig(BaseModel):
    """Opt-in desktop Discord speech routing through a virtual cable."""

    enabled: bool = False
    # This is the playback endpoint of the second virtual cable. Existing
    # installations may still use ``CABLE Input`` and remain compatible.
    device_name: str = "CABLE-B Input"


class DiscordVoiceInputConfig(BaseModel):
    """Opt-in capture of the Discord call from the first virtual cable."""

    enabled: bool = False
    # The recording endpoint paired with the Discord account's output device.
    device_name: str = "CABLE-A Output"
    chunk_ms: int = 320
    mirror_transcript: bool = False
    mirror_text: bool = False
    # Hold a little longer after speech so natural pauses do not split one
    # sentence into multiple LLM turns. Short fragments are also merged by the
    # Discord bridge before they are queued.
    silence_ms: int = 1200


class SpotifyConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""  # SPOTIFY_CLIENT_ID in .env
    client_secret: str = ""  # SPOTIFY_CLIENT_SECRET in .env
    redirect_uri: str = "http://127.0.0.1:8000/api/integrations/spotify/callback"


class TwitchConfig(BaseModel):
    enabled: bool = False
    client_id: str = ""  # TWITCH_CLIENT_ID in .env
    client_secret: str = ""  # TWITCH_CLIENT_SECRET in .env
    channel: str = ""


class ObsConfig(BaseModel):
    """OBS Studio WebSocket v5 control and Discord camera routing."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    request_timeout: float = 5.0
    allowed_scenes: list[str] = Field(default_factory=list)
    discord_camera_name: str = "OBS Virtual Camera"


class IntegrationsConfig(BaseModel):
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    spotify: SpotifyConfig = Field(default_factory=SpotifyConfig)
    twitch: TwitchConfig = Field(default_factory=TwitchConfig)
    obs: ObsConfig = Field(default_factory=ObsConfig)


class AppConfig(BaseModel):
    character: CharacterConfig = Field(default_factory=CharacterConfig)
    user: UserConfig = Field(default_factory=UserConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    voice_brain: VoiceBrainConfig = Field(default_factory=VoiceBrainConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    avatar: AvatarConfig = Field(default_factory=AvatarConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    # Kept at the top level so the YAML entry is explicit and easy to find.
    # The Discord integration API exposes the same values alongside its other
    # settings for backwards-compatible UI editing.
    discord_voice_output: DiscordVoiceOutputConfig = Field(default_factory=DiscordVoiceOutputConfig)
    discord_voice_input: DiscordVoiceInputConfig = Field(default_factory=DiscordVoiceInputConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    message_mode: str = "all"  # all | commands_only


def discord_responds_to_every_message(discord: Any) -> bool:
    """Return the explicit all-messages setting with legacy fallback.

    New settings use ``respond_to_every_message``. Older config files only
    have ``auto_reply``; preserve their blank-prefix behavior until the user
    saves the new setting explicitly.
    """

    configured = getattr(discord, "respond_to_every_message", None)
    if configured is not None:
        return bool(configured)
    return bool(getattr(discord, "auto_reply", True) and not str(getattr(discord, "command_prefix", "") or "").strip())


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load configuration from YAML file."""
    if path is None:
        # Search common locations, starting from source file location for robustness
        project_root = data_root()
        candidates = [
            project_root / "config" / "config.yaml",
            resource_root() / "config" / "config.yaml",
            Path("config/config.yaml"),
            Path("../config/config.yaml"),
            Path("../../config/config.yaml"),
            Path("config.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break
        else:
            return AppConfig()

    path = Path(path)
    if not path.exists():
        return AppConfig()

    with path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return AppConfig.model_validate(data)


def save_config(cfg: AppConfig, path: str | Path | None = None) -> Path:
    """Save configuration back to YAML file."""
    if path is None:
        project_root = data_root()
        path = project_root / "config" / "config.yaml"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump()
    # Static character identity is owned by Markdown profiles. Keep only the
    # active profile pointer and directory in YAML; the legacy fields remain
    # on the Pydantic model so older config files can still be read/imported.
    character_data = data.get("character", {})
    for field_name in (
        "name", "profile_picture", "age", "gender", "pronouns", "description", "appearance",
        "appearance_height", "appearance_build", "appearance_hair", "appearance_eyes",
        "appearance_skin_or_fur", "appearance_clothing", "appearance_accessories",
        "appearance_distinguishing_features", "appearance_visual_style", "appearance_notes",
        "personality_summary", "response_style", "style_modifiers", "style_guidance",
        "traits", "dere_types", "behavior_rules", "custom_instructions", "backstory", "core_values", "likes", "dislikes",
        "immutable_traits",
    ):
        character_data.pop(field_name, None)
    data["character"] = character_data
    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return path


# Global config instance (loaded once at startup)
settings: AppConfig = load_config()
