import { useAppStore } from "../stores/appStore";
import { Live2DCanvas } from "./Live2DCanvas";
import {
  Smile,
  Frown,
  Angry,
  Zap,
  Eye,
  Brain,
  Shield,
} from "lucide-react";

const EMOTION_CONFIG: Record<string, { color: string; icon: React.ElementType }> = {
  happiness:   { color: "text-[#b5bac1]", icon: Smile },
  excitement:  { color: "text-[#dbdee1]", icon: Zap },
  sadness:     { color: "text-[#949ba4]", icon: Frown },
  anger:       { color: "text-[#ffb4ab]", icon: Angry },
  fear:        { color: "text-[#b5bac1]", icon: Shield },
  curiosity:   { color: "text-[#dbdee1]", icon: Eye },
  confidence:  { color: "text-[#dbdee1]", icon: Shield },
  frustration: { color: "text-[#ffb4ab]", icon: Angry },
};

export function AvatarPanel() {
  const character = useAppStore((s) => s.character);
  const emotion = character?.dominant_emotion ?? "curiosity";
  const emotionCfg = EMOTION_CONFIG[emotion] ?? { color: "text-[#5865f2]", icon: Brain };
  const EmotionIcon = emotionCfg.icon;

  return (
    <div className="flex flex-col items-center justify-center h-full relative p-4 bg-[#232428]">
      <div className="relative w-full max-w-[280px] aspect-[3/4] rounded-xl bg-[#1e1f22] border border-[#3a3d43] overflow-hidden shadow-lg">
        <Live2DCanvas />
      </div>

      {/* Emotion badge */}
      <div className="mt-3 flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-[#1e1f22] border border-[#3a3d43]">
        <EmotionIcon size={12} className={emotionCfg.color} />
        <span className="text-[10px] text-[#949ba4] capitalize font-medium">{emotion}</span>
      </div>
    </div>
  );
}
