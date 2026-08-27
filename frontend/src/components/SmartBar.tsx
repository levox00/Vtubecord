import { useState, useRef, useEffect, useCallback } from "react";
import { useAppStore } from "../stores/appStore";
import { fetchSettings, updateSettings, fetchGGUFModels } from "../lib/api";
import type { Settings } from "../types";
import {
  Cpu, Volume2, Settings as SettingsIcon, X, Check, Loader2, Sparkles,
  Play, ChevronRight, Brain,
} from "lucide-react";

interface SmartBarProps {
  activeChannel: string;
}

function settingsMatch(left: Settings | null, right: Settings | null): boolean {
  return Boolean(left && right && JSON.stringify(left) === JSON.stringify(right));
}

export function SmartBar({ activeChannel }: SmartBarProps) {
  const [openPanel, setOpenPanel] = useState<string | null>(null);

  const buttons = getButtonsForChannel(activeChannel);

  if (buttons.length === 0) return null;

  return (
    <div className="flex items-center gap-1 px-1.5 relative border-r border-[#2b2d31] mr-1">
      {buttons.map((btn) => (
        <button
          key={btn.id}
          onClick={() => setOpenPanel(openPanel === btn.id ? null : btn.id)}
          title={btn.label}
          className={`p-1.5 rounded transition-colors ${
            openPanel === btn.id
              ? "text-[#f2f3f5] bg-[#3f4147]"
              : "text-[#6d6f78] hover:text-[#dbdee1] hover:bg-[#2b2d31]"
          }`}
        >
          <btn.icon size={16} />
        </button>
      ))}

      {openPanel && (
        <SmartPanel
          panelId={openPanel}
          onClose={() => setOpenPanel(null)}
        />
      )}
    </div>
  );
}

function getButtonsForChannel(channelId: string) {
  switch (channelId) {
    case "character":
      return [
        { id: "character", label: "Character AI Persona", icon: SettingsIcon },
        { id: "model", label: "LLM Model & Sampling", icon: Cpu },
        { id: "tts", label: "TTS Voice & Mood", icon: Volume2 },
      ];
    case "live":
    case "general":
    case "chat":
    default:
      return [
        { id: "model", label: "LLM Model & Sampling", icon: Cpu },
        { id: "tts", label: "TTS Voice & Mood", icon: Volume2 },
      ];
  }
}

function SmartPanel({
  panelId,
  onClose,
}: {
  panelId: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute bottom-full left-0 mb-2 w-[340px] bg-[#232428] border border-[#3a3d43] rounded-xl shadow-2xl z-50 overflow-hidden"
    >
      <div className="flex items-center justify-between px-3.5 py-2.5 border-b border-[#3a3d43] bg-[#1e1f22]">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-[#f2f3f5]">
            {panelId === "model" && "Quick LLM Model & Sampling"}
            {panelId === "tts" && "Quick TTS Voice & Mood"}
            {panelId === "character" && "Quick Character Profile"}
          </span>
        </div>
        <button onClick={onClose} className="text-[#949ba4] hover:text-[#dbdee1] p-0.5 rounded">
          <X size={14} />
        </button>
      </div>

      <div className="p-3.5 max-h-[460px] overflow-y-auto">
        {panelId === "model" && <QuickModelPanel />}
        {panelId === "tts" && <QuickTTSPanel />}
        {panelId === "character" && <QuickCharacterPanel onClose={onClose} />}
      </div>
    </div>
  );
}

// ── Quick Model Panel ────────────────────────────────────────────

function QuickModelPanel() {
  const setActiveServer = useAppStore((s) => s.setActiveServer);
  const setActiveChannel = useAppStore((s) => s.setActiveChannel);
  const sharedSettingsDraft = useAppStore((s) => s.settingsDraft);
  const sharedSettingsPersisted = useAppStore((s) => s.settingsPersisted);
  const setSharedSettingsDraft = useAppStore((s) => s.setSettingsDraft);
  const setSharedSettingsPersisted = useAppStore((s) => s.setSettingsPersisted);

  const [settings, setSettings] = useState<Settings | null>(null);
  const [ggufModels, setGgufModels] = useState<Array<{ name: string; filename: string; size_gb: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [draftDirty, setDraftDirty] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [s, g] = await Promise.all([fetchSettings(), fetchGGUFModels()]);
        if (mounted) {
          const sharedDraft = useAppStore.getState().settingsDraft;
          const initialSettings = sharedDraft ?? s;
          setSettings(initialSettings);
          if (!sharedDraft) setSharedSettingsDraft(s);
          if (!useAppStore.getState().settingsPersisted) setSharedSettingsPersisted(s);
          setGgufModels(g);
        }
      } catch (err) {
        console.error("Failed to load quick model settings:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => { mounted = false; };
  }, []);

  // Consume drafts made in the full settings page while this panel is open.
  useEffect(() => {
    if (sharedSettingsDraft && !settingsMatch(settings, sharedSettingsDraft)) {
      setSettings(sharedSettingsDraft);
    }
  }, [sharedSettingsDraft]);

  // Publish quick-panel edits so the full settings page sees them when opened.
  useEffect(() => {
    if (settings && !settingsMatch(settings, sharedSettingsDraft)) {
      setSharedSettingsDraft(settings);
    }
  }, [settings, sharedSettingsDraft, setSharedSettingsDraft]);

  useEffect(() => {
    if (settings && sharedSettingsPersisted) {
      setDraftDirty(!settingsMatch(settings, sharedSettingsPersisted));
    }
  }, [settings, sharedSettingsPersisted]);

  const saveChange = useCallback((partial: Partial<Settings>) => {
    setSavedOk(false);
    setDraftDirty(true);
    setSettings((previous) => previous ? { ...previous, ...partial } : previous);
  }, []);

  const handleSave = async () => {
    if (!settings || !draftDirty || saving) return;
    setSaving(true);
    try {
      const updated = await updateSettings(settings);
      setSettings(updated);
      setSharedSettingsDraft(updated);
      setSharedSettingsPersisted(updated);
      setDraftDirty(false);
      setSavedOk(true);
      setTimeout(() => setSavedOk(false), 2000);
    } catch (err) {
      console.error("Failed to save quick model settings:", err);
    } finally {
      setSaving(false);
    }
  };

  if (loading || !settings) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={18} className="text-[#5865f2] animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-3.5 text-xs">
      {/* Save indicator */}
      <div className="flex items-center justify-between text-[10px] text-[#949ba4] px-1">
        <span>Active Model Configuration</span>
        {saving ? (
          <span className="flex items-center gap-1 text-[#5865f2]">
            <Loader2 size={10} className="animate-spin" /> Saving...
          </span>
        ) : savedOk ? (
          <span className="flex items-center gap-1 text-[#23a55a]">
            <Check size={10} /> Saved
          </span>
        ) : draftDirty ? (
          <span className="text-[#f0ad4e]">Unsaved draft</span>
        ) : null}
        {draftDirty && <button onClick={handleSave} className="ml-auto px-2 py-0.5 rounded bg-[#5865f2] text-white font-semibold hover:bg-[#4752c4]">Save</button>}
      </div>

      {/* Model Selector */}
      <div>
        <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Active LLM Model</label>
        {ggufModels.length > 0 ? (
          <div className="mt-1.5 space-y-1 max-h-36 overflow-y-auto">
            {ggufModels.map((m) => {
              const isSelected = settings.llm_model === m.filename || settings.llm_model === m.name;
              return (
                <button
                  key={m.filename}
                  onClick={() => {
                    setSettings({ ...settings, llm_model: m.filename });
                    saveChange({ llm_model: m.filename });
                  }}
                  className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left text-xs transition-all ${
                    isSelected
                      ? "bg-[#5865f2]/15 text-[#5865f2] border border-[#5865f2]/40 font-medium"
                      : "bg-[#1e1f22] text-[#dbdee1] border border-[#1f2023] hover:border-[#3f4147]"
                  }`}
                >
                  <Brain size={13} className={isSelected ? "text-[#5865f2]" : "text-[#949ba4]"} />
                  <div className="flex-1 truncate">
                    <span className="truncate">{m.name}</span>
                    <span className="text-[10px] text-[#949ba4] ml-1.5 font-mono">({m.size_gb}GB)</span>
                  </div>
                  {isSelected && <Check size={13} className="text-[#5865f2] shrink-0" />}
                </button>
              );
            })}
          </div>
        ) : (
          <input
            type="text"
            value={settings.llm_model}
            onChange={(e) => {
              const v = e.target.value;
              setSettings({ ...settings, llm_model: v });
              saveChange({ llm_model: v });
            }}
            className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-2.5 py-1.5 text-xs text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]"
          />
        )}
      </div>

      {/* Temperature */}
      <div>
        <div className="flex items-center justify-between">
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Temperature</label>
          <span className="text-[11px] text-[#dbdee1] font-mono">{settings.llm_temperature.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min={0}
          max={2}
          step={0.05}
          value={settings.llm_temperature}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            setSettings({ ...settings, llm_temperature: v });
            saveChange({ llm_temperature: v });
          }}
          className="w-full h-1.5 mt-1 rounded-full appearance-none cursor-pointer"
          style={{
            background: `linear-gradient(to right, #f47b67 ${settings.llm_temperature * 50}%, #1e1f22 ${settings.llm_temperature * 50}%)`,
          }}
        />
        <div className="flex justify-between mt-0.5 text-[9px] text-[#6d6f78]">
          <span>Precise (0.0)</span>
          <span>Creative (2.0)</span>
        </div>
      </div>

      {/* Max Tokens */}
      <div>
        <div className="flex items-center justify-between">
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Max Response Tokens</label>
          <span className="text-[11px] text-[#dbdee1] font-mono">{settings.llm_max_tokens}</span>
        </div>
        <input
          type="range"
          min={64}
          max={4096}
          step={64}
          value={settings.llm_max_tokens}
          onChange={(e) => {
            const v = parseInt(e.target.value);
            setSettings({ ...settings, llm_max_tokens: v });
            saveChange({ llm_max_tokens: v });
          }}
          className="w-full h-1.5 mt-1 rounded-full appearance-none cursor-pointer"
          style={{
            background: `linear-gradient(to right, #5865f2 ${
              ((settings.llm_max_tokens - 64) / (4096 - 64)) * 100
            }%, #1e1f22 ${((settings.llm_max_tokens - 64) / (4096 - 64)) * 100}%)`,
          }}
        />
        <div className="flex justify-between mt-0.5 text-[9px] text-[#6d6f78]">
          <span>64</span>
          <span>4096</span>
        </div>
      </div>

      <button
        onClick={() => {
          setActiveServer("settings");
          setActiveChannel("llm-settings");
        }}
        className="w-full flex items-center justify-center gap-1 text-[11px] text-[#5865f2] hover:underline pt-2 border-t border-[#1f2023]"
      >
        <span>Open full LLM studio</span>
        <ChevronRight size={12} />
      </button>
    </div>
  );
}

// ── Quick TTS Panel ──────────────────────────────────────────────

function QuickTTSPanel() {
  const setActiveServer = useAppStore((s) => s.setActiveServer);
  const setActiveChannel = useAppStore((s) => s.setActiveChannel);
  const voiceEnabled = useAppStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useAppStore((s) => s.setVoiceEnabled);
  const sharedSettingsDraft = useAppStore((s) => s.settingsDraft);
  const sharedSettingsPersisted = useAppStore((s) => s.settingsPersisted);
  const setSharedSettingsDraft = useAppStore((s) => s.setSettingsDraft);
  const setSharedSettingsPersisted = useAppStore((s) => s.setSettingsPersisted);

  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [draftDirty, setDraftDirty] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const s = await fetchSettings();
        if (mounted) {
          const sharedDraft = useAppStore.getState().settingsDraft;
          const initialSettings = sharedDraft ?? s;
          setSettings(initialSettings);
          if (!sharedDraft) setSharedSettingsDraft(s);
          if (!useAppStore.getState().settingsPersisted) setSharedSettingsPersisted(s);
        }
      } catch (err) {
        console.error("Failed to load quick TTS settings:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    load();
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (sharedSettingsDraft && !settingsMatch(settings, sharedSettingsDraft)) {
      setSettings(sharedSettingsDraft);
    }
  }, [sharedSettingsDraft]);

  useEffect(() => {
    if (settings && !settingsMatch(settings, sharedSettingsDraft)) {
      setSharedSettingsDraft(settings);
    }
  }, [settings, sharedSettingsDraft, setSharedSettingsDraft]);

  useEffect(() => {
    if (settings && sharedSettingsPersisted) {
      setDraftDirty(!settingsMatch(settings, sharedSettingsPersisted));
    }
  }, [settings, sharedSettingsPersisted]);

  const saveChange = (partial: Partial<Settings>) => {
    setDraftDirty(true);
    setSettings((previous) => previous ? { ...previous, ...partial } : previous);
  };

  const handleSave = async () => {
    if (!settings || !draftDirty || saving) return;
    setSaving(true);
    try {
      const updated = await updateSettings(settings);
      setSettings(updated);
      setSharedSettingsDraft(updated);
      setSharedSettingsPersisted(updated);
      setDraftDirty(false);
    } catch (err) {
      console.error("Failed to save TTS settings:", err);
    } finally {
      setSaving(false);
    }
  };

  const engines = [
    { id: "zonos", name: "Zonos", color: "#5865f2", desc: "Local GPU, dynamic emotion" },
    { id: "indextts", name: "Index-TTS", color: "#9b59b6", desc: "Local GPU, reference voice" },
    { id: "edge-tts", name: "Edge-TTS", color: "#23a55a", desc: "Cloud fallback (reliable)" },
    { id: "openrouter", name: "OpenRouter TTS", color: "#57f287", desc: "Hosted Fish Audio / other models" },
  ];

  async function handleTest() {
    if (!settings || testing) return;
    setTesting(true);
    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: "Hello! I am your AI VTuber companion.",
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
    } catch {
      // silent
    } finally {
      setTesting(false);
    }
  }

  if (loading || !settings) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={18} className="text-[#5865f2] animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-3 text-xs">
      {/* Voice Output Toggle */}
      <div className="flex items-center justify-between p-2.5 rounded-lg bg-[#1e1f22] border border-[#1f2023]">
        <div>
          <span className="text-xs font-semibold text-[#dbdee1]">Voice Output</span>
          <p className="text-[10px] text-[#949ba4]">Read AI responses aloud in chat</p>
        </div>
        <button
          onClick={() => setVoiceEnabled(!voiceEnabled)}
          className={`px-3 py-1 rounded text-xs font-semibold transition-all ${
            voiceEnabled
              ? "bg-[#23a55a] text-white hover:bg-[#1a8245] shadow-sm"
              : "bg-[#35373c] text-[#949ba4] hover:text-[#dbdee1]"
          }`}
        >
          {voiceEnabled ? "Enabled" : "Disabled"}
        </button>
      </div>

      {/* Engine Selector */}
      <div>
        <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Active Voice Engine</label>
        <div className="mt-1 space-y-1">
          {engines.map((e) => {
            const isSelected = settings.tts_engine === e.id;
            return (
              <button
                key={e.id}
                onClick={() => {
                  setSettings({ ...settings, tts_engine: e.id });
                  saveChange({ tts_engine: e.id });
                }}
                className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left text-xs transition-all ${
                  isSelected
                    ? "bg-[#5865f2]/15 text-[#dbdee1] border border-[#5865f2]/40"
                    : "bg-[#1e1f22] text-[#dbdee1] border border-[#1f2023] hover:border-[#3f4147]"
                }`}
              >
                <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: e.color }} />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-xs">{e.name}</div>
                  <div className="text-[10px] text-[#949ba4] truncate">{e.desc}</div>
                </div>
                {isSelected && <Check size={13} className="text-[#5865f2] shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>

      {/* Voice field from the current TTS settings/preset */}
      <div>
        <label className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold">Voice</label>
        <select
          value={settings.tts_voice_ref || "en-US-AnaNeural"}
          onChange={(e) => {
            const v = e.target.value;
            setSettings({ ...settings, tts_voice_ref: v });
            saveChange({ tts_voice_ref: v });
          }}
          className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-2 py-1.5 text-xs text-[#dbdee1] font-medium focus:outline-none focus:border-[#5865f2]"
        >
          <optgroup label="Female Voice (♀)">
            <option value="en-US-AnaNeural">♀ Ana — Youthful (US)</option>
            <option value="en-US-JennyNeural">♀ Jenny — Warm (US)</option>
            <option value="en-GB-SoniaNeural">♀ Sonia — British (UK)</option>
            <option value="ja-JP-NanamiNeural">♀ Nanami — Anime (JP)</option>
            <option value="voices/female_sweet.wav">♀ Yuna — Sweet Melodic</option>
            <option value="voices/female_warm.wav">♀ Maya — Soft Calming</option>
            <option value="voices/female_energetic.wav">♀ Chika — Genki Idol</option>
            <option value="voices/female_refined.wav">♀ Elena — Elegant Refined</option>
          </optgroup>
          <optgroup label="Male Voice (♂)">
            <option value="en-US-GuyNeural">♂ Guy — Confident (US)</option>
            <option value="en-GB-RyanNeural">♂ Ryan — British (UK)</option>
            <option value="voices/male_hero.wav">♂ Alex — Heroic Adventurer</option>
            <option value="voices/male_deep.wav">♂ Marcus — Deep Baritone</option>
          </optgroup>
        </select>
      </div>

      {/* Smart Emotion Mode Selector */}
      <div className="p-2.5 rounded-lg bg-[#1e1f22] border border-[#1f2023] space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-[#949ba4] uppercase tracking-wider font-semibold flex items-center gap-1">
            <Sparkles size={11} className="text-[#eb459e]" /> Emotional Mode
          </span>
          <div className="flex bg-[#141517] p-0.5 rounded border border-[#2b2d31]">
            <button
              onClick={() => {
                setSettings({ ...settings, tts_emotion_mode: "smart" });
                saveChange({ tts_emotion_mode: "smart" });
              }}
              className={`px-2 py-0.5 text-[10px] rounded font-semibold transition-all ${
                settings.tts_emotion_mode !== "manual" ? "bg-[#5865f2] text-white" : "text-[#949ba4]"
              }`}
            >
              Smart Mood
            </button>
            <button
              onClick={() => {
                setSettings({ ...settings, tts_emotion_mode: "manual" });
                saveChange({ tts_emotion_mode: "manual" });
              }}
              className={`px-2 py-0.5 text-[10px] rounded font-semibold transition-all ${
                settings.tts_emotion_mode === "manual" ? "bg-[#5865f2] text-white" : "text-[#949ba4]"
              }`}
            >
              Manual
            </button>
          </div>
        </div>
        <p className="text-[10px] text-[#949ba4]">
          {settings.tts_emotion_mode !== "manual"
            ? "Voice dynamically infers emotion from AI mood & tone."
            : "Voice uses static manual slider weights."}
        </p>
      </div>

      {/* Test Voice & Full Settings buttons */}
      <div className="flex gap-2 pt-1">
        {draftDirty && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1.5 rounded-lg bg-[#23a55a] hover:bg-[#1a8245] text-white text-xs font-semibold transition-colors disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        )}
        <button
          onClick={handleTest}
          disabled={testing || saving}
          className="flex-1 py-1.5 rounded-lg bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-semibold transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5 shadow-sm"
        >
          {testing ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          <span>{testing ? "Testing..." : "Test Audio"}</span>
        </button>
        <button
          onClick={() => {
            setActiveServer("settings");
            setActiveChannel("tts-settings");
          }}
          className="px-3 py-1.5 rounded-lg bg-[#1e1f22] border border-[#1f2023] text-[#dbdee1] hover:border-[#3f4147] text-xs transition-colors"
        >
          Full Studio
        </button>
      </div>
    </div>
  );
}

// ── Quick Character Panel ────────────────────────────────────────

function QuickCharacterPanel({ onClose }: { onClose: () => void }) {
  const setActiveServer = useAppStore((s) => s.setActiveServer);
  const setActiveChannel = useAppStore((s) => s.setActiveChannel);
  const character = useAppStore((s) => s.character);

  return (
    <div className="space-y-3 text-xs">
      <div className="p-3 bg-[#1e1f22] rounded-lg border border-[#1f2023] space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-[#dbdee1]">{character?.name || "AI Character"}</span>
          <span className="text-[10px] px-2 py-0.5 rounded bg-[#23a55a]/15 text-[#23a55a] font-semibold uppercase">
            {character?.dominant_emotion || "happy"}
          </span>
        </div>
        <p className="text-[11px] text-[#949ba4] line-clamp-3">
          {character?.description || "Persistent AI companion with memory and real-time voice interaction."}
        </p>
      </div>

      <button
        onClick={() => {
          setActiveServer("settings");
          setActiveChannel("character-settings");
          onClose();
        }}
        className="w-full py-2 rounded-lg bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium transition-colors flex items-center justify-center gap-1"
      >
        <span>Open Character AI Settings</span>
        <ChevronRight size={13} />
      </button>
    </div>
  );
}
