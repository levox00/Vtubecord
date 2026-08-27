import { fetchPresets, resolvePreset } from "./api";
import { useAppStore, type Channel } from "../stores/appStore";
import type { Settings } from "../types";

const inFlight = new Map<string, Promise<Settings>>();

/**
 * Resolve a channel's optional master bundle for display and request routing.
 * This deliberately does not call the global preset-apply endpoint: channel
 * bundles are overlays, not changes to the settings editor's active draft.
 */
export function resolveChannelMasterPreset(channel: Channel | undefined): Promise<Settings | null> {
  const presetId = channel?.masterPresetId?.trim();
  if (!presetId) {
    if (channel?.id) useAppStore.getState().setChannelRuntime(channel.id, null, null);
    return Promise.resolve(null);
  }

  const key = `${channel?.id ?? "channel"}:${presetId}`;
  const existing = inFlight.get(key);
  if (existing) return existing;

  const request = Promise.all([resolvePreset(presetId), fetchPresets()])
    .then(([settings, presets]) => {
      const master = presets.find((preset) => preset.id === presetId);
      const store = useAppStore.getState();
      const channelSettings = master?.data?.avatar_preset_id || Object.prototype.hasOwnProperty.call(master?.data ?? {}, "avatar_model")
        ? settings
        : { ...settings, avatar_model: "" };
      store.setChannelRuntime(channel?.id ?? "channel", channelSettings, master?.name ?? null);
      return channelSettings;
    })
    .finally(() => inFlight.delete(key));

  inFlight.set(key, request);
  return request;
}
