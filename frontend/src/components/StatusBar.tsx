import { useAppStore } from "../stores/appStore";
import { Activity, Loader2, CheckCircle2 } from "lucide-react";

export function StatusBar() {
  const character = useAppStore((s) => s.character);
  const isThinking = useAppStore((s) => s.isThinking);
  const isConnected = useAppStore((s) => s.isConnected);

  return (
    <div className="flex items-center gap-3 px-4 py-1.5 border-t border-white/5 bg-[#0e0e16] text-[10px] text-white/30">
      <div className="flex items-center gap-1.5">
        {isThinking ? (
          <Loader2 size={10} className="text-violet-400 animate-spin" />
        ) : (
          <CheckCircle2 size={10} className="text-emerald-400/60" />
        )}
        <span>{isThinking ? "Processing" : "Ready"}</span>
      </div>

      <span className="text-white/10">|</span>

      <div className="flex items-center gap-1.5">
        <Activity size={10} className="text-white/20" />
        <span>
          Emotion: <span className="text-violet-400/70 capitalize">{character?.dominant_emotion ?? "neutral"}</span>
        </span>
      </div>

      <span className="text-white/10">|</span>

      <div className="flex items-center gap-1.5">
        <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? "bg-emerald-400/60" : "bg-red-400/60"}`} />
        <span>{isConnected ? "Connected" : "Disconnected"}</span>
      </div>
    </div>
  );
}
