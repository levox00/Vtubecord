import { useMemo } from "react";

interface OrbAnimationProps {
  isThinking: boolean;
  isSpeaking: boolean;
  isListening?: boolean;
  emotion?: string;
  size?: number;
}

const EMOTION_TINTS: Record<string, string> = {
  happiness: "#fee75c",
  sadness: "#5865f2",
  anger: "#f23f43",
  fear: "#9b59b6",
  excitement: "#f47b67",
  curiosity: "#00aff4",
  confidence: "#57f287",
};

const BASE = "#5865f2";

export function OrbAnimation({
  isThinking,
  isSpeaking,
  isListening = false,
  emotion,
  size = 120,
}: OrbAnimationProps) {
  const tint = useMemo(
    () => (emotion && EMOTION_TINTS[emotion]) ?? null,
    [emotion]
  );

  const glowColor = tint
    ? `${tint}44`
    : isListening
    ? `${BASE}22`
    : `${BASE}33`;

  const speakingGlow = tint
    ? `${tint}66`
    : `${BASE}55`;

  const listeningGlow = tint
    ? `${tint}33`
    : `${BASE}28`;

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size * 1.8, height: size * 1.8 }}
    >
      {/* Outer glow */}
      <div
        className="absolute rounded-full"
        style={{
          width: size * 1.6,
          height: size * 1.6,
          background: `radial-gradient(circle, ${isSpeaking ? speakingGlow : isListening ? listeningGlow : glowColor} 0%, transparent 70%)`,
          animation: isSpeaking
            ? "orb-glow-speak 1s ease-in-out infinite"
            : isThinking
            ? "orb-glow-think 3s ease-in-out infinite"
            : isListening
            ? "orb-glow-listen 2.5s ease-in-out infinite"
            : "orb-glow-idle 5s ease-in-out infinite",
        }}
      />

      {/* Thinking ring */}
      {isThinking && (
        <div
          className="absolute rounded-full"
          style={{
            width: size + 24,
            height: size + 24,
            border: `2px dashed ${tint ?? BASE}88`,
            animation: "orb-ring-spin 4s linear infinite",
          }}
        />
      )}

      {/* Main circle */}
      <div
        className="relative rounded-full"
        style={{
          width: size,
          height: size,
          background: tint
            ? `radial-gradient(circle at 38% 38%, ${tint}dd, ${BASE})`
            : `radial-gradient(circle at 38% 38%, ${BASE}ee, ${BASE})`,
          boxShadow: isSpeaking
            ? `0 0 ${size * 0.4}px ${speakingGlow}, 0 0 ${size * 0.8}px ${glowColor}, inset 0 -${size * 0.08}px ${size * 0.15}px rgba(0,0,0,0.15)`
            : `0 0 ${size * 0.2}px ${glowColor}, inset 0 -${size * 0.08}px ${size * 0.15}px rgba(0,0,0,0.15)`,
          animation: isSpeaking
            ? "orb-speak 0.6s ease-in-out infinite"
            : "orb-idle 5s ease-in-out infinite",
        }}
      >
        {/* Inner highlight */}
        <div
          className="absolute rounded-full"
          style={{
            width: size * 0.28,
            height: size * 0.2,
            top: "18%",
            left: "24%",
            background:
              "radial-gradient(ellipse, rgba(255,255,255,0.45), transparent)",
            filter: "blur(2px)",
          }}
        />

        {/* Speaking waveform bars */}
        {isSpeaking && (
          <div
            className="absolute flex items-center justify-center"
            style={{
              bottom: size * 0.2,
              left: "50%",
              transform: "translateX(-50%)",
              gap: 2,
            }}
          >
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="rounded-full"
                style={{
                  width: 2.5,
                  background: "rgba(255,255,255,0.85)",
                  animation: `orb-bar 0.45s ease-in-out ${i * 0.07}s infinite alternate`,
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Subtle secondary glow for speaking */}
      {isSpeaking && (
        <div
          className="absolute rounded-full pointer-events-none"
          style={{
            width: size * 1.3,
            height: size * 1.3,
            background: `radial-gradient(circle, ${speakingGlow} 0%, transparent 60%)`,
            animation: "orb-speak-ring 1.2s ease-in-out infinite",
          }}
        />
      )}

      <style>{`
        @keyframes orb-idle {
          0%, 100% { transform: scale(0.97); }
          50% { transform: scale(1.03); }
        }
        @keyframes orb-speak {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.06); }
        }
        @keyframes orb-glow-idle {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50% { opacity: 0.8; transform: scale(1.04); }
        }
        @keyframes orb-glow-listen {
          0%, 100% { opacity: 0.3; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.02); }
        }
        @keyframes orb-glow-speak {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.08); }
        }
        @keyframes orb-glow-think {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 0.7; transform: scale(1.03); }
        }
        @keyframes orb-ring-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes orb-bar {
          from { height: 5px; }
          to { height: 16px; }
        }
        @keyframes orb-speak-ring {
          0%, 100% { opacity: 0.3; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.06); }
        }
      `}</style>
    </div>
  );
}
