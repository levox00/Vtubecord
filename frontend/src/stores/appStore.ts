import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AvatarAction, CharacterPublic, ChatMessage, Settings } from "../types";
import { resolveLive2DModelPath } from "../lib/live2dModels";
import {
  DEFAULT_LIVE2D_IDLE_PRESET,
  getLive2DIdlePreset,
  type Live2DIdlePresetId,
} from "../lib/live2dIdlePresets";

export interface BridgeMessage {
  type: "incoming" | "outgoing";
  channel_id: string;
  guild_id?: string;
  message_id: string;
  author: { name: string; id: string };
  content: string;
  timestamp: string;
  routing_status?: string;
  routing_detail?: string;
}

export type ServerId = "chat" | "discord" | "memory" | "goals" | "skills" | "games" | "settings" | "datasets";

export interface Server {
  id: ServerId;
  label: string;
  color: string;
}

export interface Channel {
  id: string;
  label: string;
  type: "chat" | "list" | "form" | "markdown";
  server: ServerId;
  icon?: string;
  custom?: boolean; // user-created channels can be deleted
  /** Chat channels can be text or voice; legacy channels infer text. */
  kind?: "text" | "voice";
  /** Category id within the channel's server. */
  categoryId?: string;
  /** Optional master preset applied when this channel is used. */
  masterPresetId?: string | null;
}

export interface ChannelCategory {
  id: string;
  label: string;
  server: ServerId;
  custom?: boolean;
}

export const SERVERS: Server[] = [
  { id: "chat", label: "Chat", color: "#5865f2" },
  { id: "discord", label: "Discord", color: "#5865f2" },
  { id: "memory", label: "Memory", color: "#eb459e" },
  { id: "goals", label: "Goals", color: "#fee75c" },
  { id: "skills", label: "Skills", color: "#57f287" },
  { id: "games", label: "Games", color: "#ed4245" },
  { id: "settings", label: "Settings", color: "#9b59b6" },
  { id: "datasets", label: "Datasets", color: "#5865f2" },
];

// Default channels (built-in, cannot be deleted)
const DEFAULT_CHANNELS: Channel[] = [
  // Chat server
  { id: "general", label: "general", type: "chat", kind: "text", categoryId: "text", server: "chat", icon: "#" },
  { id: "live", label: "live", type: "chat", kind: "voice", categoryId: "voice", server: "chat", icon: "#" },
  // Discord server
  { id: "discord-settings", label: "configuration", type: "form", server: "discord", icon: "#" },
  { id: "discord-status", label: "status", type: "form", server: "discord", icon: "#" },
  // Memory server
  { id: "memories", label: "all-memories", type: "list", server: "memory", icon: "#" },
  { id: "episodic", label: "episodic", type: "list", server: "memory", icon: "#" },
  { id: "semantic", label: "semantic", type: "list", server: "memory", icon: "#" },
  { id: "relationships", label: "relationships", type: "list", server: "memory", icon: "#" },
  // Goals server
  { id: "active-goals", label: "active", type: "list", server: "goals", icon: "#" },
  { id: "completed-goals", label: "completed", type: "list", server: "goals", icon: "#" },
  { id: "new-goal", label: "create-goal", type: "form", server: "goals", icon: "#" },
  // Skills server
  { id: "all-skills", label: "all-skills", type: "list", server: "skills", icon: "#" },
  { id: "proficiency", label: "proficiency", type: "list", server: "skills", icon: "#" },
  { id: "new-skill", label: "create-skill", type: "form", server: "skills", icon: "#" },
  // Games server
  { id: "trivia", label: "trivia", type: "chat", server: "games", icon: "#" },
  { id: "20-questions", label: "20-questions", type: "chat", server: "games", icon: "#" },
  { id: "word-game", label: "word-game", type: "chat", server: "games", icon: "#" },
  { id: "story", label: "story-creator", type: "chat", server: "games", icon: "#" },
  { id: "riddles", label: "riddles", type: "chat", server: "games", icon: "#" },
  // Settings server
  { id: "general-settings", label: "general", type: "form", server: "settings", icon: "#" },
  { id: "character-settings", label: "character", type: "form", server: "settings", icon: "#" },
  { id: "llm-settings", label: "llm", type: "form", server: "settings", icon: "#" },
  { id: "tts-settings", label: "tts", type: "form", server: "settings", icon: "#" },
  { id: "stt-settings", label: "speech-to-text / whisper", type: "form", server: "settings", icon: "#" },
  { id: "avatar-settings", label: "avatar", type: "form", server: "settings", icon: "#" },
  { id: "memory-settings", label: "memory", type: "form", server: "settings", icon: "#" },
  { id: "spotify-integration", label: "spotify", type: "form", server: "settings", icon: "#" },
  { id: "obs-integration", label: "obs studio", type: "form", server: "settings", icon: "#" },
  { id: "master-presets", label: "master presets", type: "form", server: "settings", icon: "#" },
  { id: "logs", label: "logs", type: "form", server: "settings", icon: "#" },
];

const DEFAULT_CATEGORIES: ChannelCategory[] = [
  { id: "text", label: "Text Channels", server: "chat" },
  { id: "voice", label: "Voice Channels", server: "chat" },
];

export type ChannelSpeechState = "idle" | "processing" | "speaking";

interface AppState {
  character: CharacterPublic | null;
  /** Per-channel message history — keyed by channel ID */
  channelMessages: Record<string, ChatMessage[]>;
  /** Per-channel backend conversation ID — keyed by channel ID */
  channelConversations: Record<string, string | null>;
  isThinking: boolean;
  isConnected: boolean;
  error: string | null;
  activeServer: ServerId;
  activeChannel: string;
  previousServer: ServerId;
  previousChannel: string;
  collapsedCategories: Record<string, boolean>;
  liveMode: boolean;
  channels: Channel[];
  categories: ChannelCategory[];
  voiceEnabled: boolean;
  /** Transient TTS playback shared by channel chat and its Live2D view. */
  channelSpeechAudio: HTMLAudioElement | null;
  channelSpeechState: ChannelSpeechState;
  isMuted: boolean;
  isDeafened: boolean;
  notificationsEnabled: boolean;
  /** Real-time emotion from last chat response — drives Live2D immediately */
  chatEmotion: string | null;
  /** High-intensity expressive label (laughing, crying, etc.) from last chat response */
  expressiveLabel: string | null;
  /** Safe semantic command for the Live2D animation layer. */
  avatarAction: AvatarAction | null;
  /** Avatar display mode: "model" (Live2D) or "orb" (CSS fallback) */
  avatarMode: "model" | "orb";
  /** Active .model3.json path, synchronized from the applied avatar preset. */
  avatarModelPath: string;
  live2dIdlePreset: Live2DIdlePresetId;
  live2dIdleIntensity: number;
  smartExpressions: boolean;
  /** Bridge state — real-time Discord sync */
  bridgeConnected: boolean;
  bridgeMessages: BridgeMessage[];
  bridgeVoiceState: any;
  bridgeDiscordConfig: Record<string, any> | null;
  /** Current in-memory settings draft shared by Settings and chat quick controls. */
  settingsDraft: Settings | null;
  /** Last settings snapshot confirmed by the backend. */
  settingsPersisted: Settings | null;
  /** Resolved master settings used only while a channel is active. */
  channelRuntimeSettings: Record<string, Settings | null>;
  channelRuntimePresetNames: Record<string, string | null>;

  setCharacter: (c: CharacterPublic) => void;
  addMessage: (channelId: string, m: ChatMessage) => void;
  setMessages: (channelId: string, msgs: ChatMessage[]) => void;
  clearChannelHistory: (channelId: string) => void;
  renameCharacterInHistories: (profileId: string, name: string) => void;
  getMessages: (channelId: string) => ChatMessage[];
  getConversationId: (channelId: string) => string | null;
  setConversationId: (channelId: string, id: string | null) => void;
  setThinking: (v: boolean) => void;
  setConnected: (v: boolean) => void;
  setError: (e: string | null) => void;
  setActiveServer: (server: ServerId) => void;
  setActiveChannel: (channel: string) => void;
  setNavigation: (server: ServerId, channel: string) => void;
  toggleNav: (targetServer: ServerId, targetChannel: string) => void;
  toggleCategory: (cat: string) => void;
  setLiveMode: (v: boolean) => void;
  setVoiceEnabled: (v: boolean) => void;
  setChannelSpeech: (audio: HTMLAudioElement | null, state: ChannelSpeechState) => void;
  clearChannelSpeech: (expectedAudio?: HTMLAudioElement) => void;
  setIsMuted: (v: boolean) => void;
  setIsDeafened: (v: boolean) => void;
  setNotificationsEnabled: (v: boolean) => void;
  setChatEmotion: (e: string | null) => void;
  setExpressiveLabel: (l: string | null) => void;
  setAvatarAction: (action: AvatarAction | null) => void;
  setAvatarMode: (m: "model" | "orb") => void;
  setAvatarModelPath: (path: string) => void;
  setLive2DIdlePreset: (preset: string) => void;
  setLive2DIdleIntensity: (intensity: number) => void;
  setSmartExpressions: (v: boolean) => void;
  addBridgeMessage: (msg: BridgeMessage) => void;
  setBridgeConnected: (v: boolean) => void;
  setBridgeVoiceState: (v: any) => void;
  setBridgeDiscordConfig: (v: Record<string, any> | null) => void;
  setSettingsDraft: (settings: Settings | null) => void;
  setSettingsPersisted: (settings: Settings | null) => void;
  setChannelRuntime: (channelId: string, settings: Settings | null, presetName?: string | null) => void;
  renameChannel: (channelId: string, newLabel: string) => void;
  deleteChannel: (channelId: string) => void;
  addChannel: (channel: Omit<Channel, "custom"> & { custom?: boolean }) => void;
  updateChannel: (channelId: string, patch: Partial<Pick<Channel, "label" | "kind" | "categoryId" | "masterPresetId">>) => void;
  renameCategory: (categoryId: string, newLabel: string) => void;
  deleteCategory: (categoryId: string) => void;
  addCategory: (category: Omit<ChannelCategory, "custom"> & { custom?: boolean }) => void;
  isDefaultChannel: (channelId: string) => boolean;
  isDefaultCategory: (categoryId: string) => boolean;
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      character: null,
      channelMessages: {},
      channelConversations: {},
      isThinking: false,
      isConnected: false,
      error: null,
      activeServer: "chat",
      activeChannel: "general",
      previousServer: "chat",
      previousChannel: "general",
      collapsedCategories: {},
      liveMode: false,
      channels: [...DEFAULT_CHANNELS],
      categories: [...DEFAULT_CATEGORIES],
      voiceEnabled: true,
      channelSpeechAudio: null,
      channelSpeechState: "idle",
      isMuted: false,
      isDeafened: false,
      notificationsEnabled: true,
      chatEmotion: null,
      expressiveLabel: null,
      avatarAction: null,
      avatarMode: "model",
      avatarModelPath: resolveLive2DModelPath(),
      live2dIdlePreset: DEFAULT_LIVE2D_IDLE_PRESET,
      live2dIdleIntensity: 1,
      smartExpressions: true,
      bridgeConnected: false,
      bridgeMessages: [],
      bridgeVoiceState: null,
      bridgeDiscordConfig: null,
      settingsDraft: null,
      settingsPersisted: null,
      channelRuntimeSettings: {},
      channelRuntimePresetNames: {},

      setCharacter: (c) => set({ character: c }),

      addMessage: (channelId, m) =>
        set((s) => ({
          channelMessages: {
            ...s.channelMessages,
            [channelId]: [...(s.channelMessages[channelId] ?? []), m],
          },
        })),

      setMessages: (channelId, msgs) =>
        set((s) => ({
          channelMessages: {
            ...s.channelMessages,
            [channelId]: msgs,
          },
        })),

      clearChannelHistory: (channelId) =>
        set((s) => {
          const channelMessages = { ...s.channelMessages };
          const channelConversations = { ...s.channelConversations };
          delete channelMessages[channelId];
          delete channelConversations[channelId];
          return { channelMessages, channelConversations };
        }),

      renameCharacterInHistories: (profileId, name) =>
        set((s) => ({
          channelMessages: Object.fromEntries(
            Object.entries(s.channelMessages).map(([channelId, messages]) => [
              channelId,
              messages.map((message) =>
                message.character_profile_id === profileId
                  ? { ...message, character_name: name }
                  : message,
              ),
            ]),
          ),
        })),

      getMessages: (channelId) => {
        return get().channelMessages[channelId] ?? [];
      },

      getConversationId: (channelId) => {
        return get().channelConversations[channelId] ?? null;
      },

      setConversationId: (channelId, id) =>
        set((s) => ({
          channelConversations: {
            ...s.channelConversations,
            [channelId]: id,
          },
        })),

      setThinking: (v) => set({ isThinking: v }),
      setConnected: (v) => set({ isConnected: v }),
      setError: (e) => set({ error: e }),
      setActiveServer: (server) => set((s) => ({
        previousServer: s.activeServer,
        previousChannel: s.activeChannel,
        activeServer: server
      })),
      setActiveChannel: (channel) => set((s) => ({
        previousServer: s.activeServer,
        previousChannel: s.activeChannel,
        activeChannel: channel
      })),
      setNavigation: (server, channel) => set((s) => ({
        previousServer: s.activeServer,
        previousChannel: s.activeChannel,
        activeServer: server,
        activeChannel: channel,
      })),
      toggleNav: (targetServer, targetChannel) => {
        const state = get();
        if (state.activeServer === targetServer && state.activeChannel === targetChannel) {
          // Toggle off -> return to previous
          set({
            activeServer: state.previousServer || "chat",
            activeChannel: state.previousChannel || "general",
          });
        } else {
          // Toggle on -> switch to target and remember current
          set({
            previousServer: state.activeServer,
            previousChannel: state.activeChannel,
            activeServer: targetServer,
            activeChannel: targetChannel,
          });
        }
      },
      toggleCategory: (cat) =>
        set((s) => ({
          collapsedCategories: {
            ...s.collapsedCategories,
            [cat]: !s.collapsedCategories[cat],
          },
        })),
      setLiveMode: (v) => set({ liveMode: v }),
      setVoiceEnabled: (v) => set({ voiceEnabled: v }),
      setChannelSpeech: (audio, state) => set({
        channelSpeechAudio: audio,
        channelSpeechState: state,
      }),
      clearChannelSpeech: (expectedAudio) => set((state) => {
        if (expectedAudio && state.channelSpeechAudio !== expectedAudio) return {};
        return { channelSpeechAudio: null, channelSpeechState: "idle" };
      }),
      setIsMuted: (v) => set({ isMuted: v }),
      setIsDeafened: (v) => set({ isDeafened: v }),
      setNotificationsEnabled: (v) => set({ notificationsEnabled: v }),
      setChatEmotion: (e) => set({ chatEmotion: e }),
      setExpressiveLabel: (l) => set({ expressiveLabel: l }),
      setAvatarAction: (action) => set({ avatarAction: action }),
      setAvatarMode: (m) => set({ avatarMode: m }),
      setAvatarModelPath: (path) => set({ avatarModelPath: resolveLive2DModelPath(path) }),
      setLive2DIdlePreset: (preset) => set({ live2dIdlePreset: getLive2DIdlePreset(preset).id }),
      setLive2DIdleIntensity: (intensity) => set({
        live2dIdleIntensity: Math.min(2, Math.max(0.25, Number(intensity) || 1)),
      }),
      setSmartExpressions: (v) => set({ smartExpressions: v }),
      addBridgeMessage: (msg) =>
        set((s) => ({
          bridgeMessages: [...s.bridgeMessages.slice(-99), msg],
        })),
      setBridgeConnected: (v) => set({ bridgeConnected: v }),
      setBridgeVoiceState: (v) => set({ bridgeVoiceState: v }),
      setBridgeDiscordConfig: (v) => set({ bridgeDiscordConfig: v }),
      setSettingsDraft: (settings) => set({ settingsDraft: settings }),
      setSettingsPersisted: (settings) => set({ settingsPersisted: settings }),
      setChannelRuntime: (channelId, settings, presetName = null) => set((state) => ({
        channelRuntimeSettings: { ...state.channelRuntimeSettings, [channelId]: settings },
        channelRuntimePresetNames: { ...state.channelRuntimePresetNames, [channelId]: presetName },
      })),

      renameChannel: (channelId, newLabel) =>
        set((s) => ({
          channels: s.channels.map((ch) =>
            ch.id === channelId ? { ...ch, label: newLabel } : ch
          ),
        })),

      deleteChannel: (channelId) =>
        set((s) => {
          const ch = s.channels.find((c) => c.id === channelId);
          if (!ch || !ch.custom) return s;
          const newChannels = s.channels.filter((c) => c.id !== channelId);
          const channelMessages = { ...s.channelMessages };
          const channelConversations = { ...s.channelConversations };
          delete channelMessages[channelId];
          delete channelConversations[channelId];
          const newActive = s.activeChannel === channelId ? "general" : s.activeChannel;
          return { channels: newChannels, channelMessages, channelConversations, activeChannel: newActive };
        }),

      addChannel: (channel) =>
        set((s) => ({
          channels: [...s.channels, { ...channel, custom: true }],
        })),

      updateChannel: (channelId, patch) =>
        set((s) => ({
          channels: s.channels.map((channel) =>
            channel.id === channelId ? { ...channel, ...patch } : channel
          ),
        })),

      renameCategory: (categoryId, newLabel) =>
        set((s) => ({
          categories: s.categories.map((category) =>
            category.id === categoryId ? { ...category, label: newLabel } : category
          ),
        })),

      deleteCategory: (categoryId) =>
        set((s) => {
          const category = s.categories.find((item) => item.id === categoryId);
          if (!category || !category.custom) return s;
          const fallback = category.server === "chat" ? "text" : undefined;
          return {
            categories: s.categories.filter((item) => item.id !== categoryId),
            channels: fallback
              ? s.channels.map((channel) => channel.categoryId === categoryId ? { ...channel, categoryId: channel.kind === "voice" ? "voice" : fallback } : channel)
              : s.channels,
          };
        }),

      addCategory: (category) =>
        set((s) => ({
          categories: [...s.categories, { ...category, custom: true }],
        })),

      isDefaultChannel: (channelId) => {
        return DEFAULT_CHANNELS.some((ch) => ch.id === channelId);
      },
      isDefaultCategory: (categoryId) => {
        return DEFAULT_CATEGORIES.some((category) => category.id === categoryId);
      },
    }),
    {
      name: "ai-vtuber-ui",
      partialize: (state) => ({
        activeServer: state.activeServer,
        activeChannel: state.activeChannel,
        previousServer: state.previousServer,
        previousChannel: state.previousChannel,
        channelMessages: state.channelMessages,
        channelConversations: state.channelConversations,
        collapsedCategories: state.collapsedCategories,
        channels: state.channels,
        categories: state.categories,
        voiceEnabled: state.voiceEnabled,
        isMuted: state.isMuted,
        isDeafened: state.isDeafened,
        notificationsEnabled: state.notificationsEnabled,
        live2dIdlePreset: state.live2dIdlePreset,
        live2dIdleIntensity: state.live2dIdleIntensity,
        smartExpressions: state.smartExpressions,
      }),
      merge: (persistedState: any, currentState: AppState) => {
        if (!persistedState) return currentState;

        // Migrate old flat messages/conversationId to per-channel format
        if (persistedState.messages && !persistedState.channelMessages) {
          persistedState.channelMessages = { general: persistedState.messages };
          delete persistedState.messages;
        }
        if (persistedState.conversationId && !persistedState.channelConversations) {
          persistedState.channelConversations = { general: persistedState.conversationId };
          delete persistedState.conversationId;
        }

        // Remove legacy profile-only channels. General and Live are now the
        // only built-in chat channels; custom channels remain intact.
        const channelMessages = { ...(persistedState.channelMessages || {}) };
        const channelConversations = { ...(persistedState.channelConversations || {}) };
        delete channelMessages.avatar;
        delete channelMessages.character;
        delete channelConversations.avatar;
        delete channelConversations.character;

        const removedPresetChannels = new Set(["llm-presets", "tts-presets", "avatar-presets", "whisper-presets"]);
        const savedChannels: Channel[] = (persistedState.channels || [])
          .filter((channel: Channel) => !removedPresetChannels.has(channel.id))
          .filter((channel: Channel) => channel.id !== "dataset-editor")
          .filter((channel: Channel) => channel.id !== "avatar" && channel.id !== "character")
          .map((channel: Channel) => ({
            ...channel,
            kind: channel.kind ?? (channel.id === "live" ? "voice" : "text"),
            categoryId: channel.categoryId ?? (channel.id === "live" ? "voice" : channel.server === "chat" ? "text" : undefined),
          })
        );
        const savedIds = new Set(savedChannels.map((c) => c.id));
        // Merge missing default channels from DEFAULT_CHANNELS
        const mergedChannels = [...savedChannels];
        for (const def of DEFAULT_CHANNELS) {
          if (!savedIds.has(def.id)) {
            mergedChannels.push(def);
          }
        }
        const savedCategories: ChannelCategory[] = (persistedState.categories || [])
          .filter((category: ChannelCategory) => category.server !== "chat" || category.id !== "character")
          .map((category: ChannelCategory) => ({ ...category }));
        const savedCategoryIds = new Set(savedCategories.map((category) => category.id));
        const mergedCategories = [...savedCategories];
        for (const def of DEFAULT_CATEGORIES) {
          if (!savedCategoryIds.has(def.id)) mergedCategories.push(def);
        }
        const oldPresetChannelIds = new Set(["llm-presets", "tts-presets", "avatar-presets", "whisper-presets"]);
        const migratedActiveServer: ServerId = persistedState.activeServer === "settings" && persistedState.activeChannel === "dataset-editor"
          ? "datasets"
          : persistedState.activeServer;
        const migratedPreviousServer: ServerId = persistedState.previousServer === "settings" && persistedState.previousChannel === "dataset-editor"
          ? "datasets"
          : persistedState.previousServer;
        return {
          ...currentState,
          ...persistedState,
          activeServer: migratedActiveServer || currentState.activeServer,
          previousServer: migratedPreviousServer || currentState.previousServer,
          channelMessages,
          channelConversations,
          channels: mergedChannels,
          categories: mergedCategories,
          activeChannel: oldPresetChannelIds.has(persistedState.activeChannel) || persistedState.activeChannel === "avatar" || persistedState.activeChannel === "character" ? "general" : persistedState.activeChannel,
          previousChannel: oldPresetChannelIds.has(persistedState.previousChannel) || persistedState.previousChannel === "avatar" || persistedState.previousChannel === "character" ? "general" : persistedState.previousChannel,
        };
      },
    }
  )
);
