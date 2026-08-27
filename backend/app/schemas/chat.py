from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    # Optional channel-scoped master preset. It is resolved for this request
    # only and never persisted as the global active configuration.
    master_preset_id: str | None = None
    # Rich hierarchical context is intentionally limited to live voice paths.
    source: Literal["chat", "web_voice", "discord_voice", "voice_brain"] = "chat"
    voice_session_id: str | None = None
    situational_context: str | None = None


class ProactiveChatRequest(BaseModel):
    conversation_id: str | None = None
    trigger: str = "silence"  # silence | emotion_change | greeting
    master_preset_id: str | None = None
    voice_session_id: str | None = None
    surface: Literal["web_voice", "discord_voice", "manual"] = "manual"
    agent_instruction: str | None = None
    situational_context: str | None = None


class ChatResponse(BaseModel):
    message_id: str
    conversation_id: str
    role: str = "assistant"
    content: str
    emotion: str | None = None
    expressive_label: str | None = None
    # A bounded semantic command for the renderer — never raw Cubism params.
    avatar_action: dict[str, Any] | None = None
    model: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    character_profile_id: str | None = None
    character_name: str | None = None
    character_profile_picture: str | None = None
    created_at: datetime


class MessagePublic(BaseModel):
    id: str
    role: str
    content: str
    emotion: str | None = None
    avatar_action: dict[str, Any] | None = None
    model: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    character_profile_id: str | None = None
    character_name: str | None = None
    character_profile_picture: str | None = None
    created_at: datetime


class ConversationPublic(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class CharacterPublic(BaseModel):
    id: str
    profile_id: str = ""
    name: str
    profile_picture: str = ""
    description: str
    personality: dict[str, float]
    emotion: dict[str, float]
    dominant_emotion: str
    model_provider: str
    model_name: str


class StatusResponse(BaseModel):
    character: CharacterPublic
    conversation_id: str | None = None
    message_count: int = 0


class WSMessage(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


# --- Memory ---

class MemoryCreate(BaseModel):
    memory_type: str = "episodic"
    content: str
    importance: float = 0.5
    pinned: bool = False
    source: str | None = None
    tags: list[str] = Field(default_factory=list)


class MemoryPublic(BaseModel):
    id: str
    memory_type: str
    content: str
    importance: float
    pinned: bool
    source: str | None
    tags: list[str]
    created_at: datetime
    last_accessed: datetime | None


# --- Goal ---

class GoalCreate(BaseModel):
    title: str
    description: str = ""
    priority: int = 0


class GoalPublic(BaseModel):
    id: str
    title: str
    description: str
    status: str
    priority: int
    created_at: datetime
    completed_at: datetime | None


# --- Skill ---

class SkillCreate(BaseModel):
    name: str
    description: str = ""
    proficiency: float = 0.5


class SkillUpdate(BaseModel):
    proficiency: float | None = None
    description: str | None = None


class SkillPublic(BaseModel):
    id: str
    name: str
    description: str
    proficiency: float
    experience: int
    last_used: datetime | None
    created_at: datetime
    updated_at: datetime


class TTSRequest(BaseModel):
    text: str
    # Optional channel-scoped master preset for speech generated from a
    # channel. Like ChatRequest, this is request-local and non-persistent.
    master_preset_id: str | None = None
    voice: str = "en-US-AnaNeural"
    voice_ref: str | None = None
    engine: str | None = None  # override: zonos | indextts | edge-tts | openrouter
    openrouter_model: str | None = None
    openrouter_voice: str | None = None
    openrouter_response_format: str | None = None
    openrouter_speed: float | None = None
    smart_emotions: bool | None = None
    speaking_rate: float | None = None
    pitch_std: float | None = None
    happiness: float | None = None
    sadness: float | None = None
    anger: float | None = None
    fear: float | None = None
    seed: int | None = None


class OpenRouterKeyUpdate(BaseModel):
    """Secret input for the hosted OpenRouter TTS integration.

    The key is written to the backend environment file and is never returned
    in settings, presets, or API responses.
    """

    api_key: str
    env_name: str | None = None


class FishAudioKeyUpdate(BaseModel):
    """Secret input for Fish Audio voice-directory searches."""

    api_key: str
    env_name: str | None = None


# --- Settings ---

class SettingsResponse(BaseModel):
    character_profile_id: str = ""
    character_name: str
    character_profile_picture: str = ""
    character_age: str
    character_gender: str
    character_pronouns: str = ""
    character_description: str
    character_appearance: str
    character_appearance_height: str = ""
    character_appearance_build: str = ""
    character_appearance_hair: str = ""
    character_appearance_eyes: str = ""
    character_appearance_skin_or_fur: str = ""
    character_appearance_clothing: str = ""
    character_appearance_accessories: str = ""
    character_appearance_distinguishing_features: str = ""
    character_appearance_visual_style: str = ""
    character_appearance_notes: str = ""
    character_personality_summary: str
    character_response_style: str = "Friendly"
    character_style_modifiers: list[str] = Field(default_factory=list)
    character_style_guidance: str = ""
    character_traits: list[str] = Field(default_factory=list)
    character_dere_types: list[str] = Field(default_factory=list)
    character_behavior_rules: str = ""
    character_custom_instructions: str = ""
    character_backstory: str
    character_core_values: list[str]
    character_likes: list[str]
    character_dislikes: list[str]
    character_immutable_traits: list[str]
    user_name: str
    user_age: str
    user_height: str
    user_gender: str
    user_pronouns: str
    user_location: str
    user_occupation: str
    user_bio: str
    user_hobbies: list[str]
    user_interests: list[str]
    user_favorite_games: list[str]
    user_favorite_anime: list[str]
    user_dislikes: list[str]
    user_notes: str
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_temperature: float
    llm_max_tokens: int
    avatar_provider: str
    avatar_model: str
    avatar_smart_expressions: bool = True
    avatar_idle_preset: str = "dynamic"
    avatar_idle_intensity: float = 1.0
    memory_max_short_term: int
    memory_retrieval_top_k: int
    # Message mode
    message_mode: str
    # TTS settings
    tts_engine: str
    tts_voice_ref: str
    tts_language: str
    tts_happiness: float
    tts_sadness: float
    tts_disgust: float
    tts_fear: float
    tts_surprise: float
    tts_anger: float
    tts_other: float
    tts_neutral: float
    tts_speaking_rate: float
    tts_pitch_std: float
    tts_fmax: float
    tts_vq_score: float
    tts_dnsmos_ovrl: float
    tts_cfg_scale: float
    tts_seed: int
    tts_seed_mode: str = "fixed"
    tts_emotion_mode: str = "smart"
    tts_voice_gender: int = 50
    tts_openrouter_base_url: str = "https://openrouter.ai/api/v1"
    tts_openrouter_api_key_env: str = "OPENROUTER_API_KEY"
    tts_openrouter_model: str = "fish-audio/s2.1-pro-free:free"
    tts_openrouter_voice: str = ""
    tts_openrouter_response_format: str = "mp3"
    tts_openrouter_speed: float = 1.0
    tts_fish_audio_base_url: str = "https://api.fish.audio"
    tts_fish_audio_api_key_env: str = "FISH_AUDIO_API_KEY"
    # STT settings (the provider/model split keeps legacy Whisper presets readable)
    stt_provider: str = "nemo_speech"
    stt_model: str = "nemotron-3.5-asr-streaming-0.6b"
    stt_device: str = "auto"
    stt_compute_type: str = "float16"
    stt_beam_size: int = 5
    stt_language: str = "auto"
    stt_vad_filter: bool = True
    stt_temperature: float = 0.0
    stt_streaming_enabled: bool = True
    stt_stream_chunk_ms: int = 320
    stt_stream_language: str = "auto"
    stt_fallback_enabled: bool = True
    stt_sidecar_port: int = 8092


class IntegrationStatus(BaseModel):
    name: str
    enabled: bool
    connected: bool
    configured: bool  # has required tokens
    description: str


class IntegrationsResponse(BaseModel):
    integrations: list[IntegrationStatus]


class DiscordConfigUpdate(BaseModel):
    enabled: bool | None = None
    mode: str | None = None
    build: str | None = None
    channel_id: str | None = None
    voice_channel_id: str | None = None
    command_prefix: str | None = None
    status_text: str | None = None
    bot_token: str | None = None
    server_id: str | None = None
    auto_join_voice: bool | None = None
    join_message_author_voice: bool | None = None
    live_join_enabled: bool | None = None
    live_join_follow_author: bool | None = None
    join_method: str | None = None
    voice_channel_mode: str | None = None
    voice_channel_threshold: int | None = None
    channel_mode: str | None = None
    channel_list: list[str] | None = None
    allowed_user_ids: list[str] | None = None
    bridge_user_id: str | None = None
    auto_reply: bool | None = None
    respond_to_every_message: bool | None = None
    typing_indicator: bool | None = None
    # Desktop Equicord voice output (VB-CABLE). These map to the top-level
    # ``discord_voice_output`` YAML section while remaining part of the
    # Discord settings API.
    voice_output_enabled: bool | None = None
    voice_output_device_name: str | None = None
    # Desktop Discord voice input (second virtual cable is used for output).
    voice_input_enabled: bool | None = None
    voice_input_device_name: str | None = None
    voice_input_chunk_ms: int | None = None
    voice_input_silence_ms: int | None = None
    voice_input_mirror_transcript: bool | None = None
    voice_input_mirror_text: bool | None = None


class DiscordJoinRequest(BaseModel):
    channel_id: str | None = None
    method: str | None = None  # 'manual' or 'population'
    mode: str | None = None  # selection strategy like 'specific', 'biggest', 'above', 'below'
    threshold: int | None = None
    mode_type: str | None = None  # 'client' or 'bot'


class SpotifyConfigUpdate(BaseModel):
    enabled: bool | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None


class SpotifyControlRequest(BaseModel):
    action: Literal[
        "play",
        "play_artist",
        "resume",
        "pause",
        "next",
        "previous",
        "volume",
        "shuffle",
        "repeat",
        "queue",
        "toggle",
    ]
    query: str | None = None
    volume: int | None = None
    device_id: str | None = None


class TwitchConfigUpdate(BaseModel):
    enabled: bool | None = None
    client_id: str | None = None
    client_secret: str | None = None
    channel: str | None = None


class ObsConfigUpdate(BaseModel):
    enabled: bool | None = None
    host: str | None = None
    port: int | None = None
    password: str | None = None
    request_timeout: float | None = None
    allowed_scenes: list[str] | None = None
    discord_camera_name: str | None = None


class ObsControlRequest(BaseModel):
    action: Literal[
        "status",
        "set_scene",
        "start_stream",
        "stop_stream",
        "start_recording",
        "stop_recording",
        "start_virtual_camera",
        "stop_virtual_camera",
        "start_discord_camera",
        "stop_discord_camera",
    ]
    scene: str | None = None


class SettingsUpdate(BaseModel):
    character_profile_id: str | None = None
    character_name: str | None = None
    character_profile_picture: str | None = None
    character_age: str | None = None
    character_gender: str | None = None
    character_pronouns: str | None = None
    character_description: str | None = None
    character_appearance: str | None = None
    character_appearance_height: str | None = None
    character_appearance_build: str | None = None
    character_appearance_hair: str | None = None
    character_appearance_eyes: str | None = None
    character_appearance_skin_or_fur: str | None = None
    character_appearance_clothing: str | None = None
    character_appearance_accessories: str | None = None
    character_appearance_distinguishing_features: str | None = None
    character_appearance_visual_style: str | None = None
    character_appearance_notes: str | None = None
    character_personality_summary: str | None = None
    character_response_style: str | None = None
    character_style_modifiers: list[str] | None = None
    character_style_guidance: str | None = None
    character_traits: list[str] | None = None
    character_dere_types: list[str] | None = None
    character_behavior_rules: str | None = None
    character_custom_instructions: str | None = None
    character_backstory: str | None = None
    character_core_values: list[str] | None = None
    character_likes: list[str] | None = None
    character_dislikes: list[str] | None = None
    character_immutable_traits: list[str] | None = None
    user_name: str | None = None
    user_age: str | None = None
    user_height: str | None = None
    user_gender: str | None = None
    user_pronouns: str | None = None
    user_location: str | None = None
    user_occupation: str | None = None
    user_bio: str | None = None
    user_hobbies: list[str] | None = None
    user_interests: list[str] | None = None
    user_favorite_games: list[str] | None = None
    user_favorite_anime: list[str] | None = None
    user_dislikes: list[str] | None = None
    user_notes: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    avatar_provider: str | None = None
    avatar_model: str | None = None
    avatar_smart_expressions: bool | None = None
    avatar_idle_preset: str | None = None
    avatar_idle_intensity: float | None = Field(default=None, ge=0.25, le=2.0)
    memory_max_short_term: int | None = None
    memory_retrieval_top_k: int | None = None
    # Message mode
    message_mode: str | None = None
    # TTS settings
    tts_engine: str | None = None
    tts_voice_ref: str | None = None
    tts_language: str | None = None
    tts_happiness: float | None = None
    tts_sadness: float | None = None
    tts_disgust: float | None = None
    tts_fear: float | None = None
    tts_surprise: float | None = None
    tts_anger: float | None = None
    tts_other: float | None = None
    tts_neutral: float | None = None
    tts_speaking_rate: float | None = None
    tts_pitch_std: float | None = None
    tts_fmax: float | None = None
    tts_vq_score: float | None = None
    tts_dnsmos_ovrl: float | None = None
    tts_cfg_scale: float | None = None
    tts_seed: int | None = None
    tts_seed_mode: str | None = None
    tts_emotion_mode: str | None = None
    tts_voice_gender: int | None = None
    tts_openrouter_base_url: str | None = None
    tts_openrouter_api_key_env: str | None = None
    tts_openrouter_model: str | None = None
    tts_openrouter_voice: str | None = None
    tts_openrouter_response_format: str | None = None
    tts_openrouter_speed: float | None = Field(default=None, ge=0.25, le=4.0)
    tts_fish_audio_base_url: str | None = None
    tts_fish_audio_api_key_env: str | None = None
    # STT settings
    stt_provider: str | None = None
    stt_model: str | None = None
    stt_device: str | None = None
    stt_compute_type: str | None = None
    stt_beam_size: int | None = None
    stt_language: str | None = None
    stt_vad_filter: bool | None = None
    stt_temperature: float | None = None
    stt_streaming_enabled: bool | None = None
    stt_stream_chunk_ms: int | None = None
    stt_stream_language: str | None = None
    stt_fallback_enabled: bool | None = None
    stt_sidecar_port: int | None = None
