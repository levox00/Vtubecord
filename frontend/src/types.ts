export interface CharacterPublic {
  id: string;
  profile_id?: string;
  name: string;
  profile_picture?: string;
  description: string;
  personality: Record<string, number>;
  emotion: Record<string, number>;
  dominant_emotion: string;
  model_provider: string;
  model_name: string;
}

export interface StatusResponse {
  character: CharacterPublic;
  conversation_id: string | null;
  message_count: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  emotion?: string | null;
  expressive_label?: string | null;
  avatar_action?: AvatarAction | null;
  model?: string | null;
  tools_used?: string[];
  character_profile_id?: string | null;
  character_name?: string | null;
  character_profile_picture?: string | null;
  created_at?: string;
  voiceBlob?: Blob;
  voiceUrl?: string;
}

export interface Conversation {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatResponse {
  message_id: string;
  conversation_id: string;
  role: string;
  content: string;
  emotion: string | null;
  expressive_label: string | null;
  avatar_action: AvatarAction | null;
  model: string | null;
  tools_used: string[];
  character_profile_id?: string | null;
  character_name?: string | null;
  character_profile_picture?: string | null;
  created_at: string;
}

export type VoiceBrainPhase =
  | "idle"
  | "listening"
  | "user_speaking"
  | "processing"
  | "deciding"
  | "generating"
  | "reflecting"
  | "speaking";

export interface VoiceBrainSessionStatus {
  id?: string;
  surface?: "web_voice" | "discord_voice";
  active: boolean;
  enabled?: boolean;
  phase?: VoiceBrainPhase | string;
  conversation_id?: string | null;
  silence_seconds?: number;
  next_wake_seconds?: number;
  proactive_turns_this_hour?: number;
  proactive_limit_per_hour?: number;
  pending_events?: number;
  internal_state?: Record<string, number>;
  last_decision?: VoiceBrainDecision;
  last_error?: string | null;
  subscriber_count?: number;
}

export interface VoiceBrainDecision {
  action: "WAIT" | "SPEAK" | "START_TOPIC" | "OBSERVE" | "REFLECT" | "ACT";
  reason: string;
  topic: string;
  confidence: number;
  next_wake_seconds: number;
  capability?: string;
  arguments?: Record<string, unknown>;
  speak_after_action?: boolean;
}

export interface VoiceBrainSettings {
  enabled: boolean;
  tick_seconds: number;
  min_silence_seconds: number;
  min_speak_cooldown_seconds: number;
  soft_max_silence_seconds: number;
  hard_max_silence_seconds: number;
  max_proactive_turns_per_hour: number;
  decision_temperature: number;
  decision_max_tokens: number;
  minimum_speak_confidence: number;
  event_ttl_seconds: number;
  max_pending_events: number;
  reflection_enabled: boolean;
  auto_memory_enabled: boolean;
  evaluator_enabled: boolean;
  allowed_autonomous_capabilities: string[];
}

/** Actions the AI may request; the animation director owns their Cubism implementation. */
export type AvatarGesture =
  | "wave"
  | "warm_nod"
  | "celebrate"
  | "dance"
  | "bow"
  | "wink"
  | "look_down"
  | "firm_shake"
  | "recoil"
  | "head_tilt"
  | "lean_in"
  | "look_away"
  | "laugh";

/** Safe, model-agnostic avatar command emitted by the AI controller. */
export interface AvatarAction {
  emotion: string;
  gesture: AvatarGesture;
  intensity: number;
  hold_ms: number;
}

export interface Memory {
  id: string;
  memory_type: string;
  content: string;
  importance: number;
  pinned: boolean;
  source: string | null;
  tags: string[];
  created_at: string;
  last_accessed: string | null;
}

export interface Goal {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: number;
  created_at: string;
  completed_at: string | null;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  proficiency: number;
  experience: number;
  last_used: string | null;
  created_at: string;
  updated_at: string;
}

export interface Settings {
  character_profile_id: string;
  character_name: string;
  character_profile_picture: string;
  character_age: string;
  character_gender: string;
  character_pronouns: string;
  character_description: string;
  character_appearance: string;
  character_appearance_height: string;
  character_appearance_build: string;
  character_appearance_hair: string;
  character_appearance_eyes: string;
  character_appearance_skin_or_fur: string;
  character_appearance_clothing: string;
  character_appearance_accessories: string;
  character_appearance_distinguishing_features: string;
  character_appearance_visual_style: string;
  character_appearance_notes: string;
  character_personality_summary: string;
  character_response_style: string;
  character_style_modifiers: string[];
  character_style_guidance: string;
  character_traits: string[];
  character_dere_types: string[];
  character_behavior_rules: string;
  character_custom_instructions: string;
  character_backstory: string;
  character_core_values: string[];
  character_likes: string[];
  character_dislikes: string[];
  character_immutable_traits: string[];
  // User Profile
  user_name: string;
  user_age: string;
  user_height: string;
  user_gender: string;
  user_pronouns: string;
  user_location: string;
  user_occupation: string;
  user_bio: string;
  user_hobbies: string[];
  user_interests: string[];
  user_favorite_games: string[];
  user_favorite_anime: string[];
  user_dislikes: string[];
  user_notes: string;
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  llm_temperature: number;
  llm_max_tokens: number;
  avatar_provider: string;
  avatar_model: string;
  avatar_smart_expressions: boolean;
  avatar_idle_preset: string;
  avatar_idle_intensity: number;
  memory_max_short_term: number;
  memory_retrieval_top_k: number;
  // Message mode
  message_mode: string;
  // TTS settings
  tts_engine: string;
  tts_voice_ref: string;
  tts_language: string;
  tts_happiness: number;
  tts_sadness: number;
  tts_disgust: number;
  tts_fear: number;
  tts_surprise: number;
  tts_anger: number;
  tts_other: number;
  tts_neutral: number;
  tts_speaking_rate: number;
  tts_pitch_std: number;
  tts_fmax: number;
  tts_vq_score: number;
  tts_dnsmos_ovrl: number;
  tts_cfg_scale: number;
  tts_seed: number;
  tts_seed_mode: string;
  tts_emotion_mode: string;
  tts_voice_gender: number;
  tts_openrouter_base_url: string;
  tts_openrouter_api_key_env: string;
  tts_openrouter_model: string;
  tts_openrouter_voice: string;
  tts_openrouter_response_format: string;
  tts_openrouter_speed: number;
  tts_fish_audio_base_url: string;
  tts_fish_audio_api_key_env: string;
  // STT (Whisper)
  stt_provider: string;
  stt_model: string;
  stt_device: string;
  stt_compute_type: string;
  stt_beam_size: number;
  stt_language: string;
  stt_vad_filter: boolean;
  stt_temperature: number;
  stt_streaming_enabled: boolean;
  stt_stream_chunk_ms: number;
  stt_stream_language: string;
  stt_fallback_enabled: boolean;
  stt_sidecar_port: number;
}

export interface WhisperModelInfo {
  id: string;
  name: string;
  params: string;
  size_mb: number;
  vram_mb: number;
  relative_speed: string;
  wer: string;
  description: string;
  downloaded: boolean;
  is_active: boolean;
  provider?: "nemo_speech" | "faster_whisper" | string;
  runtime?: string;
  streaming?: boolean;
  languages?: string;
  license?: string;
  license_url?: string;
  source_url?: string;
  license_accepted?: boolean;
  ready?: boolean;
  filename?: string;
  download_url?: string;
  default?: boolean;
  sha256?: string | null;
  download?: STTDownloadStatus;
  runtime_installation?: STTRuntimeInstallationStatus;
}

export interface STTDownloadStatus {
  model: string;
  status: "idle" | "paused" | "downloading" | "ready" | "error" | string;
  downloaded_bytes: number;
  total_bytes: number | null;
  progress_percent: number | null;
  speed_bytes_per_sec: number | null;
  error: string | null;
  started_at: number | null;
  updated_at: number | null;
}

export interface STTRuntimeInstallationStatus {
  status: "idle" | "installing" | "ready" | "error" | string;
  executable?: string | null;
  error?: string | null;
  last_output?: string | null;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface LLMDownloadStatus {
  model: string;
  status: "idle" | "paused" | "downloading" | "ready" | "error" | string;
  downloaded_bytes: number;
  total_bytes: number | null;
  progress_percent: number | null;
  speed_bytes_per_sec: number | null;
  error: string | null;
  started_at: number | null;
  updated_at: number | null;
}

export interface LLMModelInfo {
  id: string;
  name: string;
  filename: string;
  size_bytes: number;
  size_gb: number;
  quantization?: string | null;
  parameters?: string | null;
  description: string;
  source_url?: string | null;
  official_source_url?: string | null;
  download_url?: string | null;
  license?: string | null;
  license_url?: string | null;
  requires_hf_access?: boolean;
  downloaded: boolean;
  ready: boolean;
  license_accepted: boolean;
  download: LLMDownloadStatus;
}

export interface LLMModelLicense {
  model: string;
  license: string;
  license_url: string;
  source_url: string;
  official_source_url: string;
  requires_hf_access: boolean;
  accepted: boolean;
  text: string;
}

export interface STTRuntimeStatus {
  provider: string;
  configured_provider?: string;
  model: string;
  device: string;
  compute_type?: string;
  cuda_devices?: number;
  ready: boolean;
  streaming: boolean;
  fallback_enabled?: boolean;
  chunk_ms?: number;
  sidecar_port?: number;
  error?: string | null;
  sidecar_installed?: boolean;
  model_downloaded?: boolean;
  fallback_active?: boolean;
  installation?: STTRuntimeInstallationStatus;
}

export interface Preset {
  id: string;
  name: string;
  // Legacy types stay readable for old snapshots; new presets are engine-scoped.
  type: "master" | "user" | "character" | "llm" | "tts" | "avatar" | "stt";
  data: Partial<Settings> & {
    llm_preset_id?: string;
    tts_preset_id?: string;
    avatar_preset_id?: string;
    stt_preset_id?: string;
    character_profile_id?: string;
  };
  created_at: string;
}

export interface AppearanceProfile {
  height: string;
  build: string;
  hair: string;
  eyes: string;
  skin_or_fur: string;
  clothing: string;
  accessories: string;
  distinguishing_features: string;
  visual_style: string;
  notes: string;
}

export interface CharacterProfile {
  id: string;
  name: string;
  profile_picture: string;
  age: string;
  gender: string;
  pronouns: string;
  response_style: string;
  style_modifiers: string[];
  style_guidance: string;
  traits: string[];
  dere_types: string[];
  core_values: string[];
  likes: string[];
  dislikes: string[];
  immutable_traits: string[];
  description: string;
  personality_guidance: string;
  appearance: AppearanceProfile;
  appearance_notes: string;
  backstory: string;
  behavior_rules: string;
  custom_instructions: string;
  source_file: string;
  active: boolean;
}

export interface TraitOption {
  id: string;
  label: string;
  category: string;
  description: string;
  guidance: string;
  tags: string[];
}

export interface CharacterTraitLibrary {
  styles: string[];
  style_modifiers: string[];
  traits: TraitOption[];
  dere_types: TraitOption[];
  core_values: string[];
  immutable_traits: string[];
  appearance_options: Record<string, string[]>;
  metadata: Record<string, unknown>;
}

export interface TTSVoices {
  zonos: Array<{ name: string; path: string }>;
  indextts: Array<{ name: string; path: string }>;
  edge: Array<{ name: string; path: string }>;
}

// --- Integrations ---

export interface IntegrationStatus {
  name: string;
  enabled: boolean;
  connected: boolean;
  configured: boolean;
  description: string;
}

export interface IntegrationsResponse {
  integrations: IntegrationStatus[];
}

export interface DiscordConfig {
  enabled: boolean;
  bot_token: string;
  channel_id: string;
  voice_channel_id: string;
  command_prefix: string;
  status_text: string;
  server_id: string;
  auto_join_voice: boolean;
  join_message_author_voice?: boolean;
  live_join_follow_author?: boolean;
  voice_channel_mode: string;
  voice_channel_threshold: number;
  channel_mode: string;
  channel_list: string[];
  allowed_user_ids: string[];
  respond_to_every_message?: boolean;
  typing_indicator?: boolean;
  voice_output_enabled?: boolean;
  voice_output_device_name?: string;
  voice_input_enabled?: boolean;
  voice_input_device_name?: string;
  voice_input_chunk_ms?: number;
  voice_input_silence_ms?: number;
  voice_input_mirror_transcript?: boolean;
  voice_input_mirror_text?: boolean;
}

export interface DiscordVoiceOutputStatus {
  config: { enabled: boolean; device_name: string };
  device_found: boolean;
  device_selected: { index?: number; name?: string; default_samplerate?: number } | null;
  available_devices: Array<{
    index: number;
    name: string;
    max_output_channels: number;
    default_samplerate: number;
    is_virtual_cable?: boolean;
  }>;
  playing: boolean;
  last_playback_error?: string | null;
  bridge_connected: boolean;
  voice_connected: boolean;
  voice_channel_id?: string | null;
  diagnostics?: { ready?: boolean; reason?: string; next_step?: string };
}

export interface DiscordVoiceInputStatus {
  config: {
    enabled: boolean;
    device_name: string;
    chunk_ms: number;
    silence_ms: number;
    mirror_text: boolean;
  };
  capture: {
    enabled: boolean;
    running: boolean;
    state: string;
    channel_id?: string | null;
    device_found: boolean;
    device_selected: { index?: number; name?: string; default_samplerate?: number } | null;
    configured_device_name?: string;
    available_devices: Array<{
      index: number;
      name: string;
      max_input_channels: number;
      default_samplerate: number;
      is_virtual_cable?: boolean;
    }>;
    last_error?: string | null;
    last_partial?: string;
    last_final?: string;
    last_language?: string;
    frames_dropped?: number;
  };
  runtime?: { provider?: string; model?: string; device?: string; ready?: boolean; error?: string | null };
  bridge_connected: boolean;
  voice_connected: boolean;
  voice_channel_id?: string | null;
  queue_depth?: number;
  diagnostics?: { ready?: boolean; reason?: string; next_step?: string };
}

export interface SpotifyConfig {
  enabled: boolean;
  client_id: string;
  client_secret: string;
  redirect_uri: string;
}

export interface SpotifyPlayerStatus {
  connected: boolean;
  is_playing: boolean;
  ai_control_mode?: "detecting" | "tool_calling" | "parser_fallback";
  ai_tool_capable?: boolean;
  liked_songs_scope_granted?: boolean;
  liked_songs_modify_scope_granted?: boolean;
  progress_ms?: number;
  volume_percent?: number | null;
  error?: string;
  device?: {
    id?: string | null;
    name?: string | null;
    type?: string | null;
    is_active?: boolean;
  } | null;
  item?: {
    id?: string | null;
    uri?: string | null;
    name?: string | null;
    artists?: string[];
    album?: string | null;
    image_url?: string | null;
    duration_ms?: number | null;
  } | null;
}

export type SpotifyControlAction =
  | "play"
  | "play_artist"
  | "resume"
  | "pause"
  | "next"
  | "previous"
  | "volume"
  | "shuffle"
  | "repeat"
  | "queue"
  | "toggle";

export interface TwitchConfig {
  enabled: boolean;
  client_id: string;
  client_secret: string;
  channel: string;
}

export interface ObsConfig {
  enabled: boolean;
  host: string;
  port: number;
  password?: string;
  request_timeout: number;
  allowed_scenes: string[];
  discord_camera_name: string;
}

export interface ObsStatus {
  connected: boolean;
  enabled?: boolean;
  error?: string;
  obs_studio_version?: string;
  obs_websocket_version?: string;
  current_scene?: string;
  scenes?: string[];
  stream?: { active: boolean; reconnecting?: boolean; timecode?: string };
  recording?: { active: boolean; paused?: boolean; timecode?: string };
  virtual_camera?: { active: boolean };
  discord_camera?: {
    bridge_connected: boolean;
    voice_connected: boolean;
    active: boolean;
    device_id?: string | null;
    device_name?: string | null;
    error?: string;
  };
  config?: {
    host: string;
    port: number;
    password_configured: boolean;
    request_timeout: number;
    allowed_scenes: string[];
    discord_camera_name: string;
  };
}

export type ObsControlAction =
  | "status"
  | "set_scene"
  | "start_stream"
  | "stop_stream"
  | "start_recording"
  | "stop_recording"
  | "start_virtual_camera"
  | "stop_virtual_camera"
  | "start_discord_camera"
  | "stop_discord_camera";
