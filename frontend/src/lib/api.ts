import type {
  ChatMessage,
  ChatResponse,
  CharacterProfile,
  CharacterTraitLibrary,
  Conversation,
  DiscordConfig,
  DiscordVoiceInputStatus,
  DiscordVoiceOutputStatus,
  Goal,
  IntegrationsResponse,
  LLMDownloadStatus,
  LLMModelInfo,
  LLMModelLicense,
  Memory,
  ObsConfig,
  ObsControlAction,
  ObsStatus,
  Preset,
  Settings,
  Skill,
  SpotifyConfig,
  SpotifyControlAction,
  SpotifyPlayerStatus,
  STTRuntimeStatus,
  StatusResponse,
  TTSVoices,
  TwitchConfig,
  VoiceBrainSessionStatus,
  VoiceBrainSettings,
} from "../types";
import { apiBase } from "./runtime";

const BASE = apiBase();

function reportToolCalls(response: ChatResponse): ChatResponse {
  for (const tool of response.tools_used || []) {
    console.info(`Tool calling feature ${tool} used by ${response.model || "unknown-model"}`);
  }
  return response;
}

export async function fetchStatus(): Promise<StatusResponse> {
  const res = await fetch(`${BASE}/status`);
  if (!res.ok) throw new Error(`Status failed: ${res.status}`);
  return res.json();
}

export async function sendChat(
  message: string,
  conversationId?: string | null,
  masterPresetId?: string | null,
  voiceContext?: {
    source: "web_voice" | "discord_voice" | "voice_brain";
    sessionId?: string | null;
    situationalContext?: string | null;
  },
): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      conversation_id: conversationId || null,
      master_preset_id: masterPresetId || null,
      source: voiceContext?.source || "chat",
      voice_session_id: voiceContext?.sessionId || null,
      situational_context: voiceContext?.situationalContext || null,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Chat failed: ${res.status} ${text}`);
  }
  return reportToolCalls(await res.json());
}

// --- Autonomous live voice brain ---

export async function openVoiceBrainSession(data: {
  session_id: string;
  surface: "web_voice" | "discord_voice";
  channel_key?: string;
  conversation_id?: string | null;
  master_preset_id?: string | null;
  enabled?: boolean;
  phase?: string;
}): Promise<VoiceBrainSessionStatus> {
  const res = await fetch(`${BASE}/voice-brain/sessions/open`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Voice brain session failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function heartbeatVoiceBrainSession(
  sessionId: string,
  data: { phase?: string; conversation_id?: string | null; enabled?: boolean },
): Promise<VoiceBrainSessionStatus> {
  const res = await fetch(`${BASE}/voice-brain/sessions/${encodeURIComponent(sessionId)}/heartbeat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Voice brain heartbeat failed: ${res.status}`);
  return res.json();
}

export async function sendVoiceBrainEvent(
  sessionId: string,
  data: { event_type: string; source?: string; priority?: number; payload?: Record<string, unknown> },
): Promise<{ event_id: string }> {
  const res = await fetch(`${BASE}/voice-brain/sessions/${encodeURIComponent(sessionId)}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Voice brain event failed: ${res.status}`);
  return res.json();
}

export async function closeVoiceBrainSession(sessionId: string): Promise<void> {
  await fetch(`${BASE}/voice-brain/sessions/${encodeURIComponent(sessionId)}/close`, { method: "POST" });
}

export async function fetchVoiceBrainSettings(): Promise<VoiceBrainSettings> {
  const res = await fetch(`${BASE}/voice-brain/settings`);
  if (!res.ok) throw new Error(`Voice brain settings failed: ${res.status}`);
  return res.json();
}

export async function updateVoiceBrainSettings(
  data: Partial<VoiceBrainSettings>,
): Promise<VoiceBrainSettings> {
  const res = await fetch(`${BASE}/voice-brain/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Voice brain settings update failed: ${res.status} ${await res.text()}`);
  return res.json();
}

export async function sendProactiveChat(
  conversationId?: string | null,
  trigger: string = "silence",
  masterPresetId?: string | null,
): Promise<ChatResponse> {
  const res = await fetch(`${BASE}/chat/proactive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId || null,
      trigger,
      master_preset_id: masterPresetId || null,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Proactive chat failed: ${res.status} ${text}`);
  }
  return reportToolCalls(await res.json());
}

// --- Memories ---

export async function fetchMemories(type?: string): Promise<Memory[]> {
  const url = type ? `${BASE}/memories?memory_type=${type}` : `${BASE}/memories`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch memories: ${res.status}`);
  return res.json();
}

export async function createMemory(data: {
  memory_type?: string;
  content: string;
  importance?: number;
  tags?: string[];
}): Promise<Memory> {
  const res = await fetch(`${BASE}/memories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create memory: ${res.status}`);
  return res.json();
}

export async function deleteMemory(id: string): Promise<void> {
  const res = await fetch(`${BASE}/memories/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete memory: ${res.status}`);
}

// --- Goals ---

export async function fetchGoals(status?: string): Promise<Goal[]> {
  const url = status ? `${BASE}/goals?status=${status}` : `${BASE}/goals`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch goals: ${res.status}`);
  return res.json();
}

export async function createGoal(data: {
  title: string;
  description?: string;
  priority?: number;
}): Promise<Goal> {
  const res = await fetch(`${BASE}/goals`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create goal: ${res.status}`);
  return res.json();
}

export async function updateGoal(
  id: string,
  status: string
): Promise<Goal> {
  const res = await fetch(`${BASE}/goals/${id}?status=${status}`, {
    method: "PATCH",
  });
  if (!res.ok) throw new Error(`Failed to update goal: ${res.status}`);
  return res.json();
}

export async function deleteGoal(id: string): Promise<void> {
  const res = await fetch(`${BASE}/goals/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete goal: ${res.status}`);
}

// --- Skills ---

export async function fetchSkills(): Promise<Skill[]> {
  const res = await fetch(`${BASE}/skills`);
  if (!res.ok) throw new Error(`Failed to fetch skills: ${res.status}`);
  return res.json();
}

export async function createSkill(data: {
  name: string;
  description?: string;
  proficiency?: number;
}): Promise<Skill> {
  const res = await fetch(`${BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create skill: ${res.status}`);
  return res.json();
}

export async function updateSkill(
  id: string,
  data: { proficiency?: number; description?: string }
): Promise<Skill> {
  const res = await fetch(`${BASE}/skills/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update skill: ${res.status}`);
  return res.json();
}

export async function deleteSkill(id: string): Promise<void> {
  const res = await fetch(`${BASE}/skills/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete skill: ${res.status}`);
}

// --- Settings ---

export async function fetchSettings(): Promise<Settings> {
  const res = await fetch(`${BASE}/settings`);
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.status}`);
  return res.json();
}

export async function updateSettings(data: Partial<Settings>): Promise<Settings> {
  const res = await fetch(`${BASE}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update settings: ${res.status}`);
  return res.json();
}

// --- Presets ---

export async function fetchPresets(): Promise<Preset[]> {
  const res = await fetch(`${BASE}/presets`);
  if (!res.ok) throw new Error(`Failed to fetch presets: ${res.status}`);
  return res.json();
}

export async function fetchGGUFModels(): Promise<Array<{ name: string; filename: string; size_gb: number }>> {
  const res = await fetch(`${BASE}/models/gguf`);
  if (!res.ok) throw new Error(`Failed to fetch GGUF models: ${res.status}`);
  return res.json();
}

export async function fetchLLMModels(): Promise<LLMModelInfo[]> {
  const res = await fetch(`${BASE}/llm/models`);
  if (!res.ok) throw new Error(`Failed to fetch local LLM models: ${res.status}`);
  return res.json();
}

export async function fetchLLMModelLicense(model: string): Promise<LLMModelLicense> {
  const res = await fetch(`${BASE}/llm/models/${encodeURIComponent(model)}/license`);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to fetch model license: ${res.status}`);
  }
  return res.json();
}

export async function acceptLLMModelLicense(model: string): Promise<{ accepted_at: string }> {
  const res = await fetch(`${BASE}/llm/models/${encodeURIComponent(model)}/license/accept`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to accept model license: ${res.status}`);
  }
  return res.json();
}

export async function downloadLLMModel(model: string): Promise<{ status: string; model: string; message: string; download?: LLMDownloadStatus }> {
  const res = await fetch(`${BASE}/llm/models/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to trigger local LLM download: ${res.status}`);
  }
  return res.json();
}

export async function fetchLLMDownloadStatus(model: string): Promise<LLMDownloadStatus> {
  const res = await fetch(`${BASE}/llm/models/${encodeURIComponent(model)}/download-status`);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to read LLM download status: ${res.status}`);
  }
  return res.json();
}

export async function createPreset(data: { name: string; type: string; data: Partial<Settings> }): Promise<Preset> {
  const res = await fetch(`${BASE}/presets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create preset: ${res.status}`);
  return res.json();
}

export async function updatePreset(id: string, data: { name?: string; data?: Partial<Settings> }): Promise<Preset> {
  const res = await fetch(`${BASE}/presets/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update preset: ${res.status}`);
  return res.json();
}

export async function deletePreset(id: string): Promise<void> {
  const res = await fetch(`${BASE}/presets/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete preset: ${res.status}`);
}

export async function applyPreset(id: string): Promise<Settings> {
  const res = await fetch(`${BASE}/presets/${id}/apply`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to apply preset: ${res.status}`);
  return res.json();
}

/** Resolve a channel master bundle without changing the active global draft. */
export async function resolvePreset(id: string): Promise<Settings> {
  const res = await fetch(`${BASE}/presets/${id}/resolve`);
  if (!res.ok) throw new Error(`Failed to resolve preset: ${res.status}`);
  return res.json();
}

// --- Markdown character profiles ---

export async function fetchCharacterProfiles(): Promise<CharacterProfile[]> {
  const res = await fetch(`${BASE}/character-profiles`);
  if (!res.ok) throw new Error(`Failed to fetch character profiles: ${res.status}`);
  return res.json();
}

export async function fetchCharacterProfile(id: string): Promise<CharacterProfile> {
  const res = await fetch(`${BASE}/character-profiles/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to fetch character profile: ${res.status}`);
  return res.json();
}

export async function createCharacterProfile(data: Partial<CharacterProfile> & { id?: string }): Promise<CharacterProfile> {
  const res = await fetch(`${BASE}/character-profiles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create character profile: ${res.status}`);
  return res.json();
}

export async function updateCharacterProfile(id: string, data: Partial<CharacterProfile>): Promise<CharacterProfile> {
  const res = await fetch(`${BASE}/character-profiles/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update character profile: ${res.status}`);
  return res.json();
}

export async function uploadCharacterProfilePicture(id: string, file: File): Promise<CharacterProfile> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${BASE}/character-profiles/${encodeURIComponent(id)}/picture`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Failed to upload character picture: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function deleteCharacterProfile(id: string): Promise<void> {
  const res = await fetch(`${BASE}/character-profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete character profile: ${res.status}`);
}

export async function applyCharacterProfile(id: string): Promise<CharacterProfile> {
  const res = await fetch(`${BASE}/character-profiles/${encodeURIComponent(id)}/apply`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to apply character profile: ${res.status}`);
  return res.json();
}

export async function fetchCharacterTraitLibrary(query?: string): Promise<CharacterTraitLibrary> {
  const suffix = query?.trim() ? `?query=${encodeURIComponent(query.trim())}` : "";
  const res = await fetch(`${BASE}/character-trait-library${suffix}`);
  if (!res.ok) throw new Error(`Failed to fetch character trait library: ${res.status}`);
  return res.json();
}

export async function addCharacterTraitOption(data: { id: string; label: string; category: string; description?: string; guidance?: string; tags?: string[] }): Promise<CharacterTraitLibrary> {
  const res = await fetch(`${BASE}/character-trait-library`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to save character trait: ${res.status}`);
  return res.json();
}

// --- Conversations ---

export async function fetchConversations(): Promise<Conversation[]> {
  const res = await fetch(`${BASE}/conversations`);
  if (!res.ok) throw new Error(`Failed to fetch conversations: ${res.status}`);
  return res.json();
}

export async function fetchMessages(conversationId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${BASE}/conversations/${conversationId}/messages`);
  if (!res.ok) throw new Error(`Failed to fetch messages: ${res.status}`);
  return res.json();
}

// --- TTS ---

export async function fetchTTS(
  text: string,
  voice?: string,
  engine?: string,
  voiceRef?: string,
  masterPresetId?: string | null,
): Promise<Blob> {
  const payload: Record<string, any> = { text };
  if (voice && voice !== "default") payload.voice = voice;
  if (engine) payload.engine = engine;
  if (voiceRef) payload.voice_ref = voiceRef;
  if (masterPresetId) payload.master_preset_id = masterPresetId;

  const res = await fetch(`${BASE}/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`TTS failed: ${res.status}`);
  return res.blob();
}

export async function fetchTTSVoices(): Promise<TTSVoices> {
  const res = await fetch(`${BASE}/tts/voices`);
  if (!res.ok) throw new Error(`Failed to fetch TTS voices: ${res.status}`);
  return res.json();
}

export async function uploadTTSVoice(file: File): Promise<{ path: string; name: string }> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${BASE}/tts/upload-voice`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`Failed to upload voice: ${res.status}`);
  return res.json();
}

// --- STT (local Whisper) ---

export async function fetchSTT(audioBlob: Blob, masterPresetId?: string | null): Promise<string> {
  const formData = new FormData();
  formData.append("file", audioBlob, "audio.wav");
  if (masterPresetId) formData.append("master_preset_id", masterPresetId);
  const res = await fetch(`${BASE}/stt`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error(`STT failed: ${res.status}`);
  const data = await res.json();
  return data.text;
}

// --- Integrations ---

export async function fetchIntegrations(): Promise<IntegrationsResponse> {
  const res = await fetch(`${BASE}/integrations`);
  if (!res.ok) throw new Error(`Failed to fetch integrations: ${res.status}`);
  return res.json();
}

export async function updateDiscordIntegration(config: Partial<DiscordConfig>): Promise<void> {
  const res = await fetch(`${BASE}/integrations/discord`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`Failed to update Discord: ${res.status}`);
}

export async function fetchDiscordVoiceOutputStatus(): Promise<DiscordVoiceOutputStatus> {
  const res = await fetch(`${BASE}/integrations/discord/voice-output/status`);
  if (!res.ok) throw new Error(`Discord voice output status failed: ${res.status}`);
  return res.json();
}

export async function fetchDiscordVoiceOutputDevices(): Promise<DiscordVoiceOutputStatus["available_devices"]> {
  const res = await fetch(`${BASE}/integrations/discord/voice-output/devices`);
  if (!res.ok) throw new Error(`Discord audio devices failed: ${res.status}`);
  const data = await res.json();
  return data.devices || [];
}

export async function testDiscordVoiceOutput(): Promise<{ ok: boolean; message?: string; error?: string; status?: DiscordVoiceOutputStatus }> {
  const res = await fetch(`${BASE}/integrations/discord/voice-output/test`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `Discord voice output test failed: ${res.status}`);
  return data;
}

export async function fetchDiscordVoiceInputStatus(): Promise<DiscordVoiceInputStatus> {
  const res = await fetch(`${BASE}/integrations/discord/voice-input/status`);
  if (!res.ok) throw new Error(`Discord voice input status failed: ${res.status}`);
  return res.json();
}

export async function fetchDiscordVoiceInputDevices(): Promise<DiscordVoiceInputStatus["capture"]["available_devices"]> {
  const res = await fetch(`${BASE}/integrations/discord/voice-input/devices`);
  if (!res.ok) throw new Error(`Discord voice input devices failed: ${res.status}`);
  const data = await res.json();
  return data.devices || [];
}

export async function testDiscordVoiceInput(): Promise<{ ok: boolean; message?: string; error?: string; status?: DiscordVoiceInputStatus; device?: unknown }> {
  const res = await fetch(`${BASE}/integrations/discord/voice-input/test`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `Discord voice input test failed: ${res.status}`);
  return data;
}

export async function updateSpotifyIntegration(config: Partial<SpotifyConfig>): Promise<void> {
  const res = await fetch(`${BASE}/integrations/spotify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`Failed to update Spotify: ${res.status}`);
}

export async function updateTwitchIntegration(config: Partial<TwitchConfig>): Promise<void> {
  const res = await fetch(`${BASE}/integrations/twitch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`Failed to update Twitch: ${res.status}`);
}

export async function updateObsIntegration(config: Partial<ObsConfig>): Promise<void> {
  const res = await fetch(`${BASE}/integrations/obs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `Failed to update OBS: ${res.status}`);
}

export async function fetchObsStatus(): Promise<ObsStatus> {
  const res = await fetch(`${BASE}/integrations/obs/status`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `OBS status failed: ${res.status}`);
  return data;
}

export async function testObsIntegration(): Promise<{ success: boolean; message: string; status?: ObsStatus }> {
  const res = await fetch(`${BASE}/integrations/obs/test`, { method: "POST" });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `OBS test failed: ${res.status}`);
  return { success: data.success ?? data.ok ?? false, message: data.message ?? data.error ?? "", status: data.status };
}

export async function controlObs(action: ObsControlAction, options: { scene?: string } = {}): Promise<ObsStatus> {
  const res = await fetch(`${BASE}/integrations/obs/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...options }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `OBS control failed: ${res.status}`);
  return data.status;
}

export async function testDiscordIntegration(): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${BASE}/integrations/discord/test`, { method: "POST" });
  if (!res.ok) throw new Error(`Discord test failed: ${res.status}`);
  return res.json();
}

export async function testSpotifyIntegration(): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${BASE}/integrations/spotify/test`, { method: "POST" });
  if (!res.ok) throw new Error(`Spotify test failed: ${res.status}`);
  const data = await res.json();
  return { success: data.success ?? data.ok ?? false, message: data.message ?? data.error ?? "" };
}

export async function fetchSpotifyAuthUrl(): Promise<{ auth_url: string; redirect_uri: string }> {
  const res = await fetch(`${BASE}/integrations/spotify/auth-url`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `Spotify auth failed: ${res.status}`);
  return data;
}

export async function fetchSpotifyStatus(): Promise<SpotifyPlayerStatus> {
  const res = await fetch(`${BASE}/integrations/spotify/status`);
  if (!res.ok) throw new Error(`Spotify status failed: ${res.status}`);
  return res.json();
}

export async function controlSpotify(
  action: SpotifyControlAction,
  options: { query?: string; volume?: number; device_id?: string | null } = {},
): Promise<SpotifyPlayerStatus> {
  const res = await fetch(`${BASE}/integrations/spotify/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...options }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || `Spotify control failed: ${res.status}`);
  return data.status;
}

export async function logoutSpotify(): Promise<void> {
  const res = await fetch(`${BASE}/integrations/spotify/logout`, { method: "POST" });
  if (!res.ok) throw new Error(`Spotify logout failed: ${res.status}`);
}

// --- Logs ---

export interface LogEntry {
  timestamp: string;
  level: string;
  source: string;
  message: string;
}

export async function fetchLogs(limit = 100, level?: string, source?: string): Promise<LogEntry[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (level) params.set("level", level);
  if (source) params.set("source", source);
  const res = await fetch(`${BASE}/logs?${params}`);
  if (!res.ok) throw new Error(`Failed to fetch logs: ${res.status}`);
  return res.json();
}

export async function clearLogs(): Promise<void> {
  await fetch(`${BASE}/logs`, { method: "DELETE" });
}

// --- Voice Messages ---

export async function sendVoiceMessage(
  audioBlob: Blob,
  conversationId?: string | null,
  masterPresetId?: string | null,
): Promise<ChatResponse> {
  const formData = new FormData();
  formData.append("file", audioBlob, "voice.webm");
  if (conversationId) formData.append("conversation_id", conversationId);
  if (masterPresetId) formData.append("master_preset_id", masterPresetId);
  const res = await fetch(`${BASE}/chat/voice`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Voice chat failed: ${res.status} ${text}`);
  }
  return reportToolCalls(await res.json());
}

// --- Telemetry ---

export interface TelemetryData {
  gpu: {
    name: string;
    total_vram_mb: number;
    used_vram_mb: number;
    free_vram_mb: number;
    utilization_pct: number;
    temperature_c: number | null;
    available: boolean;
  };
  llm: {
    model_name: string;
    architecture: string;
    file_size_gb: number;
    vram_allocated_gb: number;
    tokens_per_sec: number;
    gpu_load_pct: number;
    context_window: number;
    provider: string;
  };
  tts: {
    engine: string;
    name: string;
    vram_allocated_gb: number;
    vram_allocated_mb: number;
    device: string;
    speed_multiplier: string;
    latency_ms: number;
    sample_rate: string;
    precision: string;
    specs: string[];
  };
  stt?: {
    model: string;
    name: string;
    params: string;
    vram_allocated_mb: number;
    vram_allocated_gb: number;
    device: string;
    compute_type: string;
    speed_multiplier: string;
    latency_per_sec: string;
    beam_size: number;
    vad_filter: boolean;
    language: string;
    wer: string;
    specs: string[];
  };
}

export interface TelemetryQuery {
  llm_model?: string;
  llm_provider?: string;
  tts_engine?: string;
  stt_model?: string;
  stt_provider?: string;
  stt_device?: string;
  stt_compute_type?: string;
}

export async function fetchTelemetry(query: TelemetryQuery = {}): Promise<TelemetryData> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, value);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${BASE}/telemetry${suffix}`);
  if (!res.ok) throw new Error(`Failed to fetch telemetry: ${res.status}`);
  return res.json();
}

// --- Resource monitor ---

export interface ResourceMonitorProcess {
  role: string;
  pid: number;
  name: string;
  status: string;
  ram_mb: number | null;
  vram_mb: number | null;
  cpu_percent: number | null;
}

export interface ResourceMonitorModel {
  id: string;
  label: string;
  model: string;
  engine: string;
  status: "active" | "configured" | "cloud";
  pid: number | null;
  process_name: string | null;
  ram_mb: number | null;
  vram_mb: number | null;
  cpu_percent: number | null;
}

export interface ResourceMonitorService {
  name: string;
  url: string;
  status: "online" | "error" | "offline";
  latency_ms: number | null;
  http_status: number | null;
}

export interface ResourceMonitorData {
  timestamp: string;
  host: {
    cpu_percent: number | null;
    ram: {
      total_mb: number | null;
      used_mb: number | null;
      available_mb: number | null;
      percent: number | null;
      available: boolean;
    };
    gpu: TelemetryData["gpu"];
  };
  models: ResourceMonitorModel[];
  processes: ResourceMonitorProcess[];
  services: ResourceMonitorService[];
}

export async function fetchResourceMonitor(): Promise<ResourceMonitorData> {
  const res = await fetch(`${BASE}/resource-monitor`);
  if (!res.ok) throw new Error(`Failed to fetch resource monitor: ${res.status}`);
  return res.json();
}

// --- STT (Whisper) ---

import type { STTDownloadStatus, WhisperModelInfo } from "../types";

export async function fetchSTTModels(): Promise<WhisperModelInfo[]> {
  const res = await fetch(`${BASE}/stt/models`);
  if (!res.ok) throw new Error(`Failed to fetch STT models: ${res.status}`);
  return res.json();
}

export async function downloadSTTModel(model: string): Promise<{ status: string; model: string; message: string; download?: STTDownloadStatus; runtime_installation?: import("../types").STTRuntimeInstallationStatus }> {
  const res = await fetch(`${BASE}/stt/models/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to trigger model download: ${res.status}`);
  }
  return res.json();
}

export async function fetchSTTDownloadStatus(model: string): Promise<STTDownloadStatus> {
  const res = await fetch(`${BASE}/stt/models/${encodeURIComponent(model)}/download-status`);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `Failed to read model download status: ${res.status}`);
  }
  return res.json();
}

export async function fetchSTTRuntime(): Promise<STTRuntimeStatus> {
  const res = await fetch(`${BASE}/stt/runtime`);
  if (!res.ok) throw new Error(`Failed to fetch STT runtime: ${res.status}`);
  return res.json();
}

export async function fetchSTTLicense(model: string): Promise<{
  model: string;
  license: string;
  license_url: string;
  source_url: string;
  accepted: boolean;
  text: string;
}> {
  const res = await fetch(`${BASE}/stt/models/${encodeURIComponent(model)}/license`);
  if (!res.ok) throw new Error(`Failed to fetch STT license: ${res.status}`);
  return res.json();
}

export async function acceptSTTLicense(model: string, revision = "main"): Promise<{ accepted_at: string }> {
  const res = await fetch(`${BASE}/stt/models/${encodeURIComponent(model)}/license/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision }),
  });
  if (!res.ok) throw new Error(`Failed to accept STT license: ${res.status}`);
  return res.json();
}

export async function transcribeAudio(audioBlob: Blob, filename = "audio.webm"): Promise<{ text: string; language: string; duration: number }> {
  const formData = new FormData();
  formData.append("file", audioBlob, filename);
  const res = await fetch(`${BASE}/stt`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Transcription failed (${res.status}): ${errText}`);
  }
  return res.json();
}
