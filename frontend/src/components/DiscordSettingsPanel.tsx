import { useState, useEffect, useRef } from "react";
import {
  Bot,
  Monitor,
  Radio,
  Loader2,
  Check,
  Server,
  Volume2,
  Hash,
  Plus,
  X,
  Users,
  ArrowUp,
  ArrowDown,
  List,
  Eye,
  Shield,
  Phone,
  PhoneOff,
  Send,
  MessageSquare,
} from "lucide-react";
import { sfxConnect, sfxDisconnect, sfxSuccess, sfxError } from "../lib/sounds";
import { useAppStore } from "../stores/appStore";
import type { DiscordVoiceInputStatus, DiscordVoiceOutputStatus } from "../types";

type DiscordMode = "client" | "bot";
type DiscordBuild = "stable" | "canary" | "ptb";
type VoiceChannelMode = "specific" | "biggest" | "lowest" | "above" | "below";
type ChannelFilterMode = "all" | "allowlist" | "blocklist";

interface DiscordSettings {
  mode: DiscordMode;
  build: DiscordBuild;
  bot_token: string;
  channel_id: string;
  voice_channel_id: string;
  command_prefix: string;
  status_text: string;
  enabled: boolean;
  server_id: string;
  auto_join_voice: boolean;
  join_message_author_voice: boolean;
  live_join_enabled?: boolean;
  live_join_follow_author: boolean;
  join_method?: "manual" | "population";
  voice_channel_mode: VoiceChannelMode;
  voice_channel_threshold: number;
  channel_mode: ChannelFilterMode;
  channel_list: string[];
  allowed_user_ids: string[];
  bridge_user_id: string;
  auto_reply: boolean;
  respond_to_every_message: boolean;
  typing_indicator: boolean;
  voice_output_enabled: boolean;
  voice_output_device_name: string;
  voice_input_enabled: boolean;
  voice_input_device_name: string;
  voice_input_chunk_ms: number;
  voice_input_silence_ms: number;
  voice_input_mirror_transcript: boolean;
  voice_input_mirror_text: boolean;
}

const DEFAULT_SETTINGS: DiscordSettings = {
  mode: "client",
  build: "stable",
  bot_token: "",
  channel_id: "",
  voice_channel_id: "",
  command_prefix: "ai!",
  status_text: "Listening...",
  enabled: false,
  server_id: "",
  auto_join_voice: false,
  join_message_author_voice: false,
  live_join_enabled: false,
  live_join_follow_author: false,
  join_method: "manual",
  voice_channel_mode: "specific",
  voice_channel_threshold: 0,
  channel_mode: "all",
  channel_list: [],
  allowed_user_ids: [],
  bridge_user_id: "",
  auto_reply: true,
  respond_to_every_message: true,
  typing_indicator: true,
  voice_output_enabled: false,
  voice_output_device_name: "CABLE-B Input",
  voice_input_enabled: false,
  voice_input_device_name: "CABLE-A Output",
  voice_input_chunk_ms: 320,
  voice_input_silence_ms: 1200,
  voice_input_mirror_transcript: false,
  voice_input_mirror_text: false,
};

const BUILD_INFO: Record<DiscordBuild, { label: string; description: string; color: string }> = {
  stable: { label: "Stable", description: "Production release — most reliable", color: "#23a55a" },
  canary: { label: "Canary", description: "Early testing — latest features, some bugs", color: "#f0b232" },
  ptb: { label: "PTB", description: "Public Test Build — preview of next release", color: "#5865f2" },
};

const VOICE_MODE_INFO: Record<VoiceChannelMode, { label: string; description: string; icon: React.ElementType }> = {
  specific: { label: "Specific Channel", description: "Join a specific voice channel by ID", icon: Hash },
  biggest: { label: "Biggest Channel", description: "Join the voice channel with the most users", icon: ArrowUp },
  lowest: { label: "Lowest Channel", description: "Join the voice channel with the fewest users", icon: ArrowDown },
  above: { label: "Above Threshold", description: "Join a channel with more users than the threshold", icon: Users },
  below: { label: "Below Threshold", description: "Join a channel with fewer users than the threshold", icon: Users },
};

const ROUTING_LABELS: Record<string, { label: string; color: string }> = {
  accepted: { label: "AI accepted", color: "text-[#23a55a]" },
  needs_prefix: { label: "Needs prefix", color: "text-[#f0b232]" },
  empty_after_prefix: { label: "Needs message", color: "text-[#f0b232]" },
  auto_reply_paused: { label: "Replies paused", color: "text-[#f0b232]" },
  prefix_disabled: { label: "Command mode disabled", color: "text-[#f0b232]" },
  ignored_user: { label: "User filtered", color: "text-[#f23f43]" },
  ignored_channel: { label: "Channel filtered", color: "text-[#f23f43]" },
};

interface DiscordSettingsPanelProps {
  channel?: string;
}

function openDiscordJoinTarget(target: string) {
  const sanitized = (target || '').trim();
  if (!sanitized) return;

  // iframe src is the most reliable way to trigger custom protocol handlers in Chromium
  try {
    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    iframe.src = sanitized;
    document.body.appendChild(iframe);
    setTimeout(() => iframe.remove(), 3000);
  } catch {
    window.location.href = sanitized;
  }
}

export function DiscordSettingsPanel({ channel }: DiscordSettingsPanelProps) {
  const [settings, setSettings] = useState<DiscordSettings>(DEFAULT_SETTINGS);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<"ok" | "err" | null>(null);
  const [joinMsg, setJoinMsg] = useState<string | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [newChannelId, setNewChannelId] = useState("");
  const [newAllowedUserId, setNewAllowedUserId] = useState("");

  // Bridge state — use store for real-time, local for REST polling
  const bridgeConnected = useAppStore((s) => s.bridgeConnected);
  const bridgeVoiceState = useAppStore((s) => s.bridgeVoiceState);
  const bridgeMessages = useAppStore((s) => s.bridgeMessages);
  const [bridgeChannels, setBridgeChannels] = useState<any[]>([]);
  const [bridgeSending, setBridgeSending] = useState(false);
  const [bridgeMsg, setBridgeMsg] = useState<string | null>(null);
  const [bridgeChatInput, setBridgeChatInput] = useState("");
  const [bridgeTargetChannel, setBridgeTargetChannel] = useState("");
  const [voiceOutputStatus, setVoiceOutputStatus] = useState<DiscordVoiceOutputStatus | null>(null);
  const [voiceInputStatus, setVoiceInputStatus] = useState<DiscordVoiceInputStatus | null>(null);
  const [voiceOutputTesting, setVoiceOutputTesting] = useState(false);
  const [voiceInputTesting, setVoiceInputTesting] = useState(false);
  const bridgeMsgEndRef = useRef<HTMLDivElement>(null);

  const update = <K extends keyof DiscordSettings>(key: K, value: DiscordSettings[K]) => {
    setSettings((s) => ({ ...s, [key]: value }));
    setSaveMsg(null);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    try {
      const payload: Record<string, unknown> = { ...settings };
      // The backend never returns the saved token. Do not erase an existing
      // bot token merely because another Discord setting was saved.
      if (!settings.bot_token.trim()) delete payload.bot_token;
      const res = await fetch("/api/integrations/discord", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const body = await res.json();
        if (body?.config) {
          const { bot_token: _maskedToken, ...savedConfig } = body.config;
          setSettings((current) => ({
            ...current,
            ...savedConfig,
            bot_token: current.bot_token,
          } as DiscordSettings));
        }
        sfxSuccess();
        setSaveMsg("ok");
      } else {
        sfxError();
        setSaveMsg("err");
      }
    } catch {
      sfxError();
      setSaveMsg("err");
    } finally {
      setSaving(false);
      setTimeout(() => setSaveMsg(null), 2000);
    }
  };

  const addChannelToList = () => {
    const id = newChannelId.trim();
    if (id && !settings.channel_list.includes(id)) {
      update("channel_list", [...settings.channel_list, id]);
      setNewChannelId("");
    }
  };

  const removeChannelFromList = (id: string) => {
    update("channel_list", settings.channel_list.filter((c) => c !== id));
  };

  const addAllowedUser = () => {
    const id = newAllowedUserId.trim();
    if (id && !settings.allowed_user_ids.includes(id)) {
      update("allowed_user_ids", [...settings.allowed_user_ids, id]);
      setNewAllowedUserId("");
    }
  };

  const removeAllowedUser = (id: string) => {
    update("allowed_user_ids", settings.allowed_user_ids.filter((userId) => userId !== id));
  };

  // Load current config on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/integrations/discord/config');
        if (!res.ok) return;
        const body = await res.json();
        if (body && body.config) {
          // merge known fields into settings, preserve local bot_token
          // (backend returns bot_token_masked, not bot_token)
          const { bot_token_masked, ...configFields } = body.config;
          setSettings((s) => ({ ...s, ...configFields } as DiscordSettings));
        }
      } catch (e) {
        // ignore — UI will show defaults
        console.error('Failed to load discord config', e);
      }
    })();
  }, []);

  // Sync config from bridge WebSocket (backend pushes config_updated events)
  const bridgeDiscordConfig = useAppStore((s) => s.bridgeDiscordConfig);
  useEffect(() => {
    if (bridgeDiscordConfig) {
      // Preserve local bot_token — backend never sends it (security)
      setSettings((s) => ({ ...s, ...bridgeDiscordConfig, bot_token: s.bot_token } as DiscordSettings));
    }
  }, [bridgeDiscordConfig]);

  // Bridge status polling — uses store setters for real-time sync
  const setStoreBridgeConnected = useAppStore((s) => s.setBridgeConnected);
  const setStoreBridgeVoiceState = useAppStore((s) => s.setBridgeVoiceState);

  useEffect(() => {
    const pollBridge = async () => {
      try {
        const res = await fetch("/api/discord/bridge/status");
        const data = await res.json();
        setStoreBridgeConnected(data.connected || false);
        if (data.connected) {
          // Fetch voice state
          const vsRes = await fetch("/api/discord/bridge/voice-state");
          const vsData = await vsRes.json();
          setStoreBridgeVoiceState(vsData);
          // Fetch channels
          const chRes = await fetch("/api/discord/bridge/channels");
          const chData = await chRes.json();
          if (chData.channels) setBridgeChannels(chData.channels);
        } else {
          setStoreBridgeVoiceState(null);
          setBridgeChannels([]);
        }
      } catch {
        setStoreBridgeConnected(false);
      }
      try {
        const statusRes = await fetch("/api/integrations/discord/voice-output/status");
        if (statusRes.ok) setVoiceOutputStatus(await statusRes.json());
      } catch {
        // Keep the last known device status visible while the backend starts.
      }
      try {
        const inputStatusRes = await fetch("/api/integrations/discord/voice-input/status");
        if (inputStatusRes.ok) setVoiceInputStatus(await inputStatusRes.json());
      } catch {
        // Keep the last known capture status visible while the backend starts.
      }
    };
    pollBridge();
    const interval = setInterval(pollBridge, 5000);
    return () => clearInterval(interval);
  }, []);

  // Status page
  if (channel === "discord-status") {
    return (
      <div className="flex flex-col h-full p-5 overflow-y-auto bg-[#313338]">
        <div className="bg-[#2b2d31] rounded-xl border border-[#3a3d43] p-4 mb-3 shadow-sm">
          <div className="flex items-center gap-3 mb-4">
            <div className={`w-3 h-3 rounded-full ${settings.enabled ? "bg-[#23a55a]" : "bg-[#f23f43]"}`} />
            <h3 className="text-sm font-semibold text-white">{settings.enabled ? "Connected" : "Disconnected"}</h3>
          </div>
          <div className="space-y-3">
            <StatusRow label="Mode" value={settings.mode === "client" ? "Client (self-bot)" : "Bot Token"} />
            {settings.mode === "client" && <StatusRow label="Build" value={BUILD_INFO[settings.build].label} />}
            <StatusRow label="Server" value={settings.server_id || "All servers"} />
            <StatusRow label="Channel" value={settings.channel_id || "All channels"} />
            <StatusRow label="Channel Filter" value={settings.channel_mode} />
            <StatusRow label="Voice Auto-Join" value={settings.auto_join_voice ? "Yes" : "No"} />
            {settings.auto_join_voice && <StatusRow label="Voice Mode" value={VOICE_MODE_INFO[settings.voice_channel_mode].label} />}
            <StatusRow label="Follow Author When Idle" value={settings.join_message_author_voice ? "Yes" : "No"} />
            <StatusRow label="Follow Author On Join" value={settings.live_join_follow_author ? "Yes" : "No"} />
            <StatusRow label="Respond every message" value={settings.respond_to_every_message ? "Yes" : "No — prefix required"} />
            <StatusRow label="AI typing indicator" value={settings.typing_indicator ? "Enabled" : "Disabled"} />
            <StatusRow label="Prefix" value={settings.command_prefix || (settings.respond_to_every_message ? "Optional" : "Empty — commands disabled")} />
            <StatusRow label="Discord Voice Output" value={settings.voice_output_enabled ? "Enabled" : "Disabled"} />
            {settings.voice_output_enabled && (
              <StatusRow label="Cable Device" value={voiceOutputStatus?.device_selected?.name || "Not found"} />
            )}
            <StatusRow label="Discord Voice Transcription" value={settings.voice_input_enabled ? "Enabled" : "Disabled"} />
            {settings.voice_input_enabled && (
              <>
                <StatusRow label="Capture Device" value={voiceInputStatus?.capture?.device_selected?.name || "Not found"} />
                <StatusRow label="Capture State" value={voiceInputStatus?.capture?.state || "Idle"} />
                <StatusRow label="Queued Turns" value={String(voiceInputStatus?.queue_depth ?? 0)} />
              </>
            )}
          </div>
        </div>

        {/* Bridge Status */}
        <div className="bg-[#2b2d31] rounded-xl border border-[#3a3d43] p-4 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <Monitor size={16} className="text-[#5865f2]" />
            <h3 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider">Equicord Bridge</h3>
          </div>
          <p className="text-xs text-[#949ba4] mb-3">
            The AI VTuber Equicord plugin connects via WebSocket to let the AI control Discord directly.
          </p>
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${bridgeConnected ? "bg-[#23a55a] animate-pulse" : "bg-[#f23f43]"}`} />
              <span className="text-xs text-[#dbdee1]">{bridgeConnected ? "Connected" : "Disconnected"}</span>
            </div>
            <StatusRow label="Bridge Endpoint" value="ws://127.0.0.1:8000/api/ws/discord" />
            <StatusRow label="User ID" value={settings.bridge_user_id || "Not set (set your Discord user ID)"} />
            {bridgeVoiceState?.connected && (
              <StatusRow label="Voice Channel" value={bridgeVoiceState.channel_id} />
            )}
            <div className="mt-2 p-2 bg-[#1e1f22] rounded border border-[#1f2023]">
              <p className="text-[10px] text-[#949ba4]">
                To use the bridge: Enable the "AIBridge" plugin in Equicord Settings → Plugins,
                then set your Discord User ID above. The AI can then send messages, join voice,
                speak explicit sentences in the call, and interact with Discord through your client.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Main configuration page
  return (
    <div className="flex flex-col h-full p-5 overflow-y-auto space-y-3 bg-[#313338]">
      {/* Mode Selection */}
      <Section icon={Bot} title="Connection Mode">
        <p className="text-xs text-[#949ba4] mb-3">
          Choose how the AI connects to Discord. Client mode uses your own account (self-bot).
          Bot mode uses a dedicated bot token with more features.
        </p>
        <div className="grid grid-cols-2 gap-2">
          <ModeCard icon={Monitor} title="Client" description="Login as your account. Simpler setup." selected={settings.mode === "client"} onClick={() => update("mode", "client")} />
          <ModeCard icon={Bot} title="Bot Token" description="Use a bot token. More reliable, supports voice." selected={settings.mode === "bot"} onClick={() => update("mode", "bot")} />
        </div>
      </Section>

      {/* Build Selection (client mode only) */}
      {settings.mode === "client" && (
        <Section icon={Monitor} title="Discord Build">
          <div className="space-y-1.5">
            {(Object.keys(BUILD_INFO) as DiscordBuild[]).map((build) => {
              const info = BUILD_INFO[build];
              const selected = settings.build === build;
              return (
                <button key={build} onClick={() => update("build", build)} className={`w-full flex items-center gap-3 p-2.5 rounded-lg border transition-all ${selected ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: info.color }} />
                  <div className="flex-1 text-left">
                    <div className="text-sm text-[#dbdee1] font-medium">{info.label}</div>
                    <div className="text-[10px] text-[#949ba4]">{info.description}</div>
                  </div>
                  {selected && <Check size={16} className="text-[#5865f2]" />}
                </button>
              );
            })}
          </div>
        </Section>
      )}

      {/* Bot Token (bot mode only) */}
      {settings.mode === "bot" && (
        <Section icon={Bot} title="Bot Token">
          <p className="text-xs text-[#949ba4] mb-2">
            Create a bot at{' '}
            <a href="https://discord.com/developers/applications" target="_blank" rel="noreferrer" className="text-[#5865f2] hover:underline">discord.com/developers</a>{' '}
            and paste the token here.
          </p>
          <div className="flex items-center gap-2">
            <input type={showToken ? "text" : "password"} value={settings.bot_token} onChange={(e) => update("bot_token", e.target.value)} placeholder="Bot token..." className="flex-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
            <button onClick={() => setShowToken(!showToken)} className="px-3 py-2 rounded bg-[#1e1f22] border border-[#1f2023] text-[#949ba4] hover:text-[#dbdee1] text-xs">
              {showToken ? "Hide" : "Show"}
            </button>
          </div>
        </Section>
      )}

      {/* Server Scope */}
      <Section icon={Server} title="Server">
        <p className="text-xs text-[#949ba4] mb-2">
          Restrict the AI to a specific Discord server. Leave empty to operate in all servers the bot is in.
        </p>
        <div>
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Server ID</label>
          <input value={settings.server_id} onChange={(e) => update("server_id", e.target.value)} placeholder="123456789012345678 (empty = all servers)" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
        </div>
      </Section>

      {/* Equicord Bridge */}
      <Section icon={Monitor} title="Equicord Bridge">
        <p className="text-xs text-[#949ba4] mb-3">
          Connect the AI directly to Discord via the Equicord plugin. The AI can send messages,
          join voice channels, mute/deafen its own client during an active call, and interact with Discord without a bot token.
        </p>
        <div>
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Your Discord User ID</label>
          <input value={settings.bridge_user_id} onChange={(e) => update("bridge_user_id", e.target.value)} placeholder="123456789012345678 (your account's user ID)" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
        </div>
        <p className="text-[10px] text-[#6d6f78] mt-2">
          Find your user ID: enable Developer Mode in Discord, then right-click your username → Copy User ID.
          The AIBridge plugin must be enabled in Equicord for this to work.
        </p>
      </Section>

      {/* Desktop voice output through VB-CABLE */}
      <Section icon={Volume2} title="Discord Voice Output (VB-CABLE)">
        <p className="text-xs text-[#949ba4] mb-3">
          When enabled, AI replies received through the Equicord desktop bridge are spoken into
          Discord through the selected Windows playback device. The AI can also explicitly say a requested sentence in the call. Web UI speech remains local to the browser.
        </p>
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-sm text-[#dbdee1]">Mirror AI TTS / LLM responses to current voice chat</span>
            <p className="text-[10px] text-[#6d6f78]">Routes final AI speech through VB-CABLE when Neuro is in a voice channel.</p>
          </div>
          <button
            onClick={() => update("voice_output_enabled", !settings.voice_output_enabled)}
            className={`w-10 h-5 rounded-full transition-colors relative ${settings.voice_output_enabled ? "bg-[#23a55a]" : "bg-[#80848e]"}`}
            aria-label="Toggle Discord voice output"
          >
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.voice_output_enabled ? "left-5" : "left-0.5"}`} />
          </button>
        </div>
        <div className="space-y-2">
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Virtual playback device</label>
          <select
            value={settings.voice_output_device_name}
            onChange={(e) => update("voice_output_device_name", e.target.value)}
            className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
          >
            <option value="CABLE-B Input">CABLE-B Input (VB-Audio Cable B)</option>
            <option value="CABLE Input">CABLE Input (VB-Audio Virtual Cable)</option>
            {(voiceOutputStatus?.available_devices || []).map((device) => (
              <option key={`${device.index}-${device.name}`} value={device.name}>{device.name}</option>
            ))}
          </select>
          <p className="text-[10px] text-[#6d6f78]">
            In Discord, set the Neuro account microphone to <span className="text-[#dbdee1]">CABLE-B Output</span>.
            Keep Discord output on your normal headphones or speakers.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 mt-3 text-[10px]">
          <StatusBadge label="Device" ok={Boolean(voiceOutputStatus?.device_found)} value={voiceOutputStatus?.device_selected?.name || "Not found"} />
          <StatusBadge label="Bridge" ok={Boolean(voiceOutputStatus?.bridge_connected)} value={voiceOutputStatus?.bridge_connected ? "Connected" : "Disconnected"} />
          <StatusBadge label="Voice channel" ok={Boolean(voiceOutputStatus?.voice_connected)} value={voiceOutputStatus?.voice_connected ? "Connected" : "Not connected"} />
          <StatusBadge label="Playback" ok={Boolean(voiceOutputStatus?.playing)} value={voiceOutputStatus?.playing ? "Speaking" : "Idle"} neutral />
        </div>
        {voiceOutputStatus?.diagnostics?.next_step && voiceOutputStatus.diagnostics.reason !== "ready" && (
          <div className="mt-2 rounded border border-[#f0b232]/30 bg-[#f0b232]/10 px-2.5 py-2 text-[10px] text-[#f0b232]">
            <span className="font-semibold">Voice output not ready:</span> {voiceOutputStatus.diagnostics.next_step}
          </div>
        )}
        {voiceOutputStatus?.last_playback_error && (
          <p className="mt-2 text-[10px] text-[#f23f43]">Last playback error: {voiceOutputStatus.last_playback_error}</p>
        )}
        <button
          onClick={async () => {
            setVoiceOutputTesting(true);
            try {
              const res = await fetch("/api/integrations/discord/voice-output/test", { method: "POST" });
              const data = await res.json();
              setVoiceOutputStatus(data.status || null);
              setBridgeMsg(data.ok ? "Test audio played" : (data.error || "Voice output test failed"));
            } catch {
              setBridgeMsg("Voice output test failed");
            } finally {
              setVoiceOutputTesting(false);
              setTimeout(() => setBridgeMsg(null), 4000);
            }
          }}
          disabled={voiceOutputTesting}
          className="mt-3 px-3 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium disabled:opacity-50 flex items-center gap-2"
        >
          {voiceOutputTesting && <Loader2 size={12} className="animate-spin" />}
          {voiceOutputTesting ? "Testing..." : "Test voice output"}
        </button>
      </Section>

      {/* Discord voice input and Nemotron streaming capture */}
      <Section icon={Radio} title="Discord Voice Transcription (VB-CABLE A)">
        <p className="text-xs text-[#949ba4] mb-3">
          Capture everyone in the Discord call through the first virtual cable. Finalized
          utterances are answered one at a time; speech received while Neuro is talking is queued.
          No speaker or content filtering is applied.
        </p>
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-sm text-[#dbdee1]">Enable Discord voice transcription</span>
            <p className="text-[10px] text-[#6d6f78]">Requires a Nemotron streaming model and a connected voice channel.</p>
          </div>
          <button
            onClick={() => update("voice_input_enabled", !settings.voice_input_enabled)}
            className={`w-10 h-5 rounded-full transition-colors relative ${settings.voice_input_enabled ? "bg-[#23a55a]" : "bg-[#80848e]"}`}
            aria-label="Toggle Discord voice transcription"
          >
            <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.voice_input_enabled ? "left-5" : "left-0.5"}`} />
          </button>
        </div>
        <div className="space-y-2">
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Discord capture device</label>
          <select
            value={settings.voice_input_device_name}
            onChange={(e) => update("voice_input_device_name", e.target.value)}
            className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
          >
            <option value="CABLE-A Output">CABLE-A Output (VB-Audio Cable A)</option>
            {(voiceInputStatus?.capture?.available_devices || []).map((device) => (
              <option key={`${device.index}-${device.name}`} value={device.name}>{device.name}</option>
            ))}
          </select>
          <p className="text-[10px] text-[#6d6f78]">
            Set the Neuro Discord account's output to <span className="text-[#dbdee1]">CABLE-A Input</span>.
            The backend listens to the matching <span className="text-[#dbdee1]">CABLE-A Output</span> endpoint.
          </p>
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider block pt-1">Streaming chunk</label>
          <select
            value={settings.voice_input_chunk_ms}
            onChange={(e) => update("voice_input_chunk_ms", Number(e.target.value))}
            className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
          >
            {[80, 160, 320, 560, 1120].map((ms) => <option key={ms} value={ms}>{ms} ms</option>)}
          </select>
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider block pt-1">End-of-speech pause</label>
          <select
            value={settings.voice_input_silence_ms}
            onChange={(e) => update("voice_input_silence_ms", Number(e.target.value))}
            className="w-full bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
          >
            {[800, 1000, 1200, 1500, 1800, 2200].map((ms) => <option key={ms} value={ms}>{ms} ms</option>)}
          </select>
          <p className="text-[10px] text-[#6d6f78]">Longer pauses prevent a sentence from being split into multiple AI replies. Short endpoint fragments are merged automatically.</p>
          <label className="flex items-center gap-2 text-xs text-[#dbdee1] pt-1">
            <input type="checkbox" checked={settings.voice_input_mirror_transcript} onChange={(e) => update("voice_input_mirror_transcript", e.target.checked)} />
            Mirror Whisper transcripts to the current voice channel chat
          </label>
          <label className="flex items-center gap-2 text-xs text-[#dbdee1] pt-1">
            <input type="checkbox" checked={settings.voice_input_mirror_text} onChange={(e) => update("voice_input_mirror_text", e.target.checked)} />
            Mirror AI voice replies to the configured Discord text channel
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2 mt-3 text-[10px]">
          <StatusBadge label="Capture device" ok={Boolean(voiceInputStatus?.capture?.device_found)} value={voiceInputStatus?.capture?.device_selected?.name || "Not found"} />
          <StatusBadge label="Capture" ok={Boolean(voiceInputStatus?.capture?.running)} value={voiceInputStatus?.capture?.state || "Idle"} neutral={!voiceInputStatus?.capture?.running} />
          <StatusBadge label="Bridge" ok={Boolean(voiceInputStatus?.bridge_connected)} value={voiceInputStatus?.bridge_connected ? "Connected" : "Disconnected"} />
          <StatusBadge label="Voice channel" ok={Boolean(voiceInputStatus?.voice_connected)} value={voiceInputStatus?.voice_connected ? "Connected" : "Not connected"} />
          <StatusBadge label="Queue" ok={true} value={`${voiceInputStatus?.queue_depth ?? 0} pending`} neutral />
          <StatusBadge label="Runtime" ok={Boolean(voiceInputStatus?.runtime?.ready || voiceInputStatus?.capture?.running)} value={voiceInputStatus?.runtime?.provider || "Not ready"} neutral={!voiceInputStatus?.runtime?.ready && !voiceInputStatus?.capture?.running} />
        </div>
        {voiceInputStatus?.diagnostics?.next_step && voiceInputStatus.diagnostics.reason !== "streaming" && (
          <div className="mt-2 rounded border border-[#f0b232]/30 bg-[#f0b232]/10 px-2.5 py-2 text-[10px] text-[#f0b232]">
            <span className="font-semibold">Voice capture not ready:</span> {voiceInputStatus.diagnostics.next_step}
          </div>
        )}
        {(voiceInputStatus?.capture?.last_error || voiceInputStatus?.runtime?.error) && (
          <p className="mt-2 text-[10px] text-[#f23f43]">{voiceInputStatus.capture.last_error || voiceInputStatus.runtime?.error}</p>
        )}
        <button
          onClick={async () => {
            setVoiceInputTesting(true);
            try {
              const res = await fetch("/api/integrations/discord/voice-input/test", { method: "POST" });
              const data = await res.json();
              if (data.status) setVoiceInputStatus((current) => ({ ...(current || data.status), ...data.status }));
              setBridgeMsg(data.ok ? "Capture device is available" : (data.error || "Voice input test failed"));
            } catch {
              setBridgeMsg("Voice input test failed");
            } finally {
              setVoiceInputTesting(false);
              setTimeout(() => setBridgeMsg(null), 4000);
            }
          }}
          disabled={voiceInputTesting}
          className="mt-3 px-3 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium disabled:opacity-50 flex items-center gap-2"
        >
          {voiceInputTesting && <Loader2 size={12} className="animate-spin" />}
          {voiceInputTesting ? "Checking..." : "Test capture device"}
        </button>
      </Section>

      {/* Bridge Control Panel */}
      {bridgeConnected && (
        <Section icon={Monitor} title="Bridge Controls">
          <div className="flex items-center gap-2 mb-3 p-2 bg-[#23a55a]/10 border border-[#23a55a]/30 rounded">
            <div className="w-2 h-2 rounded-full bg-[#23a55a] animate-pulse" />
            <span className="text-xs text-[#23a55a] font-medium">Bridge Connected</span>
            <span className="text-[10px] text-[#949ba4] ml-auto">Equicord plugin active</span>
          </div>

          {/* Voice Controls */}
          <div className="mb-3">
            <h4 className="text-[10px] text-[#949ba4] uppercase tracking-wider mb-2">Voice Channel</h4>
            {bridgeVoiceState?.connected ? (
              <div className="p-2 bg-[#1e1f22] rounded border border-[#1f2023] mb-2">
                <div className="flex items-center gap-2">
                  <Volume2 size={14} className="text-[#23a55a]" />
                  <span className="text-xs text-[#dbdee1]">
                    In voice channel {bridgeVoiceState.channel_id}
                  </span>
                </div>
                {bridgeVoiceState.users?.length > 0 && (
                  <div className="mt-1 text-[10px] text-[#949ba4]">
                    {bridgeVoiceState.users.length} user(s) connected
                  </div>
                )}
              </div>
            ) : (
              <div className="p-2 bg-[#1e1f22] rounded border border-[#1f2023] mb-2">
                <span className="text-xs text-[#949ba4]">Not in voice</span>
              </div>
            )}
            <div className="flex gap-2">
              <button
                onClick={async () => {
                  setBridgeSending(true);
                  try {
                    const channelId = settings.voice_channel_id || bridgeTargetChannel;
                    if (!channelId) {
                      setBridgeMsg("Set a voice channel ID first");
                      setTimeout(() => setBridgeMsg(null), 3000);
                      return;
                    }
                    const res = await fetch("/api/discord/bridge/join-voice", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ channel_id: channelId }),
                    });
                    const data = await res.json();
                    if (data.ok) {
                      sfxConnect();
                      setBridgeMsg("Joined voice channel");
                    } else {
                      sfxError();
                      setBridgeMsg(data.error || "Failed to join");
                    }
                    setTimeout(() => setBridgeMsg(null), 3000);
                  } catch {
                    setBridgeMsg("Failed to join voice");
                    setTimeout(() => setBridgeMsg(null), 3000);
                  } finally {
                    setBridgeSending(false);
                  }
                }}
                disabled={bridgeSending}
                className="flex items-center gap-2 px-3 py-1.5 rounded bg-[#23a55a] hover:bg-[#1a8c47] text-white text-xs font-medium transition-colors disabled:opacity-50"
              >
                <Phone size={12} />
                Join Voice
              </button>
              <button
                onClick={async () => {
                  setBridgeSending(true);
                  try {
                    const res = await fetch("/api/discord/bridge/leave-voice", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                    });
                    const data = await res.json();
                    if (data.ok) {
                      sfxDisconnect();
                      setBridgeMsg("Left voice channel");
                    } else {
                      sfxError();
                      setBridgeMsg(data.error || "Failed to leave");
                    }
                    setTimeout(() => setBridgeMsg(null), 3000);
                  } catch {
                    setBridgeMsg("Failed to leave voice");
                    setTimeout(() => setBridgeMsg(null), 3000);
                  } finally {
                    setBridgeSending(false);
                  }
                }}
                disabled={bridgeSending}
                className="flex items-center gap-2 px-3 py-1.5 rounded bg-[#f23f43] hover:bg-[#d1383b] text-white text-xs font-medium transition-colors disabled:opacity-50"
              >
                <PhoneOff size={12} />
                Leave Voice
              </button>
            </div>
            {bridgeMsg && (
              <div className="mt-2 text-xs text-[#fee75c]">{bridgeMsg}</div>
            )}
          </div>

          {/* Send Message */}
          <div className="mb-3">
            <h4 className="text-[10px] text-[#949ba4] uppercase tracking-wider mb-2">Send Message</h4>
            <div className="flex gap-2">
              <select
                value={bridgeTargetChannel}
                onChange={(e) => setBridgeTargetChannel(e.target.value)}
                className="w-40 bg-[#1e1f22] border border-[#1f2023] rounded px-2 py-1.5 text-xs text-[#dbdee1] focus:outline-none focus:border-[#5865f2]"
              >
                <option value="">Select channel...</option>
                {bridgeChannels
                  .filter((ch: any) => ch.type === 0 || ch.type === 2 || ch.type === 13)
                  .map((ch: any) => (
                    <option key={ch.id} value={ch.id}>
                      #{ch.name} ({ch.type === 0 ? "text" : ch.type === 2 ? "voice" : "stage"})
                    </option>
                  ))}
              </select>
              <input
                value={bridgeChatInput}
                onChange={(e) => setBridgeChatInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && bridgeChatInput.trim() && bridgeTargetChannel) {
                    (async () => {
                      setBridgeSending(true);
                      try {
                        await fetch("/api/discord/bridge/send", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            channel_id: bridgeTargetChannel,
                            content: bridgeChatInput.trim(),
                          }),
                        });
                        setBridgeChatInput("");
                        setBridgeMsg("Message sent");
                        setTimeout(() => setBridgeMsg(null), 3000);
                      } catch {
                        setBridgeMsg("Failed to send");
                        setTimeout(() => setBridgeMsg(null), 3000);
                      } finally {
                        setBridgeSending(false);
                      }
                    })();
                  }
                }}
                placeholder="Type a message..."
                className="flex-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-1.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
              />
              <button
                onClick={async () => {
                  if (!bridgeChatInput.trim() || !bridgeTargetChannel) return;
                  setBridgeSending(true);
                  try {
                    await fetch("/api/discord/bridge/send", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        channel_id: bridgeTargetChannel,
                        content: bridgeChatInput.trim(),
                      }),
                    });
                    setBridgeChatInput("");
                    setBridgeMsg("Message sent");
                    setTimeout(() => setBridgeMsg(null), 3000);
                  } catch {
                    setBridgeMsg("Failed to send");
                    setTimeout(() => setBridgeMsg(null), 3000);
                  } finally {
                    setBridgeSending(false);
                  }
                }}
                disabled={bridgeSending || !bridgeChatInput.trim() || !bridgeTargetChannel}
                className="px-3 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium transition-colors disabled:opacity-50"
              >
                <Send size={12} />
              </button>
            </div>
          </div>

          {/* Channel List */}
          <div>
            <h4 className="text-[10px] text-[#949ba4] uppercase tracking-wider mb-2">Accessible Channels</h4>
            <div className="max-h-32 overflow-y-auto p-2 bg-[#1e1f22] rounded border border-[#1f2023]">
              {bridgeChannels.length === 0 ? (
                <span className="text-[10px] text-[#6d6f78]">No channels loaded</span>
              ) : (
                bridgeChannels
                  .filter((ch: any) => ch.type === 0 || ch.type === 2 || ch.type === 13)
                  .map((ch: any) => (
                    <div
                      key={ch.id}
                      className="flex items-center gap-2 py-0.5 cursor-pointer hover:bg-[#2b2d31] rounded px-1"
                      onClick={() => {
                        setBridgeTargetChannel(ch.id);
                        if (ch.type === 2 || ch.type === 13) {
                          update("voice_channel_id", ch.id);
                        }
                      }}
                    >
                      <Hash size={10} className="text-[#6d6f78]" />
                      <span className="text-[10px] text-[#dbdee1]">{ch.name}</span>
                      <span className="text-[8px] text-[#6d6f78] ml-auto">{ch.type === 0 ? "text" : ch.type === 2 ? "voice" : "stage"}</span>
                    </div>
                  ))
              )}
            </div>
          </div>
        </Section>
      )}

      {/* Bridge Messages — real-time Discord sync */}
      {bridgeConnected && bridgeMessages.length > 0 && (
        <Section icon={MessageSquare} title="Bridge Messages">
          <div className="max-h-48 overflow-y-auto p-2 bg-[#1e1f22] rounded border border-[#1f2023] space-y-1">
            {bridgeMessages.slice(-20).map((msg, i) => (
              <div key={i} className="flex flex-col gap-0.5 rounded px-1 py-0.5 hover:bg-[#232428]">
                <div className="flex items-start gap-2 text-[10px]">
                  <span className={msg.type === "outgoing" ? "text-[#23a55a]" : "text-[#5865f2]"}>
                    {msg.type === "outgoing" ? "AI" : msg.author.name}
                  </span>
                  <span className="text-[#6d6f78]">#{msg.channel_id}</span>
                  <span className="text-[#dbdee1] flex-1 truncate">{msg.content}</span>
                  {msg.type === "incoming" && msg.routing_status && ROUTING_LABELS[msg.routing_status] && (
                    <span
                      className={`shrink-0 ${ROUTING_LABELS[msg.routing_status].color}`}
                      title={msg.routing_detail || ROUTING_LABELS[msg.routing_status].label}
                    >
                      {ROUTING_LABELS[msg.routing_status].label}
                    </span>
                  )}
                </div>
                {msg.type === "incoming" && msg.routing_detail && (
                  <span className="pl-2 text-[9px] text-[#6d6f78]">{msg.routing_detail}</span>
                )}
              </div>
            ))}
            <div ref={bridgeMsgEndRef} />
          </div>
        </Section>
      )}

      {/* Channel Filtering */}
      <Section icon={Hash} title="Channel Filtering">
        <p className="text-xs text-[#949ba4] mb-3">
          Control which text channels the AI responds in. An empty channel list always means every channel.
        </p>

        <div className="mb-3">
          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">AI Speaking Channel ID</label>
          <input value={settings.channel_id} onChange={(e) => update("channel_id", e.target.value)} placeholder="Optional default channel for AI-initiated messages" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
          <p className="text-[10px] text-[#6d6f78] mt-1">Replies stay in their source channel. This channel is used when you tell the AI to send something to Discord from the web UI.</p>
        </div>

        <div className="space-y-1.5 mb-3">
          {([
            { id: "all" as const, label: "All Channels", description: "Respond in every channel", icon: Eye },
            { id: "allowlist" as const, label: "Allowlist", description: "Only listed channels; an empty list means all", icon: List },
            { id: "blocklist" as const, label: "Blocklist", description: "Respond everywhere except listed channels", icon: Shield },
          ]).map(({ id, label, description, icon: Icon }) => (
            <button key={id} onClick={() => update("channel_mode", id)} className={`w-full flex items-center gap-3 p-2.5 rounded-lg border transition-all ${settings.channel_mode === id ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>
              <Icon size={16} className={settings.channel_mode === id ? "text-[#5865f2]" : "text-[#949ba4]"} />
              <div className="flex-1 text-left">
                <div className="text-sm text-[#dbdee1] font-medium">{label}</div>
                <div className="text-[10px] text-[#949ba4]">{description}</div>
              </div>
              {settings.channel_mode === id && <Check size={16} className="text-[#5865f2]" />}
            </button>
          ))}
        </div>

        {settings.channel_mode !== "all" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <input value={newChannelId} onChange={(e) => setNewChannelId(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addChannelToList()} placeholder="Channel ID to add..." className="flex-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
              <button onClick={addChannelToList} className="p-2 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white transition-colors"><Plus size={14} /></button>
            </div>
            {settings.channel_list.length > 0 ? (
              <div className="space-y-1">
                {settings.channel_list.map((id) => (
                  <div key={id} className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-[#1e1f22] border border-[#1f2023] group">
                    <Hash size={12} className="text-[#6d6f78] shrink-0" />
                    <span className="flex-1 text-xs text-[#dbdee1] font-mono truncate">{id}</span>
                    <button onClick={() => removeChannelFromList(id)} className="text-[#6d6f78] hover:text-[#f23f43] opacity-0 group-hover:opacity-100 transition-opacity"><X size={12} /></button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[10px] text-[#6d6f78]">No channels added — the AI may respond in any channel</p>
            )}
          </div>
        )}
      </Section>

      {/* User Filtering */}
      <Section icon={Users} title="Allowed Users">
        <p className="text-xs text-[#949ba4] mb-3">
          Leave this list empty to respond to anyone. Add Discord user IDs to respond only to those people.
        </p>
        <div className="flex items-center gap-2">
          <input value={newAllowedUserId} onChange={(e) => setNewAllowedUserId(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addAllowedUser()} placeholder="Discord user ID..." className="flex-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
          <button onClick={addAllowedUser} className="p-2 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white transition-colors"><Plus size={14} /></button>
        </div>
        {settings.allowed_user_ids.length > 0 ? (
          <div className="space-y-1 mt-2">
            {settings.allowed_user_ids.map((id) => (
              <div key={id} className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-[#1e1f22] border border-[#1f2023] group">
                <Users size={12} className="text-[#6d6f78] shrink-0" />
                <span className="flex-1 text-xs text-[#dbdee1] font-mono truncate">{id}</span>
                <button onClick={() => removeAllowedUser(id)} className="text-[#6d6f78] hover:text-[#f23f43] opacity-0 group-hover:opacity-100 transition-opacity"><X size={12} /></button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[10px] text-[#6d6f78] mt-2">No user restriction — anyone can address the AI</p>
        )}
      </Section>

      {/* Voice Settings (bot and client modes) */}
      {(settings.mode === "bot" || settings.mode === "client") && (
        <Section icon={Volume2} title="Voice Channel">
          <p className="text-xs text-[#949ba4] mb-3">
            Configure which voice channel the AI joins.
          </p>

          <div className="flex items-center justify-between mb-3">
            <span className="text-sm text-[#dbdee1]">Auto-join voice on start</span>
            <button onClick={() => update("auto_join_voice", !settings.auto_join_voice)} className={`w-10 h-5 rounded-full transition-colors relative ${settings.auto_join_voice ? "bg-[#23a55a]" : "bg-[#80848e]"}`}>
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.auto_join_voice ? "left-5" : "left-0.5"}`} />
            </button>
          </div>

          {settings.auto_join_voice && (
            <div className="space-y-3">
              <div>
                <label className="text-[10px] text-[#949ba4] uppercase tracking-wider mb-1.5 block">Voice Channel Selection</label>
                <div className="space-y-1.5">
                  {(Object.keys(VOICE_MODE_INFO) as VoiceChannelMode[]).map((mode) => {
                    const info = VOICE_MODE_INFO[mode];
                    const Icon = info.icon;
                    const selected = settings.voice_channel_mode === mode;
                    return (
                      <button key={mode} onClick={() => update("voice_channel_mode", mode)} className={`w-full flex items-center gap-3 p-2.5 rounded-lg border transition-all ${selected ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>
                        <Icon size={16} className={selected ? "text-[#5865f2]" : "text-[#949ba4]"} />
                        <div className="flex-1 text-left">
                          <div className="text-sm text-[#dbdee1] font-medium">{info.label}</div>
                          <div className="text-[10px] text-[#949ba4]">{info.description}</div>
                        </div>
                        {selected && <Check size={16} className="text-[#5865f2]" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              {settings.voice_channel_mode === "specific" && (
                <div>
                  <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Voice Channel ID</label>
                  <input value={settings.voice_channel_id} onChange={(e) => update("voice_channel_id", e.target.value)} placeholder="123456789012345678" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
                </div>
              )}

              {(settings.voice_channel_mode === "above" || settings.voice_channel_mode === "below") && (
                <div>
                  <div className="flex items-center justify-between">
                    <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">User Count Threshold</label>
                    <span className="text-[11px] text-[#dbdee1] font-mono">{settings.voice_channel_threshold}</span>
                  </div>
                  <input type="range" min={0} max={50} step={1} value={settings.voice_channel_threshold} onChange={(e) => update("voice_channel_threshold", parseInt(e.target.value))} className="w-full h-1.5 mt-1.5 rounded-full appearance-none cursor-pointer" style={{ background: `linear-gradient(to right, #5865f2 ${(settings.voice_channel_threshold / 50) * 100}%, #1e1f22 ${(settings.voice_channel_threshold / 50) * 100}%)` }} />
                  <div className="flex justify-between mt-0.5">
                    <span className="text-[9px] text-[#6d6f78]">0</span>
                    <span className="text-[9px] text-[#6d6f78]">50</span>
                  </div>
                  <p className="text-[9px] text-[#6d6f78] mt-1">
                    {settings.voice_channel_mode === "above"
                      ? `Join a voice channel with more than ${settings.voice_channel_threshold} users`
                      : `Join a voice channel with fewer than ${settings.voice_channel_threshold} users`}
                  </p>
                </div>
              )}
            </div>
          )}

          <div className="mt-3 pt-3 border-t border-[#1f2023]">
            <div className="flex items-center justify-between mb-1">
              <div>
                <span className="text-sm text-[#dbdee1]">Follow message authors when idle</span>
                <p className="text-[10px] text-[#6d6f78]">
                  If the person who messages the AI is in voice, join their channel only when no active voice session is running.
                </p>
              </div>
              <button
                onClick={() => update("join_message_author_voice", !settings.join_message_author_voice)}
                className={`w-10 h-5 rounded-full transition-colors relative ${settings.join_message_author_voice ? "bg-[#23a55a]" : "bg-[#80848e]"}`}
                aria-label="Toggle following message authors when idle"
              >
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.join_message_author_voice ? "left-5" : "left-0.5"}`} />
              </button>
            </div>
            {settings.join_message_author_voice && (
              <p className="text-[10px] text-[#f0b232]">
                Requires the Equicord bridge and a voice-state event for the author. Active calls stay locked to their current channel.
              </p>
            )}
          </div>

          {/* Live Join (on-demand/manual) */}
          <div className="mt-3 pt-3 border-t border-[#1f2023]">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm text-[#dbdee1]">Enable Live Join (join calls on demand)</span>
              <button onClick={() => update("live_join_enabled", !settings.live_join_enabled)} className={`w-10 h-5 rounded-full transition-colors relative ${settings.live_join_enabled ? "bg-[#23a55a]" : "bg-[#80848e]"}`}>
                <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.live_join_enabled ? "left-5" : "left-0.5"}`} />
              </button>
            </div>

            {settings.live_join_enabled && (
              <div className="space-y-3">
                <div className="flex items-center justify-between rounded-lg border border-[#1f2023] bg-[#1e1f22] p-3">
                  <div className="pr-3">
                    <span className="text-sm text-[#dbdee1]">Follow requesting author on join</span>
                    <p className="text-[10px] text-[#6d6f78]">
                      When the AI is asked to join, prefer the requester’s current voice channel. The configured channel remains the fallback.
                    </p>
                  </div>
                  <button
                    onClick={() => update("live_join_follow_author", !settings.live_join_follow_author)}
                    className={`w-10 h-5 rounded-full transition-colors relative shrink-0 ${settings.live_join_follow_author ? "bg-[#23a55a]" : "bg-[#80848e]"}`}
                    aria-label="Toggle following the requesting author on voice join"
                  >
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.live_join_follow_author ? "left-5" : "left-0.5"}`} />
                  </button>
                </div>
                <div>
                  <label className="text-[10px] text-[#949ba4] uppercase tracking-wider mb-1.5 block">Join Method</label>
                  <div className="flex gap-2">
                    <button onClick={() => update("join_method", "manual")} className={`flex-1 p-2.5 rounded-lg border ${settings.join_method === "manual" ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>Manual (Channel ID)</button>
                    <button onClick={() => update("join_method", "population")} className={`flex-1 p-2.5 rounded-lg border ${settings.join_method === "population" ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>Population-based</button>
                  </div>
                </div>

                {settings.join_method === "manual" && (
                  <div>
                    <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Channel ID to Join</label>
                    <input value={settings.voice_channel_id} onChange={(e) => update("voice_channel_id", e.target.value)} placeholder="123456789012345678" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] font-mono focus:outline-none focus:border-[#5865f2]" />
                  </div>
                )}

                {settings.join_method === "population" && (
                  <div>
                    <div className="flex items-center justify-between">
                      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Selection Strategy</label>
                      <span className="text-[11px] text-[#dbdee1] font-mono">{VOICE_MODE_INFO[settings.voice_channel_mode].label}</span>
                    </div>
                    <div className="space-y-1.5">
                      {(Object.keys(VOICE_MODE_INFO) as VoiceChannelMode[]).map((mode) => {
                        const info = VOICE_MODE_INFO[mode];
                        const Icon = info.icon;
                        const selected = settings.voice_channel_mode === mode;
                        return (
                          <button key={mode} onClick={() => update("voice_channel_mode", mode)} className={`w-full flex items-center gap-3 p-2.5 rounded-lg border transition-all ${selected ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>
                            <Icon size={16} className={selected ? "text-[#5865f2]" : "text-[#949ba4]"} />
                            <div className="flex-1 text-left">
                              <div className="text-sm text-[#dbdee1] font-medium">{info.label}</div>
                              <div className="text-[10px] text-[#949ba4]">{info.description}</div>
                            </div>
                            {selected && <Check size={16} className="text-[#5865f2]" />}
                          </button>
                        );
                      })}
                    </div>

                    {(settings.voice_channel_mode === "above" || settings.voice_channel_mode === "below") && (
                      <div>
                        <div className="flex items-center justify-between">
                          <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">User Count Threshold</label>
                          <span className="text-[11px] text-[#dbdee1] font-mono">{settings.voice_channel_threshold}</span>
                        </div>
                        <input type="range" min={0} max={50} step={1} value={settings.voice_channel_threshold} onChange={(e) => update("voice_channel_threshold", parseInt(e.target.value))} className="w-full h-1.5 mt-1.5 rounded-full appearance-none cursor-pointer" style={{ background: `linear-gradient(to right, #5865f2 ${(settings.voice_channel_threshold / 50) * 100}%, #1e1f22 ${(settings.voice_channel_threshold / 50) * 100}%)` }} />
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <button onClick={async () => {
                    try {
                      const payload = {
                        channel_id: settings.voice_channel_id,
                        method: settings.join_method,
                        mode: settings.voice_channel_mode,
                        threshold: settings.voice_channel_threshold,
                        mode_type: settings.mode,
                        build: settings.build,
                      };
                      const res = await fetch('/api/integrations/discord/join', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
                      const data = await res.json().catch(() => ({}));

                      // Bridge joined successfully
                      if (data?.action === 'bridge_join') {
                        setJoinMsg(`Joined voice channel via Equicord bridge.`);
                        setSaveMsg('ok');
                        setTimeout(() => { setJoinMsg(null); setSaveMsg(null); }, 4000);
                        return;
                      }

                      if (settings.mode === 'client' && (data?.action === 'client_not_running' || !res.ok)) {
                        const buildName = settings.build === 'canary' ? 'Canary' : settings.build === 'ptb' ? 'PTB' : 'Stable';
                        setJoinMsg(`Discord ${buildName} is not running. Would you like to start it and join the selected voice channel?`);
                        setSaveMsg('err');
                        setTimeout(() => setSaveMsg(null), 2000);
                        return;
                      }

                      if (settings.mode === 'client' && data?.action === 'client_running') {
                        if (!settings.server_id && settings.voice_channel_id) {
                          setJoinMsg('Discord client deep links need the server (guild) ID to join a voice channel. Add the server ID to open the correct voice channel.');
                          setSaveMsg('err');
                          setTimeout(() => setJoinMsg(null), 5000);
                          setTimeout(() => setSaveMsg(null), 2000);
                          return;
                        }

                        const target = data.join_target || (
                          settings.server_id && settings.voice_channel_id
                            ? `discord://discord.com/channels/${settings.server_id}/${settings.voice_channel_id}`
                            : 'discord://'
                        );
                        openDiscordJoinTarget(target);
                        setJoinMsg('Discord client is running. Trying to open the selected channel in Discord.');
                        setSaveMsg('ok');
                        setTimeout(() => setJoinMsg(null), 4000);
                        setTimeout(() => setSaveMsg(null), 2000);
                        return;
                      }

                      setSaveMsg('ok');
                      setTimeout(() => setSaveMsg(null), 2000);
                    } catch (e) {
                      setSaveMsg('err');
                      setTimeout(() => setSaveMsg(null), 2000);
                    }
                  }} className="px-3 py-2 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-sm font-medium transition-colors">Join Now</button>
                  <span className="text-[10px] text-[#6d6f78]">Interface adapts to {settings.mode === 'client' ? 'local client' : 'bot account'} mode.</span>
                </div>
                {/* Inline join message */}
                {joinMsg && (
                  <div className="mt-2">
                    <div className="text-sm text-yellow-300">{joinMsg}</div>
                    <div className="mt-2 flex gap-2">
                      <button onClick={async () => {
                        try {
                          const buildName = settings.build === 'canary' ? 'canary' : settings.build === 'ptb' ? 'ptb' : 'stable';
                          await fetch('/api/integrations/discord/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ build: buildName }) });
                          if (!settings.server_id && settings.voice_channel_id) {
                            setJoinMsg('The Discord client started, but a server (guild) ID is required to join a specific voice channel. Add the server ID and retry.');
                            setTimeout(() => setJoinMsg(null), 5000);
                            return;
                          }
                          const target = settings.server_id && settings.voice_channel_id ? `discord://discord.com/channels/${settings.server_id}/${settings.voice_channel_id}` : 'discord://';
                          setJoinMsg('Started the selected Discord client. Opening the target channel...');
                          setTimeout(() => {
                            openDiscordJoinTarget(target);
                          }, 1500);
                          setTimeout(() => setJoinMsg(null), 4000);
                        } catch (e) {
                          setJoinMsg('Failed to start the selected Discord client. Please start it manually and retry.');
                          setTimeout(() => setJoinMsg(null), 4000);
                        }
                      }} className="px-3 py-2 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-sm font-medium transition-colors">Start Client</button>
                      <button onClick={() => { setJoinMsg(null); }} className="px-3 py-2 rounded bg-[#2b2d31] border border-[#1f2023] text-sm">Dismiss</button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </Section>
      )}

      {/* Bot Settings */}
      <Section icon={Radio} title="Bot Settings">
        <div className="space-y-2">
          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">AI Command Prefix</label>
            <input value={settings.command_prefix} onChange={(e) => update("command_prefix", e.target.value)} placeholder="ai! (empty disables command mode)" className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] font-mono focus:outline-none focus:border-[#5865f2]" />
            <p className="text-[10px] text-[#6d6f78] mt-1">When Respond to every message is off, this prefix is required. Leave it empty to disable command-mode replies.</p>
            <div className="mt-2 rounded border border-[#1f2023] bg-[#1e1f22] px-2 py-1.5 text-[10px] text-[#b5bac1]">
              Effective rule: {settings.respond_to_every_message
                ? "every eligible message reaches the AI (prefix optional)"
                : settings.command_prefix.trim()
                  ? `messages must start with “${settings.command_prefix.trim()}”`
                  : "command-mode replies are disabled until a prefix is configured"}
            </div>
          </div>
          <div>
            <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">Status Text</label>
            <input value={settings.status_text} onChange={(e) => update("status_text", e.target.value)} className="w-full mt-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-2 text-sm text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]" />
          </div>
          <div className="flex items-center justify-between pt-1">
            <span className="text-sm text-[#dbdee1]">Enable Discord Integration</span>
            <button onClick={() => update("enabled", !settings.enabled)} className={`w-10 h-5 rounded-full transition-colors relative ${settings.enabled ? "bg-[#23a55a]" : "bg-[#80848e]"}`}>
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.enabled ? "left-5" : "left-0.5"}`} />
            </button>
          </div>
          <div className="flex items-center justify-between pt-3">
            <div>
              <span className="text-sm text-[#dbdee1]">Respond to every eligible message</span>
              <p className="text-[10px] text-[#949ba4]">When on, every eligible message reaches the AI. When off, a configured prefix is required; an empty prefix disables commands.</p>
            </div>
            <button onClick={() => update("respond_to_every_message", !settings.respond_to_every_message)} className={`w-10 h-5 rounded-full transition-colors relative ${settings.respond_to_every_message ? "bg-[#23a55a]" : "bg-[#80848e]"}`}>
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.respond_to_every_message ? "left-5" : "left-0.5"}`} />
            </button>
          </div>
          <div className="flex items-center justify-between pt-3 gap-4">
            <div>
              <span className="text-sm text-[#dbdee1]">Show typing while AI generates</span>
              <p className="text-[10px] text-[#949ba4]">Displays Discord's native typing indicator during LLM and tool-call processing.</p>
            </div>
            <button onClick={() => update("typing_indicator", !settings.typing_indicator)} className={`w-10 h-5 shrink-0 rounded-full transition-colors relative ${settings.typing_indicator ? "bg-[#23a55a]" : "bg-[#80848e]"}`}>
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${settings.typing_indicator ? "left-5" : "left-0.5"}`} />
            </button>
          </div>
        </div>
      </Section>

      {/* Save Button */}
      <div className="flex items-center gap-2 pt-1 pb-4">
        <button onClick={handleSave} disabled={saving} className="px-4 py-2 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
          {saving ? <Loader2 size={14} className="animate-spin" /> : saveMsg === "ok" ? <Check size={14} /> : null}
          {saving ? "Saving..." : saveMsg === "ok" ? "Saved" : saveMsg === "err" ? "Failed" : "Save Changes"}
        </button>
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: React.ElementType; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-[#2b2d31] rounded-lg border border-[#1f2023] p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon size={16} className="text-[#5865f2]" />
        <h3 className="text-xs font-semibold text-[#dbdee1] uppercase tracking-wider">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function ModeCard({ icon: Icon, title, description, selected, onClick }: { icon: React.ElementType; title: string; description: string; selected: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className={`flex flex-col items-center gap-2 p-3 rounded-lg border transition-all ${selected ? "border-[#5865f2] bg-[#5865f2]/10" : "border-[#1f2023] bg-[#1e1f22] hover:border-[#3f4147]"}`}>
      <Icon size={24} className={selected ? "text-[#5865f2]" : "text-[#949ba4]"} />
      <div className="text-center">
        <div className="text-sm text-[#dbdee1] font-medium">{title}</div>
        <div className="text-[10px] text-[#949ba4] mt-0.5">{description}</div>
      </div>
      {selected && <div className="w-1.5 h-1.5 rounded-full bg-[#5865f2]" />}
    </button>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[#949ba4]">{label}</span>
      <span className="text-xs text-[#dbdee1] font-mono">{value || "\u2014"}</span>
    </div>
  );
}

function StatusBadge({ label, value, ok, neutral = false }: { label: string; value: string; ok: boolean; neutral?: boolean }) {
  return (
    <div className="rounded border border-[#1f2023] bg-[#1e1f22] px-2 py-1.5">
      <div className="text-[#6d6f78] uppercase tracking-wider">{label}</div>
      <div className={`mt-0.5 flex items-center gap-1 ${neutral ? "text-[#dbdee1]" : ok ? "text-[#23a55a]" : "text-[#f23f43]"}`}>
        <span className={`w-1.5 h-1.5 rounded-full ${neutral ? "bg-[#949ba4]" : ok ? "bg-[#23a55a]" : "bg-[#f23f43]"}`} />
        <span className="truncate" title={value}>{value}</span>
      </div>
    </div>
  );
}
