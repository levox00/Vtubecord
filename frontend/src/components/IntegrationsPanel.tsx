import { useEffect, useState, useCallback } from "react";
import {
  MessageSquare,
  Music,
  Tv,
  Loader2,
  Check,
  AlertCircle,
  ChevronDown,
  Eye,
  EyeOff,
  Zap,
  Save,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  LogOut,
  RefreshCw,
  Volume2,
  Video,
  Camera,
  CircleStop,
} from "lucide-react";
import {
  fetchIntegrations,
  updateDiscordIntegration,
  updateSpotifyIntegration,
  updateTwitchIntegration,
  testDiscordIntegration,
  testSpotifyIntegration,
  controlSpotify,
  fetchSpotifyAuthUrl,
  fetchSpotifyStatus,
  logoutSpotify,
  updateObsIntegration,
  fetchObsStatus,
  testObsIntegration,
  controlObs,
} from "../lib/api";
import type {
  IntegrationStatus,
  DiscordConfig,
  SpotifyConfig,
  SpotifyPlayerStatus,
  TwitchConfig,
  ObsConfig,
  ObsStatus,
} from "../types";

interface IntegrationsPanelProps {
  channel?: string;
}

type ConnectionTest = {
  status: "idle" | "loading" | "success" | "error";
  message: string;
};

const INTEGRATION_ICONS: Record<string, React.ElementType> = {
  discord: MessageSquare,
  spotify: Music,
  twitch: Tv,
  obs: Video,
};

const INTEGRATION_COLORS: Record<string, string> = {
  discord: "#5865f2",
  spotify: "#1db954",
  twitch: "#9146ff",
  obs: "#8d99a6",
};

export function IntegrationsPanel({ channel }: IntegrationsPanelProps) {
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchIntegrations()
      .then((res) => setIntegrations(res.integrations))
      .catch((e) => console.error("Failed to load integrations", e))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={20} className="text-[#5865f2] animate-spin" />
      </div>
    );
  }

  const filtered = channel && channel !== "integrations"
    ? integrations.filter((i) => `${i.name}-integration` === channel)
    : integrations;

  return (
    <div className="flex flex-col h-full p-5 overflow-y-auto bg-[#313338]">
      {filtered.length === 0 ? (
        <div className="text-[#949ba4] text-xs text-center mt-8">
          No integrations found
        </div>
      ) : (
        filtered.map((integration) => (
          <IntegrationCard key={integration.name} integration={integration} />
        ))
      )}
    </div>
  );
}

function IntegrationCard({ integration }: { integration: IntegrationStatus }) {
  const [expanded, setExpanded] = useState(false);
  const [test, setTest] = useState<ConnectionTest>({ status: "idle", message: "" });
  const [localEnabled, setLocalEnabled] = useState(integration.enabled);

  const Icon = INTEGRATION_ICONS[integration.name] || MessageSquare;
  const color = INTEGRATION_COLORS[integration.name] || "#5865f2";

  const handleTest = useCallback(async () => {
    setTest({ status: "loading", message: "" });
    try {
      let result: { success: boolean; message: string };
      if (integration.name === "discord") {
        result = await testDiscordIntegration();
      } else if (integration.name === "spotify") {
        result = await testSpotifyIntegration();
      } else if (integration.name === "obs") {
        result = await testObsIntegration();
      } else {
        result = { success: false, message: "Test not available for this integration" };
      }
      setTest({
        status: result.success ? "success" : "error",
        message: result.message,
      });
    } catch (e) {
      setTest({ status: "error", message: e instanceof Error ? e.message : "Test failed" });
    }
  }, [integration.name]);

  const statusBadge = integration.connected
    ? { label: "Connected", color: "#23a55a", icon: Check }
    : integration.configured
    ? { label: "Configured", color: "#faa61a", icon: AlertCircle }
    : { label: "Not Configured", color: "#f23f43", icon: AlertCircle };

  return (
    <div className="bg-[#2b2d31] rounded-xl border border-[#3a3d43] mb-3 overflow-hidden shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between p-4">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center"
            style={{ backgroundColor: `${color}20` }}
          >
            <Icon size={20} style={{ color }} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#dbdee1] capitalize">
              {integration.name}
            </h3>
            <p className="text-[10px] text-[#949ba4]">{integration.description}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Status badge */}
          <div
            className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium"
            style={{
              backgroundColor: `${statusBadge.color}15`,
              color: statusBadge.color,
            }}
          >
            <statusBadge.icon size={10} />
            {statusBadge.label}
          </div>

          {/* Toggle */}
          <ToggleSwitch
            checked={localEnabled}
            onChange={(v) => {
              setLocalEnabled(v);
              if (integration.name === "spotify") {
                updateSpotifyIntegration({ enabled: v }).catch(() => setLocalEnabled(!v));
              } else if (integration.name === "obs") {
                updateObsIntegration({ enabled: v }).catch(() => setLocalEnabled(!v));
              }
            }}
          />
        </div>
      </div>

      {/* Expand button */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-center gap-1 py-1.5 text-[10px] text-[#949ba4] hover:text-[#dbdee1] hover:bg-[#35373c] transition-colors border-t border-[#1f2023]"
      >
        Configure
        <ChevronDown
          size={12}
          className={`transition-transform ${expanded ? "rotate-180" : ""}`}
        />
      </button>

      {/* Config section */}
      {expanded && (
        <ConfigSection
          name={integration.name}
          test={test}
          onTest={handleTest}
        />
      )}
    </div>
  );
}

function ConfigSection({
  name,
  test,
  onTest,
}: {
  name: string;
  test: ConnectionTest;
  onTest: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<"idle" | "success" | "error">("idle");

  if (name === "discord") return <DiscordConfigForm test={test} onTest={onTest} saving={saving} setSaving={setSaving} saveResult={saveResult} setSaveResult={setSaveResult} />;
  if (name === "spotify") return <SpotifyConfigForm test={test} onTest={onTest} saving={saving} setSaving={setSaving} saveResult={saveResult} setSaveResult={setSaveResult} />;
  if (name === "twitch") return <TwitchConfigForm test={test} onTest={onTest} saving={saving} setSaving={setSaving} saveResult={saveResult} setSaveResult={setSaveResult} />;
  if (name === "obs") return <ObsConfigForm test={test} onTest={onTest} saving={saving} setSaving={setSaving} saveResult={saveResult} setSaveResult={setSaveResult} />;

  return null;
}

// --- Toggle Switch ---

function ToggleSwitch({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none"
      style={{
        backgroundColor: checked ? "#23a55a" : "#4e5058",
      }}
    >
      <span
        className="inline-block h-4 w-4 rounded-full bg-white shadow transition-transform"
        style={{
          transform: checked ? "translateX(22px)" : "translateX(2px)",
        }}
      />
    </button>
  );
}

// --- Discord Config ---

function DiscordConfigForm({
  test,
  onTest,
  saving,
  setSaving,
  saveResult,
  setSaveResult,
}: {
  test: ConnectionTest;
  onTest: () => void;
  saving: boolean;
  setSaving: (v: boolean) => void;
  saveResult: "idle" | "success" | "error";
  setSaveResult: (v: "idle" | "success" | "error") => void;
}) {
  const [config, setConfig] = useState<Partial<DiscordConfig>>({});
  const [showToken, setShowToken] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaveResult("idle");
    try {
      await updateDiscordIntegration(config);
      setSaveResult("success");
      setTimeout(() => setSaveResult("idle"), 2000);
    } catch {
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 border-t border-[#1f2023] space-y-3">
      <ConfigField
        label="Bot Token"
        value={config.bot_token || ""}
        onChange={(v) => setConfig({ ...config, bot_token: v })}
        masked
        showMask={showToken}
        onToggleMask={() => setShowToken(!showToken)}
      />
      <ConfigField
        label="Channel ID"
        value={config.channel_id || ""}
        onChange={(v) => setConfig({ ...config, channel_id: v })}
        placeholder="123456789012345678"
      />
      <ConfigField
        label="Voice Channel ID"
        value={config.voice_channel_id || ""}
        onChange={(v) => setConfig({ ...config, voice_channel_id: v })}
        placeholder="123456789012345678"
      />
      <ConfigField
        label="Command Prefix"
        value={config.command_prefix || ""}
        onChange={(v) => setConfig({ ...config, command_prefix: v })}
        placeholder="!"
      />
      <ConfigField
        label="Status Text"
        value={config.status_text || ""}
        onChange={(v) => setConfig({ ...config, status_text: v })}
        placeholder="Listening to..."
      />

      <ActionButtons
        saving={saving}
        saveResult={saveResult}
        test={test}
        onSave={handleSave}
        onTest={onTest}
      />
    </div>
  );
}

// --- Spotify Config ---

function SpotifyConfigForm({
  test,
  onTest,
  saving,
  setSaving,
  saveResult,
  setSaveResult,
}: {
  test: ConnectionTest;
  onTest: () => void;
  saving: boolean;
  setSaving: (v: boolean) => void;
  saveResult: "idle" | "success" | "error";
  setSaveResult: (v: "idle" | "success" | "error") => void;
}) {
  const [config, setConfig] = useState<Partial<SpotifyConfig>>({});
  const [showSecret, setShowSecret] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaveResult("idle");
    try {
      await updateSpotifyIntegration(config);
      setSaveResult("success");
      setTimeout(() => setSaveResult("idle"), 2000);
    } catch {
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 border-t border-[#1f2023] space-y-3">
      <ConfigField
        label="Client ID"
        value={config.client_id || ""}
        onChange={(v) => setConfig({ ...config, client_id: v })}
      />
      <ConfigField
        label="Client Secret"
        value={config.client_secret || ""}
        onChange={(v) => setConfig({ ...config, client_secret: v })}
        masked
        showMask={showSecret}
        onToggleMask={() => setShowSecret(!showSecret)}
      />
      <ConfigField
        label="Redirect URI"
        value={config.redirect_uri || ""}
        onChange={(v) => setConfig({ ...config, redirect_uri: v })}
        placeholder="http://127.0.0.1:8000/api/integrations/spotify/callback"
      />
      <p className="text-[10px] leading-relaxed text-[#6d7078]">
        Add this exact callback URL to your Spotify Developer Dashboard before connecting. Spotify does not allow localhost; use the explicit 127.0.0.1 loopback address.
      </p>

      <ActionButtons
        saving={saving}
        saveResult={saveResult}
        test={test}
        onSave={handleSave}
        onTest={onTest}
      />
      <SpotifyPlayer />
    </div>
  );
}

function SpotifyPlayer() {
  const [status, setStatus] = useState<SpotifyPlayerStatus>({
    connected: false,
    is_playing: false,
    item: null,
    device: null,
  });
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [query, setQuery] = useState("");
  const [volume, setVolume] = useState(50);
  const [error, setError] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      const next = await fetchSpotifyStatus();
      setStatus(next);
      if (typeof next.volume_percent === "number") setVolume(next.volume_percent);
      setError(next.error || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load Spotify status");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    const interval = window.setInterval(() => void loadStatus(), 5000);
    const handleAuth = (event: MessageEvent) => {
      if (event.data?.type === "spotify-auth") void loadStatus();
    };
    window.addEventListener("message", handleAuth);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("message", handleAuth);
    };
  }, [loadStatus]);

  const connect = async () => {
    setError("");
    try {
      const { auth_url } = await fetchSpotifyAuthUrl();
      const popup = window.open(auth_url, "spotify-auth", "popup,width=520,height=720");
      if (!popup) window.location.assign(auth_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to start Spotify authorization");
    }
  };

  const run = async (action: Parameters<typeof controlSpotify>[0], options: Parameters<typeof controlSpotify>[1] = {}) => {
    setWorking(true);
    setError("");
    try {
      const next = await controlSpotify(action, options);
      setStatus(next);
      if (typeof next.volume_percent === "number") setVolume(next.volume_percent);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Spotify playback command failed");
    } finally {
      setWorking(false);
    }
  };

  const playSearch = () => {
    const value = query.trim();
    if (value) {
      void run("play", { query: value });
      setQuery("");
    } else {
      void run(status.is_playing ? "pause" : "resume");
    }
  };

  const item = status.item;
  const artists = item?.artists?.join(", ") || "";

  return (
    <div className="border-t border-[#1f2023] pt-3 mt-1 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-xs font-semibold text-[#dbdee1]">Spotify player</h4>
          <p className="text-[10px] text-[#949ba4]">Control the active Spotify device from the AI or this panel.</p>
        </div>
        {status.connected ? (
          <button
            type="button"
            onClick={() => { void logoutSpotify().then(loadStatus).catch((e) => setError(e instanceof Error ? e.message : "Unable to disconnect Spotify")); }}
            className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] text-[#b5bac1] hover:bg-[#35373c] hover:text-[#f23f43]"
          >
            <LogOut size={12} /> Disconnect
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void connect()}
            className="inline-flex items-center gap-1 rounded bg-[#1db954] px-2.5 py-1.5 text-[10px] font-semibold text-black hover:bg-[#1ed760]"
          >
            Connect Spotify
          </button>
        )}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[10px] text-[#949ba4]"><Loader2 size={13} className="animate-spin" /> Loading player…</div>
      ) : status.connected ? (
        <>
          <div className="rounded-lg border border-[#3a3d43] bg-[#232428] px-2.5 py-2 text-[10px] leading-relaxed text-[#b5bac1]">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-[#dbdee1]">AI control</span>
              <span className="text-[#1db954]">
                {status.ai_control_mode === "tool_calling"
                  ? "Tool calling"
                  : status.ai_control_mode === "parser_fallback"
                  ? "Parser fallback"
                  : "Detecting"}
              </span>
            </div>
            <p className="mt-1 text-[#949ba4]">
              Try “what’s playing?”, “favorite this song”, “play my favorite songs”, “play the next song”, “start music”, “one song back”, “pause”, or “play Daft Punk”.
            </p>
            <p className={status.liked_songs_scope_granted === false || status.liked_songs_modify_scope_granted === false ? "mt-1 text-[#f0a35b]" : "mt-1 text-[#777b84]"}>
              {status.liked_songs_scope_granted === false || status.liked_songs_modify_scope_granted === false
                ? "Liked Songs access is incomplete. Click Disconnect, then Connect Spotify again to allow reading and favoriting tracks."
                : "The AI can play your Liked Songs and save the exact current track when you ask to favorite or like it."}
            </p>
          </div>
          <div className="flex items-center gap-3 rounded-lg bg-[#1e1f22] p-2.5">
            {item?.image_url ? (
              <img src={item.image_url} alt="" className="h-12 w-12 rounded object-cover" />
            ) : (
              <div className="flex h-12 w-12 items-center justify-center rounded bg-[#1db954]/15 text-[#1db954]"><Music size={20} /></div>
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-[#dbdee1]">{item?.name || "Nothing playing"}</div>
              <div className="truncate text-[10px] text-[#949ba4]">{artists || status.device?.name || "Start Spotify on a device"}</div>
            </div>
            <button type="button" title="Refresh player" onClick={() => void loadStatus()} className="rounded p-1 text-[#949ba4] hover:bg-[#35373c] hover:text-[#dbdee1]"><RefreshCw size={13} /></button>
          </div>

          <div className="flex items-center justify-center gap-1.5">
            <button type="button" title="Previous track" disabled={working} onClick={() => void run("previous")} className="rounded p-2 text-[#b5bac1] hover:bg-[#35373c] hover:text-white disabled:opacity-40"><SkipBack size={16} /></button>
            <button type="button" title={status.is_playing ? "Pause" : "Resume"} disabled={working} onClick={playSearch} className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1db954] text-black hover:bg-[#1ed760] disabled:opacity-40">{status.is_playing ? <Pause size={15} /> : <Play size={15} fill="currentColor" />}</button>
            <button type="button" title="Next track" disabled={working} onClick={() => void run("next")} className="rounded p-2 text-[#b5bac1] hover:bg-[#35373c] hover:text-white disabled:opacity-40"><SkipForward size={16} /></button>
          </div>

          <div className="flex items-center gap-2">
            <Volume2 size={14} className="shrink-0 text-[#949ba4]" />
            <input
              aria-label="Spotify volume"
              type="range"
              min="0"
              max="100"
              value={volume}
              onChange={(event) => setVolume(Number(event.target.value))}
              onPointerUp={() => void run("volume", { volume })}
              onKeyUp={() => void run("volume", { volume })}
              className="h-1.5 min-w-0 flex-1 accent-[#1db954]"
            />
            <span className="w-8 text-right text-[10px] text-[#949ba4]">{volume}%</span>
          </div>

          <form onSubmit={(event) => { event.preventDefault(); playSearch(); }} className="flex items-center gap-1.5">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Play a song or artist…"
              className="min-w-0 flex-1 rounded bg-[#1e1f22] px-2.5 py-2 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:ring-1 focus:ring-[#1db954]"
            />
            <button type="submit" disabled={!query.trim() || working} className="rounded bg-[#1db954] px-2.5 py-2 text-[10px] font-semibold text-black hover:bg-[#1ed760] disabled:opacity-40">Play</button>
          </form>
        </>
      ) : (
        <div className="space-y-1 text-[10px] leading-relaxed text-[#949ba4]">
          <p>Connect Spotify to let the AI read the current song, search, play, pause, skip, rewind, queue songs, and change volume.</p>
          <p className="text-[#6d7078]">Example: “what’s playing?”, “play the next song”, “start music”, or “one song back”. Playback requires an active Spotify Premium device.</p>
        </div>
      )}

      {error && <p className="rounded bg-[#f23f43]/10 px-2.5 py-2 text-[10px] leading-relaxed text-[#f23f43]">{error}</p>}
    </div>
  );
}

// --- OBS Config ---

function ObsConfigForm({
  test,
  onTest,
  saving,
  setSaving,
  saveResult,
  setSaveResult,
}: {
  test: ConnectionTest;
  onTest: () => void;
  saving: boolean;
  setSaving: (v: boolean) => void;
  saveResult: "idle" | "success" | "error";
  setSaveResult: (v: "idle" | "success" | "error") => void;
}) {
  const [config, setConfig] = useState<Partial<ObsConfig>>({
    host: "127.0.0.1",
    port: 4455,
    request_timeout: 5,
    allowed_scenes: [],
    discord_camera_name: "OBS Virtual Camera",
  });
  const [status, setStatus] = useState<ObsStatus>({ connected: false });
  const [showPassword, setShowPassword] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  const loadStatus = useCallback(async () => {
    try {
      const next = await fetchObsStatus();
      setStatus(next);
      if (next.config) {
        setConfig((current) => ({
          ...current,
          host: next.config?.host || "127.0.0.1",
          port: next.config?.port || 4455,
          request_timeout: next.config?.request_timeout || 5,
          allowed_scenes: next.config?.allowed_scenes || [],
          discord_camera_name: next.config?.discord_camera_name || "OBS Virtual Camera",
        }));
      }
      setError(next.error || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to read OBS status");
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    const interval = window.setInterval(() => void loadStatus(), 5000);
    return () => window.clearInterval(interval);
  }, [loadStatus]);

  const handleSave = async () => {
    setSaving(true);
    setSaveResult("idle");
    setError("");
    try {
      const payload = { ...config };
      if (!payload.password) delete payload.password;
      await updateObsIntegration(payload);
      setConfig((current) => ({ ...current, password: "" }));
      setSaveResult("success");
      window.setTimeout(() => setSaveResult("idle"), 2000);
      await loadStatus();
    } catch (e) {
      setSaveResult("error");
      setError(e instanceof Error ? e.message : "Unable to save OBS settings");
    } finally {
      setSaving(false);
    }
  };

  const run = async (action: Parameters<typeof controlObs>[0], scene?: string) => {
    setWorking(true);
    setError("");
    try {
      await controlObs(action, scene ? { scene } : {});
      await loadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "OBS command failed");
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="p-4 border-t border-[#1f2023] space-y-3">
      <div className="grid grid-cols-[1fr_90px] gap-2">
        <ConfigField label="WebSocket Host" value={config.host || ""} onChange={(v) => setConfig({ ...config, host: v })} placeholder="127.0.0.1" />
        <ConfigField label="Port" value={String(config.port || 4455)} onChange={(v) => setConfig({ ...config, port: Number(v) || 4455 })} placeholder="4455" />
      </div>
      <ConfigField
        label="WebSocket Password"
        value={config.password || ""}
        onChange={(v) => setConfig({ ...config, password: v })}
        placeholder={status.config?.password_configured ? "Saved — leave blank to keep" : "OBS WebSocket password"}
        masked
        showMask={showPassword}
        onToggleMask={() => setShowPassword(!showPassword)}
      />
      <ConfigField
        label="Discord Camera Device"
        value={config.discord_camera_name || ""}
        onChange={(v) => setConfig({ ...config, discord_camera_name: v })}
        placeholder="OBS Virtual Camera"
      />
      <ConfigField
        label="Allowed Scenes (comma separated; blank allows all)"
        value={(config.allowed_scenes || []).join(", ")}
        onChange={(v) => setConfig({ ...config, allowed_scenes: v.split(",").map((item) => item.trim()).filter(Boolean) })}
        placeholder="Gameplay, Just Chatting, BRB"
      />
      <p className="text-[10px] leading-relaxed text-[#6d7078]">
        In OBS open Tools → WebSocket Server Settings, enable the server, and use port 4455. Stream keys and destinations stay inside OBS.
      </p>

      <ActionButtons saving={saving} saveResult={saveResult} test={test} onSave={handleSave} onTest={onTest} />

      <div className="rounded-lg border border-[#3a3d43] bg-[#232428] p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div>
            <div className="text-xs font-semibold text-[#dbdee1]">OBS control</div>
            <div className="text-[10px] text-[#949ba4]">
              {status.connected ? `Connected · ${status.current_scene || "No scene"}` : "Not connected"}
            </div>
          </div>
          <button type="button" title="Refresh OBS status" onClick={() => void loadStatus()} className="rounded p-1.5 text-[#949ba4] hover:bg-[#35373c] hover:text-white"><RefreshCw size={13} /></button>
        </div>

        {status.connected && (
          <>
            <select
              aria-label="OBS scene"
              value={status.current_scene || ""}
              onChange={(event) => void run("set_scene", event.target.value)}
              disabled={working}
              className="w-full rounded bg-[#1e1f22] border border-[#3f4147] px-2.5 py-2 text-xs text-[#dbdee1]"
            >
              {(status.scenes || []).map((scene) => <option key={scene} value={scene}>{scene}</option>)}
            </select>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" disabled={working} onClick={() => void run(status.stream?.active ? "stop_stream" : "start_stream")} className={`flex items-center justify-center gap-1.5 rounded px-2 py-2 text-[10px] font-semibold disabled:opacity-40 ${status.stream?.active ? "bg-[#f23f43]/15 text-[#ff7b7e]" : "bg-[#f23f43] text-white"}`}>
                {status.stream?.active ? <CircleStop size={13} /> : <Video size={13} />}{status.stream?.active ? "Stop stream" : "Start stream"}
              </button>
              <button type="button" disabled={working} onClick={() => void run(status.recording?.active ? "stop_recording" : "start_recording")} className={`flex items-center justify-center gap-1.5 rounded px-2 py-2 text-[10px] font-semibold disabled:opacity-40 ${status.recording?.active ? "bg-[#f23f43]/15 text-[#ff7b7e]" : "bg-[#3f4147] text-white"}`}>
                <CircleStop size={13} />{status.recording?.active ? "Stop recording" : "Start recording"}
              </button>
              <button type="button" disabled={working || status.discord_camera?.active} title={status.discord_camera?.active ? "Stop the Discord camera first" : undefined} onClick={() => void run(status.virtual_camera?.active ? "stop_virtual_camera" : "start_virtual_camera")} className="flex items-center justify-center gap-1.5 rounded bg-[#3f4147] px-2 py-2 text-[10px] font-semibold text-white disabled:opacity-40">
                <Camera size={13} />{status.virtual_camera?.active ? "Stop Virtual Cam" : "Start Virtual Cam"}
              </button>
              <button type="button" disabled={working} onClick={() => void run(status.discord_camera?.active ? "stop_discord_camera" : "start_discord_camera")} className={`flex items-center justify-center gap-1.5 rounded px-2 py-2 text-[10px] font-semibold text-white disabled:opacity-40 ${status.discord_camera?.active ? "bg-[#f23f43]" : "bg-[#5865f2]"}`}>
                <Camera size={13} />{status.discord_camera?.active ? "Stop Discord camera" : "Send camera to Discord"}
              </button>
            </div>
          </>
        )}
      </div>
      {error && <p className="rounded bg-[#f23f43]/10 px-2.5 py-2 text-[10px] leading-relaxed text-[#f23f43]">{error}</p>}
    </div>
  );
}

// --- Twitch Config ---

function TwitchConfigForm({
  test,
  onTest,
  saving,
  setSaving,
  saveResult,
  setSaveResult,
}: {
  test: ConnectionTest;
  onTest: () => void;
  saving: boolean;
  setSaving: (v: boolean) => void;
  saveResult: "idle" | "success" | "error";
  setSaveResult: (v: "idle" | "success" | "error") => void;
}) {
  const [config, setConfig] = useState<Partial<TwitchConfig>>({});
  const [showSecret, setShowSecret] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaveResult("idle");
    try {
      await updateTwitchIntegration(config);
      setSaveResult("success");
      setTimeout(() => setSaveResult("idle"), 2000);
    } catch {
      setSaveResult("error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 border-t border-[#1f2023] space-y-3">
      <ConfigField
        label="Client ID"
        value={config.client_id || ""}
        onChange={(v) => setConfig({ ...config, client_id: v })}
      />
      <ConfigField
        label="Client Secret"
        value={config.client_secret || ""}
        onChange={(v) => setConfig({ ...config, client_secret: v })}
        masked
        showMask={showSecret}
        onToggleMask={() => setShowSecret(!showSecret)}
      />
      <ConfigField
        label="Channel"
        value={config.channel || ""}
        onChange={(v) => setConfig({ ...config, channel: v })}
        placeholder="your_channel_name"
      />

      <ActionButtons
        saving={saving}
        saveResult={saveResult}
        test={test}
        onSave={handleSave}
        onTest={onTest}
      />
    </div>
  );
}

// --- Shared sub-components ---

function ConfigField({
  label,
  value,
  onChange,
  placeholder,
  masked,
  showMask,
  onToggleMask,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  masked?: boolean;
  showMask?: boolean;
  onToggleMask?: () => void;
}) {
  return (
    <div>
      <label className="text-[10px] text-[#949ba4] uppercase tracking-wider">
        {label}
      </label>
      <div className="flex items-center gap-1 mt-1">
        <input
          type={masked && !showMask ? "password" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-[#1e1f22] border border-[#1f2023] rounded px-3 py-1.5 text-sm text-[#dbdee1] font-mono placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2]"
        />
        {masked && onToggleMask && (
          <button
            type="button"
            onClick={onToggleMask}
            className="p-1.5 text-[#949ba4] hover:text-[#dbdee1] transition-colors"
          >
            {showMask ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
      </div>
    </div>
  );
}

function ActionButtons({
  saving,
  saveResult,
  test,
  onSave,
  onTest,
}: {
  saving: boolean;
  saveResult: "idle" | "success" | "error";
  test: ConnectionTest;
  onSave: () => void;
  onTest: () => void;
}) {
  return (
    <div className="flex items-center gap-2 pt-1">
      {/* Save */}
      <button
        onClick={onSave}
        disabled={saving}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#5865f2] hover:bg-[#4752c4] text-white text-xs font-medium transition-colors disabled:opacity-50"
      >
        {saving ? (
          <Loader2 size={12} className="animate-spin" />
        ) : saveResult === "success" ? (
          <Check size={12} />
        ) : (
          <Save size={12} />
        )}
        {saveResult === "success" ? "Saved" : saving ? "Saving..." : "Save"}
      </button>

      {/* Test */}
      <button
        onClick={onTest}
        disabled={test.status === "loading"}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#1e1f22] border border-[#1f2023] hover:border-[#5865f2] text-[#dbdee1] text-xs font-medium transition-colors disabled:opacity-50"
      >
        {test.status === "loading" ? (
          <Loader2 size={12} className="animate-spin" />
        ) : (
          <Zap size={12} />
        )}
        Test Connection
      </button>

      {/* Test result */}
      {test.status !== "idle" && test.status !== "loading" && (
        <span
          className="text-[10px] font-medium"
          style={{ color: test.status === "success" ? "#23a55a" : "#f23f43" }}
        >
          {test.message}
        </span>
      )}
    </div>
  );
}
