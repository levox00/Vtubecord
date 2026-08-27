import { useEffect, useState } from "react";
import { useAppStore } from "../stores/appStore";
import { Hash, Settings, Bookmark, Bell, Pin, Search, HelpCircle, Volume2, VolumeX, Volume } from "lucide-react";
import { ResourceMonitorPopover } from "./ResourceMonitorPopover";

export function ChannelHeader() {
  const activeChannel = useAppStore((s) => s.activeChannel);
  const activeServer = useAppStore((s) => s.activeServer);
  const channels = useAppStore((s) => s.channels);
  const toggleNav = useAppStore((s) => s.toggleNav);
  const voiceEnabled = useAppStore((s) => s.voiceEnabled);
  const setVoiceEnabled = useAppStore((s) => s.setVoiceEnabled);
  const liveMode = useAppStore((s) => s.liveMode);
  const channelRuntimePresetNames = useAppStore((s) => s.channelRuntimePresetNames);
  const channel = channels.find((c) => c.id === activeChannel);
  const [monitorOpen, setMonitorOpen] = useState(false);

  // Live AI owns the screen while active, so close a monitor that was opened in
  // the regular UI. It remains open across channel changes until explicitly
  // closed otherwise.
  useEffect(() => {
    if (liveMode) setMonitorOpen(false);
  }, [liveMode]);

  function handleToggleLogs() {
    toggleNav("settings", "logs");
  }

  function handleTogglePresets() {
    toggleNav("settings", "master-presets");
  }

  return (
    <div className="h-14 px-4 flex items-center justify-between border-b border-[#3a3d43] bg-[#2b2d31] shrink-0">
      <div className="flex min-w-0 items-center gap-2">
        {channel?.type === "form" ? (
          <Settings size={17} className="text-[#949ba4]" />
        ) : channel?.kind === "voice" ? (
          <Volume size={17} className="text-[#949ba4]" />
        ) : (
          <Hash size={17} className="text-[#949ba4]" />
        )}
        <div className="min-w-0">
          <span className="block text-sm font-semibold text-[#f2f3f5] truncate">{channel?.label ?? "channel"}</span>
          {channel?.type === "chat" && <span className="block text-[10px] text-[#6d6f78] truncate max-w-[360px]">{channel.masterPresetId ? `Channel preset: ${channelRuntimePresetNames[activeChannel] || "loading…"}` : getChannelDescription(activeChannel, channel.kind)}</span>}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5">
        {/* Quick TTS Voice Toggle */}
        <button
          onClick={() => setVoiceEnabled(!voiceEnabled)}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
            voiceEnabled
              ? "bg-[#3f4147] text-[#f2f3f5] border border-[#5865f2]/60 hover:bg-[#4e5058]"
              : "bg-[#1e1f22] border border-[#3a3d43] text-[#949ba4] hover:text-[#dbdee1] hover:bg-[#35373c]"
          }`}
          title={voiceEnabled ? "AI Voice Responses are ON (Click to mute)" : "AI Voice Responses are OFF (Click to unmute)"}
        >
          {voiceEnabled ? <Volume2 size={15} /> : <VolumeX size={15} />}
          <span>{voiceEnabled ? "Voice ON" : "Voice OFF"}</span>
        </button>

        <span className="w-px h-4 bg-[#3f4147] mx-0.5" />

        <button
          onClick={handleToggleLogs}
          className={`p-1.5 rounded hover:bg-[#35373c] transition-colors ${
            activeServer === "settings" && activeChannel === "logs" ? "text-[#dbdee1] bg-[#3f4147]" : "text-[#b5bac1]"
          }`}
          title="Toggle system logs"
        >
          <Bell size={18} />
        </button>
        <div className="relative">
          <button
            onClick={() => setMonitorOpen((open) => !open)}
            className={`p-1.5 rounded hover:bg-[#35373c] transition-colors ${monitorOpen ? "text-[#dbdee1] bg-[#3f4147]" : "text-[#b5bac1]"}`}
            title={monitorOpen ? "Close resource monitor" : "Open resource monitor"}
            aria-label={monitorOpen ? "Close resource monitor" : "Open resource monitor"}
            aria-expanded={monitorOpen}
          >
            <Pin size={18} />
          </button>
          {monitorOpen && !liveMode && <ResourceMonitorPopover onClose={() => setMonitorOpen(false)} />}
        </div>
        <button
          onClick={handleTogglePresets}
          className={`p-1.5 rounded hover:bg-[#35373c] transition-colors ${
            activeServer === "settings" && activeChannel === "master-presets" ? "text-[#dbdee1] bg-[#3f4147]" : "text-[#b5bac1]"
          }`}
          title="Open master presets"
        >
          <Bookmark size={18} />
        </button>
        <div className="relative ml-1">
          <input
            placeholder="Search"
            className="w-36 h-8 bg-[#1e1f22] border border-[#3a3d43] rounded-md px-2.5 text-xs text-[#dbdee1] placeholder:text-[#6d6f78] focus:outline-none focus:border-[#5865f2] focus:w-56 transition-all"
          />
          <Search size={14} className="absolute right-2 top-1/2 -translate-y-1/2 text-[#949ba4]" />
        </div>
        <button
          className="p-1.5 rounded hover:bg-[#35373c] text-[#b5bac1] transition-colors"
          title="Help (coming soon)"
        >
          <HelpCircle size={18} />
        </button>
      </div>
    </div>
  );
}

function getChannelDescription(channelId: string, kind?: "text" | "voice"): string {
  if (kind === "voice") return "Voice-enabled live conversation mode";
  const descriptions: Record<string, string> = {
    general: "General chat with your AI companion",
    live: "Voice-enabled live conversation mode",
    character: "Character profile and personality",
    memories: "All character memories",
    episodic: "Event-based memories",
    semantic: "Factual knowledge",
    relationships: "People and relationship data",
    "active-goals": "Currently active goals",
    "completed-goals": "Finished goals",
    "new-goal": "Create a new goal",
    "all-skills": "All learned skills",
    proficiency: "Skill proficiency tracking",
    "new-skill": "Add a new skill",
    trivia: "Test your knowledge together",
    "20-questions": "Think of something, I'll guess",
    "word-game": "Word association game",
    story: "Collaborative story creation",
    riddles: "Riddles and brain teasers",
    "general-settings": "General configuration",
    "character-settings": "Character personality settings",
    "llm-settings": "Language model configuration",
    "tts-settings": "Text-to-speech engine and voice settings",
    "stt-settings": "Whisper speech-to-text model studio & hardware tuning",
    "avatar-settings": "Avatar and appearance settings",
    "memory-settings": "Memory system settings",
    logs: "Recent system events",
    "master-presets": "Combine engine presets and a character persona",
  };
  return descriptions[channelId] || "";
}
