import { useState } from "react";
import {
  MessageSquare,
  Brain,
  Target,
  Zap,
  Gamepad2,
  Settings,
  Radio,
  Database,
} from "lucide-react";
import { useAppStore, SERVERS, type ServerId } from "../stores/appStore";

function DiscordIcon({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
      <path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286z" />
    </svg>
  );
}

const SERVER_ICONS: Record<ServerId, React.ElementType> = {
  chat: MessageSquare,
  discord: DiscordIcon,
  memory: Brain,
  goals: Target,
  skills: Zap,
  games: Gamepad2,
  settings: Settings,
  datasets: Database,
};

const SERVER_DESCRIPTIONS: Record<ServerId, string> = {
  chat: "Chat with AI",
  discord: "Discord bot integration",
  memory: "Memories & knowledge",
  goals: "Active goals",
  skills: "Skills & proficiency",
  games: "Mini games",
  settings: "Configure settings",
  datasets: "Curate and export training datasets",
};

export function ServerSidebar() {
  const activeServer = useAppStore((s) => s.activeServer);
  const setActiveServer = useAppStore((s) => s.setActiveServer);
  const setActiveChannel = useAppStore((s) => s.setActiveChannel);
  const liveMode = useAppStore((s) => s.liveMode);
  const setLiveMode = useAppStore((s) => s.setLiveMode);
  const isConnected = useAppStore((s) => s.isConnected);

  const [hoveredServer, setHoveredServer] = useState<ServerId | "live" | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  function handleServerClick(id: ServerId) {
    setActiveServer(id);
    const defaults: Record<ServerId, string> = {
      chat: "general",
      discord: "discord-settings",
      memory: "memories",
      goals: "active-goals",
      skills: "all-skills",
      games: "trivia",
      settings: "general-settings",
      datasets: "",
    };
    setActiveChannel(defaults[id]);
  }

  function handleMouseEnter(e: React.MouseEvent, id: string, _label: string, _desc: string) {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setTooltipPos({ x: rect.right + 12, y: rect.top + rect.height / 2 });
    setHoveredServer(id as ServerId);
  }

  const tooltipLabel = hoveredServer === "live"
    ? "Live Voice"
    : hoveredServer
    ? SERVERS.find((s) => s.id === hoveredServer)?.label ?? hoveredServer
    : "";
  const tooltipDesc = hoveredServer === "live"
    ? "Voice conversation mode"
    : hoveredServer
    ? SERVER_DESCRIPTIONS[hoveredServer as ServerId] ?? ""
    : "";

  return (
    <div className="w-full h-full bg-[#1e1f22] flex flex-col items-center justify-start pt-3 gap-2 overflow-y-auto shrink-0 border-r border-[#2b2d31]">
      {/* Live mode button - TOP */}
      <button
        onClick={() => {
          const next = !liveMode;
          setLiveMode(next);
          if (next) {
            setActiveServer("chat");
            setActiveChannel("live");
          }
        }}
        className="relative group"
        onMouseEnter={(e) => handleMouseEnter(e, "live", "Live Voice", "Voice conversation mode")}
        onMouseLeave={() => setHoveredServer(null)}
      >
        {liveMode && (
          <span className="absolute left-[-4px] top-1/2 -translate-y-1/2 w-1 h-10 bg-white rounded-r-full" />
        )}
        <div
          className={`w-12 h-12 rounded-3xl flex items-center justify-center transition-all duration-200 ${
            liveMode
              ? "rounded-xl bg-[#3f4147] ring-1 ring-[#6f7480]"
              : "bg-[#2b2d31] hover:bg-[#3f4147] hover:rounded-xl"
          }`}
        >
          <Radio size={20} className={`text-white ${liveMode ? "animate-pulse" : ""}`} />
        </div>
      </button>

      <div className="w-8 h-0.5 bg-[#35363c] rounded-full my-0.5" />

      {/* Home / DM button */}
      <button
        onClick={() => {
          setActiveServer("chat");
          setActiveChannel("general");
        }}
        className="relative group"
        onMouseEnter={(e) => handleMouseEnter(e, "chat", "Chat", "Chat with AI")}
        onMouseLeave={() => setHoveredServer(null)}
      >
        {activeServer === "chat" && (
          <span className="absolute left-[-4px] top-1/2 -translate-y-1/2 w-1 h-10 bg-white rounded-r-full" />
        )}
        <div
          className={`w-12 h-12 rounded-3xl flex items-center justify-center transition-all duration-200 ${
            activeServer === "chat"
              ? "rounded-xl bg-[#3f4147] ring-1 ring-[#6f7480]"
              : "bg-[#2b2d31] hover:bg-[#3f4147] hover:rounded-xl"
          }`}
        >
          <MessageSquare size={20} className="text-white" />
        </div>
        <span
          className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-[#1e1f22] ${
            isConnected ? "bg-[#23a55a]" : "bg-[#f23f43]"
          }`}
        />
      </button>

      <div className="w-8 h-0.5 bg-[#35363c] rounded-full my-0.5" />

      {/* Server icons */}
      {SERVERS.filter((s) => s.id !== "chat").map((server) => {
        const Icon = SERVER_ICONS[server.id];
        const active = activeServer === server.id;

        return (
          <button
            key={server.id}
            onClick={() => handleServerClick(server.id)}
            onMouseEnter={(e) => handleMouseEnter(e, server.id, server.label, SERVER_DESCRIPTIONS[server.id])}
            onMouseLeave={() => setHoveredServer(null)}
            className="relative group"
          >
            {active && (
              <span className="absolute left-[-4px] top-1/2 -translate-y-1/2 w-1 h-10 bg-white rounded-r-full transition-all duration-200" />
            )}
            <div
              className={`w-12 h-12 rounded-3xl flex items-center justify-center transition-all duration-200 ${
                active
                  ? "rounded-xl bg-[#3f4147] ring-1 ring-[#6f7480]"
                  : "bg-[#2b2d31] hover:rounded-xl hover:bg-[#3f4147]"
              }`}
            >
              <Icon size={20} className={active ? "text-white" : "text-[#b5bac1]"} />
            </div>
          </button>
        );
      })}

      {/* Tooltip */}
      {hoveredServer && (
        <div
          className="fixed z-[200] pointer-events-none"
          style={{
            left: tooltipPos.x,
            top: tooltipPos.y,
            transform: "translateY(-50%)",
          }}
        >
          <div className="bg-[#111214] border border-[#1f2023] rounded-lg px-3 py-2 shadow-xl whitespace-nowrap">
            <div className="text-sm font-semibold text-white">{tooltipLabel}</div>
            <div className="text-[11px] text-[#949ba4]">{tooltipDesc}</div>
          </div>
        </div>
      )}
    </div>
  );
}
