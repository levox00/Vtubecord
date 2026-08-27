import { useEffect } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { ServerSidebar } from "./components/ServerSidebar";
import { ChannelSidebar } from "./components/ChannelSidebar";
import { ChannelHeader } from "./components/ChannelHeader";
import { ChatPanel } from "./components/ChatPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { GoalsPanel } from "./components/GoalsPanel";
import { SkillsPanel } from "./components/SkillsPanel";
import { sfxError } from "./lib/sounds";
import { GamesPanel } from "./components/GamesPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { DiscordSettingsPanel } from "./components/DiscordSettingsPanel";
import { IntegrationsPanel } from "./components/IntegrationsPanel";
import { DatasetEditorPanel } from "./components/DatasetEditorPanel";
import { LiveMode } from "./components/LiveMode";
import { Live2DCanvas } from "./components/Live2DCanvas";
import { OrbAnimation } from "./components/OrbAnimation";
import { useAppStore } from "./stores/appStore";
import { fetchStatus, fetchMessages, fetchSettings } from "./lib/api";
import { resolveChannelMasterPreset } from "./lib/channelRuntime";
import { useBridgeEvents } from "./hooks/useBridgeEvents";

function ChannelContent() {
  const activeServer = useAppStore((s) => s.activeServer);
  const activeChannel = useAppStore((s) => s.activeChannel);
  const avatarMode = useAppStore((s) => s.avatarMode);
  const liveMode = useAppStore((s) => s.liveMode);
  const isThinking = useAppStore((s) => s.isThinking);
  const voiceEnabled = useAppStore((s) => s.voiceEnabled);
  const channelSpeechAudio = useAppStore((s) => s.channelSpeechAudio);
  const channelSpeechState = useAppStore((s) => s.channelSpeechState);
  const live2dIdlePreset = useAppStore((s) => s.live2dIdlePreset);
  const live2dIdleIntensity = useAppStore((s) => s.live2dIdleIntensity);
  const channelRuntimeSettings = useAppStore((s) => s.channelRuntimeSettings[activeChannel]);
  const emotion = useAppStore((s) => s.chatEmotion ?? s.character?.dominant_emotion ?? "curiosity");
  const channelAvatarVoiceState = isThinking
    ? "thinking"
    : voiceEnabled
    ? channelSpeechState
    : "idle";

  // Chat server: show chat panel
  if (activeServer === "chat") {
    return (
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0">
          <ChatPanel />
        </div>
        {/*
         * Live2D's Cubism WebGL renderer uses a shared shader singleton. Two
         * canvases cannot safely render at the same time because each Pixi
         * renderer would overwrite that singleton's WebGL context. LiveMode
         * owns the avatar while it is open, so keep the normal chat avatar
         * unmounted until LiveMode closes.
         */}
        {!liveMode && (
          <div className="w-[280px] border-l border-[#3a3d43] bg-[#232428] flex flex-col items-center justify-center p-3 h-full max-h-[600px]">
              {avatarMode === "model" ? (
                <Live2DCanvas
                  idlePreset={channelRuntimeSettings?.avatar_idle_preset || live2dIdlePreset}
                  idleIntensity={channelRuntimeSettings?.avatar_idle_intensity ?? live2dIdleIntensity}
                  lipSync={voiceEnabled}
                  audioElement={voiceEnabled && channelSpeechState === "speaking" ? channelSpeechAudio : null}
                  voiceState={channelAvatarVoiceState}
                  showThinking={true}
                  className="rounded-xl"
                />
              ) : (
                <OrbAnimation
                  isThinking={isThinking}
                  isSpeaking={voiceEnabled && channelSpeechState === "speaking"}
                  emotion={emotion}
                />
              )}
          </div>
        )}
      </div>
    );
  }

  // Discord server
  if (activeServer === "discord") {
    return <DiscordSettingsPanel channel={activeChannel} />;
  }

  // Games server
  if (activeServer === "games") {
    return <GamesPanel channelId={activeChannel} />;
  }

  // Memory server
  if (activeServer === "memory") {
    return <MemoryPanel filter={activeChannel} />;
  }

  // Goals server
  if (activeServer === "goals") {
    return <GoalsPanel channel={activeChannel} />;
  }

  // Skills server
  if (activeServer === "skills") {
    return <SkillsPanel channel={activeChannel} />;
  }

  // Settings server
  if (activeServer === "settings") {
    if (activeChannel === "spotify-integration" || activeChannel === "obs-integration") {
      return <IntegrationsPanel channel={activeChannel} />;
    }
    return <SettingsPanel section={activeChannel} />;
  }

  // Dataswipe is a standalone workspace rather than a channelized server.
  if (activeServer === "datasets") {
    return <DatasetEditorPanel />;
  }

  return <ChatPanel />;
}

export default function App() {
  const setCharacter = useAppStore((s) => s.setCharacter);
  const setSmartExpressions = useAppStore((s) => s.setSmartExpressions);
  const setAvatarModelPath = useAppStore((s) => s.setAvatarModelPath);
  const setLive2DIdlePreset = useAppStore((s) => s.setLive2DIdlePreset);
  const setLive2DIdleIntensity = useAppStore((s) => s.setLive2DIdleIntensity);
  const setAvatarMode = useAppStore((s) => s.setAvatarMode);
  const setConversationId = useAppStore((s) => s.setConversationId);
  const setMessages = useAppStore((s) => s.setMessages);
  const setConnected = useAppStore((s) => s.setConnected);
  const setError = useAppStore((s) => s.setError);
  const error = useAppStore((s) => s.error);
  const liveMode = useAppStore((s) => s.liveMode);
  const activeServer = useAppStore((s) => s.activeServer);
  const activeChannel = useAppStore((s) => s.activeChannel);
  const channels = useAppStore((s) => s.channels);

  // A channel can opt into a master bundle. Resolve it for channel-scoped
  // display when entering the channel; it must not replace the global draft.
  useEffect(() => {
    if (activeServer !== "chat") return;
    const channel = channels.find((item) => item.id === activeChannel);
    if (!channel?.masterPresetId) return;
    void resolveChannelMasterPreset(channel).catch((err) => {
      setError(err instanceof Error ? `Channel preset failed: ${err.message}` : "Channel preset failed");
    });
  }, [activeServer, activeChannel, channels, setError]);

  // Connect to Discord bridge events (real-time sync)
  useBridgeEvents();

  // Play error sound when error state changes
  useEffect(() => {
    if (error) sfxError();
  }, [error]);

  useEffect(() => {
    let cancelled = false;

    async function load(isInitial = false) {
      try {
        const status = await fetchStatus();
        if (cancelled) return;
        setCharacter(status.character);
        // Load the persisted avatar preference at app startup so Live2D uses
        // the configured smart-emotion mode even before Settings is opened.
        fetchSettings()
          .then((settings) => {
            setSmartExpressions(settings.avatar_smart_expressions !== false);
            setAvatarModelPath(settings.avatar_model);
            setLive2DIdlePreset(settings.avatar_idle_preset || "dynamic");
            setLive2DIdleIntensity(settings.avatar_idle_intensity ?? 1);
            setAvatarMode(settings.avatar_model ? "model" : "orb");
          })
          .catch(() => {});
        setConnected(true);
        setError(null);

        const state = useAppStore.getState();
        const activeChannel = state.activeChannel;
        const currentConvId = state.channelConversations[activeChannel] ?? null;
        let bootstrappedGeneral = false;

        // The backend exposes one legacy/default conversation. It belongs to
        // General only; load it there on first boot.
        if (isInitial && !state.channelConversations.general && status.conversation_id) {
          bootstrappedGeneral = true;
          setConversationId("general", status.conversation_id);
          try {
            const msgs = await fetchMessages(status.conversation_id);
            if (!cancelled && msgs.length > 0) setMessages("general", msgs);
          } catch {}
        }

        // On initial load: if backend has a conversation_id and no channel has one yet, assign to active channel
        if (isInitial && activeChannel === "general" && !currentConvId && status.conversation_id && !bootstrappedGeneral) {
          setConversationId(activeChannel, status.conversation_id);
          try {
            const msgs = await fetchMessages(status.conversation_id);
            if (!cancelled && msgs.length > 0) setMessages(activeChannel, msgs);
          } catch {}
        } else if (currentConvId && !state.isThinking) {
          // Poll messages for the active channel's conversation
          try {
            const msgs = await fetchMessages(currentConvId);
            if (!cancelled && msgs.length > 0) {
              const currentLocal = state.channelMessages[activeChannel] ?? [];
              if (currentLocal.length === 0) {
                setMessages(activeChannel, msgs);
              } else if (msgs.length > currentLocal.length) {
                const localIds = new Set(currentLocal.map((m) => m.id));
                const newFromRemote = msgs.filter((m) => !localIds.has(m.id));
                if (newFromRemote.length > 0) {
                  setMessages(activeChannel, [...currentLocal, ...newFromRemote]);
                }
              }
            }
          } catch {}
        }
      } catch (err) {
        if (cancelled) return;
        setConnected(false);
        setError(
          err instanceof Error
            ? err.message
            : "Failed to connect to backend. Is the server running?"
        );
      }
    }

    load(true);
    const interval = setInterval(() => load(false), 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [setCharacter, setSmartExpressions, setAvatarModelPath, setLive2DIdleIntensity, setLive2DIdlePreset, setAvatarMode, setConversationId, setMessages, setConnected, setError]);

  return (
    <div className="h-screen flex overflow-hidden font-display bg-[#1f2023] text-[#f2f3f5]">
      {liveMode && <LiveMode />}

      <Group orientation="horizontal" id="vtuber-layout">
        {/* Server sidebar - fixed width, not resizable */}
        <Panel id="server" defaultSize="72px" minSize="72px" maxSize="72px">
          <ServerSidebar />
        </Panel>

        <Separator className="resize-handle" />

        {/* Dataswipe intentionally has no channel list. */}
        {activeServer !== "datasets" && (
          <>
            <Panel id="channels" defaultSize="240px" minSize="180px" maxSize="400px">
              <ChannelSidebar />
            </Panel>
            <Separator className="resize-handle" />
          </>
        )}

        {/* Main content area - fills remaining space */}
        <Panel id="main" minSize="20%">
          <div className="flex-1 flex flex-col min-w-0 w-full h-full bg-[#313338]">
            {error && (
              <div className="bg-[#f23f43]/10 border-b border-[#f23f43]/30 text-[#ffb4ab] text-xs px-4 py-2 text-center">
                {error}
              </div>
            )}

            {activeServer !== "datasets" && <ChannelHeader />}

            <div className="flex-1 flex min-h-0">
              <ChannelContent />
            </div>
          </div>
        </Panel>
      </Group>
    </div>
  );
}
