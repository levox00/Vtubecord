import { useEffect, useState, useRef, useCallback } from "react";

// Built-in voice list to detect custom uploaded voices
const BUILTIN_TTS_VOICES = [
  "en-US-AnaNeural","en-US-JennyNeural","en-GB-SoniaNeural","ja-JP-NanamiNeural",
  "voices/female_sweet.wav","voices/female_warm.wav","voices/female_energetic.wav","voices/female_refined.wav",
  "en-US-GuyNeural","en-GB-RyanNeural","voices/male_hero.wav","voices/male_deep.wav"
];
import {
  fetchStatus, fetchSettings, fetchPresets, createPreset, updatePreset, deletePreset, applyPreset, fetchLLMModels,
  fetchCharacterProfiles, createCharacterProfile, updateCharacterProfile, deleteCharacterProfile, applyCharacterProfile, uploadCharacterProfilePicture,
  fetchCharacterTraitLibrary, addCharacterTraitOption,
  fetchTelemetry, fetchSTTModels, downloadSTTModel, fetchSTTDownloadStatus, downloadLLMModel, fetchLLMDownloadStatus, fetchLLMModelLicense, acceptLLMModelLicense, transcribeAudio, fetchSTTRuntime, fetchSTTLicense, acceptSTTLicense, type TelemetryData,
  fetchTTS,
} from "../lib/api";
import type { AvatarGesture, CharacterProfile, CharacterTraitLibrary, LLMDownloadStatus, LLMModelInfo, LLMModelLicense, Settings, Preset, STTDownloadStatus, TraitOption, WhisperModelInfo } from "../types";
import { MasterPresets, type MasterPresetReferences } from "./MasterPresets";
import { LogsPanel } from "./LogsPanel";
import { Live2DCanvas } from "./Live2DCanvas";
import {
  User, Palette, Database, Volume2, Loader2, Upload, Mic, Activity, Zap, Brain,
  AudioLines, Settings2, Gauge, MemoryStick, Cloud, Sparkles, Save, Bookmark,
  BookmarkPlus, Trash2, Copy, ChevronDown, Check, Pencil, X, Shuffle, Sliders, Eye,
  RefreshCw, Search, Shield, HardDrive, Heart, Play, Cpu, Download, Square, Radio,
} from "lucide-react";
import { useAppStore } from "../stores/appStore";
import { findLive2DModel, LIVE2D_MODELS } from "../lib/live2dModels";
import { getLive2DIdlePreset, LIVE2D_IDLE_PRESETS } from "../lib/live2dIdlePresets";

interface SettingsPanelProps {
  section?: string;
  onSettingsChanged?: () => void;
}

type PresetOverwriteHandler = (id: string, name: string, presetType?: string) => void;

const FALLBACK_STYLE_OPTIONS = [
  "Friendly", "Professional", "Casual", "Formal", "Warm", "Playful",
  "Supportive", "Direct", "Concise", "Detailed", "Witty", "Reserved",
];

const FALLBACK_STYLE_MODIFIERS = [
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
];

const PRESET_SETTING_KEYS: Record<string, Array<keyof Settings>> = {
  user: [
    "user_name", "user_age", "user_height", "user_gender", "user_pronouns",
    "user_location", "user_occupation", "user_bio", "user_hobbies", "user_interests",
    "user_favorite_games", "user_favorite_anime", "user_dislikes", "user_notes",
  ],
  llm: ["llm_provider", "llm_model", "llm_base_url", "llm_temperature", "llm_max_tokens"],
  tts: [
    "tts_engine", "tts_voice_ref", "tts_language", "tts_happiness", "tts_sadness", "tts_disgust",
    "tts_fear", "tts_surprise", "tts_anger", "tts_other", "tts_neutral", "tts_speaking_rate",
    "tts_pitch_std", "tts_fmax", "tts_vq_score", "tts_dnsmos_ovrl", "tts_cfg_scale", "tts_seed",
    "tts_seed_mode", "tts_emotion_mode", "tts_voice_gender", "tts_openrouter_base_url",
    "tts_openrouter_api_key_env", "tts_openrouter_model", "tts_openrouter_voice",
    "tts_openrouter_response_format", "tts_openrouter_speed", "tts_fish_audio_base_url",
    "tts_fish_audio_api_key_env",
  ],
  avatar: ["avatar_provider", "avatar_model", "avatar_smart_expressions", "avatar_idle_preset", "avatar_idle_intensity"],
  stt: ["stt_provider", "stt_model", "stt_device", "stt_compute_type", "stt_beam_size", "stt_language", "stt_vad_filter", "stt_temperature", "stt_streaming_enabled", "stt_stream_chunk_ms", "stt_stream_language", "stt_fallback_enabled", "stt_sidecar_port"],
};

function settingsForPreset(settings: Settings, type: string): Partial<Settings> {
  const keys = PRESET_SETTING_KEYS[type];
  if (!keys) return settings;
  return Object.fromEntries(keys.map((key) => [key, settings[key]])) as Partial<Settings>;
}

function settingsToProfileData(settings: Settings, name?: string): Partial<CharacterProfile> {
  return {
    name: name || settings.character_name || "New Character",
    profile_picture: settings.character_profile_picture,
    age: settings.character_age,
    gender: settings.character_gender,
    pronouns: settings.character_pronouns,
    response_style: settings.character_response_style,
    style_modifiers: settings.character_style_modifiers,
    style_guidance: settings.character_style_guidance,
    traits: settings.character_traits,
    dere_types: settings.character_dere_types,
    behavior_rules: settings.character_behavior_rules,
    custom_instructions: settings.character_custom_instructions,
    core_values: settings.character_core_values,
    likes: settings.character_likes,
    dislikes: settings.character_dislikes,
    immutable_traits: settings.character_immutable_traits,
    description: settings.character_description,
    personality_guidance: settings.character_personality_summary,
    appearance_notes: settings.character_appearance,
    appearance: {
      height: settings.character_appearance_height,
      build: settings.character_appearance_build,
      hair: settings.character_appearance_hair,
      eyes: settings.character_appearance_eyes,
      skin_or_fur: settings.character_appearance_skin_or_fur,
      clothing: settings.character_appearance_clothing,
      accessories: settings.character_appearance_accessories,
      distinguishing_features: settings.character_appearance_distinguishing_features,
      visual_style: settings.character_appearance_visual_style,
      notes: settings.character_appearance_notes,
    },
    backstory: settings.character_backstory,
  };
}

function settingsMatch(left: Settings | null, right: Settings | null): boolean {
  return Boolean(left && right && JSON.stringify(left) === JSON.stringify(right));
}

function readUiPreference<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

function writeUiPreference(key: string, value: unknown): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // UI preferences are optional and should never block settings actions.
  }
}

export function SettingsPanel({ section, onSettingsChanged }: SettingsPanelProps) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [persistedSettings, setPersistedSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saveMsg, setSaveMsg] = useState<"ok" | "err" | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [currentPresetByType, setCurrentPresetByType] = useState<Record<string, string | null>>({});
  const [llmModels, setLlmModels] = useState<LLMModelInfo[]>([]);
  const [sttModels, setSttModels] = useState<WhisperModelInfo[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const [characterProfiles, setCharacterProfiles] = useState<CharacterProfile[]>([]);
  const [traitLibrary, setTraitLibrary] = useState<CharacterTraitLibrary | null>(null);

  // Modal state
  const [modal, setModal] = useState<{
    mode: "create" | "rename" | "overwrite" | "character-overwrite";
    presetType: string;
    presetId?: string;
    presetName?: string;
  } | null>(null);

  const character = useAppStore((s) => s.character);
  const setSmartExpressions = useAppStore((s) => s.setSmartExpressions);
  const setAvatarModelPath = useAppStore((s) => s.setAvatarModelPath);
  const setLive2DIdlePreset = useAppStore((s) => s.setLive2DIdlePreset);
  const setLive2DIdleIntensity = useAppStore((s) => s.setLive2DIdleIntensity);
  const sharedSettingsDraft = useAppStore((s) => s.settingsDraft);
  const sharedSettingsPersisted = useAppStore((s) => s.settingsPersisted);
  const setSharedSettingsDraft = useAppStore((s) => s.setSettingsDraft);
  const setSharedSettingsPersisted = useAppStore((s) => s.setSettingsPersisted);
  const renameCharacterInHistories = useAppStore((s) => s.renameCharacterInHistories);

  // Settings and the chat quick controls are separate UI trees. Mirror the
  // in-memory draft between them so switching views never shows an old model
  // or TTS engine. The backend remains the source of truth when a save occurs.
  useEffect(() => {
    if (settings && !settingsMatch(settings, sharedSettingsDraft)) {
      setSharedSettingsDraft(settings);
    }
  }, [settings, sharedSettingsDraft, setSharedSettingsDraft]);

  useEffect(() => {
    if (sharedSettingsDraft && !settingsMatch(settings, sharedSettingsDraft)) {
      setSettings(sharedSettingsDraft);
    }
  }, [sharedSettingsDraft]);

  useEffect(() => {
    if (persistedSettings && !settingsMatch(persistedSettings, sharedSettingsPersisted)) {
      setSharedSettingsPersisted(persistedSettings);
    }
  }, [persistedSettings, sharedSettingsPersisted, setSharedSettingsPersisted]);

  useEffect(() => {
    if (sharedSettingsPersisted && !settingsMatch(persistedSettings, sharedSettingsPersisted)) {
      setPersistedSettings(sharedSettingsPersisted);
    }
  }, [sharedSettingsPersisted]);

  useEffect(() => {
    if (persistedSettings?.avatar_model) setAvatarModelPath(persistedSettings.avatar_model);
  }, [persistedSettings?.avatar_model, setAvatarModelPath]);

  useEffect(() => {
    if (settings?.avatar_idle_preset) setLive2DIdlePreset(settings.avatar_idle_preset);
  }, [settings?.avatar_idle_preset, setLive2DIdlePreset]);

  useEffect(() => {
    if (settings?.avatar_idle_intensity != null) setLive2DIdleIntensity(settings.avatar_idle_intensity);
  }, [settings?.avatar_idle_intensity, setLive2DIdleIntensity]);

  const loadData = useCallback(async () => {
    try {
      const [s, p, llm, t, stt, profiles, traits] = await Promise.allSettled([
        fetchSettings(),
        fetchPresets(),
        fetchLLMModels(),
        fetchTelemetry(),
        fetchSTTModels(),
        fetchCharacterProfiles(),
        fetchCharacterTraitLibrary(),
      ]);
      if (s.status === "fulfilled") {
        // Preserve a draft created by the quick chat controls while opening
        // the full settings page. A fresh backend snapshot is still used when
        // no in-memory draft exists.
        const shared = useAppStore.getState();
        const initialSettings = shared.settingsDraft ?? s.value;
        const initialPersisted = shared.settingsPersisted ?? s.value;
        setSettings(initialSettings);
        setPersistedSettings(initialPersisted);
        setSharedSettingsDraft(initialSettings);
        setSharedSettingsPersisted(initialPersisted);
        // Keep the Live2D runtime in lockstep with the persisted avatar
        // setting. Missing legacy values intentionally default to enabled.
        setSmartExpressions(s.value.avatar_smart_expressions !== false);
      }
      if (p.status === "fulfilled") {
        setPresets(p.value);
        // Select the preset whose stored fields match the persisted runtime
        // settings so the first edit is clearly associated with a preset.
        if (s.status === "fulfilled") {
          const nextCurrent: Record<string, string> = {};
          for (const type of ["user", "llm", "tts", "avatar", "stt"]) {
            const matching = p.value.find((preset) => {
              if (preset.type !== type || !preset.data || !Object.keys(preset.data).length) return false;
              const allowedKeys = PRESET_SETTING_KEYS[type];
              const entries = Object.entries(preset.data).filter(([key]) =>
                !allowedKeys || allowedKeys.includes(key as keyof Settings),
              );
              return entries.length > 0 && entries.every(([key, value]) => (s.value as any)[key] === value);
            });
            if (matching) nextCurrent[type] = matching.id;
          }
          setCurrentPresetByType(nextCurrent);
        }
      }
      if (llm.status === "fulfilled") setLlmModels(llm.value);
      if (t.status === "fulfilled") setTelemetry(t.value);
      if (stt.status === "fulfilled") setSttModels(stt.value);
      if (profiles.status === "fulfilled") setCharacterProfiles(profiles.value);
      if (traits.status === "fulfilled") setTraitLibrary(traits.value);
    } catch (e) {
      console.error("Failed to load settings data", e);
    } finally {
      setLoading(false);
    }
  }, [setSharedSettingsDraft, setSharedSettingsPersisted, setSmartExpressions]);

  // Refreshing model availability must not reload settings: a 700 MB model
  // download can take a while and users should not lose an unrelated draft.
  const refreshSTTModels = useCallback(async () => {
    try {
      setSttModels(await fetchSTTModels());
    } catch (error) {
      console.error("Failed to refresh speech model availability", error);
    }
  }, []);

  const refreshLLMModels = useCallback(async () => {
    try {
      setLlmModels(await fetchLLMModels());
    } catch (error) {
      console.error("Failed to refresh local LLM availability", error);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Telemetry follows the current draft selections immediately, while the
  // backend still remains authoritative about what is actually loaded.
  const refreshTelemetry = useCallback(async () => {
    if (!settings) return;
    try {
      const t = await fetchTelemetry({
        llm_model: settings.llm_model,
        llm_provider: settings.llm_provider,
        tts_engine: settings.tts_engine,
        stt_model: settings.stt_model,
        stt_provider: settings.stt_provider,
        stt_device: settings.stt_device,
        stt_compute_type: settings.stt_compute_type,
      });
      setTelemetry(t);
    } catch {}
  }, [settings?.llm_model, settings?.llm_provider, settings?.tts_engine, settings?.stt_model, settings?.stt_provider, settings?.stt_device, settings?.stt_compute_type]);

  useEffect(() => {
    if (!settings) return;
    void refreshTelemetry();
    const interval = setInterval(() => { void refreshTelemetry(); }, 4000);
    return () => clearInterval(interval);
  }, [refreshTelemetry]);

  const update = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    if (key === "avatar_smart_expressions") {
      setSmartExpressions(Boolean(value));
    }
    if (key === "avatar_model") {
      setAvatarModelPath(String(value));
    }
    if (key === "avatar_idle_preset") {
      setLive2DIdlePreset(String(value));
    }
    if (key === "avatar_idle_intensity") {
      setLive2DIdleIntensity(Number(value));
    }
    setSettings((prev) => {
      if (!prev) return prev;
      return { ...prev, [key]: value };
    });
  }, [setAvatarModelPath, setLive2DIdleIntensity, setLive2DIdlePreset, setSmartExpressions]);

  const isDraftDirty = Boolean(
    settings && persistedSettings && JSON.stringify(settings) !== JSON.stringify(persistedSettings),
  );

  // Preset operations
  const handleApplyPreset = useCallback(async (id: string) => {
    try {
      const saved = await applyPreset(id);
      setSettings(saved);
      setPersistedSettings(saved);
      setSmartExpressions(saved.avatar_smart_expressions !== false);
      const appliedPreset = presets.find((preset) => preset.id === id);
      if (appliedPreset) {
        setCurrentPresetByType((previous) => ({ ...previous, [appliedPreset.type]: id }));
        if (appliedPreset.type === "master") {
          const refs = appliedPreset.data as any;
          setCurrentPresetByType((previous) => ({
            ...previous,
            llm: refs.llm_preset_id ?? previous.llm,
            tts: refs.tts_preset_id ?? previous.tts,
            avatar: refs.avatar_preset_id ?? previous.avatar,
            stt: refs.stt_preset_id ?? previous.stt,
          }));
        }
      }
      setSaveMsg("ok");
      onSettingsChanged?.();
      setTimeout(() => setSaveMsg(null), 1500);
    } catch (e) { console.error("Failed to apply preset", e); }
  }, [onSettingsChanged, presets, setSmartExpressions]);

  const handleRenamePreset = useCallback((id: string, currentName: string) => {
    setModal({ mode: "rename", presetType: "", presetId: id, presetName: currentName });
  }, []);

  const handleOverwritePreset = useCallback((id: string, _name: string, presetType?: string) => {
    const targetType = presetType || presets.find((preset) => preset.id === id)?.type;
    if (!targetType) return;
    const available = presets.filter((preset) => preset.type === targetType);
    if (available.length === 0) return;
    const selectedId = id && available.some((preset) => preset.id === id) ? id : available[0].id;
    setModal({ mode: "overwrite", presetType: targetType, presetId: selectedId });
  }, [presets]);

  const handleSaveCurrentPreset = useCallback(async (id: string) => {
    if (!settings) return;
    try {
      const presetType = presets.find((preset) => preset.id === id)?.type ?? "";
      const updated = await updatePreset(id, { data: settingsForPreset(settings, presetType) });
      setPresets((previous) => previous.map((preset) => preset.id === id ? updated : preset));
      // Saving a draft to a preset also makes that preset the active runtime
      // configuration. This keeps the editor and the running services in sync.
      const saved = await applyPreset(id);
      setSettings(saved);
      setPersistedSettings(saved);
      setSmartExpressions(saved.avatar_smart_expressions !== false);
      onSettingsChanged?.();
      setSaveMsg("ok");
      setTimeout(() => setSaveMsg(null), 1500);
    } catch (error) {
      console.error("Failed to save changes to preset", error);
      setSaveMsg("err");
    }
  }, [onSettingsChanged, presets, setSmartExpressions, settings]);

  const handleDeletePreset = useCallback(async (id: string) => {
    if (!confirm("Delete this preset?")) return;
    try {
      await deletePreset(id);
      setPresets((prev) => prev.filter((p) => p.id !== id));
      setCurrentPresetByType((previous) => Object.fromEntries(Object.entries(previous).map(([type, currentId]) => [type, currentId === id ? null : currentId])));
    } catch (e) { console.error("Failed to delete preset", e); }
  }, []);

  const handleSavePreset = useCallback((presetType: string) => {
    setModal({ mode: "create", presetType });
  }, []);

  const handleOverwriteConfirm = useCallback(async (targetId: string) => {
    if (!settings) return;
    const target = presets.find((preset) => preset.id === targetId);
    if (!target || target.type !== modal?.presetType) {
      setModal(null);
      return;
    }

    try {
      const data = target.type === "master"
        ? {
            ...(target.data as any),
            llm_preset_id: currentPresetByType.llm ?? (target.data as any)?.llm_preset_id,
            tts_preset_id: currentPresetByType.tts ?? (target.data as any)?.tts_preset_id,
            avatar_preset_id: currentPresetByType.avatar ?? (target.data as any)?.avatar_preset_id,
            stt_preset_id: currentPresetByType.stt ?? (target.data as any)?.stt_preset_id,
            character_profile_id: settings.character_profile_id || (target.data as any)?.character_profile_id,
          }
        : settingsForPreset(settings, target.type);
      const updated = await updatePreset(target.id, { data });
      setPresets((previous) => previous.map((preset) => preset.id === target.id ? updated : preset));
      setCurrentPresetByType((previous) => ({ ...previous, [target.type]: target.id }));

      // Engine presets are applied immediately so the saved target and the
      // running runtime stay in sync. Master presets only update their bundle
      // references, preserving the existing master-editor behavior.
      if (target.type !== "master") {
        const saved = await applyPreset(target.id);
        setSettings(saved);
        setPersistedSettings(saved);
        setSmartExpressions(saved.avatar_smart_expressions !== false);
        onSettingsChanged?.();
      }
      setSaveMsg("ok");
      setTimeout(() => setSaveMsg(null), 1500);
    } catch (error) {
      console.error("Failed to overwrite preset", error);
      setSaveMsg("err");
    } finally {
      setModal(null);
    }
  }, [currentPresetByType, modal?.presetType, onSettingsChanged, presets, setSmartExpressions, settings]);

  const handleModalConfirm = useCallback(async (name: string) => {
    if (!modal || !settings) return;
    try {
      if (modal.mode === "create") {
        const existing = presets.find((p) => p.name === name && p.type === modal.presetType);
        if (existing) {
          if (!confirm(`A preset named "${name}" already exists. Overwrite it?`)) {
            setModal(null);
            return;
          }
          const updated = await updatePreset(existing.id, { name, data: settingsForPreset(settings, modal.presetType) });
          setPresets((prev) => prev.map((p) => p.id === existing.id ? updated : p));
          setCurrentPresetByType((previous) => ({ ...previous, [modal.presetType]: existing.id }));
          const saved = await applyPreset(existing.id);
          setSettings(saved);
          setPersistedSettings(saved);
          setSmartExpressions(saved.avatar_smart_expressions !== false);
          onSettingsChanged?.();
        } else {
          const p = await createPreset({ name, type: modal.presetType, data: settingsForPreset(settings, modal.presetType) });
          setPresets((prev) => [...prev, p]);
          setCurrentPresetByType((previous) => ({ ...previous, [modal.presetType]: p.id }));
          const saved = await applyPreset(p.id);
          setSettings(saved);
          setPersistedSettings(saved);
          setSmartExpressions(saved.avatar_smart_expressions !== false);
          onSettingsChanged?.();
        }
      } else if (modal.mode === "rename" && modal.presetId) {
        const updated = await updatePreset(modal.presetId, { name });
        setPresets((prev) => prev.map((p) => p.id === modal.presetId ? updated : p));
      }
    } catch (e) { console.error("Preset operation failed", e); }
    setModal(null);
  }, [modal, onSettingsChanged, presets, setSmartExpressions, settings]);

  // MasterPresets handlers
  const handleApplyFromMaster = useCallback(async (id: string) => {
    try {
      const saved = await applyPreset(id);
      setSettings(saved);
      setPersistedSettings(saved);
      setSmartExpressions(saved.avatar_smart_expressions !== false);
      const appliedPreset = presets.find((preset) => preset.id === id);
      if (appliedPreset) {
        setCurrentPresetByType((previous) => ({ ...previous, [appliedPreset.type]: id }));
        if (appliedPreset.type === "master") {
          const refs = appliedPreset.data as any;
          setCurrentPresetByType((previous) => ({
            ...previous,
            llm: refs.llm_preset_id ?? previous.llm,
            tts: refs.tts_preset_id ?? previous.tts,
            avatar: refs.avatar_preset_id ?? previous.avatar,
            stt: refs.stt_preset_id ?? previous.stt,
          }));
        }
      }
      setSaveMsg("ok");
      onSettingsChanged?.();
      setTimeout(() => setSaveMsg(null), 1500);
    } catch (e) { console.error("Failed to apply preset", e); }
  }, [onSettingsChanged, presets, setSmartExpressions]);

  const handleRenameFromMaster = useCallback(async (id: string, name: string) => {
    try {
      const updated = await updatePreset(id, { name });
      setPresets((prev) => prev.map((p) => p.id === id ? updated : p));
    } catch (e) { console.error("Failed to rename preset", e); }
  }, []);

  const handleOverwriteFromMaster = useCallback(async (id: string) => {
    if (!settings) return;
    try {
      const presetType = presets.find((preset) => preset.id === id)?.type ?? "";
      const existing = presets.find((preset) => preset.id === id);
      const data = presetType === "master"
        ? {
            ...(existing?.data as any),
            llm_preset_id: currentPresetByType.llm ?? (existing?.data as any)?.llm_preset_id,
            tts_preset_id: currentPresetByType.tts ?? (existing?.data as any)?.tts_preset_id,
            avatar_preset_id: currentPresetByType.avatar ?? (existing?.data as any)?.avatar_preset_id,
            stt_preset_id: currentPresetByType.stt ?? (existing?.data as any)?.stt_preset_id,
            character_profile_id: settings.character_profile_id || (existing?.data as any)?.character_profile_id,
          }
        : settingsForPreset(settings, presetType);
      const updated = await updatePreset(id, { data });
      setPresets((prev) => prev.map((p) => p.id === id ? updated : p));
    } catch (e) { console.error("Failed to overwrite preset", e); }
  }, [currentPresetByType, settings, presets]);

  const handleDeleteFromMaster = useCallback(async (id: string) => {
    if (!confirm("Delete this preset?")) return;
    try {
      await deletePreset(id);
      setPresets((prev) => prev.filter((p) => p.id !== id));
    } catch (e) { console.error("Failed to delete preset", e); }
  }, []);

  const handleSaveNewFromMaster = useCallback(async (name: string, type: string) => {
    if (!settings) return;
    try {
      const existing = presets.find((p) => p.name === name && p.type === type);
      const data = settingsForPreset(settings, type);
      if (existing) {
        const updated = await updatePreset(existing.id, { name, data });
        setPresets((prev) => prev.map((p) => p.id === existing.id ? updated : p));
        setCurrentPresetByType((previous) => ({ ...previous, [type]: existing.id }));
      } else {
        const p = await createPreset({ name, type, data });
        setPresets((prev) => [...prev, p]);
        setCurrentPresetByType((previous) => ({ ...previous, [type]: p.id }));
      }
    } catch (e) { console.error("Failed to save preset", e); }
  }, [settings, presets]);

  const handleDuplicatePreset = useCallback(async (preset: Preset) => {
    const duplicate = await createPreset({ name: `${preset.name} Copy`, type: preset.type, data: preset.data });
    setPresets((previous) => [...previous, duplicate]);
    setCurrentPresetByType((previous) => ({ ...previous, [duplicate.type]: duplicate.id }));
  }, []);

  const handleSaveMaster = useCallback(async (name: string, references: MasterPresetReferences) => {
    const master = await createPreset({ name, type: "master", data: references as Partial<Settings> });
    setPresets((previous) => [...previous, master]);
  }, []);

  const handleUpdateMaster = useCallback(async (id: string, name: string, references: MasterPresetReferences) => {
    const updated = await updatePreset(id, { name, data: references as Partial<Settings> });
    setPresets((previous) => previous.map((preset) => preset.id === id ? updated : preset));
  }, []);

  const refreshCharacterProfiles = useCallback(async () => {
    const [profiles, traits] = await Promise.all([fetchCharacterProfiles(), fetchCharacterTraitLibrary()]);
    setCharacterProfiles(profiles);
    setTraitLibrary(traits);
  }, []);

  const refreshActiveCharacter = useCallback(async () => {
    const [updatedSettings, status] = await Promise.all([fetchSettings(), fetchStatus()]);
    setSettings(updatedSettings);
    setPersistedSettings(updatedSettings);
    setSmartExpressions(updatedSettings.avatar_smart_expressions !== false);
    useAppStore.getState().setCharacter(status.character);
  }, [setSmartExpressions]);

  const handleApplyCharacterProfile = useCallback(async (id: string) => {
    await applyCharacterProfile(id);
    await refreshActiveCharacter();
    await refreshCharacterProfiles();
    onSettingsChanged?.();
  }, [onSettingsChanged, refreshActiveCharacter, refreshCharacterProfiles]);

  const handleSaveCharacterProfile = useCallback(async () => {
    if (!settings?.character_profile_id) return;
    try {
      await updateCharacterProfile(settings.character_profile_id, settingsToProfileData(settings));
      await applyCharacterProfile(settings.character_profile_id);
      renameCharacterInHistories(settings.character_profile_id, settings.character_name);
      await refreshActiveCharacter();
      await refreshCharacterProfiles();
      setSaveMsg("ok");
      onSettingsChanged?.();
      setTimeout(() => setSaveMsg(null), 1500);
    } catch (error) {
      console.error("Failed to save character profile changes", error);
      setSaveMsg("err");
    }
  }, [onSettingsChanged, refreshActiveCharacter, refreshCharacterProfiles, renameCharacterInHistories, settings]);

  const handleOverwriteCharacterProfile = useCallback((profileId?: string) => {
    if (characterProfiles.length === 0) return;
    const selectedId = profileId && characterProfiles.some((profile) => profile.id === profileId)
      ? profileId
      : settings?.character_profile_id && characterProfiles.some((profile) => profile.id === settings.character_profile_id)
      ? settings.character_profile_id
      : characterProfiles[0].id;
    setModal({ mode: "character-overwrite", presetType: "character", presetId: selectedId });
  }, [characterProfiles, settings?.character_profile_id]);

  const handleOverwriteCharacterProfileConfirm = useCallback(async (profileId: string) => {
    if (!settings || !characterProfiles.some((profile) => profile.id === profileId)) {
      setModal(null);
      return;
    }
    try {
      const updatedProfile = await updateCharacterProfile(profileId, settingsToProfileData(settings));
      await applyCharacterProfile(profileId);
      renameCharacterInHistories(profileId, updatedProfile.name);
      await refreshActiveCharacter();
      await refreshCharacterProfiles();
      setSaveMsg("ok");
      onSettingsChanged?.();
      setTimeout(() => setSaveMsg(null), 1500);
    } catch (error) {
      console.error("Failed to overwrite character profile", error);
      setSaveMsg("err");
    } finally {
      setModal(null);
    }
  }, [characterProfiles, onSettingsChanged, refreshActiveCharacter, refreshCharacterProfiles, renameCharacterInHistories, settings]);

  const handleCreateCharacterProfile = useCallback(async (name: string) => {
    if (!settings) return;
    const created = await createCharacterProfile(settingsToProfileData(settings, name));
    await applyCharacterProfile(created.id);
    await refreshActiveCharacter();
    await refreshCharacterProfiles();
  }, [settings, refreshActiveCharacter, refreshCharacterProfiles]);

  const handleRenameCharacterProfile = useCallback(async (id: string, name: string) => {
    const updated = await updateCharacterProfile(id, { name });
    renameCharacterInHistories(id, updated.name);
    await refreshCharacterProfiles();
  }, [refreshCharacterProfiles, renameCharacterInHistories]);

  const handleDuplicateCharacterProfile = useCallback(async (id: string, name: string) => {
    const original = characterProfiles.find((profile) => profile.id === id);
    if (!original) return;
    const { id: _id, source_file: _sourceFile, active: _active, ...data } = original;
    await createCharacterProfile({ ...data, name });
    await refreshCharacterProfiles();
  }, [characterProfiles, refreshCharacterProfiles]);

  const handleDeleteCharacterProfile = useCallback(async (id: string) => {
    await deleteCharacterProfile(id);
    await refreshCharacterProfiles();
  }, [refreshCharacterProfiles]);

  const handleUploadCharacterProfilePicture = useCallback(async (id: string, file: File) => {
    const updated = await uploadCharacterProfilePicture(id, file);
    setCharacterProfiles((previous) => previous.map((profile) => profile.id === id ? updated : profile));
    if (updated.active) await refreshActiveCharacter();
  }, [refreshActiveCharacter]);

  const handleAddTraitOption = useCallback(async (category: string, label: string) => {
    const id = label.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (!id) return;
    const updatedLibrary = await addCharacterTraitOption({ id, label: label.trim(), category, description: "Custom trait added from the character editor.", guidance: "Apply this trait consistently while respecting the user's boundaries." });
    setTraitLibrary(updatedLibrary);
  }, []);

  // Logs channel
  if (section === "logs") {
    return <LogsPanel />;
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={20} className="text-[#5865f2] animate-spin" />
      </div>
    );
  }
  if (!settings) {
    return <div className="p-4 text-[#949ba4] text-xs">Failed to load settings</div>;
  }

  const sectionPresets = (type: string) => presets.filter((p) => p.type === type);
  if (section === "master-presets") {
    return (
      <MasterPresets
        presets={presets}
        currentSettings={settings}
        onApply={handleApplyFromMaster}
        onRename={handleRenameFromMaster}
        onOverwrite={handleOverwriteFromMaster}
        onDelete={handleDeleteFromMaster}
        onDuplicate={handleDuplicatePreset}
        onSaveNew={handleSaveNewFromMaster}
        onSaveMaster={handleSaveMaster}
        onUpdateMaster={handleUpdateMaster}
        characterProfiles={characterProfiles}
        onApplyCharacterProfile={handleApplyCharacterProfile}
        onDuplicateCharacterProfile={handleDuplicateCharacterProfile}
        onRenameCharacterProfile={handleRenameCharacterProfile}
        onDeleteCharacterProfile={handleDeleteCharacterProfile}
      />
    );
  }

  return (
    <div className="settings-quiet flex flex-col h-full min-w-0 overflow-y-auto">
      {/* Modal */}
      {modal?.mode === "character-overwrite" ? (
        <CharacterProfileOverwriteModal
          profiles={characterProfiles}
          initialProfileId={modal.presetId}
          onConfirm={handleOverwriteCharacterProfileConfirm}
          onCancel={() => setModal(null)}
        />
      ) : modal?.mode === "overwrite" ? (
        <PresetOverwriteModal
          presetType={modal.presetType}
          presets={presets.filter((preset) => preset.type === modal.presetType)}
          initialPresetId={modal.presetId}
          onConfirm={handleOverwriteConfirm}
          onCancel={() => setModal(null)}
        />
      ) : modal ? (
        <PresetModal
          mode={modal.mode}
          initialName={modal.presetName || ""}
          presetType={modal.presetType}
          onConfirm={handleModalConfirm}
          onCancel={() => setModal(null)}
        />
      ) : null}

      <div className="flex-1 w-full p-5 xl:px-7 space-y-4">
        {/* Draft status bar: edits stay local until an explicit preset action. */}
        <div className="sticky top-0 z-10 px-4 py-2.5 bg-[#313338]/95 backdrop-blur rounded-lg border border-[#1f2023] flex items-center gap-2 text-xs shadow-sm">
          {saveMsg === "ok" ? (
            <>
              <Check size={13} className="text-[#23a55a]" />
              <span className="text-[#23a55a] font-medium">Changes saved and applied</span>
            </>
          ) : saveMsg === "err" ? (
            <>
              <X size={13} className="text-[#f23f43]" />
              <span className="text-[#f23f43] font-medium">Save failed</span>
            </>
          ) : isDraftDirty ? (
            <>
              <span className="h-2 w-2 rounded-full bg-[#f0ad4e]" />
              <span className="text-[#f0ad4e] font-medium">Unsaved draft changes</span>
              <span className="text-[#949ba4]">Use Save changes or Save as new in the preset menu.</span>
            </>
          ) : (
            <>
              <span className="text-[#949ba4]">No unsaved changes</span>
            </>
          )}
        </div>

        {/* 1. General: User Profile */}
        {(!section || section === "general-settings") && (
          <UserProfileSection
            settings={settings}
            update={update}
            presets={sectionPresets("user")}
            onApply={handleApplyPreset}
            onRename={handleRenamePreset}
            onOverwrite={handleOverwritePreset}
            onSaveCurrent={handleSaveCurrentPreset}
            onDelete={handleDeletePreset}
            onDuplicate={handleDuplicatePreset}
            onSave={() => handleSavePreset("user")}
            currentPresetId={currentPresetByType.user}
            currentSettings={settings}
          />
        )}

        {/* 2. Character: AI Companion Profile */}
        {(!section || section === "character-settings") && (
          <CharacterProfileSection
            settings={settings}
            update={update}
            character={character}
            profiles={characterProfiles}
            traitLibrary={traitLibrary}
            onApplyProfile={handleApplyCharacterProfile}
            onSaveProfile={handleSaveCharacterProfile}
            onOverwriteProfile={handleOverwriteCharacterProfile}
            onCreateProfile={handleCreateCharacterProfile}
            onRenameProfile={handleRenameCharacterProfile}
            onDuplicateProfile={handleDuplicateCharacterProfile}
            onDeleteProfile={handleDeleteCharacterProfile}
            onRefreshProfiles={refreshCharacterProfiles}
            onAddTraitOption={handleAddTraitOption}
            onUploadProfilePicture={handleUploadCharacterProfilePicture}
          />
        )}

        {/* 3. LLM: Model & Sampling */}
        {(!section || section === "llm-settings") && (
          <LLMSettingsSection
            settings={settings}
            onChange={update}
            presets={sectionPresets("llm")}
            onApply={handleApplyPreset}
            onRename={handleRenamePreset}
            onOverwrite={handleOverwritePreset}
            onSaveCurrent={handleSaveCurrentPreset}
            onDelete={handleDeletePreset}
            onDuplicate={handleDuplicatePreset}
            onSave={() => handleSavePreset("llm")}
            llmModels={llmModels}
            onRefreshModels={refreshLLMModels}
            telemetry={telemetry}
            currentPresetId={currentPresetByType.llm}
            currentSettings={settings}
          />
        )}

        {/* 4. TTS: Voice & Audio */}
        {(!section || section === "tts-settings") && (
          <TTSSettingsSection
            settings={settings}
            onChange={update}
            presets={sectionPresets("tts")}
            onApply={handleApplyPreset}
            onRename={handleRenamePreset}
            onOverwrite={handleOverwritePreset}
            onSaveCurrent={handleSaveCurrentPreset}
            onDelete={handleDeletePreset}
            onDuplicate={handleDuplicatePreset}
            onSave={() => handleSavePreset("tts")}
            telemetry={telemetry}
            currentPresetId={currentPresetByType.tts}
            currentSettings={settings}
          />
        )}

        {/* 5. STT: Whisper Speech-to-Text Studio */}
        {(!section || section === "stt-settings") && (
          <STTSettingsSection
            settings={settings}
            onChange={update}
            presets={sectionPresets("stt")}
            onApply={handleApplyPreset}
            onRename={handleRenamePreset}
            onOverwrite={handleOverwritePreset}
            onSaveCurrent={handleSaveCurrentPreset}
            onDelete={handleDeletePreset}
            onDuplicate={handleDuplicatePreset}
            onSave={() => handleSavePreset("stt")}
            sttModels={sttModels}
            onRefreshModels={refreshSTTModels}
            telemetry={telemetry}
            currentPresetId={currentPresetByType.stt}
            currentSettings={settings}
          />
        )}

        {/* 6. Avatar: Live2D & Visual Studio */}
        {(!section || section === "avatar-settings") && (
          <AvatarSettingsSection
            settings={settings}
            onChange={update}
            presets={sectionPresets("avatar")}
            onApply={handleApplyPreset}
            onRename={handleRenamePreset}
            onOverwrite={handleOverwritePreset}
            onSaveCurrent={handleSaveCurrentPreset}
            onDelete={handleDeletePreset}
            onDuplicate={handleDuplicatePreset}
            onSave={() => handleSavePreset("avatar")}
            currentPresetId={currentPresetByType.avatar}
          />
        )}

        {/* 7. Memory: Knowledge Base & Retention */}
        {(!section || section === "memory-settings") && (
          <MemorySettingsSection
            settings={settings}
            onChange={update}
          />
        )}
      </div>
    </div>
  );
}

// ── 1. User Profile Section ──────────────────────────────────────────

function UserProfileSection({ settings, update, presets, onApply, onRename, onOverwrite, onSaveCurrent, onDelete, onDuplicate, onSave, currentPresetId, currentSettings }: {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  presets: Preset[];
  onApply: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onOverwrite: PresetOverwriteHandler;
  onSaveCurrent: (id: string) => void;
  onDelete: (id: string) => void;
  onDuplicate: (preset: Preset) => void;
  onSave: () => void;
  currentPresetId?: string | null;
  currentSettings?: Settings | null;
}) {
  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm">
      <SectionHeader
        icon={User}
        title="User Profile (Your Data)"
        presetType="user"
        presets={presets}
        onApply={onApply}
        onRename={onRename}
        onOverwrite={onOverwrite}
        onSaveCurrent={onSaveCurrent}
        onDelete={onDelete}
        onDuplicate={onDuplicate}
        onSave={onSave}
        currentPresetId={currentPresetId}
        currentSettings={currentSettings}
        showPresetActions
      />
      <p className="text-xs text-[#949ba4] mb-4">
        Your personal profile and preferences. The AI character uses this identity data to personalize conversations and address you accurately.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column: Identity & Bio */}
        <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
          <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
            <User size={14} className="text-[#5865f2]" /> Personal Details
          </h4>

          <div className="grid grid-cols-2 gap-2.5">
            <EditableField label="Your Name" value={settings.user_name} onChange={(v) => update("user_name", v)} />
            <EditableField label="Your Age" value={settings.user_age} onChange={(v) => update("user_age", v)} />
          </div>

          <div className="grid grid-cols-2 gap-2.5">
            <EditableField label="Height" value={settings.user_height} onChange={(v) => update("user_height", v)} />
            <EditableField label="Gender" value={settings.user_gender} onChange={(v) => update("user_gender", v)} />
          </div>

          <div className="grid grid-cols-2 gap-2.5">
            <EditableField label="Pronouns" value={settings.user_pronouns} onChange={(v) => update("user_pronouns", v)} />
            <EditableField label="Location" value={settings.user_location} onChange={(v) => update("user_location", v)} />
          </div>

          <EditableField label="Occupation" value={settings.user_occupation} onChange={(v) => update("user_occupation", v)} />
          <EditableField label="Bio / About You" value={settings.user_bio} onChange={(v) => update("user_bio", v)} multiline />
          <EditableField label="Special Instructions / Notes for AI" value={settings.user_notes} onChange={(v) => update("user_notes", v)} multiline />
        </div>

        {/* Right Column: Interests & Prompt Context */}
        <div className="space-y-4">
          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Heart size={14} className="text-[#eb459e]" /> Interests & Preferences
            </h4>
            <TagField label="Hobbies" values={settings.user_hobbies} onChange={(v) => update("user_hobbies", v)} />
            <TagField label="Interests" values={settings.user_interests} onChange={(v) => update("user_interests", v)} />
            <TagField label="Favorite Games" values={settings.user_favorite_games} onChange={(v) => update("user_favorite_games", v)} />
            <TagField label="Favorite Anime / Media" values={settings.user_favorite_anime} onChange={(v) => update("user_favorite_anime", v)} />
            <TagField label="Dislikes / Disliked Topics" values={settings.user_dislikes} onChange={(v) => update("user_dislikes", v)} />
          </div>

          {/* AI Context Preview Card */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <Eye size={14} className="text-[#57f287]" /> Prompt Injection Preview
            </h4>
            <p className="text-[11px] text-[#949ba4] mb-2">How your identity is formatted for the LLM:</p>
            <div className="p-3 bg-[#141517] rounded font-mono text-[11px] text-[#8ce8a2] leading-relaxed overflow-x-auto border border-[#2b2d31]">
              <div>[USER PROFILE]</div>
              <div>Name: {settings.user_name || "(Anonymous)"}</div>
              <div>Pronouns: {settings.user_pronouns || "they/them"} | Age: {settings.user_age || "unspecified"}</div>
              <div>Location: {settings.user_location || "unspecified"}</div>
              {settings.user_bio && <div>Bio: {settings.user_bio}</div>}
              {settings.user_notes && <div>Notes: {settings.user_notes}</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 2. Character Profile Section ─────────────────────────────────────

function CharacterProfileSection({ settings, update, character, profiles, traitLibrary, onApplyProfile, onSaveProfile, onOverwriteProfile, onCreateProfile, onRenameProfile, onDuplicateProfile, onDeleteProfile, onRefreshProfiles, onAddTraitOption, onUploadProfilePicture }: {
  settings: Settings;
  update: <K extends keyof Settings>(key: K, value: Settings[K]) => void;
  character: any;
  profiles: CharacterProfile[];
  traitLibrary: CharacterTraitLibrary | null;
  onApplyProfile: (id: string) => Promise<void>;
  onSaveProfile: () => Promise<void>;
  onOverwriteProfile: (id?: string) => void;
  onCreateProfile: (name: string) => Promise<void>;
  onRenameProfile: (id: string, name: string) => Promise<void>;
  onDuplicateProfile: (id: string, name: string) => Promise<void>;
  onDeleteProfile: (id: string) => Promise<void>;
  onRefreshProfiles: () => Promise<void>;
  onAddTraitOption: (category: string, label: string) => Promise<void>;
  onUploadProfilePicture: (id: string, file: File) => Promise<void>;
}) {
  const [personalityQuery, setPersonalityQuery] = useState("");
  const [dereQuery, setDereQuery] = useState("");
  const activeProfile = profiles.find((profile) => profile.id === settings.character_profile_id);
  const standardGenders = traitLibrary?.appearance_options.gender ?? ["Female", "Male", "Non-binary", "Genderfluid", "Agender", "Other", "Prefer not to say"];
  const isStandardGender = standardGenders.includes(settings.character_gender);
  const styles = traitLibrary?.styles ?? FALLBACK_STYLE_OPTIONS;
  const styleModifiers = traitLibrary?.style_modifiers ?? FALLBACK_STYLE_MODIFIERS;
  const appearanceOptions = traitLibrary?.appearance_options ?? {};

  const askForName = (initial: string, message: string) => {
    const name = window.prompt(message, initial)?.trim();
    return name || null;
  };

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm">
      <SectionHeader icon={Sparkles} title="Character AI Profile (Markdown Persona)" />

      <div className="mb-4 rounded-lg border border-[#5865f2]/30 bg-[#5865f2]/10 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={settings.character_profile_id || ""}
            onChange={(event) => { if (event.target.value) void onApplyProfile(event.target.value); }}
            className="min-w-[190px] flex-1 rounded bg-[#141517] px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
          >
            {profiles.length === 0 && <option value={settings.character_profile_id || ""}>{settings.character_name || "Loading profile…"}</option>}
            {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}{profile.active ? " · active" : ""}</option>)}
          </select>
          <button onClick={() => { const name = askForName("New Character", "Name this new persona"); if (name) void onCreateProfile(name); }} className="rounded bg-[#5865f2] px-2.5 py-2 text-xs font-medium text-white hover:bg-[#4752c4]">New persona</button>
          <button disabled={!activeProfile} onClick={() => void onSaveProfile()} className="rounded bg-[#3f4147] px-2.5 py-2 text-xs font-medium text-[#f2f3f5] hover:bg-[#4e5058] disabled:opacity-40">Save changes</button>
          <button disabled={profiles.length === 0} onClick={() => onOverwriteProfile()} className="rounded bg-[#3f4147] px-2.5 py-2 text-xs font-medium text-[#f0d19a] hover:bg-[#4e5058] disabled:opacity-40">Overwrite</button>
          <button disabled={!activeProfile} onClick={() => { const name = askForName(`${activeProfile?.name ?? "Character"} Copy`, "Name the duplicate persona"); if (name && activeProfile) void onDuplicateProfile(activeProfile.id, name); }} className="rounded bg-[#3f4147] px-2.5 py-2 text-xs text-[#dbdee1] hover:bg-[#4e5058] disabled:opacity-40">Duplicate</button>
          <button disabled={!activeProfile} onClick={() => { const name = askForName(activeProfile?.name ?? "", "Rename this persona"); if (name && activeProfile) void onRenameProfile(activeProfile.id, name); }} className="rounded bg-[#3f4147] px-2.5 py-2 text-xs text-[#dbdee1] hover:bg-[#4e5058] disabled:opacity-40">Rename</button>
          <button disabled={!activeProfile || activeProfile.active || profiles.length < 2} onClick={() => { if (activeProfile && window.confirm(`Delete ${activeProfile.name}?`)) void onDeleteProfile(activeProfile.id); }} className="rounded bg-[#f23f43]/15 px-2.5 py-2 text-xs text-[#f23f43] hover:bg-[#f23f43]/25 disabled:opacity-40">Delete</button>
          <button onClick={() => void onRefreshProfiles()} className="rounded p-2 text-[#949ba4] hover:bg-[#3f4147] hover:text-white" title="Reload Markdown profiles"><RefreshCw size={14} /></button>
        </div>
        <div className="mt-2 text-[10px] text-[#949ba4]">{activeProfile?.source_file ?? "Markdown profiles are loaded from data/character-profiles"}</div>
      </div>

      <p className="text-xs text-[#949ba4] mb-4">Static persona details are saved to a readable Markdown file. Runtime emotions, adaptive traits, memories, and chat history remain in SQLite.</p>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <div className="space-y-4">
          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5"><Sparkles size={14} className="text-[#eb459e]" /> Identity & communication</h4>
            <div className="grid grid-cols-2 gap-2.5">
              <EditableField label="Character Name" value={settings.character_name} onChange={(v) => update("character_name", v)} />
              <EditableField label="Age" value={settings.character_age} onChange={(v) => update("character_age", v)} />
            </div>
            <ProfilePicturePicker
              value={settings.character_profile_picture}
              profileId={settings.character_profile_id}
              onChange={(value) => update("character_profile_picture", value)}
              onUpload={onUploadProfilePicture}
            />
            <div className="grid grid-cols-2 gap-2.5">
              <div>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Gender</label>
                <select value={isStandardGender ? settings.character_gender : "__custom"} onChange={(event) => update("character_gender", event.target.value === "__custom" ? "" : event.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"><option value="">Unspecified</option>{standardGenders.map((gender) => <option key={gender} value={gender}>{gender}</option>)}<option value="__custom">Custom</option></select>
              </div>
              <EditableField label="Pronouns" value={settings.character_pronouns} onChange={(v) => update("character_pronouns", v)} />
            </div>
            {(!isStandardGender || settings.character_gender === "Other") && <EditableField label="Custom gender / identity detail" value={settings.character_gender === "Other" ? "" : settings.character_gender} onChange={(v) => update("character_gender", v)} />}
            <div>
              <SearchableSingleSelect
                label="Primary response style"
                value={settings.character_response_style}
                options={styles}
                onChange={(value) => update("character_response_style", value)}
              />
            </div>
            <ModifierPicker
              values={settings.character_style_modifiers}
              options={styleModifiers}
              onChange={(values) => update("character_style_modifiers", values)}
            />
            <EditableField label="Style guidance" value={settings.character_style_guidance} onChange={(v) => update("character_style_guidance", v)} multiline />
            <EditableField label="Short description" value={settings.character_description} onChange={(v) => update("character_description", v)} multiline />
            <EditableField label="Personality guidance" value={settings.character_personality_summary} onChange={(v) => update("character_personality_summary", v)} multiline />
          </div>

          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5"><Eye size={14} className="text-[#57f287]" /> Structured appearance</h4>
            <div className="grid grid-cols-2 gap-2.5">
              <EditableField label="Height" value={settings.character_appearance_height} onChange={(v) => update("character_appearance_height", v)} />
              <div><label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Build</label><select value={settings.character_appearance_build} onChange={(event) => update("character_appearance_build", event.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"><option value="">Unspecified</option>{(appearanceOptions.build ?? []).map((value) => <option key={value} value={value}>{value}</option>)}</select></div>
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              <EditableField label="Hair" value={settings.character_appearance_hair} onChange={(v) => update("character_appearance_hair", v)} />
              <EditableField label="Eyes" value={settings.character_appearance_eyes} onChange={(v) => update("character_appearance_eyes", v)} />
            </div>
            <EditableField label="Skin / fur" value={settings.character_appearance_skin_or_fur} onChange={(v) => update("character_appearance_skin_or_fur", v)} />
            <EditableField label="Clothing" value={settings.character_appearance_clothing} onChange={(v) => update("character_appearance_clothing", v)} />
            <EditableField label="Accessories" value={settings.character_appearance_accessories} onChange={(v) => update("character_appearance_accessories", v)} />
            <EditableField label="Distinguishing features" value={settings.character_appearance_distinguishing_features} onChange={(v) => update("character_appearance_distinguishing_features", v)} />
            <EditableField label="Visual style" value={settings.character_appearance_visual_style} onChange={(v) => update("character_appearance_visual_style", v)} />
            <EditableField label="Appearance notes" value={settings.character_appearance_notes} onChange={(v) => update("character_appearance_notes", v)} multiline />
            <EditableField label="Free-form physical appearance" value={settings.character_appearance} onChange={(v) => update("character_appearance", v)} multiline />
            <EditableField label="Backstory & origins" value={settings.character_backstory} onChange={(v) => update("character_backstory", v)} multiline />
          </div>
        </div>

        <div className="space-y-4">
          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5"><Brain size={14} className="text-[#5865f2]" /> Searchable traits & values</h4>
            <TraitPicker label="Personality traits (A–Z)" category="personality" values={settings.character_traits} options={traitLibrary?.traits ?? []} query={personalityQuery} onQueryChange={setPersonalityQuery} onChange={(v) => update("character_traits", v)} onAddToLibrary={onAddTraitOption} />
            <TraitPicker label="-dere archetypes" category="dere" values={settings.character_dere_types} options={traitLibrary?.dere_types ?? []} query={dereQuery} onQueryChange={setDereQuery} onChange={(v) => update("character_dere_types", v)} onAddToLibrary={onAddTraitOption} />
            <SuggestionTagField label="Core values" values={settings.character_core_values} suggestions={traitLibrary?.core_values ?? []} onChange={(v) => update("character_core_values", v)} />
            <TagField label="Likes" values={settings.character_likes} onChange={(v) => update("character_likes", v)} />
            <TagField label="Dislikes" values={settings.character_dislikes} onChange={(v) => update("character_dislikes", v)} />
            <SuggestionTagField label="Immutable traits" values={settings.character_immutable_traits} suggestions={traitLibrary?.immutable_traits ?? []} onChange={(v) => update("character_immutable_traits", v)} />
            <EditableField label="Behavior rules" value={settings.character_behavior_rules} onChange={(v) => update("character_behavior_rules", v)} multiline />
            <EditableField label="Custom instructions" value={settings.character_custom_instructions} onChange={(v) => update("character_custom_instructions", v)} multiline />
          </div>

          <ProfilePreview settings={settings} />

          {character?.emotion && (
            <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
              <div className="flex items-center justify-between mb-3"><h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5"><Activity size={14} className="text-[#23a55a]" /> Live Emotional State</h4><span className="text-[10px] px-2 py-0.5 rounded bg-[#23a55a]/15 text-[#23a55a] font-semibold uppercase">Dominant: {character.dominant_emotion || "neutral"}</span></div>
              <div className="grid grid-cols-2 gap-2 text-xs">{Object.entries(character.emotion).map(([emo, val]: [string, any]) => <div key={emo} className="bg-[#141517] p-2 rounded border border-[#2b2d31]"><div className="flex justify-between text-[10px] text-[#949ba4] uppercase font-mono"><span>{emo}</span><span>{(val * 100).toFixed(0)}%</span></div><div className="w-full bg-[#2b2d31] h-1.5 rounded-full mt-1 overflow-hidden"><div className="bg-[#5865f2] h-full rounded-full transition-all" style={{ width: `${Math.min(100, Math.max(0, val * 100))}%` }} /></div></div>)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ProfilePicturePicker({ value, profileId, onChange, onUpload }: { value?: string; profileId?: string; onChange: (value: string) => void; onUpload: (id: string, file: File) => Promise<void> }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File | undefined) {
    if (!file || !profileId) return;
    setUploading(true);
    setError(null);
    try {
      await onUpload(profileId, file);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload picture");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Chat profile picture</label>
      <div className="mt-1.5 flex items-center gap-3 rounded-lg border border-[#1f2023] bg-[#141517] p-2.5">
        {value ? (
          <img src={value} alt="Character profile" className="h-12 w-12 shrink-0 rounded-full object-cover border border-[#5865f2]/50" />
        ) : (
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#ed4245] text-sm font-bold text-white">?</div>
        )}
        <div className="min-w-0 flex-1 space-y-1.5">
          <input
            value={value ?? ""}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Paste an image URL or upload a picture"
            className="w-full rounded border border-[#1f2023] bg-[#1e1f22] px-2.5 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:border-[#5865f2] focus:outline-none"
          />
          <div className="flex items-center gap-2">
            <label className="cursor-pointer rounded bg-[#3f4147] px-2.5 py-1 text-[10px] text-[#dbdee1] hover:bg-[#4e5058]">
              {uploading ? "Uploading…" : "Upload image"}
              <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" disabled={uploading || !profileId} onChange={(event) => { void handleFile(event.target.files?.[0]); event.currentTarget.value = ""; }} />
            </label>
            {value && <button type="button" onClick={() => onChange("")} className="text-[10px] text-[#f23f43] hover:underline">Remove</button>}
          </div>
        </div>
      </div>
      {error && <div className="mt-1 text-[10px] text-[#f23f43]">{error}</div>}
      <p className="mt-1 text-[10px] text-[#6d6f78]">Stored with this Markdown persona and used for its chat messages.</p>
    </div>
  );
}

function SearchableSingleSelect({ label, value, options, onChange }: { label: string; value?: string; options: string[]; onChange: (value: string) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const filtered = options.filter((option) => option.toLowerCase().includes(query.trim().toLowerCase()));
  const commit = (nextValue: string) => {
    const next = nextValue.trim();
    if (!next) return;
    setQuery(next);
    onChange(next);
    setOpen(false);
  };

  return (
    <div className="relative">
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">{label}</label>
      <input
        value={open ? query : (value || "")}
        onChange={(event) => { setQuery(event.target.value); onChange(event.target.value); setOpen(true); }}
        onFocus={() => { setQuery(""); setOpen(true); }}
        onBlur={() => window.setTimeout(() => { setOpen(false); setQuery(""); }, 120)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commit(query); } if (event.key === "Escape") setOpen(false); }}
        placeholder="Type or choose a premade style…"
        className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
      />
      {open && filtered.length > 0 && (
        <div className="absolute z-30 left-0 right-0 mt-1 max-h-44 overflow-y-auto rounded border border-[#3f4147] bg-[#18191c] p-1 shadow-xl">
          {filtered.map((option) => (
            <button key={option} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => commit(option)} className="block w-full rounded px-2.5 py-1.5 text-left text-xs text-[#dbdee1] hover:bg-[#5865f2]/20 hover:text-white">
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ModifierPicker({ values: rawValues, options: rawOptions, onChange }: { values?: string[]; options?: string[]; onChange: (values: string[]) => void }) {
  const values = Array.isArray(rawValues) ? rawValues : [];
  const options = Array.isArray(rawOptions) ? rawOptions : [];
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const filtered = options.filter((option) => !values.includes(option) && option.toLowerCase().includes(query.trim().toLowerCase()));

  const add = (value: string) => {
    const next = value.trim();
    if (!next || values.includes(next)) return;
    onChange([...values, next]);
    setQuery("");
    setOpen(false);
  };

  return (
    <div className="relative">
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Style modifiers</label>
      <div className="flex flex-wrap gap-1.5 mt-1.5">
        {values.map((value) => (
          <button key={value} type="button" onClick={() => onChange(values.filter((item) => item !== value))} className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#5865f2]/15 text-xs text-[#dbdee1] border border-[#5865f2]/30" title="Remove">
            {value} <X size={11} />
          </button>
        ))}
      </div>
      <input
        value={query}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onKeyDown={(event) => { if (event.key === "Enter" && query.trim()) { event.preventDefault(); add(query); } if (event.key === "Escape") setOpen(false); }}
        placeholder="Type to choose a modifier or add your own…"
        className="w-full mt-2 bg-[#141517] border border-[#1f2023] rounded px-3 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
      />
      {open && (filtered.length > 0 || query.trim()) && (
        <div className="absolute z-30 left-0 right-0 mt-1 max-h-44 overflow-y-auto rounded border border-[#3f4147] bg-[#18191c] p-1 shadow-xl">
          {filtered.slice(0, 24).map((option) => (
            <button key={option} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => add(option)} className="block w-full rounded px-2.5 py-1.5 text-left text-xs text-[#dbdee1] hover:bg-[#5865f2]/20 hover:text-white">
              {option}
            </button>
          ))}
          {query.trim() && !options.some((option) => option.toLowerCase() === query.trim().toLowerCase()) && (
            <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => add(query)} className="block w-full rounded border-t border-[#2b2d31] px-2.5 py-1.5 text-left text-xs text-[#57f287] hover:bg-[#57f287]/10">
              + Add “{query.trim()}”
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function TraitPicker({ label, category, values: rawValues, options: rawOptions, query, onQueryChange, onChange, onAddToLibrary }: { label: string; category: string; values?: string[]; options?: TraitOption[]; query: string; onQueryChange: (value: string) => void; onChange: (values: string[]) => void; onAddToLibrary: (category: string, label: string) => Promise<void> }) {
  // Older backends do not return the Markdown profile fields yet. Treat those
  // fields as empty instead of allowing an incomplete response to crash the
  // entire Settings page.
  const values = Array.isArray(rawValues) ? rawValues : [];
  const options = Array.isArray(rawOptions) ? rawOptions : [];
  const [open, setOpen] = useState(false);
  const filtered = options.filter((option) => `${option.label ?? ""} ${option.description ?? ""} ${option.guidance ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const addCustom = () => {
    const labelValue = query.trim();
    const id = labelValue.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    if (!id || values.includes(id)) return;
    onChange([...values, id]);
    void onAddToLibrary(category, labelValue);
    onQueryChange("");
    setOpen(false);
  };

  return (
    <div className="relative">
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">{label}</label>
      <div className="flex flex-wrap gap-1.5 mt-1.5">
        {values.map((value) => (
          <button key={value} type="button" onClick={() => onChange(values.filter((item) => item !== value))} className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#5865f2]/15 text-xs text-[#dbdee1] border border-[#5865f2]/30" title="Remove">
            {options.find((option) => option.id === value)?.label ?? value} <X size={11} />
          </button>
        ))}
      </div>
      <input
        value={query}
        onChange={(event) => { onQueryChange(event.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        placeholder="Type to choose a premade trait…"
        className="w-full mt-2 bg-[#141517] border border-[#1f2023] rounded px-3 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
        onKeyDown={(event) => { if (event.key === "Enter" && query.trim()) { event.preventDefault(); addCustom(); } if (event.key === "Escape") setOpen(false); }}
      />
      {open && (filtered.length > 0 || query.trim()) && (
        <div className="absolute z-30 left-0 right-0 mt-1 max-h-48 overflow-y-auto rounded border border-[#3f4147] bg-[#18191c] p-1 shadow-xl">
          {filtered.slice(0, 24).map((option) => (
            <button key={option.id} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { if (!values.includes(option.id)) onChange([...values, option.id]); onQueryChange(""); setOpen(false); }} disabled={values.includes(option.id)} className="block w-full rounded px-2.5 py-1.5 text-left text-xs text-[#dbdee1] hover:bg-[#5865f2]/20 hover:text-white disabled:opacity-40" title={option.description}>
              <span className="font-medium">{option.label}</span>
              {option.description && <span className="ml-2 text-[10px] text-[#949ba4]">{option.description}</span>}
            </button>
          ))}
          {query.trim() && <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={addCustom} className="block w-full rounded border-t border-[#2b2d31] px-2.5 py-1.5 text-left text-xs text-[#57f287] hover:bg-[#57f287]/10">+ Add “{query.trim()}” as a custom value</button>}
        </div>
      )}
    </div>
  );
}

function SuggestionTagField({ label, values: rawValues, suggestions: rawSuggestions, onChange }: { label: string; values?: string[]; suggestions?: string[]; onChange: (values: string[]) => void }) {
  const values = Array.isArray(rawValues) ? rawValues : [];
  const suggestions = Array.isArray(rawSuggestions) ? rawSuggestions : [];
  return <div><TagField label={label} values={values} onChange={onChange} /><div className="flex flex-wrap gap-1 mt-1.5">{suggestions.filter((suggestion) => !values.includes(suggestion)).map((suggestion) => <button key={suggestion} onClick={() => onChange([...values, suggestion])} className="rounded bg-[#141517] px-2 py-0.5 text-[10px] text-[#949ba4] hover:text-[#dbdee1] hover:bg-[#35373c]">+ {suggestion}</button>)}</div></div>;
}

function ProfilePreview({ settings }: { settings: Settings }) {
  const appearance = [
    ["Height", settings.character_appearance_height], ["Build", settings.character_appearance_build], ["Hair", settings.character_appearance_hair], ["Eyes", settings.character_appearance_eyes], ["Skin / fur", settings.character_appearance_skin_or_fur], ["Clothing", settings.character_appearance_clothing], ["Accessories", settings.character_appearance_accessories], ["Distinguishing features", settings.character_appearance_distinguishing_features], ["Visual style", settings.character_appearance_visual_style], ["Notes", settings.character_appearance_notes],
  ].filter(([, value]) => value);
  const traits = Array.isArray(settings.character_traits) ? settings.character_traits : [];
  const dereTypes = Array.isArray(settings.character_dere_types) ? settings.character_dere_types : [];
  const coreValues = Array.isArray(settings.character_core_values) ? settings.character_core_values : [];
  const preview = `---\nid: ${settings.character_profile_id || ""}\nname: ${settings.character_name || ""}\nage: ${settings.character_age || ""}\ngender: ${settings.character_gender || ""}\npronouns: ${settings.character_pronouns || ""}\nresponse_style: ${settings.character_response_style || "Friendly"}\ntraits: [${traits.join(", ")}]\ndere_types: [${dereTypes.join(", ")}]\ncore_values: [${coreValues.join(", ")}]\n---\n\n# ${settings.character_name || "Character"}\n\n## Description\n${settings.character_description || "(empty)"}\n\n## Personality Guidance\n${settings.character_personality_summary || "(empty)"}\n\n## Appearance\n${appearance.map(([label, value]) => `- ${label}: ${value}`).join("\n") || "(empty)"}\n\n## Backstory\n${settings.character_backstory || "(empty)"}`;
  return <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]"><div className="flex items-center justify-between mb-2"><h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5"><Eye size={14} className="text-[#57f287]" /> Markdown profile preview</h4><span className="text-[10px] text-[#6d7078]">live</span></div><pre className="max-h-64 overflow-auto rounded bg-[#141517] p-3 text-[10px] leading-relaxed text-[#8ce8a2] whitespace-pre-wrap">{preview}</pre></div>;
}

// ── 3. LLM Settings ──────────────────────────────────────────────────

function LLMSettingsSection({ settings, onChange, presets, onApply, onRename, onOverwrite, onSaveCurrent, onDelete, onDuplicate, onSave, llmModels, onRefreshModels, telemetry, currentPresetId, currentSettings: _currentSettings }: {
  settings: Settings; onChange: (k: keyof Settings, v: string | number | string[]) => void;
  presets: Preset[]; onApply: (id: string) => void; onRename: (id: string, name: string) => void;
  onOverwrite: PresetOverwriteHandler; onSaveCurrent: (id: string) => void; onDelete: (id: string) => void; onSave: () => void;
  onDuplicate: (preset: Preset) => void;
  llmModels: LLMModelInfo[];
  onRefreshModels: () => Promise<void> | void;
  telemetry: TelemetryData | null;
  currentPresetId?: string | null;
  currentSettings?: Settings | null;
}) {
  const [downloadingIds, setDownloadingIds] = useState<string[]>([]);
  const [downloadProgressById, setDownloadProgressById] = useState<Record<string, LLMDownloadStatus>>({});
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);
  const [licensePrompt, setLicensePrompt] = useState<LLMModelLicense | null>(null);
  const [pendingLicenseModel, setPendingLicenseModel] = useState<string | null>(null);
  const [acceptingLicense, setAcceptingLicense] = useState(false);

  useEffect(() => {
    const activeIds = llmModels.filter((model) => model.download?.status === "downloading").map((model) => model.id);
    if (!activeIds.length) return;
    setDownloadingIds((previous) => Array.from(new Set([...previous, ...activeIds])));
    setDownloadProgressById((previous) => {
      const next = { ...previous };
      for (const model of llmModels) {
        if (model.download?.status === "downloading") next[model.id] = model.download;
      }
      return next;
    });
  }, [llmModels]);

  useEffect(() => {
    if (!downloadingIds.length) return;
    let disposed = false;
    const refreshProgress = async () => {
      const results = await Promise.all(downloadingIds.map(async (modelId) => {
        try {
          return { modelId, status: await fetchLLMDownloadStatus(modelId) };
        } catch (error) {
          return { modelId, error: error instanceof Error ? error.message : "Download status unavailable." };
        }
      }));
      if (disposed) return;
      const finished: Array<{ modelId: string; status: "ready" | "error"; error?: string }> = results.flatMap((result) => {
        if (!result.status) return [{ modelId: result.modelId, status: "error" as const, error: result.error }];
        if (result.status.status === "ready" || result.status.status === "error") {
          return [{ modelId: result.modelId, status: result.status.status, error: result.status.error || undefined }];
        }
        return [];
      });
      setDownloadProgressById((previous) => {
        const next = { ...previous };
        for (const result of results) {
          if (result.status) {
            next[result.modelId] = result.status;
          } else {
            next[result.modelId] = {
              model: result.modelId,
              status: "error",
              downloaded_bytes: previous[result.modelId]?.downloaded_bytes || 0,
              total_bytes: previous[result.modelId]?.total_bytes || null,
              progress_percent: previous[result.modelId]?.progress_percent || null,
              speed_bytes_per_sec: null,
              error: result.error || "Download status unavailable.",
              started_at: previous[result.modelId]?.started_at || null,
              updated_at: Date.now(),
            };
          }
        }
        return next;
      });
      if (finished.length) {
        setDownloadingIds((previous) => previous.filter((id) => !finished.some((item) => item.modelId === id)));
        const ready = finished.filter((item) => item.status === "ready").length;
        const failed = finished.filter((item) => item.status === "error");
        setDownloadMsg(failed.length ? `Download failed: ${failed[0].error || "Unknown download error"}` : `${ready} local LLM download${ready === 1 ? "" : "s"} ready to use.`);
        void onRefreshModels();
      }
    };
    void refreshProgress();
    const timer = window.setInterval(() => { void refreshProgress(); }, 750);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [downloadingIds, onRefreshModels]);

  const beginModelDownload = async (modelId: string) => {
    setDownloadingIds((previous) => Array.from(new Set([...previous, modelId])));
    setDownloadProgressById((previous) => {
      const next = { ...previous };
      delete next[modelId];
      return next;
    });
    setDownloadMsg("Preparing local LLM download...");
    try {
      const result = await downloadLLMModel(modelId);
      if (result.download) setDownloadProgressById((previous) => ({ ...previous, [modelId]: result.download! }));
      if (result.status === "ready") {
        setDownloadingIds((previous) => previous.filter((id) => id !== modelId));
        setDownloadMsg("This local LLM is already downloaded and ready.");
        await onRefreshModels();
      } else {
        setDownloadMsg("Downloading the GGUF model to the local cache...");
      }
    } catch (error) {
      setDownloadingIds((previous) => previous.filter((id) => id !== modelId));
      setDownloadProgressById((previous) => ({
        ...previous,
        [modelId]: {
          ...(previous[modelId] || { model: modelId, downloaded_bytes: 0, total_bytes: null, progress_percent: null, started_at: null, updated_at: null }),
          status: "error",
          speed_bytes_per_sec: null,
          error: error instanceof Error ? error.message : "Download failed.",
        },
      }));
      setDownloadMsg(error instanceof Error ? `Download failed: ${error.message}` : "Download failed.");
    }
  };

  const handleDownload = async (model: LLMModelInfo) => {
    if (!model.license_accepted) {
      try {
        setPendingLicenseModel(model.id);
        setLicensePrompt(await fetchLLMModelLicense(model.id));
      } catch (error) {
        setDownloadMsg(error instanceof Error ? `Could not load license details: ${error.message}` : "Could not load license details.");
      }
      return;
    }
    await beginModelDownload(model.id);
  };

  const confirmLicenseAndDownload = async () => {
    if (!licensePrompt || !pendingLicenseModel) return;
    setAcceptingLicense(true);
    try {
      await acceptLLMModelLicense(pendingLicenseModel);
      const modelId = pendingLicenseModel;
      setLicensePrompt(null);
      setPendingLicenseModel(null);
      await beginModelDownload(modelId);
    } catch (error) {
      setDownloadMsg(error instanceof Error ? `License acceptance failed: ${error.message}` : "License acceptance failed.");
    } finally {
      setAcceptingLicense(false);
    }
  };

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm space-y-4">
      <SectionHeader icon={Brain} title="LLM & Intelligence Engine" presetType="llm" presets={presets} onApply={onApply} onRename={onRename} onOverwrite={onOverwrite} onSaveCurrent={onSaveCurrent} onDelete={onDelete} onDuplicate={onDuplicate} onSave={onSave} showPresetActions modelKey="llm_model" modelValue={settings.llm_model} currentPresetId={currentPresetId} currentSettings={settings} />

      {downloadMsg && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-[#5865f2]/30 bg-[#5865f2]/15 p-3 text-xs text-[#dbdee1]">
          <span className="flex min-w-0 items-center gap-2"><Loader2 size={14} className={downloadingIds.length ? "shrink-0 animate-spin text-[#8ea1ff]" : "shrink-0 text-[#8ea1ff]"} />{downloadMsg}</span>
          <button onClick={() => setDownloadMsg(null)} className="shrink-0 text-[#949ba4] hover:text-white" aria-label="Dismiss download message"><X size={12} /></button>
        </div>
      )}

      {licensePrompt && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="llm-license-title">
          <div className="w-full max-w-lg rounded-xl border border-[#5865f2]/50 bg-[#2b2d31] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="llm-license-title" className="text-base font-semibold text-[#f2f3f5]">Accept model license</h3>
                <p className="mt-1 text-xs text-[#949ba4]">{licensePrompt.model} · {licensePrompt.license}</p>
              </div>
              <button onClick={() => { setLicensePrompt(null); setPendingLicenseModel(null); }} className="rounded p-1 text-[#949ba4] hover:bg-[#35373c] hover:text-white" aria-label="Close license dialog"><X size={16} /></button>
            </div>
            <p className="mt-4 rounded-lg border border-[#3f4147] bg-[#1e1f22] p-3 text-sm leading-6 text-[#dbdee1]">{licensePrompt.text}</p>
            {licensePrompt.requires_hf_access && <p className="mt-3 rounded-lg border border-[#fee75c]/30 bg-[#fee75c]/10 p-3 text-xs leading-5 text-[#fee75c]">Gemma requires you to sign in and accept access on its official Hugging Face page before you confirm here. This app records only your local confirmation.</p>}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex gap-3">
                <button onClick={() => window.open(licensePrompt.license_url, "_blank", "noopener,noreferrer")} className="text-xs text-[#8ea1ff] hover:underline">Open license</button>
                <button onClick={() => window.open(licensePrompt.official_source_url, "_blank", "noopener,noreferrer")} className="text-xs text-[#8ea1ff] hover:underline">Open official model</button>
              </div>
              <div className="flex gap-2">
                <button onClick={() => { setLicensePrompt(null); setPendingLicenseModel(null); }} className="rounded-lg px-3 py-2 text-xs font-semibold text-[#b5bac1] hover:bg-[#35373c]">Cancel</button>
                <button onClick={confirmLicenseAndDownload} disabled={acceptingLicense} className="flex items-center gap-2 rounded-lg bg-[#5865f2] px-3 py-2 text-xs font-semibold text-white hover:bg-[#4752c4] disabled:opacity-50">
                  {acceptingLicense && <Loader2 size={13} className="animate-spin" />} I agree and download
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column: Models & Provider */}
        <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
          <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
            <Cpu size={14} className="text-[#5865f2]" /> Model Selection
          </h4>

          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Provider Engine</label>
            <select value={settings.llm_provider} onChange={(e) => onChange("llm_provider", e.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]">
              <option value="openai_compatible">OpenAI Compatible (Local llama.cpp / vLLM / Ollama)</option>
              <option value="openai">OpenAI (GPT-4o, GPT-4o-mini)</option>
              <option value="anthropic">Anthropic (Claude 3.5 Sonnet)</option>
              <option value="ollama">Ollama Native</option>
            </select>
          </div>

          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Local Model Library</label>
            <div className="mt-1 max-h-[360px] space-y-2 overflow-y-auto pr-1">
              {llmModels.map((model) => {
                const isSelected = settings.llm_model === model.filename;
                const isDownloading = downloadingIds.includes(model.id);
                const progress = isDownloading ? downloadProgressById[model.id] : model.download;
                const percent = progress?.progress_percent;
                return (
                  <div key={model.id} className={`rounded-lg border p-2.5 transition-all ${isSelected ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#141517]"}`}>
                    <div className="flex items-start gap-2.5">
                      <Brain size={15} className={isSelected ? "mt-0.5 shrink-0 text-[#8ea1ff]" : "mt-0.5 shrink-0 text-[#949ba4]"} />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-xs font-semibold text-[#dbdee1]">{model.name}</span>
                          {model.ready ? <span className="rounded bg-[#23a55a]/15 px-1.5 py-0.5 text-[9px] font-semibold text-[#23a55a]">Downloaded</span> : <span className="rounded bg-[#fee75c]/15 px-1.5 py-0.5 text-[9px] font-semibold text-[#fee75c]">Available</span>}
                          {model.quantization && <span className="rounded bg-[#2b2d31] px-1.5 py-0.5 text-[9px] font-mono text-[#949ba4]">{model.quantization}</span>}
                          {isSelected && <span className="rounded bg-[#5865f2] px-1.5 py-0.5 text-[9px] font-semibold text-white">ACTIVE</span>}
                        </div>
                        <p className="mt-1 text-[10px] leading-snug text-[#949ba4]">{model.description}</p>
                        <div className="mt-1.5 flex flex-wrap gap-1.5 text-[9px] text-[#949ba4]">
                          <span className="rounded bg-[#2b2d31] px-1.5 py-0.5 font-mono">{model.size_gb} GB</span>
                          {model.parameters && <span className="rounded bg-[#2b2d31] px-1.5 py-0.5">{model.parameters}</span>}
                          {model.license && <span className="rounded bg-[#2b2d31] px-1.5 py-0.5">{model.license}</span>}
                        </div>
                        {isDownloading && (
                          <div className="mt-2.5 rounded-md border border-[#5865f2]/30 bg-[#5865f2]/10 p-2" aria-live="polite">
                            <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] text-[#dbdee1]">
                              <span className="flex items-center gap-1.5"><Loader2 size={11} className="animate-spin text-[#8ea1ff]" /> Downloading locally</span>
                              <span className="font-mono text-[#8ea1ff]">{percent !== null && percent !== undefined ? `${percent.toFixed(1)}%` : "Starting…"}</span>
                            </div>
                            <div className="h-1.5 overflow-hidden rounded-full bg-[#1e1f22]" role="progressbar" aria-label={`Downloading ${model.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
                              <div className="h-full rounded-full bg-[#5865f2] transition-[width] duration-300" style={{ width: `${Math.max(1, Math.min(100, percent ?? 2))}%` }} />
                            </div>
                            <div className="mt-1.5 flex flex-wrap justify-between gap-x-2 gap-y-0.5 text-[9px] text-[#949ba4]">
                              <span>{formatDownloadBytes(progress?.downloaded_bytes)}{progress?.total_bytes ? ` / ${formatDownloadBytes(progress.total_bytes)}` : ""}</span>
                              {formatDownloadRate(progress?.speed_bytes_per_sec) && <span>{formatDownloadRate(progress?.speed_bytes_per_sec)}</span>}
                            </div>
                          </div>
                        )}
                        {!isDownloading && progress?.status === "error" && <p className="mt-2 text-[10px] text-[#ed4245]">Previous download failed: {progress.error || "Unknown error"}. Click Download to resume.</p>}
                      </div>
                    </div>
                    <div className="mt-2.5 flex items-center justify-end gap-2 border-t border-[#1f2023] pt-2">
                      {!model.ready && model.download_url && <button onClick={() => void handleDownload(model)} disabled={isDownloading} className="flex items-center gap-1 rounded bg-[#35373c] px-2.5 py-1 text-xs font-semibold text-[#dbdee1] transition-all hover:bg-[#404249] disabled:opacity-50">{isDownloading ? <Loader2 size={12} className="animate-spin text-[#8ea1ff]" /> : <Download size={12} />} {isDownloading ? "Downloading…" : "Download"}</button>}
                      <button onClick={() => onChange("llm_model", model.filename)} disabled={!model.ready || isSelected} className={`flex items-center gap-1 rounded px-3 py-1 text-xs font-semibold transition-all ${isSelected ? "cursor-default bg-[#5865f2]/20 text-[#8ea1ff]" : "bg-[#5865f2] text-white hover:bg-[#4752c4] disabled:cursor-not-allowed disabled:opacity-50"}`}>{isSelected ? <Check size={12} /> : null}{isSelected ? "Selected" : "Use model"}</button>
                    </div>
                  </div>
                );
              })}
            </div>
            <input type="text" value={settings.llm_model} onChange={(e) => onChange("llm_model", e.target.value)} placeholder="Or enter a server model identifier" className="mt-2 w-full rounded border border-[#1f2023] bg-[#141517] px-3 py-2 text-xs font-mono text-[#dbdee1] focus:border-[#5865f2] focus:outline-none" />
          </div>

          <EditableField label="Base URL" value={settings.llm_base_url} onChange={(v) => onChange("llm_base_url", v)} mono />
        </div>

        {/* Right Column: Sampling & Performance */}
        <div className="space-y-4">
          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Sliders size={14} className="text-[#fee75c]" /> Sampling Parameters
            </h4>

            <div>
              <div className="flex items-center justify-between">
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Temperature (Creativity)</label>
                <span className="text-[11px] text-[#dbdee1] font-mono">{settings.llm_temperature.toFixed(2)}</span>
              </div>
              <input type="range" min={0} max={2} step={0.05} value={settings.llm_temperature} onChange={(e) => onChange("llm_temperature", parseFloat(e.target.value))} className="w-full h-1.5 mt-1.5 rounded-full appearance-none cursor-pointer" style={{ background: `linear-gradient(to right, #5865f2 ${settings.llm_temperature * 50}%, #2b2d31 ${settings.llm_temperature * 50}%)` }} />
              <div className="flex justify-between mt-0.5 text-[9px] text-[#6d6f78]">
                <span>Deterministic (0.0)</span>
                <span>Balanced (0.7)</span>
                <span>Wild (2.0)</span>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Max Response Tokens</label>
                <span className="text-[11px] text-[#dbdee1] font-mono">{settings.llm_max_tokens}</span>
              </div>
              <input type="range" min={64} max={4096} step={64} value={settings.llm_max_tokens} onChange={(e) => onChange("llm_max_tokens", parseInt(e.target.value))} className="w-full h-1.5 mt-1.5 rounded-full appearance-none cursor-pointer" style={{ background: `linear-gradient(to right, #5865f2 ${((settings.llm_max_tokens - 64) / (4096 - 64)) * 100}%, #2b2d31 ${((settings.llm_max_tokens - 64) / (4096 - 64)) * 100}%)` }} />
              <div className="flex justify-between mt-0.5 text-[9px] text-[#6d6f78]">
                <span>64 tokens</span>
                <span>2048 tokens</span>
                <span>4096 tokens</span>
              </div>
            </div>
          </div>

          {/* Performance Stat Cards */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Gauge size={15} className="text-[#23a55a]" />
                <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider">LLM Hardware Telemetry</h4>
              </div>
              <span className="text-[10px] font-mono text-[#949ba4] bg-[#141517] px-2 py-0.5 rounded border border-[#2b2d31]">
                {telemetry?.gpu.name || "NVIDIA GPU"}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <PerfStatCard icon={Zap} label="Tokens/sec" value={`~${telemetry?.llm.tokens_per_sec ?? 48} t/s`} color="#fee75c" />
              <PerfStatCard icon={MemoryStick} label="VRAM Allocated" value={`${telemetry?.llm.vram_allocated_gb ?? 5.8} GB`} color="#5865f2" />
              <PerfStatCard icon={Activity} label="GPU Load" value={`${telemetry?.llm.gpu_load_pct ?? 76}%`} color="#23a55a" />
            </div>
            <div className="p-2.5 bg-[#141517] rounded border border-[#2b2d31] flex items-center justify-between text-[11px] text-[#949ba4]">
              <span>Architecture: <strong className="text-[#dbdee1] font-mono">{telemetry?.llm.architecture || "GGUF Quantized"}</strong></span>
              <span>Model Size: <strong className="text-[#dbdee1] font-mono">{telemetry?.llm.file_size_gb ? `${telemetry.llm.file_size_gb} GB` : "6.8 GB"}</strong></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 4. TTS Settings ──────────────────────────────────────────────────

function TTSSettingsSection({ settings, onChange, presets, onApply, onRename, onOverwrite, onSaveCurrent, onDelete, onDuplicate, onSave, telemetry, currentPresetId, currentSettings: _currentSettings }: {
  settings: Settings; onChange: (k: keyof Settings, v: string | number | string[]) => void;
  presets: Preset[]; onApply: (id: string) => void; onRename: (id: string, name: string) => void;
  onOverwrite: PresetOverwriteHandler; onSaveCurrent: (id: string) => void; onDelete: (id: string) => void; onSave: () => void;
  onDuplicate: (preset: Preset) => void;
  telemetry: TelemetryData | null;
  currentPresetId?: string | null;
  currentSettings?: Settings | null;
}) {
  const [uploading, setUploading] = useState(false);
  const [testText, setTestText] = useState("Hello! I am your AI VTuber companion. How does my voice sound?");
  const [testing, setTesting] = useState(false);
  const [openrouterSearch, setOpenrouterSearch] = useState("fish-audio");
  const [openrouterModels, setOpenrouterModels] = useState<Array<{
    id: string;
    name: string;
    description: string;
    supported_voices: string[];
    prompt_price?: string | number | null;
    completion_price?: string | number | null;
  }>>([]);
  const [openrouterModelsLoading, setOpenrouterModelsLoading] = useState(false);
  const [openrouterModelsError, setOpenrouterModelsError] = useState<string | null>(null);
  const [openrouterApiKey, setOpenrouterApiKey] = useState("");
  const [openrouterKeyConfigured, setOpenrouterKeyConfigured] = useState(false);
  const [openrouterKeyMasked, setOpenrouterKeyMasked] = useState("");
  const [openrouterKeySaving, setOpenrouterKeySaving] = useState(false);
  const [openrouterKeyMessage, setOpenrouterKeyMessage] = useState<string | null>(null);
  const [fishVoiceSearch, setFishVoiceSearch] = useState("");
  const [fishVoices, setFishVoices] = useState<Array<{
    id: string;
    title: string;
    description: string;
    author: string;
    tags: string[];
    languages: string[];
    licensed: boolean;
    url: string;
  }>>([]);
  const [fishVoicesLoading, setFishVoicesLoading] = useState(false);
  const [fishVoicesError, setFishVoicesError] = useState<string | null>(null);
  const [fishApiKey, setFishApiKey] = useState("");
  const [fishKeyConfigured, setFishKeyConfigured] = useState(false);
  const [fishKeyMasked, setFishKeyMasked] = useState("");
  const [fishKeySaving, setFishKeySaving] = useState(false);
  const [fishKeyMessage, setFishKeyMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (settings.tts_engine !== "openrouter") return;
    let cancelled = false;
    void fetch("/api/tts/openrouter/key-status")
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `Key status failed (${response.status})`);
        if (!cancelled) {
          setOpenrouterKeyConfigured(Boolean(data.configured));
          setOpenrouterKeyMasked(String(data.masked || ""));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOpenrouterKeyConfigured(false);
          setOpenrouterKeyMasked("");
        }
      });
    return () => { cancelled = true; };
  }, [settings.tts_engine, settings.tts_openrouter_api_key_env]);

  useEffect(() => {
    if (settings.tts_engine !== "openrouter") return;
    let cancelled = false;
    void fetch("/api/tts/fish/key-status")
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `Fish key status failed (${response.status})`);
        if (!cancelled) {
          setFishKeyConfigured(Boolean(data.configured));
          setFishKeyMasked(String(data.masked || ""));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFishKeyConfigured(false);
          setFishKeyMasked("");
        }
      });
    return () => { cancelled = true; };
  }, [settings.tts_engine, settings.tts_fish_audio_api_key_env]);

  const saveOpenrouterApiKey = async () => {
    if (!openrouterApiKey.trim() || openrouterKeySaving) return;
    setOpenrouterKeySaving(true);
    setOpenrouterKeyMessage(null);
    try {
      const response = await fetch("/api/tts/openrouter/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: openrouterApiKey.trim(),
          env_name: settings.tts_openrouter_api_key_env || "OPENROUTER_API_KEY",
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Could not save API key (${response.status})`);
      setOpenrouterApiKey("");
      setOpenrouterKeyConfigured(Boolean(data.configured));
      setOpenrouterKeyMasked(String(data.masked || ""));
      setOpenrouterKeyMessage("Saved to backend/.env");
    } catch (error) {
      setOpenrouterKeyMessage(error instanceof Error ? error.message : "Could not save API key");
    } finally {
      setOpenrouterKeySaving(false);
    }
  };

  const saveFishApiKey = async () => {
    if (!fishApiKey.trim() || fishKeySaving) return;
    setFishKeySaving(true);
    setFishKeyMessage(null);
    try {
      const response = await fetch("/api/tts/fish/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_key: fishApiKey.trim(),
          env_name: settings.tts_fish_audio_api_key_env || "FISH_AUDIO_API_KEY",
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Could not save Fish Audio key (${response.status})`);
      setFishApiKey("");
      setFishKeyConfigured(Boolean(data.configured));
      setFishKeyMasked(String(data.masked || ""));
      setFishKeyMessage("Saved to backend/.env");
    } catch (error) {
      setFishKeyMessage(error instanceof Error ? error.message : "Could not save Fish Audio key");
    } finally {
      setFishKeySaving(false);
    }
  };

  const fetchFishVoices = async () => {
    if (fishVoicesLoading) return;
    setFishVoicesLoading(true);
    setFishVoicesError(null);
    try {
      const query = fishVoiceSearch.trim();
      const response = await fetch(`/api/tts/fish/voices${query ? `?q=${encodeURIComponent(query)}` : ""}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Fish Audio voice search failed (${response.status})`);
      setFishVoices(Array.isArray(data.voices) ? data.voices : []);
    } catch (error) {
      setFishVoicesError(error instanceof Error ? error.message : "Could not fetch Fish Audio voices.");
      setFishVoices([]);
    } finally {
      setFishVoicesLoading(false);
    }
  };

  const fetchOpenrouterModels = async () => {
    if (openrouterModelsLoading) return;
    setOpenrouterModelsLoading(true);
    setOpenrouterModelsError(null);
    try {
      const query = openrouterSearch.trim();
      const response = await fetch(`/api/tts/openrouter/models${query ? `?q=${encodeURIComponent(query)}` : ""}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Model search failed (${response.status})`);
      setOpenrouterModels(Array.isArray(data.models) ? data.models : []);
    } catch (error) {
      setOpenrouterModelsError(error instanceof Error ? error.message : "Could not fetch OpenRouter speech models.");
      setOpenrouterModels([]);
    } finally {
      setOpenrouterModelsLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch("/api/tts/upload-voice", { method: "POST", body: formData });
      const data = await resp.json();
      onChange("tts_voice_ref", data.path || "");
    } catch (err) { console.error("Upload failed:", err); }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = ""; }
  };

  const handleTest = async () => {
    if (!testText.trim() || testing) return;
    setTesting(true);
    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: testText,
          engine: settings.tts_engine,
          voice: settings.tts_voice_ref || settings.tts_engine,
          voice_ref: settings.tts_voice_ref,
          smart_emotions: settings.tts_emotion_mode === "smart",
          seed: settings.tts_seed,
          speaking_rate: settings.tts_speaking_rate,
          pitch_std: settings.tts_pitch_std,
          happiness: settings.tts_happiness,
          sadness: settings.tts_sadness,
          anger: settings.tts_anger,
          fear: settings.tts_fear,
          openrouter_model: settings.tts_openrouter_model,
          openrouter_voice: settings.tts_openrouter_voice,
          openrouter_response_format: settings.tts_openrouter_response_format,
          openrouter_speed: settings.tts_openrouter_speed,
        }),
      });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audio.onended = () => URL.revokeObjectURL(url);
        await audio.play();
      }
    } catch (err) { console.error("TTS test failed:", err); }
    finally { setTesting(false); }
  };

  // API keys are intentionally kept out of presets, but users commonly click
  // the same preset save actions after editing the TTS panel. Persist pending
  // keys first so those actions cannot make them look lost. The dedicated
  // key buttons remain the clearest path.
  const persistPendingTtsKeys = () => {
    if (settings.tts_engine === "openrouter" && openrouterApiKey.trim()) {
      void saveOpenrouterApiKey();
    }
    if (settings.tts_engine === "openrouter" && fishApiKey.trim()) {
      void saveFishApiKey();
    }
  };
  const saveCurrentTtsPreset = (id: string) => {
    persistPendingTtsKeys();
    onSaveCurrent(id);
  };
  const overwriteTtsPreset = (id: string, name: string, presetType?: string) => {
    persistPendingTtsKeys();
    onOverwrite(id, name, presetType);
  };
  const saveTtsPresetAsNew = () => {
    persistPendingTtsKeys();
    onSave();
  };

  const engines = [
    { id: "zonos", name: "Zonos", badge: "Primary", badgeColor: "#5865f2", icon: AudioLines, description: "Local GPU, voice cloning, emotion conditioning", specs: ["44kHz", "Port 8091", "~2GB VRAM"], color: "#b5bac1" },
    { id: "indextts", name: "Index-TTS", badge: null, badgeColor: null, icon: Sparkles, description: "Local GPU, reference audio conditioning", specs: ["v2.5", "Port 8090", "~1.5GB VRAM"], color: "#b5bac1" },
    { id: "edge-tts", name: "Edge-TTS", badge: "Cloud Fallback", badgeColor: "#b5bac1", icon: Cloud, description: "Cloud fallback, fast & resilient, no GPU needed", specs: ["Online", "No GPU", "Microsoft Neural"], color: "#b5bac1" },
    { id: "openrouter", name: "OpenRouter TTS", badge: "Hosted", badgeColor: "#57f287", icon: Cloud, description: "Hosted speech models through OpenRouter; no local model required", specs: ["API", "No VRAM", "Fish Audio S2.1"], color: "#57f287" },
  ];

  const femaleVoices = [
    { value: "en-US-AnaNeural", label: "♀ Ana — Youthful & Energetic (US)" },
    { value: "en-US-JennyNeural", label: "♀ Jenny — Warm & Natural (US)" },
    { value: "en-GB-SoniaNeural", label: "♀ Sonia — Refined & Crisp (British)" },
    { value: "ja-JP-NanamiNeural", label: "♀ Nanami — Expressive & Anime (Japanese/EN)" },
    { value: "voices/female_sweet.wav", label: "♀ Yuna — Sweet & Melodic (Hi-Fi)" },
    { value: "voices/female_warm.wav", label: "♀ Maya — Soft & Calming (Hi-Fi)" },
    { value: "voices/female_energetic.wav", label: "♀ Chika — Genki & Upbeat (Hi-Fi)" },
    { value: "voices/female_refined.wav", label: "♀ Elena — Elegant & Mature (Hi-Fi)" },
  ];
  const maleVoices = [
    { value: "en-US-GuyNeural", label: "♂ Guy — Casual & Confident (US)" },
    { value: "en-GB-RyanNeural", label: "♂ Ryan — Deep & Sophisticated (British)" },
    { value: "voices/male_hero.wav", label: "♂ Alex — Heroic & Energetic (Hi-Fi)" },
    { value: "voices/male_deep.wav", label: "♂ Marcus — Deep Baritone & Grounded (Hi-Fi)" },
  ];
  const preferredVoiceGroups = Number(settings.tts_voice_gender ?? 50) >= 0
    ? [{ label: "Female Voice Characters (♀)", voices: femaleVoices }, { label: "Male Voice Characters (♂)", voices: maleVoices }]
    : [{ label: "Male Voice Characters (♂)", voices: maleVoices }, { label: "Female Voice Characters (♀)", voices: femaleVoices }];
  const isBuiltinVoice = BUILTIN_TTS_VOICES.includes(settings.tts_voice_ref || "");

  const emotionSliders = [
    { key: "tts_happiness" as const, label: "Happiness", min: 0, max: 1, step: 0.05, color: "#5865f2" },
    { key: "tts_sadness" as const, label: "Sadness", min: 0, max: 1, step: 0.05, color: "#5865f2" },
    { key: "tts_anger" as const, label: "Anger", min: 0, max: 1, step: 0.05, color: "#5865f2" },
    { key: "tts_fear" as const, label: "Fear", min: 0, max: 1, step: 0.05, color: "#5865f2" },
    { key: "tts_speaking_rate" as const, label: "Speaking Rate", min: 0.5, max: 2.0, step: 0.05, color: "#5865f2" },
    { key: "tts_pitch_std" as const, label: "Pitch Variation", min: 0.5, max: 2.0, step: 0.05, color: "#5865f2" },
  ];

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm space-y-4">
      <SectionHeader icon={Volume2} title="TTS & Voice Studio" presetType="tts" presets={presets} onApply={onApply} onRename={onRename} onOverwrite={overwriteTtsPreset} onSaveCurrent={saveCurrentTtsPreset} onDelete={onDelete} onDuplicate={onDuplicate} onSave={saveTtsPresetAsNew} showPresetActions modelKey="tts_engine" modelValue={settings.tts_engine} currentPresetId={currentPresetId} currentSettings={settings} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column: Engine Selection & Sliders */}
        <div className="space-y-4">
          <div className="space-y-2.5 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <AudioLines size={14} className="text-[#5865f2]" /> Voice Engine
            </h4>
            <div className="space-y-2">
              {engines.map((engine) => {
                const Icon = engine.icon;
                const isSelected = settings.tts_engine === engine.id;
                return (
                  <button key={engine.id} onClick={() => onChange("tts_engine", engine.id)} className={`w-full text-left p-3 rounded-lg border transition-all ${isSelected ? "bg-[#141517] border-[#5865f2] shadow-sm" : "bg-[#141517] border-[#1f2023] hover:border-[#4e5058]"}`}>
                    <div className="flex items-start gap-3">
                      <div className="p-2 rounded-md" style={{ backgroundColor: `${engine.color}20` }}><Icon size={16} style={{ color: engine.color }} /></div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-[#dbdee1]">{engine.name}</span>
                          {engine.badge && <span className="text-[9px] px-1.5 py-0.5 rounded font-medium" style={{ backgroundColor: `${engine.badgeColor}20`, color: engine.badgeColor }}>{engine.badge}</span>}
                        </div>
                        <p className="text-[11px] text-[#949ba4] mt-0.5">{engine.description}</p>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">{engine.specs.map((s) => <span key={s} className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#949ba4] font-mono">{s}</span>)}</div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {settings.tts_engine === "openrouter" && (
            <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
                  <Cloud size={14} className="text-[#57f287]" /> OpenRouter Speech API
                </h4>
                <a href="https://openrouter.ai/docs/api/api-reference/speech/create-audio-speech" target="_blank" rel="noreferrer" className="text-[10px] text-[#5865f2] hover:underline">API docs</a>
              </div>
              <p className="text-[11px] text-[#949ba4] leading-relaxed">
                The backend sends speech requests directly to OpenRouter. Save the key with the dedicated action below; it is never saved in presets or config.yaml.
              </p>
              <div className="rounded-lg border border-[#2b2d31] bg-[#141517] p-3 space-y-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="text-[10px] text-[#dbdee1] uppercase tracking-wider font-semibold">Find hosted speech models</div>
                    <p className="text-[10px] text-[#6d6f78] mt-0.5">Searches OpenRouter’s speech catalogue. “fish-audio” is prefilled.</p>
                  </div>
                  <button type="button" onClick={fetchOpenrouterModels} disabled={openrouterModelsLoading} className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-[10px] font-semibold disabled:opacity-50">
                    {openrouterModelsLoading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    Fetch models
                  </button>
                </div>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6d6f78]" />
                    <input value={openrouterSearch} onChange={(e) => setOpenrouterSearch(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void fetchOpenrouterModels(); }} placeholder="fish-audio, kokoro, or any speech model" className="w-full bg-[#1e1f22] border border-[#2b2d31] rounded pl-8 pr-2.5 py-1.5 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]" />
                  </div>
                  {openrouterSearch && <button type="button" onClick={() => { setOpenrouterSearch(""); setOpenrouterModels([]); setOpenrouterModelsError(null); }} className="px-2 text-[#949ba4] hover:text-[#dbdee1]" title="Clear search"><X size={14} /></button>}
                </div>
                {openrouterModelsError && <div className="text-[10px] text-[#f23f43]">{openrouterModelsError}</div>}
                {openrouterModels.length > 0 && (
                  <div className="max-h-44 overflow-y-auto space-y-1 pr-1">
                    {openrouterModels.map((model) => {
                      const selected = settings.tts_openrouter_model === model.id;
                      return (
                        <button key={model.id} type="button" onClick={() => onChange("tts_openrouter_model", model.id)} className={`w-full text-left rounded border px-2.5 py-2 transition-colors ${selected ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#2b2d31] hover:border-[#4e5058]"}`}>
                          <div className="flex items-center gap-2">
                            <span className="text-[11px] font-medium text-[#dbdee1] truncate">{model.name}</span>
                            {selected && <Check size={12} className="text-[#5865f2] shrink-0" />}
                          </div>
                          <div className="text-[10px] text-[#6d6f78] font-mono truncate">{model.id}</div>
                          {model.supported_voices.length > 0 && <div className="text-[10px] text-[#949ba4] mt-0.5">Voices: {model.supported_voices.join(", ")}</div>}
                        </button>
                      );
                    })}
                  </div>
                )}
                {openrouterModels.length === 0 && !openrouterModelsLoading && !openrouterModelsError && <div className="text-[10px] text-[#6d6f78]">Fetch results to choose a model. Search results stay local to this settings session.</div>}
                <p className="text-[10px] text-[#6d6f78] leading-relaxed">OpenRouter may not publish Fish Audio community voice IDs. For those voices, paste the reference ID from a Fish Audio voice link into the Voice field below; leave it blank for the provider default.</p>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                  API key environment variable name
                  <input value={settings.tts_openrouter_api_key_env || "OPENROUTER_API_KEY"} onChange={(e) => onChange("tts_openrouter_api_key_env", e.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs normal-case text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]" />
                </label>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                  Speech model
                  <input value={settings.tts_openrouter_model || "fish-audio/s2.1-pro-free:free"} onChange={(e) => onChange("tts_openrouter_model", e.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs normal-case text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]" />
                </label>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                  Voice
                  <input value={settings.tts_openrouter_voice || ""} placeholder="Provider default (optional)" onChange={(e) => onChange("tts_openrouter_voice", e.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs normal-case text-[#dbdee1] focus:outline-none focus:border-[#5865f2]" />
                </label>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                  Output format
                  <select value={settings.tts_openrouter_response_format || "mp3"} onChange={(e) => onChange("tts_openrouter_response_format", e.target.value)} className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs normal-case text-[#dbdee1] focus:outline-none focus:border-[#5865f2]">
                    <option value="mp3">MP3 (browser/Discord compatible)</option>
                  </select>
                </label>
              </div>
              <div className="rounded-lg border border-[#2b2d31] bg-[#141517] p-3 space-y-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[10px] text-[#dbdee1] uppercase tracking-wider font-semibold">Find Fish Audio voice IDs</div>
                    <p className="text-[10px] text-[#6d6f78] mt-0.5">Search Fish Audio’s voice directory, then use a result as the OpenRouter voice value.</p>
                  </div>
                  <button type="button" onClick={() => void fetchFishVoices()} disabled={fishVoicesLoading} className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-[10px] font-semibold disabled:opacity-50">
                    {fishVoicesLoading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
                    Fetch voices
                  </button>
                </div>
                <div className="flex gap-2">
                  <div className="relative flex-1">
                    <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6d6f78]" />
                    <input value={fishVoiceSearch} onChange={(e) => setFishVoiceSearch(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void fetchFishVoices(); }} placeholder="Search title, e.g. Neuro or Onokami" className="w-full bg-[#1e1f22] border border-[#2b2d31] rounded pl-8 pr-2.5 py-1.5 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]" />
                  </div>
                  {fishVoiceSearch && <button type="button" onClick={() => { setFishVoiceSearch(""); setFishVoices([]); setFishVoicesError(null); }} className="px-2 text-[#949ba4] hover:text-[#dbdee1]" title="Clear voice search"><X size={14} /></button>}
                </div>
                {fishVoicesError && <div className="text-[10px] text-[#f23f43]">{fishVoicesError}</div>}
                {fishVoices.length > 0 && (
                  <div className="max-h-52 overflow-y-auto space-y-1 pr-1">
                    {fishVoices.map((voice) => (
                      <button key={voice.id} type="button" onClick={() => onChange("tts_openrouter_voice", voice.id)} className={`w-full text-left rounded border px-2.5 py-2 transition-colors ${settings.tts_openrouter_voice === voice.id ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#2b2d31] hover:border-[#4e5058]"}`}>
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] font-medium text-[#dbdee1] truncate">{voice.title}</span>
                          {voice.author && <span className="text-[10px] text-[#949ba4] truncate">by {voice.author}</span>}
                          {settings.tts_openrouter_voice === voice.id && <Check size={12} className="ml-auto text-[#5865f2] shrink-0" />}
                        </div>
                        <div className="text-[10px] text-[#8ea1ff] font-mono truncate">{voice.id}</div>
                        <div className="flex flex-wrap gap-1 mt-0.5">
                          {voice.languages.slice(0, 3).map((language) => <span key={language} className="text-[9px] px-1 rounded bg-[#2b2d31] text-[#949ba4]">{language}</span>)}
                          {voice.licensed && <span className="text-[9px] px-1 rounded bg-[#23a55a]/15 text-[#57f287]">licensed</span>}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
                <div className="rounded border border-[#2b2d31] bg-[#1e1f22] p-2.5">
                  <div className="flex items-end gap-2">
                    <label className="flex-1 text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                      Fish Audio API key
                      <input type="password" autoComplete="new-password" value={fishApiKey} onChange={(e) => { setFishApiKey(e.target.value); setFishKeyMessage(null); }} onKeyDown={(e) => { if (e.key === "Enter") void saveFishApiKey(); }} placeholder={fishKeyConfigured ? "Key already saved — enter a replacement" : "Paste your Fish API key"} className="w-full mt-1 bg-[#141517] border border-[#2b2d31] rounded px-3 py-2 text-xs normal-case text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]" />
                    </label>
                    <button type="button" onClick={() => void saveFishApiKey()} disabled={!fishApiKey.trim() || fishKeySaving} className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-2 rounded bg-[#3f4147] hover:bg-[#4e5058] text-[#dbdee1] text-[10px] font-semibold disabled:opacity-40">
                      {fishKeySaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                      Save key
                    </button>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-1.5 text-[10px]">
                    <span className={fishKeyConfigured ? "text-[#57f287]" : "text-[#f0ad4e]"}>{fishKeyConfigured ? `Configured (${fishKeyMasked})` : "Fish key needed for search"}</span>
                    {fishKeyMessage && <span className="text-[#949ba4]">{fishKeyMessage}</span>}
                  </div>
                  <p className="text-[10px] text-[#6d6f78] mt-1">This key is only used to search Fish Audio voice metadata. TTS still goes through your selected OpenRouter model.</p>
                </div>
              </div>
              <div className="rounded border border-[#2b2d31] bg-[#141517] p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <label className="flex-1 text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                    OpenRouter API key
                    <input type="password" autoComplete="new-password" value={openrouterApiKey} onChange={(e) => { setOpenrouterApiKey(e.target.value); setOpenrouterKeyMessage(null); }} onKeyDown={(e) => { if (e.key === "Enter") void saveOpenrouterApiKey(); }} placeholder={openrouterKeyConfigured ? "Key already saved — enter a replacement" : "Paste your sk-or-v1-… key"} className="w-full mt-1 bg-[#1e1f22] border border-[#2b2d31] rounded px-3 py-2 text-xs normal-case text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]" />
                  </label>
                  <button type="button" onClick={() => void saveOpenrouterApiKey()} disabled={!openrouterApiKey.trim() || openrouterKeySaving} className="mt-4 shrink-0 inline-flex items-center gap-1.5 px-2.5 py-2 rounded bg-[#23a55a] hover:bg-[#1a8245] text-white text-[10px] font-semibold disabled:opacity-40">
                    {openrouterKeySaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                    Save API key
                  </button>
                </div>
                <div className="flex items-center justify-between gap-2 mt-1.5 text-[10px]">
                  <span className={openrouterKeyConfigured ? "text-[#57f287]" : "text-[#f0ad4e]"}>{openrouterKeyConfigured ? `Configured (${openrouterKeyMasked})` : "No key configured"}</span>
                  {openrouterKeyMessage && <span className="text-[#949ba4]">{openrouterKeyMessage}</span>}
                </div>
                <p className="text-[10px] text-[#6d6f78] mt-1">This separate action writes the secret to <span className="font-mono">backend/.env</span>. It is never included in presets or returned by the API.</p>
              </div>
              <label className="block text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">
                Playback speed <span className="font-mono text-[#dbdee1]">{Number(settings.tts_openrouter_speed ?? 1).toFixed(2)}×</span>
                <input type="range" min="0.25" max="4" step="0.05" value={settings.tts_openrouter_speed ?? 1} onChange={(e) => onChange("tts_openrouter_speed", Number(e.target.value))} className="w-full mt-1" />
              </label>
              <p className="text-[10px] text-[#6d6f78]">Model reference: <a href="https://openrouter.ai/fish-audio/s2.1-pro-free:free" target="_blank" rel="noreferrer" className="text-[#8ea1ff] hover:underline">fish-audio/s2.1-pro-free:free</a>. Voice names are provider-specific; leave the voice blank to use the provider default unless the model documents another value.</p>
            </div>
          )}

          {/* Emotion Conditioning: Smart vs Manual */}
          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
                <Sparkles size={14} className="text-[#eb459e]" /> Emotional Conditioning
              </h4>
              <div className="flex bg-[#141517] p-0.5 rounded-lg border border-[#2b2d31]">
                <button
                  type="button"
                  onClick={() => onChange("tts_emotion_mode", "smart")}
                  className={`px-2.5 py-1 text-xs rounded-md font-semibold transition-all flex items-center gap-1 ${
                    settings.tts_emotion_mode !== "manual" ? "bg-[#5865f2] text-white shadow-sm" : "text-[#949ba4] hover:text-[#dbdee1]"
                  }`}
                >
                  <Sparkles size={11} /> Smart Mood
                </button>
                <button
                  type="button"
                  onClick={() => onChange("tts_emotion_mode", "manual")}
                  className={`px-2.5 py-1 text-xs rounded-md font-semibold transition-all ${
                    settings.tts_emotion_mode === "manual" ? "bg-[#5865f2] text-white shadow-sm" : "text-[#949ba4] hover:text-[#dbdee1]"
                  }`}
                >
                  Manual Sliders
                </button>
              </div>
            </div>

            {settings.tts_emotion_mode !== "manual" ? (
              <div className="p-3 bg-[#141517] rounded-lg border border-[#2b2d31] space-y-2">
                <div className="flex items-center gap-2">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#57f287] opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-[#57f287]"></span>
                  </span>
                  <span className="text-xs font-semibold text-[#57f287]">Smart Emotions Active</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-[#5865f2]/20 text-[#8ce8a2] font-mono ml-auto">
                    Live Reactive
                  </span>
                </div>
                <p className="text-[11px] text-[#949ba4] leading-relaxed">
                  Zonos TTS dynamically infers emotional expression and vocal tone based on the AI character's live mood and conversational context.
                </p>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <span className="text-[9px] px-2 py-0.5 rounded bg-[#2b2d31] text-[#dbdee1]">Auto-Happiness on cheer</span>
                  <span className="text-[9px] px-2 py-0.5 rounded bg-[#2b2d31] text-[#dbdee1]">Auto-Sadness on remorse</span>
                  <span className="text-[9px] px-2 py-0.5 rounded bg-[#2b2d31] text-[#dbdee1]">Surprise on questions (?)</span>
                  <span className="text-[9px] px-2 py-0.5 rounded bg-[#2b2d31] text-[#dbdee1]">Energy on exclamations (!)</span>
                </div>
              </div>
            ) : (
              <div className="space-y-2.5">
                <p className="text-[11px] text-[#949ba4]">
                  Manual override: Fix static emotional weights across all spoken dialogue.
                </p>
                {emotionSliders.map(({ key, label, min, max, step, color }) => (
                  <div key={key}>
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[10px] text-[#949ba4] uppercase font-semibold">{label}</span>
                      <span className="font-mono text-[#dbdee1] text-[11px]">{Number(settings[key] ?? 0).toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      min={min}
                      max={max}
                      step={step}
                      value={settings[key] ?? min}
                      onChange={(e) => onChange(key, parseFloat(e.target.value))}
                      className="w-full h-1.5 mt-1 rounded-full appearance-none cursor-pointer"
                      style={{ background: `linear-gradient(to right, ${color} ${(((settings[key] ?? min) - min) / (max - min)) * 100}%, #2b2d31 ${(((settings[key] ?? min) - min) / (max - min)) * 100}%)` }}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Voice Reference, Seed & Audio Testing */}
        <div className="space-y-4">
          {/* Voice Character & Cloning */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
                <Volume2 size={14} className="text-[#5865f2]" /> Voice Character & Reference
              </h4>
              <span className="text-[10px] text-[#949ba4] font-mono">{settings.tts_engine === "openrouter" ? "Hosted voice settings above" : "12 Built-in Voices"}</span>
            </div>

            {settings.tts_engine === "openrouter" && (
              <p className="text-[10px] text-[#6d6f78]">Local Zonos/Index-TTS references are kept for those engines and are not sent to OpenRouter. Configure the hosted voice in the OpenRouter panel.</p>
            )}

            <div>
              <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Voice Gender Preference</label>
              <select
                value={Number(settings.tts_voice_gender ?? 50) >= 0 ? "female" : "male"}
                onChange={(e) => onChange("tts_voice_gender", e.target.value === "female" ? 100 : -100)}
                className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] font-medium focus:outline-none focus:border-[#5865f2]"
              >
                <option value="female">Female</option>
                <option value="male">Male</option>
              </select>
              <p className="text-[10px] text-[#6d6f78] mt-1">This preference puts matching built-in voices first.</p>
            </div>

            <div>
              <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Voice in this preset</label>
              <select
                value={settings.tts_voice_ref || "en-US-AnaNeural"}
                onChange={(e) => onChange("tts_voice_ref", e.target.value)}
                className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] font-medium focus:outline-none focus:border-[#5865f2]"
              >
                {preferredVoiceGroups.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.voices.map((voice) => <option key={voice.value} value={voice.value}>{voice.label}</option>)}
                  </optgroup>
                ))}
                {settings.tts_voice_ref && !isBuiltinVoice && (
                  <optgroup label="Custom Cloned Voice">
                    <option value={settings.tts_voice_ref}>Custom Upload: {settings.tts_voice_ref.split(/[\\/]/).pop()}</option>
                  </optgroup>
                )}
              </select>
              <p className="text-[10px] text-[#6d6f78] mt-1">This is the voice or reference used by the selected TTS preset.</p>
              {settings.tts_engine === "zonos" && settings.tts_voice_ref && !isBuiltinVoice && (
                <p className="text-[10px] text-[#f0ad4e] mt-1.5">Custom Zonos reference detected: the recording determines the audible gender. The selector is preference metadata only and does not transform the audio.</p>
              )}
            </div>

            <div className="pt-1">
              <div className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold mb-1.5 flex items-center gap-1">
                <Upload size={12} /> Custom Voice Cloning Sample
              </div>
              <div className="flex gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="audio/*"
                  onChange={handleUpload}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="flex-1 py-2 rounded bg-[#141517] hover:bg-[#2b2d31] border border-[#2b2d31] text-xs font-medium text-[#dbdee1] transition-colors flex items-center justify-center gap-1.5"
                >
                  {uploading ? <Loader2 size={13} className="animate-spin text-[#5865f2]" /> : <Upload size={13} />}
                  <span>{uploading ? "Uploading sample..." : "Upload Voice File (.wav/.mp3)"}</span>
                </button>
                {settings.tts_voice_ref && !BUILTIN_TTS_VOICES.includes(settings.tts_voice_ref) && (
                  <button
                    type="button"
                    onClick={() => onChange("tts_voice_ref", "en-US-AnaNeural")}
                    className="px-2.5 py-2 rounded bg-[#141517] hover:bg-[#2b2d31] border border-[#2b2d31] text-xs text-[#f23f43]"
                    title="Reset to default voice"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Seed Configuration */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Settings2 size={14} className="text-[#57f287]" /> Generation Seed
            </h4>
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs font-medium text-[#dbdee1]">Seed Mode</span>
                <p className="text-[11px] text-[#949ba4]">
                  {settings.tts_seed_mode === "random"
                    ? "Generates a unique seed for natural vocal variety."
                    : "Uses a fixed seed for reproducible voice output."}
                </p>
              </div>
              <div className="flex bg-[#141517] p-0.5 rounded-lg border border-[#2b2d31]">
                <button
                  type="button"
                  onClick={() => onChange("tts_seed_mode", "fixed")}
                  className={`px-3 py-1 text-xs rounded-md font-semibold transition-all ${
                    settings.tts_seed_mode !== "random" ? "bg-[#5865f2] text-white shadow-sm" : "text-[#949ba4] hover:text-[#dbdee1]"
                  }`}
                >
                  Fixed
                </button>
                <button
                  type="button"
                  onClick={() => onChange("tts_seed_mode", "random")}
                  className={`px-3 py-1 text-xs rounded-md font-semibold transition-all ${
                    settings.tts_seed_mode === "random" ? "bg-[#5865f2] text-white shadow-sm" : "text-[#949ba4] hover:text-[#dbdee1]"
                  }`}
                >
                  Random
                </button>
              </div>
            </div>

            {settings.tts_seed_mode !== "random" && (
              <div>
                <div className="flex items-center justify-between">
                  <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Fixed Seed Number</label>
                  <button
                    type="button"
                    onClick={() => onChange("tts_seed", Math.floor(Math.random() * 1000000))}
                    className="flex items-center gap-1 text-[11px] text-[#5865f2] hover:text-[#eb459e] transition-colors"
                  >
                    <Shuffle size={12} /> Randomize
                  </button>
                </div>
                <input
                  type="number"
                  value={settings.tts_seed}
                  onChange={(e) => onChange("tts_seed", parseInt(e.target.value) || 0)}
                  className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]"
                />
              </div>
            )}
          </div>

          {/* Test TTS Player */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Mic size={14} className="text-[#23a55a]" /> Interactive TTS Test
            </h4>
            <textarea
              value={testText}
              onChange={(e) => setTestText(e.target.value)}
              rows={3}
              className="w-full bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2] resize-none"
            />
            <button
              onClick={handleTest}
              disabled={testing || !testText.trim()}
              className="w-full py-2.5 rounded-lg bg-[#23a55a] hover:bg-[#1a8245] text-white text-xs font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm"
            >
              {testing ? <><Loader2 size={14} className="animate-spin" /> Synthesizing Audio...</> : <><Play size={14} /> Test Audio Generation</>}
            </button>
          </div>

          {/* TTS Hardware & Engine Telemetry Card */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Gauge size={15} className="text-[#23a55a]" />
                <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider">TTS Engine Telemetry</h4>
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded bg-[#5865f2]/15 text-[#5865f2] font-semibold">
                {telemetry?.tts.device || (settings.tts_engine === "edge-tts" || settings.tts_engine === "openrouter" ? "Cloud Stream Worker" : "CUDA:0 (RTX 5070)")}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <PerfStatCard
                icon={MemoryStick}
                label="VRAM Footprint"
                value={settings.tts_engine === "edge-tts" || settings.tts_engine === "openrouter" ? "0 MB (Cloud)" : `${telemetry?.tts.vram_allocated_gb ?? (settings.tts_engine === "zonos" ? "2.1" : "1.6")} GB`}
                color="#5865f2"
              />
              <PerfStatCard
                icon={Zap}
                label="Inference Speed"
                value={telemetry?.tts.speed_multiplier ?? (settings.tts_engine === "edge-tts" || settings.tts_engine === "openrouter" ? "Hosted" : settings.tts_engine === "zonos" ? "3.4x RT" : "4.8x RT")}
                color="#fee75c"
              />
              <PerfStatCard
                icon={Activity}
                label="Latency / Stream"
                value={`~${telemetry?.tts.latency_ms ?? (settings.tts_engine === "edge-tts" || settings.tts_engine === "openrouter" ? "provider" : settings.tts_engine === "zonos" ? "175" : "135")} ms`}
                color="#23a55a"
              />
            </div>
            <div className="p-2.5 bg-[#141517] rounded border border-[#2b2d31] flex items-center justify-between text-[11px] text-[#949ba4]">
              <span>Sampling: <strong className="text-[#dbdee1] font-mono">{telemetry?.tts.sample_rate || (settings.tts_engine === "zonos" ? "44.1 kHz Hi-Fi" : settings.tts_engine === "openrouter" ? "Provider output" : "24.0 kHz")}</strong></span>
              <span>Precision: <strong className="text-[#dbdee1] font-mono">{telemetry?.tts.precision || (settings.tts_engine === "zonos" ? "BFloat16" : "FP16")}</strong></span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 5. STT (Whisper) Settings ────────────────────────────────────────

function formatDownloadBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDownloadRate(bytesPerSecond: number | null | undefined): string | null {
  if (!bytesPerSecond || bytesPerSecond <= 0) return null;
  return `${formatDownloadBytes(bytesPerSecond)}/s`;
}

function STTSettingsSection({
  settings,
  onChange,
  presets,
  onApply,
  onRename,
  onOverwrite,
  onSaveCurrent,
  onDelete,
  onDuplicate,
  onSave,
  sttModels,
  onRefreshModels,
  telemetry,
  currentPresetId,
  currentSettings: _currentSettings,
}: {
  settings: Settings;
  onChange: (k: keyof Settings, v: string | number | boolean | string[]) => void;
  presets: Preset[];
  onApply: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onOverwrite: PresetOverwriteHandler;
  onSaveCurrent: (id: string) => void;
  onDelete: (id: string) => void;
  onDuplicate: (preset: Preset) => void;
  onSave: () => void;
  sttModels: WhisperModelInfo[];
  onRefreshModels: () => void;
  telemetry: TelemetryData | null;
  currentPresetId?: string | null;
  currentSettings?: Settings | null;
}) {
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<STTDownloadStatus | null>(null);
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcriptResult, setTranscriptResult] = useState<{ text: string; language: string; duration: number } | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [sttError, setSttError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [sttRuntime, setSttRuntime] = useState<import("../types").STTRuntimeStatus | null>(null);
  const [licensePrompt, setLicensePrompt] = useState<Awaited<ReturnType<typeof fetchSTTLicense>> | null>(null);
  const [pendingLicenseModel, setPendingLicenseModel] = useState<string | null>(null);
  const [acceptingLicense, setAcceptingLicense] = useState(false);

  const refreshSTTRuntime = useCallback(() => {
    return fetchSTTRuntime().then(setSttRuntime).catch(() => setSttRuntime(null));
  }, []);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const fileTestInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void refreshSTTRuntime();
  }, [refreshSTTRuntime, settings.stt_model, settings.stt_provider]);

  useEffect(() => {
    if (sttRuntime?.installation?.status !== "installing") return;
    const timer = window.setInterval(() => { void refreshSTTRuntime(); }, 1000);
    return () => window.clearInterval(timer);
  }, [refreshSTTRuntime, sttRuntime?.installation?.status]);

  useEffect(() => {
    if (!downloadingId) return;
    let disposed = false;

    const refreshProgress = async () => {
      try {
        const status = await fetchSTTDownloadStatus(downloadingId);
        if (disposed) return;
        setDownloadProgress(status);
        void refreshSTTRuntime();

        if (status.status === "ready") {
          setDownloadingId(null);
          setDownloadMsg("Speech model is ready to use.");
          void onRefreshModels();
        } else if (status.status === "error") {
          setDownloadingId(null);
          setDownloadMsg(`Download failed: ${status.error || "Unknown download error"}`);
          void onRefreshModels();
        }
      } catch (error) {
        if (disposed) return;
        setDownloadingId(null);
        setDownloadMsg(error instanceof Error ? `Download status unavailable: ${error.message}` : "Download status unavailable.");
      }
    };

    void refreshProgress();
    const timer = window.setInterval(() => { void refreshProgress(); }, 750);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [downloadingId, onRefreshModels, refreshSTTRuntime]);

  const beginModelDownload = async (modelId: string) => {
    setDownloadingId(modelId);
    setDownloadProgress(null);
    setDownloadMsg(`Preparing ${modelId} for download...`);
    try {
      const result = await downloadSTTModel(modelId);
      if (result.download) setDownloadProgress(result.download);
      if (result.runtime_installation) {
        setSttRuntime((previous) => previous ? { ...previous, installation: result.runtime_installation } : previous);
      }
      void refreshSTTRuntime();
      if (result.status === "ready") {
        setDownloadingId(null);
        setDownloadMsg("Speech model is already downloaded and ready.");
        await onRefreshModels();
      } else {
        setDownloadMsg(`Downloading ${modelId} to the local model cache...`);
      }
    } catch (error) {
      setDownloadMsg(error instanceof Error ? `Download failed: ${error.message}` : `Download failed for ${modelId}`);
      setDownloadingId(null);
    }
  };

  const handleDownload = async (modelId: string) => {
    const selected = sttModels.find((model) => model.id === modelId);
    if (selected?.provider === "nemo_speech" && !selected.license_accepted) {
      try {
        const terms = await fetchSTTLicense(modelId);
        setPendingLicenseModel(modelId);
        setLicensePrompt(terms);
      } catch {
        setDownloadMsg("Could not load the model license. Check that the backend is running.");
      }
      return;
    }
    await beginModelDownload(modelId);
  };

  const confirmLicenseAndDownload = async () => {
    if (!licensePrompt || !pendingLicenseModel) return;
    setAcceptingLicense(true);
    try {
      await acceptSTTLicense(pendingLicenseModel);
      const modelId = pendingLicenseModel;
      setLicensePrompt(null);
      setPendingLicenseModel(null);
      await beginModelDownload(modelId);
    } catch {
      setDownloadMsg("License acceptance failed. Please try again.");
    } finally {
      setAcceptingLicense(false);
    }
  };

  const startRecording = async () => {
    setSttError(null);
    setTranscriptResult(null);
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl);
      setAudioUrl(null);
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];

      let mimeType = "";
      if (typeof MediaRecorder !== "undefined") {
        if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) mimeType = "audio/webm;codecs=opus";
        else if (MediaRecorder.isTypeSupported("audio/webm")) mimeType = "audio/webm";
        else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) mimeType = "audio/ogg;codecs=opus";
        else if (MediaRecorder.isTypeSupported("audio/mp4")) mimeType = "audio/mp4";
      }

      const mr = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mediaRecorderRef.current = mr;

      mr.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mr.onstop = async () => {
        const actualMime = mr.mimeType || mimeType || "audio/webm";
        const audioBlob = new Blob(audioChunksRef.current, { type: actualMime });
        const ext = actualMime.includes("mp4") ? "m4a" : actualMime.includes("ogg") ? "ogg" : "webm";
        
        const previewUrl = URL.createObjectURL(audioBlob);
        setAudioUrl(previewUrl);

        setIsTranscribing(true);
        try {
          const res = await transcribeAudio(audioBlob, `recording.${ext}`);
          setTranscriptResult(res);
        } catch (err: any) {
          console.error("Transcription failed", err);
          setSttError(err.message || "Whisper transcription failed.");
        } finally {
          setIsTranscribing(false);
        }

        stream.getTracks().forEach((track) => track.stop());
      };

      mr.start(250); // Slice data every 250ms
      setIsRecording(true);
      setRecordingSeconds(0);
      timerRef.current = window.setInterval(() => {
        setRecordingSeconds((prev) => prev + 1);
      }, 1000);
    } catch (err: any) {
      console.error("Microphone access error:", err);
      setSttError(err.message || "Microphone access denied or unavailable.");
    }
  };

  const stopRecording = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
    }
  };

  const handleTestFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSttError(null);
    setTranscriptResult(null);
    if (audioUrl) {
      URL.revokeObjectURL(audioUrl);
      setAudioUrl(null);
    }

    const previewUrl = URL.createObjectURL(file);
    setAudioUrl(previewUrl);

    setIsTranscribing(true);
    try {
      const res = await transcribeAudio(file, file.name);
      setTranscriptResult(res);
    } catch (err: any) {
      console.error("File transcription error:", err);
      setSttError(err.message || "Audio file transcription failed.");
    } finally {
      setIsTranscribing(false);
      if (fileTestInputRef.current) fileTestInputRef.current.value = "";
    }
  };

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm space-y-4">
      <SectionHeader
        icon={Mic}
        title="Speech-to-text / Whisper Studio"
        presetType="stt"
        presets={presets}
        onApply={onApply}
        onRename={onRename}
        onOverwrite={onOverwrite}
        onSaveCurrent={onSaveCurrent}
        onDelete={onDelete}
        onDuplicate={onDuplicate}
        onSave={onSave}
        modelKey="stt_model"
        modelValue={settings.stt_model}
        currentPresetId={currentPresetId}
        currentSettings={settings}
        showPresetActions
      />

      {downloadMsg && (
        <div className="p-3 bg-[#5865f2]/15 border border-[#5865f2]/30 rounded-lg flex items-center justify-between text-xs text-[#dbdee1]">
          <div className="flex items-center gap-2">
            <Loader2 size={14} className="animate-spin text-[#5865f2]" />
            <span>{downloadMsg}</span>
          </div>
          <button onClick={() => setDownloadMsg(null)} className="text-[#949ba4] hover:text-white"><X size={12} /></button>
        </div>
      )}

      {licensePrompt && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="stt-license-title">
          <div className="w-full max-w-lg rounded-xl border border-[#5865f2]/50 bg-[#2b2d31] p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="stt-license-title" className="text-base font-semibold text-[#f2f3f5]">Accept model license</h3>
                <p className="mt-1 text-xs text-[#949ba4]">{licensePrompt.model} · {licensePrompt.license}</p>
              </div>
              <button onClick={() => { setLicensePrompt(null); setPendingLicenseModel(null); }} className="rounded p-1 text-[#949ba4] hover:bg-[#35373c] hover:text-white" aria-label="Close license dialog"><X size={16} /></button>
            </div>
            <p className="mt-4 rounded-lg border border-[#3f4147] bg-[#1e1f22] p-3 text-sm leading-6 text-[#dbdee1]">{licensePrompt.text}</p>
            <div className="mt-4 flex items-center justify-between gap-3">
              <button onClick={() => window.open(licensePrompt.license_url, "_blank", "noopener,noreferrer")} className="text-xs text-[#8ea1ff] hover:underline">Open official license</button>
              <div className="flex gap-2">
                <button onClick={() => { setLicensePrompt(null); setPendingLicenseModel(null); }} className="rounded-lg px-3 py-2 text-xs font-semibold text-[#b5bac1] hover:bg-[#35373c]">Cancel</button>
                <button onClick={confirmLicenseAndDownload} disabled={acceptingLicense} className="flex items-center gap-2 rounded-lg bg-[#5865f2] px-3 py-2 text-xs font-semibold text-white hover:bg-[#4752c4] disabled:opacity-50">
                  {acceptingLicense && <Loader2 size={13} className="animate-spin" />} Accept and download
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column: Speech Model Library */}
        <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
           <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Mic size={14} className="text-[#5865f2]" /> Speech Model Library
            </h4>
             <span className="text-[10px] text-[#949ba4]">{sttRuntime?.provider === "nemo_speech" ? "NeMo-Speech.cpp" : "Faster-Whisper / CT2"}</span>
           </div>
           {sttRuntime?.installation?.status === "installing" && (
             <div className="flex items-center gap-2 rounded-md border border-[#5865f2]/30 bg-[#5865f2]/10 px-2.5 py-2 text-[10px] text-[#dbdee1]" aria-live="polite">
               <Loader2 size={12} className="animate-spin text-[#8ea1ff]" /> Installing NeMo-Speech.cpp runtime alongside the model…
             </div>
           )}
           {sttRuntime?.installation?.status === "error" && (
             <div className="rounded-md border border-[#ed4245]/30 bg-[#ed4245]/10 px-2.5 py-2 text-[10px] text-[#ffb4ab]" role="status">
               NeMo-Speech.cpp installation failed: {sttRuntime.installation.error || "See the launcher output for details."}
             </div>
           )}

          <div className="space-y-2 max-h-[360px] overflow-y-auto pr-1">
            {sttModels.map((m) => {
              const isSelected = settings.stt_model === m.id;
              const isDownloading = downloadingId === m.id;
              const progress = isDownloading ? downloadProgress : m.download;
              const percent = progress?.progress_percent;
              return (
                <div
                  key={m.id}
                  className={`p-3 rounded-lg border transition-all ${
                    isSelected
                      ? "bg-[#141517] border-[#5865f2] shadow-sm ring-1 ring-[#5865f2]/30"
                      : "bg-[#141517] border-[#1f2023] hover:border-[#3f4147]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-[#dbdee1]">{m.name}</span>
                        {m.downloaded || m.ready ? (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#23a55a]/15 text-[#23a55a] font-semibold flex items-center gap-1">
                            <Check size={10} /> Downloaded
                          </span>
                        ) : (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#fee75c]/15 text-[#fee75c] font-semibold">
                            Online Hub
                          </span>
                        )}
                        {m.streaming && <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#5865f2]/15 text-[#8ea1ff] font-semibold">STREAMING</span>}
                        {isSelected && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#5865f2] text-white font-semibold">
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-[#949ba4] mt-1 leading-snug">{m.description}</p>
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#dbdee1] font-mono">
                          {m.size_mb >= 1000 ? `${(m.size_mb / 1024).toFixed(1)} GB` : `${m.size_mb} MB`}
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#fee75c] font-mono">
                          {m.relative_speed} Speed
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#57f287] font-mono">
                          {m.wer} WER
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#5865f2] font-mono">
                          ~{m.vram_mb} MB VRAM
                        </span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#949ba4]">{m.languages}</span>
                        {m.license && <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#2b2d31] text-[#949ba4]">{m.license}</span>}
                      </div>
                      {isDownloading && (
                        <div className="mt-3 rounded-md border border-[#5865f2]/30 bg-[#5865f2]/10 p-2" aria-live="polite">
                          <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] text-[#dbdee1]">
                            <span className="flex min-w-0 items-center gap-1.5"><Loader2 size={11} className="shrink-0 animate-spin text-[#8ea1ff]" /> Downloading locally</span>
                            <span className="shrink-0 font-mono text-[#8ea1ff]">{percent !== null && percent !== undefined ? `${percent.toFixed(1)}%` : "Starting…"}</span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-[#141517]" role="progressbar" aria-label={`Downloading ${m.name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent ?? undefined}>
                            <div className="h-full rounded-full bg-[#5865f2] transition-[width] duration-300" style={{ width: `${Math.max(1, Math.min(100, percent ?? 2))}%` }} />
                          </div>
                          <div className="mt-1.5 flex flex-wrap justify-between gap-x-2 gap-y-0.5 text-[9px] text-[#949ba4]">
                            <span>{formatDownloadBytes(progress?.downloaded_bytes)}{progress?.total_bytes ? ` / ${formatDownloadBytes(progress.total_bytes)}` : ""}</span>
                            {formatDownloadRate(progress?.speed_bytes_per_sec) && <span>{formatDownloadRate(progress?.speed_bytes_per_sec)}</span>}
                          </div>
                        </div>
                      )}
                      {!isDownloading && progress?.status === "error" && (
                        <p className="mt-2 text-[10px] text-[#ed4245]">Previous download failed: {progress.error || "Unknown error"}. Click Download to resume.</p>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-2 mt-2.5 pt-2 border-t border-[#1f2023]">
                    {(!(m.downloaded || m.ready) || (m.provider === "nemo_speech" && sttRuntime?.sidecar_installed === false)) && (
                      <button
                        onClick={() => handleDownload(m.id)}
                        disabled={isDownloading}
                        className="flex items-center gap-1 px-2.5 py-1 rounded bg-[#35373c] hover:bg-[#404249] text-xs font-semibold text-[#dbdee1] transition-all disabled:opacity-50"
                      >
                        {isDownloading ? <Loader2 size={12} className="animate-spin text-[#5865f2]" /> : <Download size={12} />}
                         <span>{isDownloading ? "Downloading..." : (m.provider === "nemo_speech" && (m.downloaded || m.ready) ? "Install runtime" : "Download")}</span>
                      </button>
                    )}
                    <button
                      onClick={() => {
                        onChange("stt_model", m.id);
                        onChange("stt_provider", m.provider === "nemo_speech" ? "nemo_speech" : "faster_whisper");
                      }}
                      disabled={isSelected}
                      className={`flex items-center gap-1 px-3 py-1 rounded text-xs font-semibold transition-all ${
                        isSelected
                          ? "bg-[#5865f2]/20 text-[#5865f2] cursor-default"
                          : "bg-[#5865f2] hover:bg-[#4752c4] text-white shadow-sm"
                      }`}
                    >
                      {isSelected ? <Check size={12} /> : null}
                      <span>{isSelected ? "Selected" : "Use Model"}</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Inference Tuning & Telemetry */}
        <div className="space-y-4">
          {/* Inference & Compute Parameters */}
          <div className="space-y-3 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Sliders size={14} className="text-[#fee75c]" /> Inference & Recognition Tuning
            </h4>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Compute Device</label>
                <select
                  value={settings.stt_device || "auto"}
                  onChange={(e) => onChange("stt_device", e.target.value)}
                  className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
                >
                  <option value="auto">Auto (CUDA RTX 5070 Preferred)</option>
                  <option value="cuda">CUDA GPU Acceleration</option>
                  <option value="cpu">CPU (Multi-threaded)</option>
                </select>
              </div>

              <div>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Precision Format</label>
                <select
                  value={settings.stt_compute_type || "float16"}
                  onChange={(e) => onChange("stt_compute_type", e.target.value)}
                  className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
                >
                  <option value="float16">Float16 (CUDA Fast)</option>
                  <option value="int8_float16">Int8 / Float16 (Balanced)</option>
                  <option value="int8">Int8 (Quantized CPU)</option>
                  <option value="float32">Float32 (Studio Full)</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Live streaming chunk</label>
                <select
                  value={settings.stt_stream_chunk_ms || 320}
                  onChange={(e) => onChange("stt_stream_chunk_ms", parseInt(e.target.value, 10))}
                  className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
                >
                  {[80, 160, 320, 560, 1120].map((ms) => <option key={ms} value={ms}>{ms} ms ({ms <= 160 ? "low latency" : ms === 320 ? "balanced" : "higher accuracy"})</option>)}
                </select>
              </div>
              <div className="flex items-end">
                <button
                  onClick={() => onChange("stt_streaming_enabled", !settings.stt_streaming_enabled)}
                  className={`w-full px-3 py-2 rounded border text-xs font-semibold ${settings.stt_streaming_enabled ? "border-[#23a55a]/50 bg-[#23a55a]/15 text-[#57f287]" : "border-[#3f4147] text-[#949ba4]"}`}
                >
                  {settings.stt_streaming_enabled ? "Live streaming enabled" : "Live streaming disabled"}
                </button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Spoken Language</label>
                <select
                  value={settings.stt_language || "en"}
                  onChange={(e) => onChange("stt_language", e.target.value)}
                  className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
                >
                  <option value="auto">Auto-Detect Language</option>
                  <option value="en">English (en)</option>
                  <option value="ja">Japanese (日本語)</option>
                  <option value="es">Spanish (Español)</option>
                  <option value="fr">French (Français)</option>
                  <option value="de">German (Deutsch)</option>
                  <option value="zh">Chinese (中文)</option>
                </select>
              </div>

              <div>
                <div className="flex items-center justify-between">
                  <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Beam Size</label>
                  <span className="text-[11px] text-[#dbdee1] font-mono">{settings.stt_beam_size || 5}</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={1}
                  value={settings.stt_beam_size || 5}
                  onChange={(e) => onChange("stt_beam_size", parseInt(e.target.value))}
                  className="w-full h-1.5 mt-2.5 rounded-full appearance-none cursor-pointer"
                  style={{ background: `linear-gradient(to right, #5865f2 ${((settings.stt_beam_size - 1) / 9) * 100}%, #2b2d31 ${((settings.stt_beam_size - 1) / 9) * 100}%)` }}
                />
              </div>
            </div>

            {/* VAD Toggle */}
            <div className="flex items-center justify-between p-2.5 bg-[#141517] rounded-lg border border-[#1f2023]">
              <div>
                <div className="text-xs font-semibold text-[#dbdee1] flex items-center gap-1.5">
                  <Activity size={13} className="text-[#23a55a]" /> Silero Voice Activity Detector (VAD)
                </div>
                <p className="text-[10px] text-[#949ba4]">Filters silence and background noise before model inference</p>
              </div>
              <button
                onClick={() => onChange("stt_vad_filter", !settings.stt_vad_filter)}
                className={`w-10 h-5 rounded-full transition-colors relative ${
                  settings.stt_vad_filter ? "bg-[#23a55a]" : "bg-[#4e5058]"
                }`}
              >
                <div
                  className={`w-4 h-4 rounded-full bg-white transition-transform ${
                    settings.stt_vad_filter ? "translate-x-5" : "translate-x-1"
                  }`}
                />
              </button>
            </div>
          </div>

          {/* STT Hardware Telemetry */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Gauge size={15} className="text-[#23a55a]" />
                <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider">STT Engine Telemetry</h4>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#5865f2]/15 text-[#5865f2] font-semibold">
                  {sttRuntime?.device || telemetry?.stt?.device || "CUDA:0 (RTX 5070)"}
                </span>
                <button onClick={() => void refreshSTTRuntime()} className="rounded p-1 text-[#949ba4] hover:bg-[#35373c] hover:text-white" title="Refresh speech runtime status" aria-label="Refresh speech runtime status"><RefreshCw size={12} /></button>
              </div>
            </div>
            <div className="flex items-center justify-between text-[11px] text-[#949ba4]">
              <span>Runtime: <strong className="text-[#dbdee1]">{sttRuntime?.provider === "nemo_speech" ? "NeMo-Speech.cpp" : "Faster-Whisper"}</strong></span>
              <span className={sttRuntime?.ready ? "text-[#57f287]" : sttRuntime?.fallback_active ? "text-[#57f287]" : "text-[#fee75c]"}>{sttRuntime?.ready ? "Ready" : sttRuntime?.fallback_active ? "Faster-Whisper fallback active" : "Waiting"}</span>
            </div>
            {sttRuntime?.error && <div className="p-2 rounded bg-[#fee75c]/10 border border-[#fee75c]/20 text-[10px] text-[#fee75c]">{sttRuntime.error}</div>}
            <div className="grid grid-cols-3 gap-2">
              <PerfStatCard
                icon={MemoryStick}
                label="VRAM Footprint"
                value={`${telemetry?.stt?.vram_allocated_mb || 500} MB`}
                color="#5865f2"
              />
              <PerfStatCard
                icon={Zap}
                label="Inference Speed"
                value={telemetry?.stt?.speed_multiplier || "16x Realtime"}
                color="#fee75c"
              />
              <PerfStatCard
                icon={Activity}
                label="Latency / Sec Audio"
                value={telemetry?.stt?.latency_per_sec || "~28 ms/s"}
                color="#23a55a"
              />
            </div>
            <div className="p-2.5 bg-[#141517] rounded border border-[#2b2d31] flex items-center justify-between text-[11px] text-[#949ba4]">
              <span>Model WER: <strong className="text-[#57f287] font-mono">{telemetry?.stt?.wer || "8.1%"}</strong></span>
              <span>Compute: <strong className="text-[#dbdee1] font-mono">{telemetry?.stt?.compute_type?.toUpperCase() || "FLOAT16"}</strong></span>
            </div>
          </div>

          {/* Interactive STT Tester */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
                <Radio size={14} className="text-[#eb459e]" /> Live Speech-to-Text Test
              </h4>
              {isRecording && (
                <span className="flex items-center gap-1 text-[11px] text-[#f23f43] font-semibold animate-pulse">
                  <span className="w-2 h-2 rounded-full bg-[#f23f43]" /> Recording ({recordingSeconds}s)
                </span>
              )}
            </div>

            {sttError && (
              <div className="p-2.5 bg-[#f23f43]/15 border border-[#f23f43]/30 rounded-lg text-xs text-[#f23f43] flex items-center justify-between">
                <span>{sttError}</span>
                <button onClick={() => setSttError(null)}><X size={12} /></button>
              </div>
            )}

            {transcriptResult ? (
              <div className="p-3 bg-[#141517] border border-[#2b2d31] rounded-lg space-y-2">
                <div className="text-xs font-medium text-[#dbdee1] leading-relaxed">
                  "{transcriptResult.text}"
                </div>
                <div className="flex items-center justify-between text-[10px] text-[#949ba4] pt-1 border-t border-[#1f2023]">
                  <span>Lang: <strong className="text-[#dbdee1] font-mono">{transcriptResult.language}</strong></span>
                  <span>Audio: <strong className="text-[#dbdee1] font-mono">{transcriptResult.duration?.toFixed(1)}s</strong></span>
                </div>
              </div>
            ) : (
              <div className="p-3 bg-[#141517] border border-[#1f2023] rounded-lg text-center text-xs text-[#6d6f78]">
                Click "Start Voice Recording" or upload an audio file below to test instant Whisper transcription.
              </div>
            )}

            {audioUrl && (
              <div className="p-2 bg-[#141517] rounded border border-[#1f2023] flex items-center justify-between text-xs">
                <span className="text-[#949ba4] text-[11px]">Audio Preview:</span>
                <audio src={audioUrl} controls className="h-7 max-w-[200px]" />
              </div>
            )}

            <div className="space-y-2">
              <div className="flex gap-2">
                {!isRecording ? (
                  <button
                    onClick={startRecording}
                    disabled={isTranscribing}
                    className="flex-1 py-2.5 rounded-lg bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-semibold transition-colors flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
                  >
                    <Mic size={14} /> Start Voice Recording
                  </button>
                ) : (
                  <button
                    onClick={stopRecording}
                    className="flex-1 py-2.5 rounded-lg bg-[#f23f43] hover:bg-[#da373b] text-white text-xs font-semibold transition-colors flex items-center justify-center gap-2 shadow-sm"
                  >
                    <Square size={14} /> Stop & Transcribe
                  </button>
                )}
                {isTranscribing && (
                  <div className="flex items-center gap-1.5 px-3 py-2 bg-[#141517] rounded-lg text-xs text-[#949ba4] border border-[#1f2023]">
                    <Loader2 size={13} className="animate-spin text-[#5865f2]" />
                    <span>Transcribing...</span>
                  </div>
                )}
              </div>

              {/* Upload file fallback test */}
              <div className="flex items-center justify-between pt-1">
                <input
                  ref={fileTestInputRef}
                  type="file"
                  accept="audio/*"
                  onChange={handleTestFileUpload}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileTestInputRef.current?.click()}
                  disabled={isRecording || isTranscribing}
                  className="w-full py-1.5 bg-[#141517] hover:bg-[#2b2d31] border border-[#2b2d31] rounded text-[11px] text-[#949ba4] hover:text-[#dbdee1] flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                >
                  <Upload size={12} /> Test with Audio File (.wav/.mp3/.m4a/.webm)
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 6. Avatar & Live2D Studio Section ────────────────────────────────

function AvatarSettingsSection({ settings, onChange, presets, onApply, onRename, onOverwrite, onSaveCurrent, onDelete, onDuplicate, onSave, currentPresetId }: {
  settings: Settings;
  onChange: (k: keyof Settings, v: string | number | boolean | string[]) => void;
  presets: Preset[];
  onApply: (id: string) => void;
  onRename: (id: string, name: string) => void;
  onOverwrite: PresetOverwriteHandler;
  onSaveCurrent: (id: string) => void;
  onDelete: (id: string) => void;
  onDuplicate: (preset: Preset) => void;
  onSave: () => void;
  currentPresetId?: string | null;
}) {
  const [testExpression, setTestExpression] = useState<string>("neutral");
  const [lipSyncTestText, setLipSyncTestText] = useState(
    "Hello! This is a real Live2D lip sync test. How does my voice sound?",
  );
  const [lipSyncPreviewAudio, setLipSyncPreviewAudio] = useState<HTMLAudioElement | null>(null);
  const [lipSyncPreviewPhase, setLipSyncPreviewPhase] = useState<"idle" | "synthesizing" | "speaking">("idle");
  const [lipSyncPreviewError, setLipSyncPreviewError] = useState<string | null>(null);
  const lipSyncPreviewAudioRef = useRef<HTMLAudioElement | null>(null);
  const lipSyncPreviewUrlRef = useRef<string | null>(null);
  const lipSyncPreviewRequestRef = useRef(0);
  const smartExpressionsEnabled = settings.avatar_smart_expressions !== false;
  const avatarAction = useAppStore((s) => s.avatarAction);
  const setChatEmotion = useAppStore((s) => s.setChatEmotion);
  const setExpressiveLabel = useAppStore((s) => s.setExpressiveLabel);
  const setAvatarAction = useAppStore((s) => s.setAvatarAction);
  const installedModel = findLive2DModel(settings.avatar_model);
  const selectedIdlePreset = getLive2DIdlePreset(settings.avatar_idle_preset);
  const idleIntensity = Math.min(2, Math.max(0.25, settings.avatar_idle_intensity ?? 1));

  const releaseLipSyncPreview = useCallback((updateUi = true) => {
    const audio = lipSyncPreviewAudioRef.current;
    if (audio) {
      audio.onended = null;
      audio.onerror = null;
      audio.pause();
      lipSyncPreviewAudioRef.current = null;
    }
    if (lipSyncPreviewUrlRef.current) {
      URL.revokeObjectURL(lipSyncPreviewUrlRef.current);
      lipSyncPreviewUrlRef.current = null;
    }
    if (updateUi) {
      setLipSyncPreviewAudio(null);
      setLipSyncPreviewPhase("idle");
    }
  }, []);

  const stopLipSyncPreview = useCallback(() => {
    lipSyncPreviewRequestRef.current += 1;
    releaseLipSyncPreview();
  }, [releaseLipSyncPreview]);

  useEffect(() => () => {
    lipSyncPreviewRequestRef.current += 1;
    releaseLipSyncPreview(false);
  }, [releaseLipSyncPreview]);

  const startLipSyncPreview = async () => {
    const sentence = lipSyncTestText.trim();
    if (!sentence || lipSyncPreviewPhase !== "idle") return;

    const requestId = lipSyncPreviewRequestRef.current + 1;
    lipSyncPreviewRequestRef.current = requestId;
    releaseLipSyncPreview();
    setLipSyncPreviewError(null);
    setLipSyncPreviewPhase("synthesizing");

    try {
      // Use the same TTS endpoint and HTMLAudioElement-driven analyser as
      // channel chat. Explicit settings make unsaved voice changes previewable.
      const blob = await fetchTTS(
        sentence,
        settings.tts_voice_ref || undefined,
        settings.tts_engine || undefined,
        settings.tts_voice_ref || undefined,
      );
      if (lipSyncPreviewRequestRef.current !== requestId) return;

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      lipSyncPreviewUrlRef.current = url;
      lipSyncPreviewAudioRef.current = audio;

      const finish = () => {
        if (lipSyncPreviewAudioRef.current === audio) releaseLipSyncPreview();
      };
      audio.onended = finish;
      audio.onerror = () => {
        setLipSyncPreviewError("The generated test audio could not be played.");
        finish();
      };

      // Render the audio element into Live2D first so its production analyser
      // is connected before playback begins and the first phoneme is captured.
      setLipSyncPreviewAudio(audio);
      setLipSyncPreviewPhase("speaking");
      await new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => window.requestAnimationFrame(() => resolve()));
      });
      if (lipSyncPreviewRequestRef.current !== requestId) return;
      await audio.play();
    } catch (error) {
      if (lipSyncPreviewRequestRef.current !== requestId) return;
      releaseLipSyncPreview();
      setLipSyncPreviewError(error instanceof Error ? error.message : "The TTS lip sync test failed.");
    }
  };

  const expressions = [
    { id: "neutral", label: "Neutral", icon: Eye, color: "#949ba4" },
    { id: "happy", label: "Happy", icon: Heart, color: "#b5bac1" },
    { id: "blush", label: "Blush", icon: Sparkles, color: "#b5bac1" },
    { id: "angry", label: "Angry", icon: Zap, color: "#b5bac1" },
    { id: "wink", label: "Wink", icon: Eye, color: "#b5bac1" },
  ];

  const actionPreviews: Array<{ gesture: AvatarGesture; label: string; emotion: string }> = [
    { gesture: "wave", label: "Wave", emotion: "happiness" },
    { gesture: "warm_nod", label: "Nod", emotion: "confidence" },
    { gesture: "firm_shake", label: "Shake", emotion: "frustration" },
    { gesture: "bow", label: "Bow", emotion: "confidence" },
    { gesture: "dance", label: "Dance", emotion: "excitement" },
    { gesture: "laugh", label: "Laugh", emotion: "happiness" },
  ];

  const previewExpression = (id: string) => {
    setTestExpression(id);
    const preset = {
      neutral: { emotion: "curiosity", expressive: null },
      happy: { emotion: "happiness", expressive: null },
      blush: { emotion: "happiness", expressive: "blushing" },
      angry: { emotion: "anger", expressive: "yelling" },
      wink: { emotion: "confidence", expressive: null },
    }[id] ?? { emotion: "curiosity", expressive: null };
    setChatEmotion(preset.emotion);
    setExpressiveLabel(preset.expressive);
    if (id === "wink") {
      setAvatarAction({ emotion: preset.emotion, gesture: "wink", intensity: 0.65, hold_ms: 900 });
    }
  };

  const previewAction = (gesture: AvatarGesture, emotion: string) => {
    setChatEmotion(emotion);
    setExpressiveLabel(gesture === "laugh" ? "laughing" : null);
    setAvatarAction({ emotion, gesture, intensity: 0.7, hold_ms: gesture === "dance" ? 2400 : 1500 });
  };

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm space-y-4">
      <div className="flex items-center gap-2 pb-3 border-b border-[#1f2023]">
        <div className="p-1.5 rounded bg-[#eb459e]/15 text-[#eb459e]">
          <Palette size={18} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[#dbdee1]">Avatar & Live2D Studio</h3>
          <p className="text-[11px] text-[#949ba4]">Configure Live2D visual model, streaming canvas, and tracking physics</p>
        </div>
      </div>
      <SectionHeader icon={Palette} title="Avatar & Live2D Studio" presetType="avatar" presets={presets} onApply={onApply} onRename={onRename} onOverwrite={onOverwrite} onSaveCurrent={onSaveCurrent} onDelete={onDelete} onDuplicate={onDuplicate} onSave={onSave} showPresetActions currentPresetId={currentPresetId} currentSettings={settings} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column: Model & Engine */}
        <div className="space-y-4 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
          <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
            <Palette size={14} className="text-[#eb459e]" /> Model & Canvas Engine
          </h4>

          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Avatar Engine Type</label>
            <select
              value={settings.avatar_provider || "live2d"}
              onChange={(e) => onChange("avatar_provider", e.target.value)}
              className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
            >
              <option value="live2d">Live2D Cubism (Shizuku / Custom Model3)</option>
              <option value="vrm">VRM 3D Avatar (Three.js)</option>
              <option value="sprite">2D Animated PNG / GIF Sprite</option>
              <option value="orb">Audio Reactive Orb Pulse</option>
            </select>
          </div>

          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Installed Live2D Model</label>
            <select
              value={installedModel?.modelPath ?? "custom"}
              onChange={(event) => {
                if (event.target.value !== "custom") onChange("avatar_model", event.target.value);
              }}
              className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
            >
              {LIVE2D_MODELS.map((model) => (
                <option key={model.id} value={model.modelPath}>
                  {model.name} ({model.edition})
                </option>
              ))}
              <option value="custom">Custom model path</option>
            </select>
            {installedModel && (
              <p className="mt-1 text-[10px] leading-relaxed text-[#949ba4]">{installedModel.description}</p>
            )}
          </div>

           <EditableField
             label="Model Resource Path / Identifier"
            value={settings.avatar_model || "/live2d/shizuku_ja/runtime/shizuku.model3.json"}
            onChange={(v) => onChange("avatar_model", v)}
             mono
           />
          <p className="-mt-2 text-[10px] leading-relaxed text-[#949ba4]">
            Use the public URL of a <code>.model3.json</code> file, for example <code>/live2d/my-model/my-model.model3.json</code>. Keep its textures, motions, expressions, and <code>.moc3</code> files in the paths referenced by that JSON.
          </p>

          <button
            type="button"
            role="switch"
            aria-checked={smartExpressionsEnabled}
            onClick={() => onChange("avatar_smart_expressions", !smartExpressionsEnabled)}
             className={`w-full rounded-lg border p-3 text-left transition-colors ${smartExpressionsEnabled ? "border-[#5865f2]/60 bg-[#5865f2]/15" : "border-[#2b2d31] bg-[#141517] hover:border-[#3f4147]"}`}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold text-[#dbdee1]">
                   <Sparkles size={14} className={smartExpressionsEnabled ? "text-[#8ea1ff]" : "text-[#949ba4]"} />
                  Smart emotions for Live2D
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-[#949ba4]">
                  Let chat emotion, expressive labels, speaking, and idle motion drive facial actions automatically.
                </p>
              </div>
               <span className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${smartExpressionsEnabled ? "bg-[#5865f2]" : "bg-[#4e5058]"}`}>
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${smartExpressionsEnabled ? "translate-x-4" : "translate-x-0.5"}`} />
              </span>
            </div>
             <div className={`mt-2 text-[10px] font-semibold uppercase tracking-wider ${smartExpressionsEnabled ? "text-[#8ea1ff]" : "text-[#949ba4]"}`}>
              {smartExpressionsEnabled ? "Enabled by default" : "Manual expression deck only"}
            </div>
          </button>

          <div className="rounded-lg border border-[#2b2d31] bg-[#141517] p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2 text-xs font-semibold text-[#dbdee1]">
                  <Activity size={14} className="text-[#57f287]" />
                  Idle animation preset
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-[#949ba4]">
                  Controls autonomous breathing, gaze, head drift, posture, fidget frequency, and larger idle variations.
                </p>
              </div>
              <span className="shrink-0 rounded bg-[#57f287]/10 px-2 py-1 text-[9px] font-semibold uppercase tracking-wider text-[#57f287]">
                {selectedIdlePreset.energy} energy
              </span>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {LIVE2D_IDLE_PRESETS.map((preset) => {
                const selected = selectedIdlePreset.id === preset.id;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => onChange("avatar_idle_preset", preset.id)}
                    className={`rounded-lg border p-2.5 text-left transition-colors ${
                      selected
                        ? "border-[#57f287]/70 bg-[#57f287]/10"
                        : "border-[#2b2d31] bg-[#1e1f22] hover:border-[#4e5058] hover:bg-[#232428]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`text-[11px] font-semibold ${selected ? "text-[#b8f5cd]" : "text-[#dbdee1]"}`}>
                        {preset.shortLabel}
                      </span>
                      {selected && <Check size={12} className="shrink-0 text-[#57f287]" />}
                    </div>
                    <p className="mt-1 text-[9px] leading-relaxed text-[#949ba4]">{preset.description}</p>
                  </button>
                );
              })}
            </div>

            <div className="mt-3 rounded-lg border border-[#2b2d31] bg-[#1e1f22] p-2.5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <label htmlFor="avatar-idle-intensity" className="text-[10px] font-semibold uppercase tracking-wider text-[#b5bac1]">
                    Idle energy
                  </label>
                  <p className="mt-0.5 text-[9px] leading-relaxed text-[#6d6f78]">
                    Adjusts movement range, gaze range, animation speed, and fidget frequency together.
                  </p>
                </div>
                <span className="min-w-12 rounded bg-[#5865f2]/15 px-2 py-1 text-center text-[10px] font-semibold text-[#aab7ff]">
                  {Math.round(idleIntensity * 100)}%
                </span>
              </div>
              <input
                id="avatar-idle-intensity"
                type="range"
                min={0.25}
                max={2}
                step={0.05}
                value={idleIntensity}
                onChange={(event) => onChange("avatar_idle_intensity", Number(event.target.value))}
                className="mt-2 h-1.5 w-full cursor-pointer appearance-none rounded-full"
                style={{
                  background: `linear-gradient(to right, #5865f2 ${((idleIntensity - 0.25) / 1.75) * 100}%, #2b2d31 ${((idleIntensity - 0.25) / 1.75) * 100}%)`,
                }}
              />
              <div className="mt-1 flex justify-between text-[8px] uppercase tracking-wider text-[#5c5f66]">
                <span>Very subtle</span>
                <span>Expressive</span>
              </div>
            </div>

            <p className="mt-2 text-[9px] leading-relaxed text-[#6d6f78]">
              Hair and accessories receive secondary movement through each model’s Cubism physics whenever the preset moves the head or body. Explicit AI gestures always override idle behavior.
            </p>
          </div>

          <div className="rounded-lg border border-[#5865f2]/25 bg-[#5865f2]/5 p-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs font-semibold text-[#dbdee1]">AI animation controller</div>
              {avatarAction && <span className="rounded bg-[#5865f2]/20 px-1.5 py-0.5 text-[10px] font-mono text-[#8ea1ff]">{avatarAction.gesture}</span>}
            </div>
            <p className="mt-1 text-[10px] leading-relaxed text-[#949ba4]">
              The AI sends only safe actions — emotion, gesture, intensity, and duration. The animation layer maps them to this model’s motions and parameters, never exposing raw Cubism values to the LLM.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Canvas Background</label>
              <select className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]">
                <option value="transparent">Transparent (OBS Overlay)</option>
                <option value="chroma">Chroma Green (#00FF00)</option>
                <option value="dark">Discord Dark (#1e1f22)</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Target FPS</label>
              <select className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]">
                <option value="60">60 FPS (Smooth)</option>
                <option value="30">30 FPS (Low CPU)</option>
              </select>
            </div>
          </div>
        </div>

        {/* Right Column: Expression Deck & Motion Physics */}
        <div className="space-y-4">
          <div className="relative h-72 overflow-hidden rounded-lg border border-[#1f2023] bg-[#141517]">
            <Live2DCanvas
              idlePreset={selectedIdlePreset.id}
              idleIntensity={idleIntensity}
              idlePreview
              voiceState={
                lipSyncPreviewPhase === "speaking"
                  ? "speaking"
                  : lipSyncPreviewPhase === "synthesizing"
                    ? "processing"
                    : "idle"
              }
              audioElement={lipSyncPreviewPhase === "speaking" ? lipSyncPreviewAudio : null}
              showThinking={false}
              lipSync
            />
            <div className="pointer-events-none absolute left-2 top-2 rounded bg-black/45 px-2 py-1 text-[9px] font-semibold uppercase tracking-wider text-[#b8f5cd] backdrop-blur-sm">
              Live preview · {selectedIdlePreset.shortLabel}
            </div>
          </div>

          <form
            className="space-y-2.5 rounded-lg border border-[#1f2023] bg-[#1e1f22] p-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (lipSyncPreviewPhase === "idle") void startLipSyncPreview();
              else stopLipSyncPreview();
            }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <label htmlFor="live2d-lip-sync-test" className="text-[10px] font-semibold text-[#dbdee1]">
                  Real TTS lip sync test
                </label>
                <p className="text-[9px] text-[#6d6f78]">
                  Uses the current {settings.tts_engine || "TTS"} voice and the same audio-driven mouth system as channel chat.
                </p>
              </div>
              <span className="shrink-0 text-[9px] font-mono text-[#6d6f78]">
                {lipSyncTestText.length}/400
              </span>
            </div>
            <textarea
              id="live2d-lip-sync-test"
              value={lipSyncTestText}
              onChange={(event) => setLipSyncTestText(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  if (lipSyncPreviewPhase === "idle") void startLipSyncPreview();
                }
              }}
              rows={2}
              maxLength={400}
              placeholder="Type a sentence for the avatar to speak..."
              className="w-full resize-none rounded-md border border-[#2b2d31] bg-[#141517] px-3 py-2 text-xs text-[#dbdee1] outline-none transition-colors placeholder:text-[#5c5e66] focus:border-[#5865f2]"
            />
            <div className="flex items-center justify-between gap-3">
              <div className={`min-w-0 text-[9px] ${lipSyncPreviewError ? "text-[#ffb4ab]" : "text-[#949ba4]"}`} role={lipSyncPreviewError ? "alert" : undefined}>
                {lipSyncPreviewError
                  ? lipSyncPreviewError
                  : lipSyncPreviewPhase === "synthesizing"
                    ? "Generating the test voice..."
                    : lipSyncPreviewPhase === "speaking"
                      ? "Speaking · mouth is following the real audio amplitude"
                      : "Press Ctrl+Enter or use the button to preview speech."}
              </div>
              <button
                type="submit"
                aria-pressed={lipSyncPreviewPhase !== "idle"}
                disabled={lipSyncPreviewPhase === "idle" && !lipSyncTestText.trim()}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[10px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                  lipSyncPreviewPhase !== "idle"
                    ? "border-[#f23f43]/60 bg-[#f23f43]/10 text-[#ffb4ab] hover:bg-[#f23f43]/20"
                    : "border-[#5865f2]/50 bg-[#5865f2]/10 text-[#b8c2ff] hover:bg-[#5865f2]/20"
                }`}
              >
                {lipSyncPreviewPhase === "synthesizing" ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : lipSyncPreviewPhase === "speaking" ? (
                  <Square size={11} />
                ) : (
                  <AudioLines size={12} />
                )}
                {lipSyncPreviewPhase === "synthesizing"
                  ? "Cancel"
                  : lipSyncPreviewPhase === "speaking"
                    ? "Stop speech"
                    : "Speak & test"}
              </button>
            </div>
          </form>

          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Eye size={14} className="text-[#5865f2]" /> Expression Trigger Deck
            </h4>
            <p className="text-[11px] text-[#949ba4]">Preview manual morphs & poses. Smart emotions expands these from live chat and voice state.</p>
            <div className="grid grid-cols-3 gap-2">
              {expressions.map((exp) => {
                const Icon = exp.icon;
                const isSelected = testExpression === exp.id;
                return (
                  <button
                    key={exp.id}
                    onClick={() => previewExpression(exp.id)}
                    className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs font-medium transition-all ${
                      isSelected
                        ? "bg-[#5865f2]/20 border-[#5865f2] text-white"
                        : "bg-[#141517] border-[#1f2023] text-[#dbdee1] hover:border-[#3f4147]"
                    }`}
                  >
                    <Icon size={14} style={{ color: exp.color }} />
                    <span>{exp.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Play size={14} className="text-[#57f287]" /> Action Trigger Deck
            </h4>
            <p className="text-[11px] text-[#949ba4]">Test the same safe semantic actions the AI can emit. Each active rig picks its own closest motion.</p>
            <div className="grid grid-cols-3 gap-2">
              {actionPreviews.map((action) => (
                <button
                  key={action.gesture}
                  type="button"
                  onClick={() => previewAction(action.gesture, action.emotion)}
                  className="rounded-lg border border-[#1f2023] bg-[#141517] p-2.5 text-xs font-medium text-[#dbdee1] transition-colors hover:border-[#57f287]/70 hover:bg-[#57f287]/10"
                >
                  {action.label}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-2.5">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Sliders size={14} className="text-[#57f287]" /> Physics & Interaction Tuning
            </h4>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-[#141517] p-2.5 rounded border border-[#2b2d31]">
                <span className="text-[10px] text-[#949ba4] uppercase font-semibold">Lip-Sync Gain</span>
                <div className="text-sm font-semibold text-[#dbdee1] mt-0.5">1.2x (Active)</div>
              </div>
              <div className="bg-[#141517] p-2.5 rounded border border-[#2b2d31]">
                <span className="text-[10px] text-[#949ba4] uppercase font-semibold">Auto-Blink Rate</span>
                <div className="text-sm font-semibold text-[#dbdee1] mt-0.5">Every 3.5s</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 6. Memory & Knowledge Engine Section ─────────────────────────────

function MemorySettingsSection({ settings, onChange }: {
  settings: Settings;
  onChange: (k: keyof Settings, v: string | number | string[]) => void;
}) {
  const [searchQuery, setSearchQuery] = useState("");

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#1f2023] p-5 shadow-sm space-y-4">
      <div className="flex items-center gap-2 pb-3 border-b border-[#1f2023]">
        <div className="p-1.5 rounded bg-[#5865f2]/15 text-[#5865f2]">
          <Database size={18} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-[#dbdee1]">Memory & Knowledge Engine</h3>
          <p className="text-[11px] text-[#949ba4]">Configure short-term context buffers, episodic recall, and SQLite storage</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column: Buffer & Recall Limits */}
        <div className="space-y-4 bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023]">
          <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
            <HardDrive size={14} className="text-[#5865f2]" /> Context & Retrieval Limits
          </h4>

          <div>
            <div className="flex items-center justify-between">
              <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Max Short-Term History (Messages)</label>
              <span className="text-xs font-mono text-[#dbdee1] font-semibold">{settings.memory_max_short_term}</span>
            </div>
            <input
              type="range"
              min={2}
              max={50}
              step={2}
              value={settings.memory_max_short_term}
              onChange={(e) => onChange("memory_max_short_term", parseInt(e.target.value))}
              className="w-full h-1.5 mt-1.5 rounded-full appearance-none cursor-pointer"
              style={{ background: `linear-gradient(to right, #5865f2 ${((settings.memory_max_short_term - 2) / (50 - 2)) * 100}%, #2b2d31 ${((settings.memory_max_short_term - 2) / (50 - 2)) * 100}%)` }}
            />
            <p className="text-[10px] text-[#6d6f78] mt-1">Number of recent chat turns directly sent in prompt window</p>
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Retrieval Top-K (Memories Injected)</label>
              <span className="text-xs font-mono text-[#dbdee1] font-semibold">{settings.memory_retrieval_top_k}</span>
            </div>
            <input
              type="range"
              min={1}
              max={20}
              step={1}
              value={settings.memory_retrieval_top_k}
              onChange={(e) => onChange("memory_retrieval_top_k", parseInt(e.target.value))}
              className="w-full h-1.5 mt-1.5 rounded-full appearance-none cursor-pointer"
              style={{ background: `linear-gradient(to right, #5865f2 ${((settings.memory_retrieval_top_k - 1) / (20 - 1)) * 100}%, #2b2d31 ${((settings.memory_retrieval_top_k - 1) / (20 - 1)) * 100}%)` }}
            />
            <p className="text-[10px] text-[#6d6f78] mt-1">Top relevant episodic & semantic memories retrieved per interaction</p>
          </div>

          <div className="pt-2 border-t border-[#2b2d31] space-y-2">
            <span className="text-[10px] text-[#949ba4] uppercase font-semibold">Storage Engine</span>
            <div className="p-2.5 bg-[#141517] rounded border border-[#2b2d31] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Shield size={14} className="text-[#23a55a]" />
                <span className="text-xs text-[#dbdee1] font-mono">SQLite (WAL mode enabled)</span>
              </div>
              <span className="text-[10px] text-[#57f287] font-semibold">Active</span>
            </div>
          </div>
        </div>

        {/* Right Column: Memory Breakdown & Management */}
        <div className="space-y-4">
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-3">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <Search size={14} className="text-[#fee75c]" /> Test Memory Retrieval Query
            </h4>
            <div className="relative">
              <input
                type="text"
                placeholder="Search semantic & episodic memories..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2] pl-8"
              />
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#949ba4]" />
            </div>
            <div className="p-3 bg-[#141517] rounded border border-[#2b2d31] text-[11px] text-[#949ba4]">
              {searchQuery ? `Searching for "${searchQuery}" against vector index...` : "Type a query above to test top-K cosine relevance."}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="bg-[#1e1f22] p-4 rounded-lg border border-[#1f2023] space-y-2.5">
            <h4 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider flex items-center gap-1.5">
              <RefreshCw size={14} className="text-[#eb459e]" /> Memory Database Maintenance
            </h4>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => alert("Memory database index is synchronized.")}
                className="p-2.5 bg-[#141517] hover:bg-[#2b2d31] border border-[#2b2d31] rounded-lg text-xs text-[#dbdee1] font-medium transition-colors text-left"
              >
                <div className="font-semibold text-[11px]">Re-index Embeddings</div>
                <div className="text-[9px] text-[#949ba4]">Update vector embeddings</div>
              </button>
              <button
                onClick={() => alert("Short-term history is maintained per session.")}
                className="p-2.5 bg-[#141517] hover:bg-[#2b2d31] border border-[#2b2d31] rounded-lg text-xs text-[#dbdee1] font-medium transition-colors text-left"
              >
                <div className="font-semibold text-[11px]">Flush Short Buffer</div>
                <div className="text-[9px] text-[#949ba4]">Clear active message cache</div>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function FemaleGenderIcon({ size = 12, className = "text-[#eb459e]" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="12" cy="8" r="5" />
      <path d="M12 13v8" />
      <path d="M9 17h6" />
    </svg>
  );
}

function MaleGenderIcon({ size = 12, className = "text-[#5865f2]" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <circle cx="10" cy="14" r="5" />
      <path d="M19 5l-5.4 5.4" />
      <path d="M19 5h-5" />
      <path d="M19 5v5" />
    </svg>
  );
}

function getPresetGender(p: { name: string; data?: any }): "female" | "male" | null {
  const name = p.name.toLowerCase();
  const data = p.data || {};
  const gender = ((data.character_gender || data.user_gender || data.gender || "") as string).toLowerCase();
  if (name.includes("female") || name.includes("women") || name.includes("girl") || gender === "female") {
    return "female";
  }
  if (name.includes("male") || name.includes("man") || name.includes("boy") || gender === "male") {
    return "male";
  }
  return null;
}

function SectionHeader({ icon: Icon, title, presets, onApply, onRename, onOverwrite, onSaveCurrent, onDelete, onDuplicate, onSave, presetType, currentPresetId, currentSettings, showPresetActions = false }: {
  icon: React.ElementType; title: string; presets?: Preset[];
  onApply?: (id: string) => void; onRename?: (id: string, name: string) => void;
  onOverwrite?: PresetOverwriteHandler; onDelete?: (id: string) => void;
  onSaveCurrent?: (id: string) => void;
  onDuplicate?: (preset: Preset) => void;
  onSave?: () => void;
  presetType?: string;
  // Optional: Only show presets that target a specific model field/value
  modelKey?: keyof Settings;
  modelValue?: string | number | null;
  currentPresetId?: string | null;
  currentSettings?: Settings | null;
  showPresetActions?: boolean;
}) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [presetSearch, setPresetSearch] = useState(() => readUiPreference(`ai-vtuber:preset-menu-search:${presetType || title}`, ""));
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  useEffect(() => {
    writeUiPreference(`ai-vtuber:preset-menu-search:${presetType || title}`, presetSearch);
  }, [presetSearch, presetType, title]);

  const availablePresets = showPresetActions ? (presets ?? []) : [];
  // Keep the selected preset visible even after its model/engine field is
  // edited; that is what allows the user to save changes back to it.
  const visiblePresets = availablePresets;
  const currentPreset = currentPresetId ? visiblePresets.find((preset) => preset.id === currentPresetId) : null;
  const filteredPresets = visiblePresets.filter((preset) => preset.name.toLowerCase().includes(presetSearch.trim().toLowerCase()));

  return (
    <div className="flex flex-wrap items-start justify-between gap-3 pb-3 mb-3 border-b border-[#1f2023]">
      <div className="flex min-w-0 items-start gap-2">
        <div className="p-1.5 rounded-md bg-[#1e1f22] text-[#949ba4] border border-[#2b2d31]">
          <Icon size={16} />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-[#f2f3f5] truncate">{title}</h3>
          <p className="mt-0.5 text-[10px] text-[#6d6f78] truncate">
            {currentPreset ? `Current: ${currentPreset.name}` : visiblePresets.length ? `${visiblePresets.length} presets available` : "No saved presets yet"}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {visiblePresets.length > 0 && onApply && (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-[#1e1f22] border border-[#3f4147] hover:border-[#5865f2] text-xs text-[#dbdee1] transition-colors"
            >
              <Bookmark size={12} className="text-[#949ba4]" />
              <span>{currentPreset ? `Current: ${currentPreset.name}` : `Presets (${visiblePresets.length})`}</span>
              <ChevronDown size={12} />
            </button>
            {dropdownOpen && (
              <div className="absolute right-0 top-full mt-1 w-72 bg-[#1e1f22] border border-[#1f2023] rounded-lg shadow-xl p-1.5 z-30">
                <div className="relative mb-1.5">
                  <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6d6f78]" />
                  <input
                    value={presetSearch}
                    onChange={(event) => setPresetSearch(event.target.value)}
                    placeholder="Search presets..."
                    className="w-full rounded bg-[#141517] border border-[#2b2d31] px-8 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
                  />
                </div>
                <div className="max-h-56 overflow-y-auto">
                {filteredPresets.length === 0 ? <p className="px-2 py-3 text-xs text-[#6d6f78]">No matching presets.</p> : filteredPresets.map((p) => {
                  const gender = getPresetGender(p);
                  const isCurrent = currentPresetId && p.id === currentPresetId;
                  // Outdated if current and any key in preset.data differs from currentSettings
                  const isOutdated = isCurrent && currentSettings && Object.entries(p.data || {}).some(([k, v]) => (currentSettings as any)[k] !== v);
                  return (
                    <div key={p.id} className="flex items-center justify-between rounded px-2 py-1.5 hover:bg-[#2b2d31] transition-colors group">
                      <button
                        onClick={() => { onApply && onApply(p.id); setDropdownOpen(false); }}
                        className="flex-1 flex items-center gap-1.5 text-left text-xs text-[#dbdee1] truncate"
                      >
                        {gender === "female" && (
                          <span className="p-0.5 rounded bg-[#eb459e]/15 shrink-0" title="Female Voice Preset">
                            <FemaleGenderIcon size={11} className="text-[#eb459e]" />
                          </span>
                        )}
                        {gender === "male" && (
                          <span className="p-0.5 rounded bg-[#5865f2]/15 shrink-0" title="Male Voice Preset">
                            <MaleGenderIcon size={11} className="text-[#5865f2]" />
                          </span>
                        )}
                        <span className="truncate">{p.name}</span>
                        {isCurrent && (
                          <span className="ml-2 text-[10px] px-1 py-0.5 rounded bg-[#3f4147] text-[#dbdee1] font-semibold">CURRENT</span>
                        )}
                        {isOutdated && (
                          <span className="ml-2 text-[10px] px-1 py-0.5 rounded bg-[#f0ad4e]/20 text-[#f0ad4e] font-semibold">OUTDATED</span>
                        )}
                      </button>
                      <div className="flex items-center gap-1 opacity-100 ml-1.5">
                        {/* Keep all preset actions available regardless of whether
                            the selected preset is currently outdated. */}
                        {isCurrent && onSaveCurrent && <button onClick={() => { onSaveCurrent(p.id); setDropdownOpen(false); }} title="Save changes to current preset" aria-label="Save changes to current preset" className="p-0.5 text-[#949ba4] hover:text-[#57f287]"><Save size={11} /></button>}
                        {onOverwrite && <button onClick={() => { onOverwrite(p.id, p.name, presetType); setDropdownOpen(false); }} title="Choose a preset to overwrite" aria-label="Choose a preset to overwrite" className="p-0.5 text-[#949ba4] hover:text-[#fee75c]"><RefreshCw size={11} /></button>}
                        {onSave && <button onClick={() => { onSave(); setDropdownOpen(false); }} title="Save current draft as new preset" aria-label="Save current draft as new preset" className="p-0.5 text-[#949ba4] hover:text-[#dbdee1]"><BookmarkPlus size={11} /></button>}
                        {onRename && <button onClick={() => { onRename(p.id, p.name); setDropdownOpen(false); }} title="Rename" aria-label="Rename preset" className="p-0.5 text-[#949ba4] hover:text-[#dbdee1]"><Pencil size={11} /></button>}
                        {onDuplicate && <button onClick={() => { onDuplicate(p); setDropdownOpen(false); }} title="Duplicate" aria-label="Duplicate preset" className="p-0.5 text-[#949ba4] hover:text-white"><Copy size={11} /></button>}
                        {onDelete && <button onClick={() => { onDelete(p.id); setDropdownOpen(false); }} title="Delete" aria-label="Delete preset" className="p-0.5 text-[#949ba4] hover:text-[#f23f43]"><Trash2 size={11} /></button>}
                      </div>
                    </div>
                  );
                })}
                </div>
                <p className="px-1.5 pt-1.5 text-[10px] text-[#6d6f78]">Showing {filteredPresets.length} of {visiblePresets.length} · Scroll for more</p>
              </div>
            )}
          </div>
        )}

        {showPresetActions && currentPreset && onSaveCurrent && (
          <button
            onClick={() => onSaveCurrent(currentPreset.id)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-[#3f4147] hover:bg-[#4e5058] border border-[#5865f2]/50 text-[#f2f3f5] text-xs font-medium transition-colors"
            title="Save changes to the current preset"
          >
            <Save size={12} /> Save changes
          </button>
        )}
        {showPresetActions && onOverwrite && visiblePresets.length > 0 && (
          <button
            onClick={() => onOverwrite(currentPreset?.id ?? "", currentPreset?.name ?? "", presetType)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-[#3f4147] hover:bg-[#4e5058] border border-[#f0ad4e]/50 text-[#f0d19a] text-xs font-medium transition-colors"
            title="Choose an existing preset to overwrite with this draft"
          >
            <RefreshCw size={12} /> Overwrite
          </button>
        )}
        {showPresetActions && onSave && (
          <button
            onClick={onSave}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-semibold transition-colors shadow-sm"
            title="Save this draft as a new preset"
          >
            <BookmarkPlus size={12} /> Save as new
          </button>
        )}
      </div>
    </div>
  );
}

function EditableField({ label, value, onChange, multiline = false, mono = false }: {
  label: string; value: string; onChange: (v: string) => void; multiline?: boolean; mono?: boolean;
}) {
  return (
    <div>
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">{label}</label>
      {multiline ? (
        <textarea
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          className="w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2] resize-none"
        />
      ) : (
        <input
          type="text"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          className={`w-full mt-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2] ${mono ? "font-mono text-xs" : ""}`}
        />
      )}
    </div>
  );
}

function TagField({ label, values, onChange }: {
  label: string; values: string[]; onChange: (v: string[]) => void;
}) {
  const [input, setInput] = useState("");

  const handleAdd = () => {
    const trimmed = input.trim();
    if (trimmed && !(values || []).includes(trimmed)) {
      onChange([...(values || []), trimmed]);
      setInput("");
    }
  };

  const handleRemove = (tag: string) => {
    onChange((values || []).filter((v) => v !== tag));
  };

  return (
    <div>
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">{label}</label>
      <div className="flex flex-wrap gap-1.5 mt-1.5">
        {(values || []).map((tag) => (
          <span key={tag} className="flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-[#141517] text-xs text-[#dbdee1] border border-[#2b2d31]">
            <span>{tag}</span>
            <button onClick={() => handleRemove(tag)} className="text-[#949ba4] hover:text-[#f23f43] ml-0.5">
              <X size={11} />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2 mt-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleAdd(); } }}
          placeholder={`Add ${label.toLowerCase()} (press Enter)...`}
          className="flex-1 bg-[#141517] border border-[#1f2023] rounded px-3 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
        />
      </div>
    </div>
  );
}

function PerfStatCard({ icon: Icon, label, value, color }: {
  icon: React.ElementType; label: string; value: string; color: string;
}) {
  return (
    <div className="p-3 bg-[#141517] rounded-lg border border-[#2b2d31] text-center">
      <Icon size={16} className="mx-auto mb-1" style={{ color }} />
      <div className="text-sm font-bold text-[#dbdee1] font-mono">{value}</div>
      <div className="text-[9px] text-[#949ba4] uppercase mt-0.5 font-semibold">{label}</div>
    </div>
  );
}

function PresetOverwriteModal({ presetType, presets, initialPresetId, onConfirm, onCancel }: {
  presetType: string;
  presets: Preset[];
  initialPresetId?: string;
  onConfirm: (presetId: string) => void;
  onCancel: () => void;
}) {
  const fallbackId = presets[0]?.id ?? "";
  const preferenceKey = `ai-vtuber:overwrite-picker:${presetType}`;
  const savedTargetId = readUiPreference<string | null>(`${preferenceKey}:target`, null);
  const [selectedId, setSelectedId] = useState(() => (
    initialPresetId && presets.some((preset) => preset.id === initialPresetId)
      ? initialPresetId
      : savedTargetId && presets.some((preset) => preset.id === savedTargetId) ? savedTargetId : fallbackId
  ));
  const [search, setSearch] = useState(() => readUiPreference(`${preferenceKey}:search`, ""));
  const selectedPreset = presets.find((preset) => preset.id === selectedId);
  const filteredPresets = presets.filter((preset) => preset.name.toLowerCase().includes(search.trim().toLowerCase()));
  const typeLabel = presetType === "stt" ? "Whisper" : presetType === "llm" ? "LLM" : presetType === "tts" ? "TTS" : presetType === "avatar" ? "Avatar" : presetType === "master" ? "Master" : "User";

  useEffect(() => {
    writeUiPreference(`${preferenceKey}:target`, selectedId || null);
  }, [preferenceKey, selectedId]);

  useEffect(() => {
    writeUiPreference(`${preferenceKey}:search`, search);
  }, [preferenceKey, search]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div className="bg-[#2b2d31] border border-[#1f2023] rounded-xl shadow-2xl w-full max-w-sm p-5" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h3 className="text-sm font-semibold text-[#f2f3f5]">Overwrite {typeLabel} preset</h3>
            <p className="text-[11px] text-[#6d6f78] mt-0.5">Replace one saved preset with this draft</p>
          </div>
          <span className="shrink-0 rounded bg-[#3f4147] px-2 py-1 text-[10px] font-medium text-[#b5bac1]">{presets.length} available</span>
        </div>
        <p className="text-xs leading-relaxed text-[#949ba4] mb-4">
          Choose the existing preset that should receive your current draft. Its name and ID will stay unchanged.
        </p>
        <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Preset to overwrite</label>
        <div className="relative mt-1">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6d6f78]" />
          <input
            autoFocus
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search presets..."
            className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-8 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
          />
        </div>
        <div className="mt-2 max-h-56 overflow-y-auto rounded border border-[#1f2023] bg-[#1e1f22] p-1" role="listbox" aria-label={`${typeLabel} presets`}>
          {filteredPresets.length === 0 ? (
            <p className="px-2.5 py-3 text-xs text-[#6d6f78]">No matching presets.</p>
          ) : filteredPresets.map((preset) => (
            <button
              key={preset.id}
              type="button"
              role="option"
              aria-selected={preset.id === selectedId}
              onClick={() => setSelectedId(preset.id)}
              className={`w-full rounded px-2.5 py-2 text-left text-xs transition-colors ${preset.id === selectedId ? "bg-[#5865f2]/25 text-white" : "text-[#dbdee1] hover:bg-[#2b2d31]"}`}
            >
              <span className="block truncate">{preset.name}</span>
              {preset.id === selectedId && <span className="mt-0.5 block text-[10px] text-[#aeb8ff]">Selected target</span>}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[10px] text-[#6d6f78]">Showing {filteredPresets.length} of {presets.length} presets · Scroll for more</p>
        {selectedPreset && <p className="mt-2 text-[11px] text-[#6d6f78]">Target: {selectedPreset.name}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-3 py-1.5 rounded text-xs text-[#949ba4] hover:text-[#dbdee1]">Cancel</button>
          <button
            onClick={() => selectedId && onConfirm(selectedId)}
            disabled={!selectedId}
            className="px-4 py-1.5 rounded bg-[#f0ad4e] hover:bg-[#d99635] text-[#1e1f22] text-xs font-semibold disabled:opacity-40"
          >
            Confirm overwrite
          </button>
        </div>
      </div>
    </div>
  );
}

function CharacterProfileOverwriteModal({ profiles, initialProfileId, onConfirm, onCancel }: {
  profiles: CharacterProfile[];
  initialProfileId?: string;
  onConfirm: (profileId: string) => void;
  onCancel: () => void;
}) {
  const fallbackId = profiles[0]?.id ?? "";
  const preferenceKey = "ai-vtuber:character-overwrite-picker";
  const savedTargetId = readUiPreference<string | null>(`${preferenceKey}:target`, null);
  const [selectedId, setSelectedId] = useState(() => (
    initialProfileId && profiles.some((profile) => profile.id === initialProfileId)
      ? initialProfileId
      : savedTargetId && profiles.some((profile) => profile.id === savedTargetId) ? savedTargetId : fallbackId
  ));
  const [search, setSearch] = useState(() => readUiPreference(`${preferenceKey}:search`, ""));
  const selectedProfile = profiles.find((profile) => profile.id === selectedId);
  const filteredProfiles = profiles.filter((profile) => profile.name.toLowerCase().includes(search.trim().toLowerCase()));

  useEffect(() => {
    writeUiPreference(`${preferenceKey}:target`, selectedId || null);
  }, [selectedId]);

  useEffect(() => {
    writeUiPreference(`${preferenceKey}:search`, search);
  }, [search]);

  const confirmOverwrite = () => {
    if (!selectedId || !selectedProfile) return;
    if (window.confirm(`Replace the Markdown profile “${selectedProfile.name}” with the current draft?`)) {
      onConfirm(selectedId);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div className="bg-[#2b2d31] border border-[#1f2023] rounded-xl shadow-2xl w-full max-w-sm p-5" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-2">
          <div>
            <h3 className="text-sm font-semibold text-[#f2f3f5]">Overwrite character profile</h3>
            <p className="text-[11px] text-[#6d6f78] mt-0.5">Replace one Markdown persona with this draft</p>
          </div>
          <span className="shrink-0 rounded bg-[#3f4147] px-2 py-1 text-[10px] font-medium text-[#b5bac1]">{profiles.length} available</span>
        </div>
        <p className="text-xs leading-relaxed text-[#949ba4] mb-4">Choose the profile that should receive the current character draft. Its ID and filename stay unchanged.</p>
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6d6f78]" />
          <input
            autoFocus
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search character profiles..."
            className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-8 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
          />
        </div>
        <div className="mt-2 max-h-56 overflow-y-auto rounded border border-[#1f2023] bg-[#1e1f22] p-1" role="listbox" aria-label="Character profiles">
          {filteredProfiles.length === 0 ? (
            <p className="px-2.5 py-3 text-xs text-[#6d6f78]">No matching profiles.</p>
          ) : filteredProfiles.map((profile) => (
            <button
              key={profile.id}
              type="button"
              role="option"
              aria-selected={profile.id === selectedId}
              onClick={() => setSelectedId(profile.id)}
              className={`w-full rounded px-2.5 py-2 text-left text-xs transition-colors ${profile.id === selectedId ? "bg-[#5865f2]/25 text-white" : "text-[#dbdee1] hover:bg-[#2b2d31]"}`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate">{profile.name}</span>
                {profile.active && <span className="shrink-0 text-[10px] text-[#57f287]">ACTIVE</span>}
              </span>
              {profile.id === selectedId && <span className="mt-0.5 block text-[10px] text-[#aeb8ff]">Selected target</span>}
            </button>
          ))}
        </div>
        <p className="mt-1 text-[10px] text-[#6d6f78]">Showing {filteredProfiles.length} of {profiles.length} profiles · Scroll for more</p>
        {selectedProfile && <p className="mt-2 text-[11px] text-[#6d6f78]">Target: {selectedProfile.name}</p>}
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onCancel} className="px-3 py-1.5 rounded text-xs text-[#949ba4] hover:text-[#dbdee1]">Cancel</button>
          <button onClick={confirmOverwrite} disabled={!selectedId} className="px-4 py-1.5 rounded bg-[#f0ad4e] hover:bg-[#d99635] text-[#1e1f22] text-xs font-semibold disabled:opacity-40">Confirm overwrite</button>
        </div>
      </div>
    </div>
  );
}

function PresetModal({ mode, initialName, presetType, onConfirm, onCancel }: {
  mode: "create" | "rename"; initialName: string; presetType: string;
  onConfirm: (name: string) => void; onCancel: () => void;
}) {
  const [name, setName] = useState(initialName);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onCancel}>
      <div className="bg-[#2b2d31] border border-[#1f2023] rounded-xl shadow-2xl w-full max-w-sm p-5" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-[#dbdee1] mb-3">
          {mode === "create" ? `Save ${presetType} Preset` : "Rename Preset"}
        </h3>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && name.trim() && onConfirm(name.trim())}
          placeholder="Preset Name..."
          className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
        />
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onCancel} className="px-3 py-1.5 rounded text-xs text-[#949ba4] hover:text-[#dbdee1]">Cancel</button>
          <button onClick={() => name.trim() && onConfirm(name.trim())} disabled={!name.trim()} className="px-4 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium disabled:opacity-40">
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
