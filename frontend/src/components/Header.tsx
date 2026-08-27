import { useAppStore } from "../stores/appStore";
import { Radio, Cpu, Wifi, WifiOff } from "lucide-react";

export function Header() {
  const character = useAppStore((s) => s.character);
  const isConnected = useAppStore((s) => s.isConnected);
  const setLiveMode = useAppStore((s) => s.setLiveMode);
  const isThinking = useAppStore((s) => s.isThinking);

  return (
    <header className="flex items-center justify-between px-4 py-2.5 border-b border-white/5 bg-[#12121a]/80 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-violet-500/20">
          {character?.name?.[0] ?? "A"}
        </div>
        <div>
          <h1 className="text-sm font-semibold text-white/90 tracking-wide">
            {character?.name ?? "Loading..."}
          </h1>
          <p className="text-[10px] text-white/30">AI Character</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Model info badge */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/5 border border-white/5">
          <Cpu size={12} className="text-violet-400" />
          <span className="text-[10px] text-white/40 font-mono">
            {character?.model_name?.split("\\").pop()?.split("/").pop()?.substring(0, 20) ?? "..."}
          </span>
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-1.5">
          {isConnected ? (
            <Wifi size={14} className="text-emerald-400" />
          ) : (
            <WifiOff size={14} className="text-red-400" />
          )}
        </div>

        {/* Live mode button */}
        <button
          onClick={() => setLiveMode(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/10 border border-violet-500/20 text-violet-400 hover:bg-violet-500/20 hover:border-violet-500/30 transition-all text-xs font-medium"
          title="Enter live mode"
        >
          <Radio size={14} className={isThinking ? "animate-pulse" : ""} />
          <span className="hidden sm:inline">Live</span>
        </button>
      </div>
    </header>
  );
}
