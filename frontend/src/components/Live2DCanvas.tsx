import { useAppStore } from "../stores/appStore";
import { useLive2d, type UseLive2dOptions, type VoiceState } from "../hooks/useLive2d";
import { OrbAnimation } from "./OrbAnimation";
import { Loader2 } from "lucide-react";
import type { AvatarAction } from "../types";

interface Live2DCanvasProps extends UseLive2dOptions {
  className?: string;
  showThinking?: boolean;
  /** Override emotion — if not provided, reads from character store */
  emotion?: string;
  /** Voice state for expression driving — if not provided, auto-detects from store */
  voiceState?: VoiceState;
  /** High-intensity expressive label (laughing, crying, etc.) — overrides emotion face */
  expressiveLabel?: string | null;
  /** Safe semantic animation command emitted by the AI controller. */
  avatarAction?: AvatarAction | null;
}

export function Live2DCanvas({
  className = "",
  showThinking = true,
  emotion: emotionProp,
  voiceState: voiceStateProp,
  expressiveLabel: expressiveLabelProp,
  avatarAction: avatarActionProp,
  ...live2dOptions
}: Live2DCanvasProps) {
  const isThinking = useAppStore((s) => s.isThinking);
  const storeEmotion = useAppStore((s) => s.character?.dominant_emotion ?? "curiosity");
  const chatEmotion = useAppStore((s) => s.chatEmotion);
  const storeExpressiveLabel = useAppStore((s) => s.expressiveLabel);
  const storeAvatarAction = useAppStore((s) => s.avatarAction);
  const avatarModelPath = useAppStore((s) => s.avatarModelPath);

  // Prefer prop > store
  const emotion = emotionProp ?? chatEmotion ?? storeEmotion;
  const expressiveLabel = expressiveLabelProp ?? storeExpressiveLabel;
  const avatarAction = avatarActionProp ?? storeAvatarAction;

  const { containerRef, status } = useLive2d({
    ...live2dOptions,
    modelPath: live2dOptions.modelPath ?? avatarModelPath,
    emotion,
    voiceState: voiceStateProp,
    expressiveLabel,
    avatarAction,
  });

  return (
    <div
      ref={containerRef as React.RefObject<HTMLDivElement>}
      className={`relative w-full h-full overflow-hidden ${className}`}
    >
      {/* Loading state */}
      {status === "loading" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <Loader2 size={32} className="text-[#5865f2]/40 animate-spin" />
        </div>
      )}

      {/* Fallback orb on error */}
      {status === "error" && (
        <div className="absolute inset-0 flex items-center justify-center">
          <OrbAnimation isThinking={isThinking} isSpeaking={false} emotion={emotion} />
        </div>
      )}

      {/* Thinking dots overlay */}
      {showThinking && isThinking && status === "loaded" && (
        <div className="absolute bottom-3 left-0 right-0 flex justify-center gap-1 pointer-events-none">
          <span className="w-1.5 h-1.5 rounded-full bg-[#5865f2] animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-[#5865f2] animate-bounce [animation-delay:150ms]" />
          <span className="w-1.5 h-1.5 rounded-full bg-[#5865f2] animate-bounce [animation-delay:300ms]" />
        </div>
      )}
    </div>
  );
}
