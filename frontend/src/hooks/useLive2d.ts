import { useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "../stores/appStore";
import type { AvatarAction, AvatarGesture } from "../types";
import {
  DEFAULT_LIVE2D_MODEL_PATH,
  resolveMotionGroup,
  resolveMotionIndices,
} from "../lib/live2dModels";
import {
  getLive2DIdlePreset,
  type Live2DIdleMicroActionId,
  type Live2DIdlePresetId,
} from "../lib/live2dIdlePresets";

// ============================================================================
// Types
// ============================================================================

export type VoiceState =
  | "idle"
  | "listening"
  | "user_speaking"
  | "processing"
  | "thinking"
  | "speaking";

export interface UseLive2dOptions {
  modelPath?: string;
  idlePreset?: Live2DIdlePresetId | string;
  /** Multiplies idle movement, gaze, speed, and fidget frequency. */
  idleIntensity?: number;
  /** Settings-only accelerated demo; never used by chat or Live Mode. */
  idlePreview?: boolean;
  lipSync?: boolean;
  audioElement?: HTMLAudioElement | null;
  voiceState?: VoiceState;
  /** Emotion name — driven externally, overrides store */
  emotion?: string;
  /** High-intensity expressive label (laughing, crying, etc.) — overrides emotion face */
  expressiveLabel?: string | null;
  /** Bounded semantic command from the backend animation controller. */
  avatarAction?: AvatarAction | null;
}

export interface UseLive2dReturn {
  containerRef: React.RefObject<HTMLDivElement | null>;
  status: "loading" | "loaded" | "error";
  triggerMotion: (group?: string) => void;
  setExpression: (name: string) => void;
}

// ============================================================================
// Emotion → Face parameter presets
// ============================================================================

interface FacePreset {
  mouthOpen: number;    // PARAM_MOUTH_OPEN_Y  (0-1)
  mouthForm: number;    // PARAM_MOUTH_FORM    (-1 frown .. 1 smile)
  mouthSize: number;    // PARAM_MOUTH_SIZE     (0-1)
  eyeLOpen: number;     // PARAM_EYE_L_OPEN    (0 closed .. 1 open)
  eyeROpen: number;     // PARAM_EYE_R_OPEN
  eyeBallX: number;     // PARAM_EYE_BALL_X    (-1 left .. 1 right)
  eyeBallY: number;     // PARAM_EYE_BALL_Y    (-1 down .. 1 up)
  browLY: number;       // PARAM_BROW_L_Y      (-1 down .. 1 up)
  browRY: number;       // PARAM_BROW_R_Y
  browLAngle: number;   // PARAM_BROW_L_ANGLE  (-1 inner .. 1 outer)
  browRAngle: number;   // PARAM_BROW_R_ANGLE
  tere: number;         // PARAM_TERE          (0 none .. 1 blush)
  angleX: number;       // PARAM_ANGLE_X       (-1 left .. 1 right)
  angleY: number;       // PARAM_ANGLE_Y       (-1 down .. 1 up)
  angleZ: number;       // PARAM_ANGLE_Z       (-1 tilt left .. 1 tilt right)
}

const EMOTION_FACES: Record<string, FacePreset> = {
  happiness: {
    mouthOpen: 0.1, mouthForm: 0.9, mouthSize: 0.6,
    eyeLOpen: 0.8, eyeROpen: 0.8,
    eyeBallX: 0, eyeBallY: 0.1,
    browLY: 0.3, browRY: 0.3,
    browLAngle: 0, browRAngle: 0,
    tere: 0.4,
    angleX: 0, angleY: 0, angleZ: 0,
  },
  excitement: {
    mouthOpen: 0.5, mouthForm: 0.7, mouthSize: 0.8,
    eyeLOpen: 1.0, eyeROpen: 1.0,
    eyeBallX: 0, eyeBallY: 0.15,
    browLY: 0.6, browRY: 0.6,
    browLAngle: 0, browRAngle: 0,
    tere: 0.2,
    angleX: 0, angleY: 0.1, angleZ: 0,
  },
  sadness: {
    mouthOpen: 0, mouthForm: -0.8, mouthSize: 0.3,
    eyeLOpen: 0.65, eyeROpen: 0.65,
    eyeBallX: 0, eyeBallY: -0.2,
    browLY: -0.4, browRY: -0.4,
    browLAngle: -0.3, browRAngle: 0.3,
    tere: 0,
    angleX: 0, angleY: -0.1, angleZ: -0.05,
  },
  anger: {
    mouthOpen: 0, mouthForm: -0.5, mouthSize: 0.4,
    eyeLOpen: 0.7, eyeROpen: 0.7,
    eyeBallX: 0, eyeBallY: -0.1,
    browLY: -0.6, browRY: -0.6,
    browLAngle: -0.5, browRAngle: 0.5,
    tere: 0,
    angleX: 0, angleY: -0.05, angleZ: 0,
  },
  fear: {
    mouthOpen: 0.2, mouthForm: -0.3, mouthSize: 0.4,
    eyeLOpen: 1.0, eyeROpen: 1.0,
    eyeBallX: 0.1, eyeBallY: 0.1,
    browLY: 0.5, browRY: 0.5,
    browLAngle: 0, browRAngle: 0,
    tere: 0,
    angleX: 0, angleY: 0.05, angleZ: 0,
  },
  curiosity: {
    mouthOpen: 0, mouthForm: 0.2, mouthSize: 0.5,
    eyeLOpen: 0.9, eyeROpen: 0.95,
    eyeBallX: 0.25, eyeBallY: 0.1,
    browLY: 0.4, browRY: 0.1,
    browLAngle: 0.1, browRAngle: -0.1,
    tere: 0,
    angleX: 0.1, angleY: 0.05, angleZ: 0.08,
  },
  confidence: {
    mouthOpen: 0, mouthForm: 0.4, mouthSize: 0.5,
    eyeLOpen: 0.9, eyeROpen: 0.9,
    eyeBallX: 0, eyeBallY: 0,
    browLY: 0.15, browRY: 0.15,
    browLAngle: 0, browRAngle: 0,
    tere: 0.1,
    angleX: 0, angleY: 0.05, angleZ: 0,
  },
  frustration: {
    mouthOpen: 0, mouthForm: -0.4, mouthSize: 0.35,
    eyeLOpen: 0.75, eyeROpen: 0.75,
    eyeBallX: -0.1, eyeBallY: -0.1,
    browLY: -0.5, browRY: -0.5,
    browLAngle: -0.4, browRAngle: 0.4,
    tere: 0,
    angleX: -0.05, angleY: -0.05, angleZ: -0.03,
  },

  // ============================================================================
  // HIGH-INTENSITY expressive presets — triggered by expressive_label
  // These override the base emotion with extreme, clearly visible expressions
  // ============================================================================
  laughing: {
    mouthOpen: 0.7, mouthForm: 1.0, mouthSize: 0.85,
    eyeLOpen: 0.35, eyeROpen: 0.35,   // squinting eyes from laughing
    eyeBallX: 0, eyeBallY: 0.05,
    browLY: 0.3, browRY: 0.3,
    browLAngle: 0, browRAngle: 0,
    tere: 0.5,                          // blushing from laughing
    angleX: 0, angleY: -0.05, angleZ: 0.03,
  },
  crying: {
    mouthOpen: 0.3, mouthForm: -0.6, mouthSize: 0.4,
    eyeLOpen: 0.55, eyeROpen: 0.55,   // droopy eyes
    eyeBallX: 0, eyeBallY: -0.2,
    browLY: -0.5, browRY: -0.5,       // furrowed brows
    browLAngle: -0.4, browRAngle: 0.4,
    tere: 0,                           // no blush, pale
    angleX: 0, angleY: -0.1, angleZ: -0.05,
  },
  shocked: {
    mouthOpen: 0.8, mouthForm: 0, mouthSize: 0.7,
    eyeLOpen: 1.0, eyeROpen: 1.0,     // wide open eyes
    eyeBallX: 0, eyeBallY: 0,
    browLY: 0.7, browRY: 0.7,         // raised brows
    browLAngle: 0, browRAngle: 0,
    tere: 0,
    angleX: 0, angleY: 0.05, angleZ: 0,
  },
  yelling: {
    mouthOpen: 0.9, mouthForm: -0.3, mouthSize: 0.8,
    eyeLOpen: 0.6, eyeROpen: 0.6,     // narrowed from intensity
    eyeBallX: 0, eyeBallY: -0.1,
    browLY: -0.7, browRY: -0.7,       // deeply furrowed
    browLAngle: -0.5, browRAngle: 0.5,
    tere: 0,
    angleX: 0, angleY: -0.05, angleZ: 0,
  },
  panicking: {
    mouthOpen: 0.5, mouthForm: -0.4, mouthSize: 0.5,
    eyeLOpen: 1.0, eyeROpen: 1.0,     // wide terrified eyes
    eyeBallX: 0.1, eyeBallY: 0.3,     // looking up in fear
    browLY: 0.8, browRY: 0.8,         // raised high
    browLAngle: 0, browRAngle: 0,
    tere: 0,
    angleX: 0.1, angleY: 0.1, angleZ: 0,
  },
  blushing: {
    mouthOpen: 0.15, mouthForm: 0.7, mouthSize: 0.55,
    eyeLOpen: 0.7, eyeROpen: 0.7,     // shy half-closed
    eyeBallX: -0.15, eyeBallY: -0.1,  // looking away
    browLY: 0.2, browRY: 0.2,
    browLAngle: 0, browRAngle: 0,
    tere: 0.8,                         // strong blush
    angleX: -0.1, angleY: 0, angleZ: 0.1,  // tilted head
  },
  smug: {
    mouthOpen: 0, mouthForm: 0.6, mouthSize: 0.5,
    eyeLOpen: 0.8, eyeROpen: 0.65,    // one eye slightly closed
    eyeBallX: 0.15, eyeBallY: 0,      // looking to side
    browLY: 0.25, browRY: 0.1,        // one brow raised
    browLAngle: 0.1, browRAngle: -0.15,
    tere: 0.2,
    angleX: 0.08, angleY: 0, angleZ: -0.05,
  },
};

const DEFAULT_FACE: FacePreset = EMOTION_FACES.curiosity;

interface IdleVariant {
  name: string;
  face: Partial<FacePreset>;
  speed: number;
  pattern: "breathe" | "drift" | "scan" | "nod" | "peek" | "groove";
  body: { x: number; y: number; z: number };
  head: { x: number; y: number; z: number };
  gaze: { x: number; y: number };
}

/**
 * Portable idles layered over whatever Idle motions the current rig ships.
 * They only use standard Cubism parameters, so models with very different
 * bundled motion files still get a varied, recognizable idle repertoire.
 */
const IDLE_VARIANTS: readonly IdleVariant[] = [
  {
    name: "calm_breathing", pattern: "breathe", speed: 0.62,
    face: { angleZ: -0.02, eyeBallY: -0.02, mouthForm: 0.28 },
    body: { x: 0.06, y: 0.03, z: 0.04 }, head: { x: 0.015, y: 0.025, z: 0.012 }, gaze: { x: 0.025, y: 0.018 },
  },
  {
    name: "curious_lean", pattern: "peek", speed: 0.82,
    face: { angleX: 0.08, angleZ: 0.07, eyeBallX: 0.12, browLY: 0.22, browRY: 0.08 },
    body: { x: 0.12, y: 0.03, z: 0.1 }, head: { x: 0.055, y: 0.025, z: 0.045 }, gaze: { x: 0.08, y: 0.025 },
  },
  {
    name: "daydreaming", pattern: "drift", speed: 0.42,
    face: { angleY: 0.08, eyeBallY: 0.14, eyeLOpen: 0.76, eyeROpen: 0.76, mouthForm: 0.38 },
    body: { x: 0.075, y: 0.045, z: 0.055 }, head: { x: 0.035, y: 0.04, z: 0.035 }, gaze: { x: 0.045, y: 0.055 },
  },
  {
    name: "attentive", pattern: "breathe", speed: 0.76,
    face: { angleX: -0.04, eyeBallX: -0.05, eyeLOpen: 0.96, eyeROpen: 0.96, browLY: 0.14, browRY: 0.14 },
    body: { x: 0.055, y: 0.025, z: 0.035 }, head: { x: 0.018, y: 0.018, z: 0.015 }, gaze: { x: 0.025, y: 0.018 },
  },
  {
    name: "shy_sway", pattern: "drift", speed: 0.58,
    face: { angleX: -0.1, angleY: -0.05, angleZ: 0.08, eyeBallX: -0.15, eyeBallY: -0.08, tere: 0.38, mouthForm: 0.48 },
    body: { x: 0.1, y: 0.035, z: 0.085 }, head: { x: 0.035, y: 0.035, z: 0.04 }, gaze: { x: 0.045, y: 0.025 },
  },
  {
    name: "sleepy_drift", pattern: "nod", speed: 0.36,
    face: { angleY: -0.06, eyeBallY: -0.12, eyeLOpen: 0.62, eyeROpen: 0.62, browLY: -0.05, browRY: -0.05, mouthForm: 0.14 },
    body: { x: 0.065, y: 0.055, z: 0.04 }, head: { x: 0.02, y: 0.09, z: 0.025 }, gaze: { x: 0.025, y: 0.05 },
  },
  {
    name: "playful_peek", pattern: "peek", speed: 0.94,
    face: { angleX: 0.12, angleZ: -0.08, eyeBallX: 0.2, eyeLOpen: 0.88, eyeROpen: 0.76, browLY: 0.22, mouthForm: 0.68, tere: 0.18 },
    body: { x: 0.13, y: 0.025, z: 0.13 }, head: { x: 0.075, y: 0.025, z: 0.065 }, gaze: { x: 0.12, y: 0.025 },
  },
  {
    name: "thoughtful_scan", pattern: "scan", speed: 0.52,
    face: { angleY: 0.06, eyeBallY: 0.08, browLY: 0.18, browRY: 0.04, mouthForm: 0.08 },
    body: { x: 0.055, y: 0.025, z: 0.04 }, head: { x: 0.085, y: 0.035, z: 0.025 }, gaze: { x: 0.18, y: 0.04 },
  },
  {
    name: "confident_pose", pattern: "breathe", speed: 0.7,
    face: { angleY: 0.05, eyeLOpen: 0.84, eyeROpen: 0.84, browLY: 0.12, browRY: 0.12, mouthForm: 0.52, tere: 0.08 },
    body: { x: 0.045, y: 0.055, z: 0.03 }, head: { x: 0.02, y: 0.025, z: 0.012 }, gaze: { x: 0.025, y: 0.015 },
  },
  {
    name: "gentle_groove", pattern: "groove", speed: 1.05,
    face: { eyeLOpen: 0.84, eyeROpen: 0.84, mouthForm: 0.62 },
    body: { x: 0.18, y: 0.06, z: 0.17 }, head: { x: 0.065, y: 0.035, z: 0.075 }, gaze: { x: 0.055, y: 0.025 },
  },
  {
    name: "star_gazing", pattern: "drift", speed: 0.46,
    face: { angleY: 0.12, eyeBallY: 0.22, eyeLOpen: 0.92, eyeROpen: 0.92, browLY: 0.2, browRY: 0.2, mouthForm: 0.4 },
    body: { x: 0.065, y: 0.04, z: 0.05 }, head: { x: 0.035, y: 0.045, z: 0.035 }, gaze: { x: 0.06, y: 0.035 },
  },
  {
    name: "room_watch", pattern: "scan", speed: 0.66,
    face: { eyeLOpen: 0.96, eyeROpen: 0.96, browLY: 0.1, browRY: 0.1, mouthForm: 0.24 },
    body: { x: 0.075, y: 0.02, z: 0.055 }, head: { x: 0.07, y: 0.025, z: 0.025 }, gaze: { x: 0.16, y: 0.035 },
  },
] as const;

interface IdleMotionOverlay {
  bodyX: number;
  bodyY: number;
  bodyZ: number;
  headX: number;
  headY: number;
  headZ: number;
  gazeX: number;
  gazeY: number;
}

const EMPTY_IDLE_MOTION: IdleMotionOverlay = {
  bodyX: 0, bodyY: 0, bodyZ: 0,
  headX: 0, headY: 0, headZ: 0,
  gazeX: 0, gazeY: 0,
};

function getIdleVariantMotion(variant: IdleVariant, phase: number): IdleMotionOverlay {
  let primary = Math.sin(phase);
  let secondary = Math.sin(phase * 0.63 + 1.15);
  let tertiary = Math.sin(phase * 0.81 + 2.1);

  switch (variant.pattern) {
    case "scan":
      primary = Math.sin(phase * 0.58);
      secondary = Math.sin(phase * 0.31 + 0.8);
      tertiary = Math.sin(phase * 0.44 + 2.4);
      break;
    case "nod":
      primary = Math.sin(phase * 0.72);
      secondary = (Math.sin(phase * 1.18 - 0.7) + 0.35 * Math.sin(phase * 2.36)) * 0.75;
      tertiary = Math.sin(phase * 0.49 + 1.7);
      break;
    case "peek":
      primary = Math.sin(phase * 0.84);
      secondary = Math.sin(phase * 0.47 + 1.25);
      tertiary = Math.sin(phase * 1.06 + 2.2);
      break;
    case "groove":
      primary = Math.sin(phase * 1.18);
      secondary = Math.sin(phase * 2.36 + 0.8) * 0.65;
      tertiary = Math.sin(phase * 1.18 + Math.PI / 2);
      break;
    case "drift":
      primary = Math.sin(phase * 0.52);
      secondary = Math.sin(phase * 0.37 + 1.4);
      tertiary = Math.sin(phase * 0.29 + 2.3);
      break;
    default:
      break;
  }

  return {
    bodyX: primary * variant.body.x,
    bodyY: secondary * variant.body.y,
    bodyZ: tertiary * variant.body.z,
    headX: secondary * variant.head.x,
    headY: primary * variant.head.y,
    headZ: tertiary * variant.head.z,
    gazeX: primary * variant.gaze.x,
    gazeY: secondary * variant.gaze.y,
  };
}

function scaleIdleMotion(motion: IdleMotionOverlay, scale: number): IdleMotionOverlay {
  return {
    bodyX: motion.bodyX * scale,
    bodyY: motion.bodyY * scale,
    bodyZ: motion.bodyZ * scale,
    headX: motion.headX * scale,
    headY: motion.headY * scale,
    headZ: motion.headZ * scale,
    gazeX: motion.gazeX * scale,
    gazeY: motion.gazeY * scale,
  };
}

function blendIdleFace(
  base: FacePreset,
  overlay: Partial<FacePreset>,
  scale: number,
): Partial<FacePreset> {
  return Object.fromEntries(
    (Object.entries(overlay) as Array<[keyof FacePreset, number]>).map(([key, value]) => [
      key,
      lerp(base[key], value, scale),
    ]),
  ) as Partial<FacePreset>;
}

interface IdleMicroAction {
  name: Live2DIdleMicroActionId;
  duration: number;
}

interface IdleMicroOverlay extends IdleMotionOverlay {
  eyeCloseL: number;
  eyeCloseR: number;
  mouthForm: number;
}

const IDLE_MICRO_ACTIONS: readonly IdleMicroAction[] = [
  { name: "small_nod", duration: 1350 },
  { name: "double_nod", duration: 1750 },
  { name: "glance_left", duration: 2100 },
  { name: "glance_right", duration: 2100 },
  { name: "curious_tilt", duration: 1900 },
  { name: "shy_dip", duration: 2000 },
  { name: "double_blink", duration: 1050 },
  { name: "friendly_wink", duration: 1250 },
  { name: "posture_shift", duration: 1850 },
] as const;

function getIdleMicroOverlay(action: IdleMicroAction | null, progress: number): IdleMicroOverlay {
  const empty = { ...EMPTY_IDLE_MOTION, eyeCloseL: 0, eyeCloseR: 0, mouthForm: 0 };
  if (!action) return empty;

  const p = clamp(progress, 0, 1);
  const envelope = Math.sin(p * Math.PI);
  switch (action.name) {
    case "small_nod":
      return { ...empty, headY: Math.sin(p * Math.PI * 2) * 0.12 * envelope };
    case "double_nod":
      return { ...empty, headY: Math.sin(p * Math.PI * 4) * 0.1 * envelope, bodyY: -0.06 * envelope };
    case "glance_left":
      return { ...empty, headX: -0.2 * envelope, headZ: 0.045 * envelope, gazeX: -0.34 * envelope };
    case "glance_right":
      return { ...empty, headX: 0.2 * envelope, headZ: -0.045 * envelope, gazeX: 0.34 * envelope };
    case "curious_tilt":
      return { ...empty, headX: 0.08 * envelope, headZ: 0.17 * envelope, gazeX: 0.12 * envelope };
    case "shy_dip":
      return { ...empty, headY: -0.16 * envelope, headZ: -0.08 * envelope, gazeX: -0.16 * envelope, gazeY: -0.22 * envelope, mouthForm: 0.12 * envelope };
    case "double_blink": {
      const pulse = (center: number) => {
        const distance = Math.abs(p - center);
        return distance >= 0.13 ? 0 : Math.sin((1 - distance / 0.13) * Math.PI / 2) ** 2;
      };
      const close = Math.max(pulse(0.3), pulse(0.68));
      return { ...empty, eyeCloseL: close, eyeCloseR: close };
    }
    case "friendly_wink":
      return { ...empty, eyeCloseL: envelope * 0.92, headZ: -0.08 * envelope, mouthForm: 0.18 * envelope };
    case "posture_shift":
      return { ...empty, bodyX: 0.12 * envelope, bodyY: 0.08 * envelope, bodyZ: -0.14 * envelope, headZ: 0.05 * envelope };
    default:
      return empty;
  }
}

function scaleIdleMicroOverlay(
  overlay: IdleMicroOverlay,
  motionScale: number,
  faceScale: number,
): IdleMicroOverlay {
  const motion = scaleIdleMotion(overlay, motionScale);
  return {
    ...motion,
    eyeCloseL: overlay.eyeCloseL * faceScale,
    eyeCloseR: overlay.eyeCloseR * faceScale,
    mouthForm: overlay.mouthForm * faceScale,
  };
}

const MOTION_PRIORITY_IDLE = 1;
const MOTION_PRIORITY_FORCE = 3;
const MIN_ACTION_MOTION_FADE_SECONDS = 0.75;
const MIN_IDLE_MOTION_FADE_SECONDS = 1.1;

function getAvailableMotionGroups(model: any): string[] {
  const definitions = model?.internalModel?.motionManager?.definitions;
  return definitions && typeof definitions === "object" ? Object.keys(definitions) : [];
}

/**
 * Load and configure a model-authored motion before starting it. Cubism files
 * are allowed to specify extremely short (or zero) fades, which can instantly
 * replace an arm pose. The renderer owns this lower bound for every model.
 */
function playRandomMotion(
  model: any,
  group: string,
  priority: number,
  shouldStart: () => boolean = () => true,
  allowedIndices?: readonly number[],
): void {
  void (async () => {
    try {
      const manager = model?.internalModel?.motionManager;
      const definitions = manager?.definitions?.[group];
      if (!manager || !Array.isArray(definitions) || definitions.length === 0) return;

      const indices = (allowedIndices === undefined
        ? Array.from({ length: definitions.length }, (_, index) => index)
        : allowedIndices.filter((index) => Number.isInteger(index) && index >= 0 && index < definitions.length)
      );
      if (indices.length === 0) return;
      for (let i = indices.length - 1; i > 0; i -= 1) {
        const swapIndex = Math.floor(Math.random() * (i + 1));
        [indices[i], indices[swapIndex]] = [indices[swapIndex], indices[i]];
      }

      for (const index of indices) {
        const motion = await manager.loadMotion(group, index);
        if (!motion || !shouldStart()) return;

        const minimumFade = group === "Idle"
          ? MIN_IDLE_MOTION_FADE_SECONDS
          : MIN_ACTION_MOTION_FADE_SECONDS;
        if (typeof motion.setFadeInTime === "function") {
          const authoredFade = typeof motion.getFadeInTime === "function"
            ? Number(motion.getFadeInTime()) || 0
            : 0;
          motion.setFadeInTime(Math.max(authoredFade, minimumFade));
        }
        if (typeof motion.setFadeOutTime === "function") {
          const authoredFade = typeof motion.getFadeOutTime === "function"
            ? Number(motion.getFadeOutTime()) || 0
            : 0;
          motion.setFadeOutTime(Math.max(authoredFade, minimumFade));
        }

        if (!shouldStart()) return;
        if (await manager.startMotion(group, index, priority)) return;
      }
    } catch { /* this model does not expose the requested motion */ }
  })();
}

// pixi-live2d-display/cubism4 keeps its WebGL shader state in a module-level
// singleton. Serializing model construction prevents React StrictMode, a
// rapid LiveMode toggle, or a model switch from initializing two Cubism
// renderers at the same time while the previous one is still being torn down.
let live2dModelLoadQueue: Promise<void> = Promise.resolve();

async function withLive2dModelLoadLock<T>(task: () => Promise<T>): Promise<T> {
  const previous = live2dModelLoadQueue;
  let release!: () => void;
  live2dModelLoadQueue = new Promise<void>((resolve) => {
    release = resolve;
  });

  await previous;
  try {
    return await task();
  } finally {
    release();
  }
}

// ============================================================================
// State → face overrides (layered on top of emotion)
// ============================================================================

function getStateOverrides(voiceState: VoiceState): Partial<FacePreset> {
  switch (voiceState) {
    case "thinking":
      return {
        angleY: 0.15,     // look up
        angleZ: 0.05,     // slight tilt
        eyeBallY: 0.3,    // eyes up
        browLY: 0.2,
        browRY: 0.2,
      };
    case "listening":
      return {
        eyeLOpen: 1.0,
        eyeROpen: 1.0,    // eyes wide, alert
        browLY: 0.15,
        browRY: 0.15,     // brows slightly up
        angleX: 0,
        angleY: 0,
        angleZ: 0,        // face forward
      };
    case "speaking":
      return {
        browLY: 0.1,
        browRY: 0.1,
      };
    case "user_speaking":
      return {
        eyeLOpen: 0.95,
        eyeROpen: 0.95,
        angleX: 0,
        angleY: 0,
        angleZ: 0,        // face forward, attentive
      };
    default:
      return {};
  }
}

// ============================================================================
// Lerp helper
// ============================================================================

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * Math.min(1, Math.max(0, t));
}

const PARAMETER_ALIASES: Record<string, string[]> = {
  mouthOpen: ["PARAM_MOUTH_OPEN_Y", "ParamMouthOpenY", "ParamA"],
  mouthForm: ["PARAM_MOUTH_FORM", "ParamMouthForm"],
  mouthSize: ["PARAM_MOUTH_SIZE", "ParamMouthSize"],
  eyeLOpen: ["PARAM_EYE_L_OPEN", "ParamEyeLOpen"],
  eyeROpen: ["PARAM_EYE_R_OPEN", "ParamEyeROpen"],
  eyeBallX: ["PARAM_EYE_BALL_X", "ParamEyeBallX"],
  eyeBallY: ["PARAM_EYE_BALL_Y", "ParamEyeBallY"],
  browLY: ["PARAM_BROW_L_Y", "ParamBrowLY"],
  browRY: ["PARAM_BROW_R_Y", "ParamBrowRY"],
  browLAngle: ["PARAM_BROW_L_ANGLE", "ParamBrowLAngle"],
  browRAngle: ["PARAM_BROW_R_ANGLE", "ParamBrowRAngle"],
  tere: ["PARAM_TERE", "ParamTere", "ParamCheek"],
  breath: ["PARAM_BREATH", "ParamBreath"],
  angleX: ["PARAM_ANGLE_X", "ParamAngleX"],
  angleY: ["PARAM_ANGLE_Y", "ParamAngleY"],
  angleZ: ["PARAM_ANGLE_Z", "ParamAngleZ"],
  bodyAngleX: ["PARAM_BODY_ANGLE_X", "ParamBodyAngleX"],
  bodyAngleY: ["PARAM_BODY_ANGLE_Y", "ParamBodyAngleY"],
  bodyAngleZ: ["PARAM_BODY_ANGLE_Z", "ParamBodyAngleZ"],
};

function setParameter(coreModel: any, semanticName: keyof typeof PARAMETER_ALIASES, value: number) {
  // Face/body angles use degrees in the standard Cubism rigs. The director's
  // semantic presets stay normalized so the same action remains portable.
  const isHeadAngle = semanticName === "angleX" || semanticName === "angleY" || semanticName === "angleZ";
  const isBodyAngle = semanticName === "bodyAngleX" || semanticName === "bodyAngleY" || semanticName === "bodyAngleZ";
  const renderedValue = isHeadAngle ? value * 30 : isBodyAngle ? value * 10 : value;
  for (const id of PARAMETER_ALIASES[semanticName]) {
    try { coreModel.setParameterValueById(id, renderedValue); } catch { /* absent on this model */ }
  }
  if (semanticName === "mouthForm") {
    // Mao uses separate positive blend-shape parameters instead of the common
    // signed ParamMouthForm control.
    try { coreModel.setParameterValueById("ParamMouthUp", Math.max(0, value)); } catch {}
    try { coreModel.setParameterValueById("ParamMouthDown", Math.max(0, -value)); } catch {}
  }
}

function clamp(value: number, low = -1, high = 1): number {
  return Math.min(high, Math.max(low, value));
}

const MIN_GESTURE_DURATION_MS: Record<AvatarGesture, number> = {
  wave: 2600,
  warm_nod: 1300,
  celebrate: 2200,
  dance: 3000,
  bow: 1900,
  wink: 1200,
  look_down: 2000,
  firm_shake: 1600,
  recoil: 1300,
  head_tilt: 1800,
  lean_in: 1600,
  look_away: 1800,
  laugh: 2000,
};

function getAvatarActionDuration(action: AvatarAction | null): number {
  if (!action) return 0;
  return Math.max(
    MIN_GESTURE_DURATION_MS[action.gesture],
    Math.max(300, action.hold_ms || 1200),
  );
}

function smoothstep(value: number): number {
  const x = clamp(value, 0, 1);
  return x * x * (3 - 2 * x);
}

/** Smoothly raises and lowers every semantic action instead of switching it. */
function getGestureEnvelope(action: AvatarAction | null, startedAt: number, now: number): number {
  const duration = getAvatarActionDuration(action);
  if (!action || duration <= 0) return 0;
  const elapsed = now - startedAt;
  if (elapsed < 0 || elapsed > duration) return 0;
  const transitionMs = Math.min(650, Math.max(380, duration * 0.25));
  const fadeIn = smoothstep(elapsed / transitionMs);
  const fadeOut = smoothstep((duration - elapsed) / transitionMs);
  return Math.min(fadeIn, fadeOut);
}

function blendFaceOverlay(
  base: FacePreset,
  overlay: Partial<FacePreset>,
  weight: number,
): FacePreset {
  const blended = { ...base };
  for (const key of Object.keys(overlay) as Array<keyof FacePreset>) {
    const target = overlay[key];
    if (typeof target === "number") blended[key] = lerp(base[key], target, weight);
  }
  return blended;
}

interface MotionSafetyState {
  initialized: boolean;
  lastUpdate: number;
  parameterValues: number[];
  partOpacities: number[];
}

function createMotionSafetyState(): MotionSafetyState {
  return {
    initialized: false,
    lastUpdate: 0,
    parameterValues: [],
    partOpacities: [],
  };
}

function getCoreParameterId(coreModel: any, index: number): string {
  const ids = coreModel?._model?.parameters?.ids
    ?? coreModel?.getModel?.()?.parameters?.ids;
  return String(ids?.[index] ?? "");
}

function getCorePartId(coreModel: any, index: number): string {
  const ids = coreModel?._model?.parts?.ids
    ?? coreModel?.getModel?.()?.parts?.ids;
  return String(ids?.[index] ?? "");
}

/** Return a shared key for mutually exclusive arm/hand artwork variants. */
function getExclusivePoseGroup(partId: string): string | null {
  const match = partId.match(/^(.*(?:arm|hand).*?)([ab])$/i);
  return match ? match[1].toLowerCase() : null;
}

function getParameterTravelRate(parameterId: string): number {
  const id = parameterId.toLowerCase();
  // Arms and pose-bearing body controls are intentionally kept at a natural
  // full-range travel time. This is the hard anti-teleport path for gestures.
  if (/(arm|hand|shoulder|body|angle|base|bust|pose)/.test(id)) return 1.15;
  // Blinks and speech-related facial movement must remain responsive.
  if (/(eye.*open|blink|mouth|lip)/.test(id)) return 8;
  if (/(eye|brow|cheek|tere)/.test(id)) return 4.5;
  // Unknown/custom parameters are still rate-limited, so future rigs inherit
  // the no-teleport invariant without needing a model-specific allow-list.
  return 2.5;
}

function moveTowardSafely(
  previous: number,
  target: number,
  range: number,
  travelRate: number,
  deltaSeconds: number,
): number {
  const response = 1 - Math.exp(-12 * deltaSeconds);
  const desiredDelta = (target - previous) * response;
  const maximumDelta = Math.max(0.00001, range * travelRate * deltaSeconds);
  return previous + clamp(desiredDelta, -maximumDelta, maximumDelta);
}

/**
 * Final renderer-level motion guard. It runs after Cubism motions, physics and
 * pose switching, then rate-limits both parameters and part opacity. Therefore
 * a model-authored clip cannot teleport an arm by changing a parameter or by
 * instantly swapping between alternate arm parts.
 */
function applyMotionSafetySmoothing(coreModel: any, state: MotionSafetyState, now: number): void {
  const parameterCount = Number(coreModel?.getParameterCount?.() ?? 0);
  const partCount = Number(coreModel?.getPartCount?.() ?? 0);

  if (!state.initialized
    || state.parameterValues.length !== parameterCount
    || state.partOpacities.length !== partCount) {
    state.parameterValues = Array.from(
      { length: parameterCount },
      (_, index) => Number(coreModel.getParameterValueByIndex(index)) || 0,
    );
    state.partOpacities = Array.from(
      { length: partCount },
      (_, index) => Number(coreModel.getPartOpacityByIndex(index)) || 0,
    );
    state.lastUpdate = now;
    state.initialized = true;
    return;
  }

  const deltaSeconds = clamp((now - state.lastUpdate) / 1000, 1 / 240, 0.05);
  state.lastUpdate = now;

  for (let index = 0; index < parameterCount; index += 1) {
    const target = Number(coreModel.getParameterValueByIndex(index));
    if (!Number.isFinite(target)) continue;
    const minimum = Number(coreModel.getParameterMinimumValue(index));
    const maximum = Number(coreModel.getParameterMaximumValue(index));
    const range = Math.max(0.0001, Math.abs(maximum - minimum));
    const next = moveTowardSafely(
      state.parameterValues[index],
      target,
      range,
      getParameterTravelRate(getCoreParameterId(coreModel, index)),
      deltaSeconds,
    );
    state.parameterValues[index] = next;
    coreModel.setParameterValueByIndex(index, next);
  }

  const opacityTargets = Array.from(
    { length: partCount },
    (_, index) => Number(coreModel.getPartOpacityByIndex(index)),
  );
  const exclusiveGroups = new Map<string, number[]>();
  for (let index = 0; index < partCount; index += 1) {
    const group = getExclusivePoseGroup(getCorePartId(coreModel, index));
    if (!group) continue;
    exclusiveGroups.set(group, [...(exclusiveGroups.get(group) ?? []), index]);
  }

  const handledIndices = new Set<number>();
  for (const indices of exclusiveGroups.values()) {
    if (indices.length < 2) continue;
    indices.forEach((index) => handledIndices.add(index));
    const desiredIndex = indices.reduce((best, index) =>
      opacityTargets[index] > opacityTargets[best] ? index : best,
    );
    const visibleIndex = indices.reduce((best, index) =>
      state.partOpacities[index] > state.partOpacities[best] ? index : best,
    );
    const switching = visibleIndex !== desiredIndex && state.partOpacities[visibleIndex] > 0.015;

    for (const index of indices) {
      // Never cross-fade alternate arm artwork. Fade the old variant out,
      // then bring the already rate-limited replacement in from transparent.
      const target = switching
        ? 0
        : index === desiredIndex
          ? clamp(opacityTargets[index], 0, 1)
          : 0;
      const next = moveTowardSafely(
        state.partOpacities[index],
        target,
        1,
        1.6,
        deltaSeconds,
      );
      state.partOpacities[index] = clamp(next, 0, 1);
      coreModel.setPartOpacityByIndex(index, state.partOpacities[index]);
    }
  }

  for (let index = 0; index < partCount; index += 1) {
    if (handledIndices.has(index) || !Number.isFinite(opacityTargets[index])) continue;
    const next = moveTowardSafely(
      state.partOpacities[index],
      opacityTargets[index],
      1,
      1.1,
      deltaSeconds,
    );
    state.partOpacities[index] = clamp(next, 0, 1);
    coreModel.setPartOpacityByIndex(index, state.partOpacities[index]);
  }
}

/**
 * Return a mouth value that remains useful when a browser refuses to expose
 * analyser data (for example while an AudioContext is still suspended). The
 * very small fallback movement only applies while the AI is speaking; normal
 * idle/listening states still settle completely closed.
 */
function getSpeechMouthLevel(signal: number, speaking: boolean, now: number): number {
  const measured = clamp(signal, 0, 1);
  if (!speaking) return 0;
  if (measured >= 0.025) return measured;
  return 0.08 + (Math.sin(now * 0.012) + 1) * 0.08;
}

/** TTS generation is not speech; playback must have actually advanced. */
function isSpeechPlaybackActive(
  audioElement: HTMLAudioElement | null,
  voiceState: VoiceState,
): boolean {
  return Boolean(
    voiceState === "speaking"
      && audioElement
      && !audioElement.paused
      && !audioElement.ended
      && audioElement.currentTime > 0,
  );
}

/** Translate safe AI gestures into a short-lived face/body pose. */
function getGestureOverlay(action: AvatarAction | null, startedAt: number, now: number): Partial<FacePreset> {
  const duration = getAvatarActionDuration(action);
  if (!action || now - startedAt > duration) return {};
  const intensity = clamp(action.intensity || 0.5, 0.2, 0.9);
  const progress = clamp((now - startedAt) / duration, 0, 1);
  const wave = Math.sin(progress * Math.PI * 2);
  switch (action.gesture) {
    case "wave": return { angleX: 0.08 * intensity, angleZ: wave * 0.1 * intensity, mouthForm: 0.75, browLY: 0.18, browRY: 0.18 };
    case "warm_nod": return { angleY: 0.08 + wave * 0.25 * intensity, browLY: 0.15, browRY: 0.15 };
    case "celebrate": return { angleY: 0.12 + Math.abs(wave) * 0.2 * intensity, angleZ: wave * 0.18 * intensity, mouthForm: 0.9, eyeLOpen: 0.85, eyeROpen: 0.85 };
    case "dance": return { angleX: wave * 0.2 * intensity, angleZ: wave * 0.3 * intensity, mouthForm: 0.8, eyeLOpen: 0.85, eyeROpen: 0.85 };
    case "bow": return { angleY: -0.38 * intensity, eyeBallY: -0.18, mouthForm: 0.25 };
    case "wink": return { eyeLOpen: wave > 0 ? 0.08 : 0.85, eyeROpen: 0.9, mouthForm: 0.75, angleZ: -0.08 * intensity };
    case "look_down": return { angleY: -0.22 * intensity, eyeBallY: -0.35 * intensity, browLY: -0.15, browRY: -0.15 };
    case "firm_shake": return { angleX: Math.sin(progress * Math.PI * 5) * 0.45 * intensity, browLY: -0.3, browRY: -0.3 };
    case "recoil": return { angleY: 0.25 * intensity, angleX: -0.12 * intensity, eyeLOpen: 1, eyeROpen: 1 };
    case "head_tilt": return { angleZ: 0.28 * intensity, angleX: 0.12 * intensity, eyeBallX: 0.18 * intensity };
    case "lean_in": return { angleY: -0.16 * intensity, angleX: 0.08 * intensity, browLY: 0.15, browRY: 0.15 };
    case "look_away": return { angleX: -0.45 * intensity, eyeBallX: -0.48 * intensity, angleZ: 0.12 * intensity };
    case "laugh": return { angleY: -0.08, angleZ: wave * 0.14 * intensity, mouthForm: 1, eyeLOpen: 0.42, eyeROpen: 0.42 };
    default: return {};
  }
}

function isAvatarActionActive(action: AvatarAction | null, startedAt: number, now: number): boolean {
  return Boolean(action && now - startedAt <= getAvatarActionDuration(action));
}

interface BodyOverlay { x: number; y: number; z: number }

interface Live2dViewport {
  /** User-controlled zoom relative to the automatic fit scale. */
  zoom: number;
  /** User-controlled displacement from the center of the canvas. */
  panX: number;
  panY: number;
  /** Scale needed to fit the current model in the current canvas. */
  fitScale: number;
}

function getFitScale(model: any, width: number, height: number): number {
  const origW = model?.internalModel?.originalWidth || model?.width || 0;
  const origH = model?.internalModel?.originalHeight || model?.height || 0;
  if (origW <= 0 || origH <= 0) return 1;
  return Math.min((width * 0.85) / origW, (height * 0.85) / origH, 1.0);
}

function applyViewportTransform(
  model: any,
  width: number,
  height: number,
  viewport: Live2dViewport,
): void {
  if (!model) return;
  model.scale.set(viewport.fitScale * viewport.zoom);
  model.anchor.set(0.5, 0.5);
  model.x = width / 2 + viewport.panX;
  model.y = height / 2 + viewport.panY;
}

function getGestureBodyOverlay(
  action: AvatarAction | null,
  startedAt: number,
  now: number,
): BodyOverlay {
  const duration = getAvatarActionDuration(action);
  if (!action || now - startedAt > duration) {
    return { x: 0, y: 0, z: 0 };
  }
  const intensity = clamp(action.intensity || 0.5, 0.2, 0.9);
  const progress = clamp((now - startedAt) / duration, 0, 1);
  const envelope = getGestureEnvelope(action, startedAt, now);
  const wave = Math.sin(progress * Math.PI * 2);
  switch (action.gesture) {
    case "wave": return { x: wave * 0.1 * intensity * envelope, y: 0, z: wave * 0.2 * intensity * envelope };
    case "dance": return { x: wave * 0.35 * intensity * envelope, y: 0, z: wave * 0.45 * intensity * envelope };
    case "celebrate": return { x: wave * 0.18 * intensity * envelope, y: 0, z: wave * 0.25 * intensity * envelope };
    case "bow": return { x: 0, y: -0.28 * intensity * envelope, z: 0 };
    case "firm_shake": return { x: wave * 0.28 * intensity * envelope, y: 0, z: 0 };
    case "laugh": return { x: 0, y: 0, z: wave * 0.16 * intensity * envelope };
    default: return { x: 0, y: 0, z: 0 };
  }
}

// ============================================================================
// Hook
// ============================================================================
// Hook
// ============================================================================

export function useLive2d(options: UseLive2dOptions = {}): UseLive2dReturn {
  const {
    modelPath = DEFAULT_LIVE2D_MODEL_PATH,
    idlePreset: idlePresetProp,
    idleIntensity: idleIntensityProp,
    idlePreview = false,
    lipSync = true,
    audioElement = null,
    voiceState: voiceStateProp = "idle",
    emotion: emotionProp,
    expressiveLabel: expressiveLabelProp,
    avatarAction: avatarActionProp,
  } = options;

  const character = useAppStore((s) => s.character);
  const chatEmotion = useAppStore((s) => s.chatEmotion);
  const storeExpressiveLabel = useAppStore((s) => s.expressiveLabel);
  const storeAvatarAction = useAppStore((s) => s.avatarAction);
  const storeIdlePreset = useAppStore((s) => s.live2dIdlePreset);
  const storeIdleIntensity = useAppStore((s) => s.live2dIdleIntensity);
  const smartExpressions = useAppStore((s) => s.smartExpressions);

  const containerRef = useRef<HTMLDivElement>(null);
  const appRef = useRef<any>(null);
  const modelRef = useRef<any>(null);
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");

  // Prefer prop > store
  const emotion = smartExpressions
    ? emotionProp ?? chatEmotion ?? character?.dominant_emotion ?? "curiosity"
    : "curiosity";
  const expressiveLabel = smartExpressions ? expressiveLabelProp ?? storeExpressiveLabel : null;
  const avatarAction = smartExpressions ? avatarActionProp ?? storeAvatarAction : null;
  const idlePresetId = idlePresetProp ?? storeIdlePreset;
  const idleIntensity = clamp(Number(idleIntensityProp ?? storeIdleIntensity ?? 1), 0.25, 2);
  const voiceState = voiceStateProp;

  // Refs for the animation loop
  const currentFaceRef = useRef<FacePreset>({ ...DEFAULT_FACE });
  const lipSyncMouthRef = useRef(0);
  const audioElementRef = useRef<HTMLAudioElement | null>(audioElement);
  const breathRef = useRef(0);
  const voiceStateRef = useRef(voiceState);
  const emotionRef = useRef(emotion);
  const expressiveLabelRef = useRef(expressiveLabel);
  const avatarActionRef = useRef<AvatarAction | null>(avatarAction);
  const avatarActionStartedAtRef = useRef(0);
  const viewportRef = useRef<Live2dViewport>({
    zoom: 1,
    panX: 0,
    panY: 0,
    fitScale: 1,
  });
  const actionReturnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const motionRequestGenerationRef = useRef(0);

  useEffect(() => { voiceStateRef.current = voiceState; }, [voiceState]);
  useEffect(() => { audioElementRef.current = audioElement; }, [audioElement]);
  useEffect(() => { emotionRef.current = emotion; }, [emotion]);
  useEffect(() => { expressiveLabelRef.current = expressiveLabel; }, [expressiveLabel]);
  useEffect(() => {
    avatarActionRef.current = avatarAction;
    avatarActionStartedAtRef.current = performance.now();
  }, [avatarAction]);

  // ==========================================================================
  // Initialize Live2D
  // ========================================================================== 
  useEffect(() => {
    const container = containerRef.current;
    if (!container || appRef.current) return;
    // A different character starts centered at its natural fitted size. Camera
    // placement is deliberately independent from the character's animation.
    viewportRef.current = { zoom: 1, panX: 0, panY: 0, fitScale: 1 };
    const host = container;
    let destroyed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let app: any = null;
    let model: any = null;
    let removeContextLostListener: (() => void) | null = null;
    let removeMotionSafetyListener: (() => void) | null = null;
    let removeLipSyncListener: (() => void) | null = null;
    let idleRotationTimer: ReturnType<typeof setTimeout> | null = null;

    // A LiveMode overlay can be mounted in the same render pass that changes
    // the layout.  In that frame the canvas may still have a 0x0 client size,
    // and pixi-live2d-display can fail to load or attach the model.  Keep the
    // initial load self-healing so users do not have to toggle Orb/Model to
    // force a second mount.
    const cleanupRuntime = () => {
      removeContextLostListener?.();
      removeContextLostListener = null;
      removeMotionSafetyListener?.();
      removeMotionSafetyListener = null;
      removeLipSyncListener?.();
      removeLipSyncListener = null;
      if (idleRotationTimer) clearTimeout(idleRotationTimer);
      idleRotationTimer = null;
      if (model) {
        try { model.destroy(); } catch { /* ignore cleanup errors */ }
      }
      if (modelRef.current === model) modelRef.current = null;

      const view = app?.view as HTMLCanvasElement | undefined;
      if (app) {
        try { app.destroy(true); } catch { /* ignore cleanup errors */ }
      }
      if (appRef.current === app) appRef.current = null;
      if (view?.parentNode === host) view.remove();
      model = null;
      app = null;
    };

    async function init(attempt = 0): Promise<void> {
      try {
        setStatus("loading");

        // Wait for one paint so fixed/resizable LiveMode panels have their
        // final dimensions before Pixi creates its renderer.
        await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
        if (destroyed) return;

        if (host.clientWidth === 0 || host.clientHeight === 0) {
          if (attempt < 10) {
            retryTimer = setTimeout(() => { void init(attempt + 1); }, 100);
            return;
          }
          throw new Error("Live2D container has no visible size");
        }

        const PIXI = await import("pixi.js-legacy");
        const { Live2DModel } = await import("pixi-live2d-display/cubism4");

        if (destroyed) return;
        (window as any).PIXI = PIXI;

        // Suppress pixi-live2d-display's isInteractive error that floods the
        // console on every pointer event and can block click propagation.
        if (!(window as any).__pixi_isInteractive_patched) {
          (window as any).__pixi_isInteractive_patched = true;
          const origHandler = (window as any).__pixi_event_error_handler;
          if (!origHandler) {
            window.addEventListener("error", (e) => {
              if (e.message?.includes("isInteractive")) {
                e.preventDefault();
                return false;
              }
            });
          }
        }

        app = new PIXI.Application({
          backgroundAlpha: 0,
          antialias: true,
          width: host.clientWidth || 320,
          height: host.clientHeight || 400,
        });

        if (destroyed) { cleanupRuntime(); return; }

        host.appendChild(app.view as HTMLCanvasElement);
        appRef.current = app;

        // Keep model creation single-file/serial. The Cubism runtime has a
        // shared shader singleton, so overlapping `from()` calls can leave a
        // model with textures or programs owned by a different WebGL context.
        model = await withLive2dModelLoadLock(() => {
          if (destroyed) {
            return Promise.reject(new Error("Live2D initialization cancelled"));
          }
          return Live2DModel.from(modelPath, { autoInteract: false });
        });

        if (destroyed) { cleanupRuntime(); return; }

        modelRef.current = model;

        // This final-pass guard sees the output of model motions, physics and
        // pose switching. It prevents both parameter jumps and instant arm-
        // part visibility swaps, including on custom models added later.
        const motionSafetyState = createMotionSafetyState();
        const applyMotionSafetyBeforeModelUpdate = () => {
          if (!model || modelRef.current !== model) return;
          applyMotionSafetySmoothing(
            model.internalModel.coreModel,
            motionSafetyState,
            performance.now(),
          );
        };
        model.internalModel.on("beforeModelUpdate", applyMotionSafetyBeforeModelUpdate);
        removeMotionSafetyListener = () =>
          model?.internalModel?.off("beforeModelUpdate", applyMotionSafetyBeforeModelUpdate);

        // Cubism applies idle/gesture motion curves during its own update
        // pass. Apply the mouth value after those curves have run so an Idle
        // motion cannot overwrite the audio-driven lip sync before drawing.
        const applyLipSyncBeforeModelUpdate = () => {
          if (!model || modelRef.current !== model) return;
          const playbackActive = isSpeechPlaybackActive(
            audioElementRef.current,
            voiceStateRef.current,
          );
          if (!playbackActive) {
            // A model-authored idle/action motion may contain mouth curves of
            // its own. Suppress those specifically during LLM/TTS generation
            // so processing can never look like premature speech.
            if (
              voiceStateRef.current === "processing"
              || voiceStateRef.current === "thinking"
            ) {
              setParameter(model.internalModel.coreModel, "mouthOpen", 0);
            }
            return;
          }
          const level = getSpeechMouthLevel(
            lipSyncMouthRef.current,
            true,
            performance.now(),
          );
          setParameter(model.internalModel.coreModel, "mouthOpen", level);
        };
        model.internalModel.on("beforeModelUpdate", applyLipSyncBeforeModelUpdate);
        removeLipSyncListener = () =>
          model?.internalModel?.off("beforeModelUpdate", applyLipSyncBeforeModelUpdate);

        function fitModel() {
          if (!model || !app) return;
          viewportRef.current.fitScale = getFitScale(
            model,
            app.screen.width,
            app.screen.height,
          );
          applyViewportTransform(
            model,
            app.screen.width,
            app.screen.height,
            viewportRef.current,
          );
        }
        fitModel();

        app.stage.addChild(model as any);

        // Recover automatically if the browser loses this canvas's context
        // (for example after a GPU driver reset or a renderer handoff). The
        // old Pixi app is discarded before retrying so stale textures cannot
        // be submitted to the replacement context.
        const view = app.view as HTMLCanvasElement;
        const handleContextLost = (event: Event) => {
          event.preventDefault();
          if (destroyed) return;
          cleanupRuntime();
          setStatus("loading");
          retryTimer = setTimeout(() => { void init(0); }, 250);
        };
        view.addEventListener("webglcontextlost", handleContextLost, false);
        removeContextLostListener = () =>
          view.removeEventListener("webglcontextlost", handleContextLost, false);

        // Start the rig's real Idle group and rotate it periodically. Bundled
        // sample motions are authored as loops, so waiting for "finished"
        // would otherwise leave the first idle running forever.
        const beginIdleMotion = (priority: number) => {
          const requestGeneration = motionRequestGenerationRef.current + 1;
          motionRequestGenerationRef.current = requestGeneration;
          playRandomMotion(
            model,
            "Idle",
            priority,
            () => !destroyed
              && modelRef.current === model
              && motionRequestGenerationRef.current === requestGeneration,
          );
        };
        const rotateIdle = () => {
          if (!model || destroyed) return;
          if (voiceStateRef.current === "idle" && !isAvatarActionActive(
            avatarActionRef.current,
            avatarActionStartedAtRef.current,
            performance.now(),
          )) {
            try { model.internalModel.motionManager.stopAllMotions(); } catch {}
            beginIdleMotion(MOTION_PRIORITY_FORCE);
          }
          idleRotationTimer = setTimeout(rotateIdle, 7000 + Math.random() * 5000);
        };
        beginIdleMotion(MOTION_PRIORITY_IDLE);
        idleRotationTimer = setTimeout(rotateIdle, 7000 + Math.random() * 5000);

        setStatus("loaded");
      } catch (err) {
        cleanupRuntime();
        if (destroyed) return;

        // The first request can race the Vite static asset server while the
        // LiveMode overlay is appearing. Retry a couple of times before
        // showing the fallback orb and log only the final failure.
        if (attempt < 2) {
          retryTimer = setTimeout(() => { void init(attempt + 1); }, 350);
          return;
        }

        console.error("Live2D init failed:", err);
        setStatus("error");
      }
    }

    void init();

    return () => {
      destroyed = true;
      motionRequestGenerationRef.current += 1;
      if (retryTimer) clearTimeout(retryTimer);
      if (actionReturnTimerRef.current) clearTimeout(actionReturnTimerRef.current);
      cleanupRuntime();
    };
  }, [modelPath]);

  // ==========================================================================
  // Resize
  // ==========================================================================
  useEffect(() => {
    const container = containerRef.current;
    const app = appRef.current;
    if (!container || !app || status !== "loaded") return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          app.renderer.resize(width, height);
          if (modelRef.current) {
            viewportRef.current.fitScale = getFitScale(modelRef.current, width, height);
            applyViewportTransform(modelRef.current, width, height, viewportRef.current);
          }
        }
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [status]);

  // ==========================================================================
  // Animation director — runs after model-authored motion curves so the
  // selected portable preset remains visible on rigs such as Mao Pro whose
  // single Idle clip writes nearly every standard Cubism parameter.
  // ==========================================================================
  useEffect(() => {
    if (status !== "loaded") return;

    let lastTime = performance.now();
    const model = modelRef.current;
    if (!model) return;
    const idleProfile = getLive2DIdlePreset(idlePresetId);
    // Preserve each preset's deliberate ordering. Filtering IDLE_VARIANTS
    // directly made most previews begin with the same calm_breathing variant.
    const availableIdleVariants = idleProfile.variantNames
      .map((name) => IDLE_VARIANTS.find((variant) => variant.name === name))
      .filter((variant): variant is IdleVariant => Boolean(variant));
    const presetIdleVariants = availableIdleVariants.length > 0
      ? availableIdleVariants
      : IDLE_VARIANTS;
    const idleMotionScale = idleProfile.motionScale * idleIntensity;
    const idleFaceScale = idleProfile.faceScale * (0.72 + idleIntensity * 0.28);
    const idleGazeScale = idleProfile.gazeScale * idleIntensity;
    const idleSpeedScale = idleProfile.speedScale * (0.82 + idleIntensity * 0.18);
    const frequencyScale = 0.7 + idleIntensity * 0.3;
    const baseVariantHoldRange: readonly [number, number] = idlePreview
      ? [3200, 5200]
      : idleProfile.variantHoldMs;
    const baseMicroIntervalRange: readonly [number, number] = idlePreview
      ? [1700, 3200]
      : idleProfile.microIntervalMs;
    const variantHoldRange: readonly [number, number] = [
      baseVariantHoldRange[0] / frequencyScale,
      baseVariantHoldRange[1] / frequencyScale,
    ];
    const microIntervalRange: readonly [number, number] = [
      baseMicroIntervalRange[0] / frequencyScale,
      baseMicroIntervalRange[1] / frequencyScale,
    ];
    const randomBetween = (range: readonly [number, number]) =>
      range[0] + Math.random() * (range[1] - range[0]);

    // Eye blink state
    let blinkTimer = 0;
    let blinkPhase = 0; // 0=open, 1=closing, 2=closed, 3=opening
    let blinkProgress = 0;
    const BLINK_SPEED = 0.012;
    const BLINK_INTERVAL_MIN = 2500;
    const BLINK_INTERVAL_MAX = 5500;
    blinkTimer = BLINK_INTERVAL_MIN + Math.random() * (BLINK_INTERVAL_MAX - BLINK_INTERVAL_MIN);

    // Autonomous gaze state. Pointer position never enters this controller:
    // the AI/voice state and semantic actions own the character's attention.
    let gazeTimer = 1500 + Math.random() * 3000;
    let gazeX = 0;
    let gazeY = 0;
    let gazeTargetX = 0;
    let gazeTargetY = 0;
    let headX = 0;
    let headY = 0;
    let headZ = 0;
    let headTargetX = 0;
    let headTargetY = 0;
    let headTargetZ = 0;

    // Portable idle state. This changes the subtle face/body behavior even on
    // models that ship only one actual Idle motion.
    let idleVariantIndex = idlePreview ? 0 : Math.floor(Math.random() * presetIdleVariants.length);
    let idleVariantTimer = randomBetween(variantHoldRange);
    let idleMicroTimer = randomBetween(microIntervalRange);
    let idleMicroAction: IdleMicroAction | null = idlePreview
      ? IDLE_MICRO_ACTIONS.find((action) => action.name === idleProfile.previewAction) ?? null
      : null;
    let idleMicroElapsed = 0;

    function tick() {
      const now = performance.now();
      const dt = Math.min(now - lastTime, 50); // cap delta
      lastTime = now;
      if (modelRef.current !== model) return;

      const coreModel = model.internalModel.coreModel;

      // --- Compute target face ---
      // expressiveLabel (laughing, crying, etc.) overrides the base emotion face
      const expressivePreset = expressiveLabelRef.current
        ? EMOTION_FACES[expressiveLabelRef.current]
        : undefined;
      const emotionPreset = expressivePreset ?? EMOTION_FACES[emotionRef.current] ?? DEFAULT_FACE;
      const stateOverrides = getStateOverrides(voiceStateRef.current);
      const gestureOverlay = getGestureOverlay(
        avatarActionRef.current,
        avatarActionStartedAtRef.current,
        now,
      );
      const hasActiveGesture = isAvatarActionActive(
        avatarActionRef.current,
        avatarActionStartedAtRef.current,
        now,
      );
      const isPassiveIdle = voiceStateRef.current === "idle"
        && !hasActiveGesture;
      if (isPassiveIdle) {
        idleVariantTimer -= dt;
        if (idleVariantTimer <= 0) {
          idleVariantIndex = presetIdleVariants.length === 1
            ? 0
            : (idleVariantIndex + 1 + Math.floor(Math.random() * (presetIdleVariants.length - 1)))
              % presetIdleVariants.length;
          idleVariantTimer = randomBetween(variantHoldRange);
        }

        if (idleMicroAction) {
          idleMicroElapsed += dt;
          if (idleMicroElapsed >= idleMicroAction.duration) {
            idleMicroAction = null;
            idleMicroElapsed = 0;
            idleMicroTimer = randomBetween(microIntervalRange);
          }
        } else {
          idleMicroTimer -= dt;
          if (idleMicroTimer <= 0) {
            const useLargerAction = idleProfile.largerMicroActions.length > 0
              && Math.random() < idleProfile.largerActionChance;
            const actionNames = useLargerAction
              ? idleProfile.largerMicroActions
              : idleProfile.microActions;
            const actionName = actionNames[Math.floor(Math.random() * actionNames.length)];
            idleMicroAction = IDLE_MICRO_ACTIONS.find((action) => action.name === actionName) ?? null;
            idleMicroElapsed = 0;
            if (!idleMicroAction) idleMicroTimer = randomBetween(microIntervalRange);
          }
        }
      } else if (idleMicroAction) {
        // Speech, listening, and explicit AI actions interrupt decorative idle
        // behavior immediately instead of waiting for it to finish.
        idleMicroAction = null;
        idleMicroElapsed = 0;
        idleMicroTimer = randomBetween(microIntervalRange);
      }
      const idleVariant = presetIdleVariants[idleVariantIndex];
      const idleOverlay = isPassiveIdle
        ? blendIdleFace(emotionPreset, idleVariant.face, idleFaceScale)
        : {};
      const idleMicroOverlay = scaleIdleMicroOverlay(
        isPassiveIdle
          ? getIdleMicroOverlay(
              idleMicroAction,
              idleMicroAction ? idleMicroElapsed / idleMicroAction.duration : 0,
            )
          : getIdleMicroOverlay(null, 0),
        idleMotionScale,
        idleFaceScale,
      );
      const targetBeforeGesture: FacePreset = {
        ...emotionPreset,
        ...idleOverlay,
        ...stateOverrides,
      };
      const target = blendFaceOverlay(
        targetBeforeGesture,
        gestureOverlay,
        getGestureEnvelope(avatarActionRef.current, avatarActionStartedAtRef.current, now),
      );

      // --- Lerp current → target ---
      const LERP_SPEED = 0.04; // per frame at 60fps ≈ 0.24/sec
      const t = 1 - Math.pow(1 - LERP_SPEED, dt / 16.67);
      const cur = currentFaceRef.current;

      cur.mouthForm = lerp(cur.mouthForm, target.mouthForm, t);
      cur.mouthSize = lerp(cur.mouthSize, target.mouthSize, t);
      cur.eyeLOpen = lerp(cur.eyeLOpen, target.eyeLOpen, t);
      cur.eyeROpen = lerp(cur.eyeROpen, target.eyeROpen, t);
      cur.eyeBallX = lerp(cur.eyeBallX, target.eyeBallX, t);
      cur.eyeBallY = lerp(cur.eyeBallY, target.eyeBallY, t);
      cur.browLY = lerp(cur.browLY, target.browLY, t);
      cur.browRY = lerp(cur.browRY, target.browRY, t);
      cur.browLAngle = lerp(cur.browLAngle, target.browLAngle, t);
      cur.browRAngle = lerp(cur.browRAngle, target.browRAngle, t);
      cur.tere = lerp(cur.tere ?? 0, target.tere ?? 0, t);
      cur.angleX = lerp(cur.angleX, target.angleX, t);
      cur.angleY = lerp(cur.angleY, target.angleY, t);
      cur.angleZ = lerp(cur.angleZ, target.angleZ, t);

      // --- Lip sync overlay ---
      // During speaking, mouthOpen is driven by audio. Otherwise smooth to 0.
      if (isSpeechPlaybackActive(audioElementRef.current, voiceStateRef.current)) {
        // lipSyncMouthRef is set by the lip sync effect below
        cur.mouthOpen = lerp(
          cur.mouthOpen,
          getSpeechMouthLevel(lipSyncMouthRef.current, true, now),
          0.3,
        );
      } else {
        // Preserve smiles, laughter, shock, and other non-speech mouth poses.
        cur.mouthOpen = lerp(cur.mouthOpen, target.mouthOpen, t);
      }

      // --- Eye blink ---
      blinkTimer -= dt;
      if (blinkTimer <= 0 && blinkPhase === 0) {
        blinkPhase = 1; // start closing
        blinkProgress = 0;
      }

      let blinkOffset = 0;
      if (blinkPhase === 1) {
        blinkProgress += BLINK_SPEED * dt;
        if (blinkProgress >= 1) { blinkPhase = 2; blinkProgress = 0; }
        blinkOffset = blinkProgress;
      } else if (blinkPhase === 2) {
        blinkProgress += BLINK_SPEED * dt * 0.5;
        if (blinkProgress >= 1) { blinkPhase = 3; blinkProgress = 0; }
        blinkOffset = 1;
      } else if (blinkPhase === 3) {
        blinkProgress += BLINK_SPEED * dt;
        if (blinkProgress >= 1) {
          blinkPhase = 0;
          blinkProgress = 0;
          blinkTimer = BLINK_INTERVAL_MIN + Math.random() * (BLINK_INTERVAL_MAX - BLINK_INTERVAL_MIN);
          blinkOffset = 0;
        } else {
          blinkOffset = 1 - blinkProgress;
        }
      }

      const eyeL = cur.eyeLOpen * (1 - blinkOffset * 0.9) * (1 - idleMicroOverlay.eyeCloseL);
      const eyeR = cur.eyeROpen * (1 - blinkOffset * 0.9) * (1 - idleMicroOverlay.eyeCloseR);

      // --- AI/autonomous gaze ---
      gazeTimer -= dt;
      if (gazeTimer <= 0) {
        const state = voiceStateRef.current;
        const attention = state === "listening" || state === "user_speaking"
          ? 0.35
          : state === "speaking"
          ? 0.65
          : 1;
        // Occasionally return to the viewer instead of continuously darting.
        const activeIdleGazeScale = state === "idle" ? idleGazeScale : 1;
        const direction = Math.random() < 0.28 ? 0 : (Math.random() - 0.5) * 0.42 * attention * activeIdleGazeScale;
        const vertical = Math.random() < 0.35 ? 0 : (Math.random() - 0.45) * 0.24 * attention * activeIdleGazeScale;
        gazeTargetX = direction;
        gazeTargetY = vertical;
        headTargetX = direction * 0.52;
        headTargetY = vertical * 0.38;
        headTargetZ = -direction * 0.16;
        gazeTimer = state === "speaking"
          ? 1400 + Math.random() * 2600
          : 2200 + Math.random() * 4200;
      }
      // Explicit AI gestures have exclusive attention control while active.
      const gazeBlend = 1 - Math.pow(1 - (hasActiveGesture ? 0.12 : 0.025), dt / 16.67);
      const activeGazeTargetX = hasActiveGesture ? 0 : gazeTargetX;
      const activeGazeTargetY = hasActiveGesture ? 0 : gazeTargetY;
      gazeX = lerp(gazeX, activeGazeTargetX, gazeBlend);
      gazeY = lerp(gazeY, activeGazeTargetY, gazeBlend);
      headX = lerp(headX, hasActiveGesture ? 0 : headTargetX, gazeBlend);
      headY = lerp(headY, hasActiveGesture ? 0 : headTargetY, gazeBlend);
      headZ = lerp(headZ, hasActiveGesture ? 0 : headTargetZ, gazeBlend);

      // --- Breathing ---
      breathRef.current += dt * 0.001;
      const breath = (Math.sin(breathRef.current * 1.5) + 1) / 2; // 0-1 sine
      const idleMotion = isPassiveIdle
        ? scaleIdleMotion(
            getIdleVariantMotion(
              idleVariant,
              breathRef.current * idleVariant.speed * idleSpeedScale,
            ),
            idleMotionScale,
          )
        : EMPTY_IDLE_MOTION;
      const bodyOverlay = getGestureBodyOverlay(
        avatarActionRef.current,
        avatarActionStartedAtRef.current,
        now,
      );

      // --- Apply all parameters ---
      try {
        setParameter(coreModel, "mouthOpen", cur.mouthOpen);
        setParameter(coreModel, "mouthForm", clamp(cur.mouthForm + idleMicroOverlay.mouthForm));
        setParameter(coreModel, "mouthSize", cur.mouthSize);
        setParameter(coreModel, "eyeLOpen", eyeL);
        setParameter(coreModel, "eyeROpen", eyeR);
        setParameter(coreModel, "eyeBallX", clamp(cur.eyeBallX + gazeX + idleMotion.gazeX + idleMicroOverlay.gazeX));
        setParameter(coreModel, "eyeBallY", clamp(cur.eyeBallY + gazeY + idleMotion.gazeY + idleMicroOverlay.gazeY));
        setParameter(coreModel, "browLY", cur.browLY);
        setParameter(coreModel, "browRY", cur.browRY);
        setParameter(coreModel, "browLAngle", cur.browLAngle);
        setParameter(coreModel, "browRAngle", cur.browRAngle);
        setParameter(coreModel, "tere", cur.tere ?? 0);
        setParameter(coreModel, "breath", breath);
        setParameter(coreModel, "bodyAngleX", idleMotion.bodyX + idleMicroOverlay.bodyX + bodyOverlay.x);
        setParameter(coreModel, "bodyAngleY", idleMotion.bodyY + idleMicroOverlay.bodyY + bodyOverlay.y);
        setParameter(coreModel, "bodyAngleZ", idleMotion.bodyZ + idleMicroOverlay.bodyZ + bodyOverlay.z);
        // Head pose is always owned by the animation director. Semantic AI
        // actions take priority; otherwise subtle autonomous attention is
        // layered over emotion, voice state, and the selected idle variant.
        setParameter(coreModel, "angleX", cur.angleX + headX + idleMotion.headX + idleMicroOverlay.headX);
        setParameter(coreModel, "angleY", cur.angleY + headY + idleMotion.headY + idleMicroOverlay.headY);
        setParameter(coreModel, "angleZ", cur.angleZ + headZ + idleMotion.headZ + idleMicroOverlay.headZ);
      } catch {}

    }

    model.internalModel.on("afterMotionUpdate", tick);
    return () => model?.internalModel?.off("afterMotionUpdate", tick);
  }, [status, idlePresetId, idleIntensity, idlePreview]);

  // ==========================================================================
  // Lip sync — real TTS playback only
  // ==========================================================================
  useEffect(() => {
    const model = modelRef.current;
    if (!model || status !== "loaded" || !lipSync) return;

    let audioContext: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    let source: MediaElementAudioSourceNode | null = null;
    let rafId: number | null = null;
    let smoothMouth = 0;

    if (audioElement) {
      try {
        audioContext = new AudioContext();
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.65;
        source = audioContext.createMediaElementSource(audioElement);
        source.connect(analyser);
        analyser.connect(audioContext.destination);

        // Audio created after an async TTS request is commonly attached while
        // the context is suspended. Resume it explicitly so the analyser sees
        // the same signal that is sent to the speakers.
        void audioContext.resume().catch(() => {});

        const dataArray = new Uint8Array(analyser.fftSize);

        function updateLip() {
          if (!analyser) return;
          // Time-domain RMS is more reliable than sampling a few FFT bins:
          // speech energy can move between bins depending on the voice and
          // TTS codec, while the waveform always reflects audible loudness.
          analyser.getByteTimeDomainData(dataArray);
          let sumSquares = 0;
          for (let i = 0; i < dataArray.length; i++) {
            const centered = (dataArray[i] - 128) / 128;
            sumSquares += centered * centered;
          }
          const rms = Math.sqrt(sumSquares / dataArray.length);
          const raw = rms < 0.012 ? 0 : clamp(rms * 4.5, 0, 1);
          // Smooth to avoid jitter while preserving consonant openings.
          smoothMouth = lerp(smoothMouth, raw, raw > smoothMouth ? 0.5 : 0.25);
          lipSyncMouthRef.current = smoothMouth;
          rafId = requestAnimationFrame(updateLip);
        }
        rafId = requestAnimationFrame(updateLip);
      } catch (err) {
        console.warn("Live2D lip sync failed:", err);
        // getSpeechMouthLevel supplies a restrained fallback, but only after
        // this audio element has actually started advancing through playback.
        lipSyncMouthRef.current = 0;
      }
    } else {
      lipSyncMouthRef.current = 0;
    }

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      if (source) { try { source.disconnect(); } catch {} }
      if (audioContext) { try { audioContext.close(); } catch {} }
      lipSyncMouthRef.current = 0;
    };
  }, [audioElement, lipSync, status]);

  // ==========================================================================
  // Semantic AI gesture → an optional model motion, with the parameter pose
  // above as the portable fallback for models that have different motion names.
  // ========================================================================== 
  useEffect(() => {
    const model = modelRef.current;
    if (!model || status !== "loaded") return;

    const requestGeneration = motionRequestGenerationRef.current + 1;
    motionRequestGenerationRef.current = requestGeneration;
    if (!avatarAction) {
      try { model.internalModel.motionManager.stopAllMotions(); } catch {}
      if (voiceStateRef.current === "idle") {
        playRandomMotion(
          model,
          "Idle",
          MOTION_PRIORITY_IDLE,
          () => modelRef.current === model
            && voiceStateRef.current === "idle"
            && motionRequestGenerationRef.current === requestGeneration,
        );
      }
      return;
    }

    // An interaction owns the motion track exclusively. Stop an authored idle
    // before loading the action so its arm/part curves cannot remain in the
    // motion queue and blend with the incoming gesture.
    try { model.internalModel.motionManager.stopAllMotions(); } catch {}
    const group = resolveMotionGroup(avatarAction.gesture, getAvailableMotionGroups(model));
    if (group !== undefined) {
      const allowedIndices = resolveMotionIndices(avatarAction.gesture, group, modelPath);
      playRandomMotion(
        model,
        group,
        MOTION_PRIORITY_FORCE,
        () => modelRef.current === model
          && avatarActionRef.current === avatarAction
          && motionRequestGenerationRef.current === requestGeneration,
        allowedIndices,
      );
    }

    // All bundled sample action motions are loops. Stop them at the semantic
    // command boundary and hand control back through a smoothed Idle motion.
    if (actionReturnTimerRef.current) clearTimeout(actionReturnTimerRef.current);
    actionReturnTimerRef.current = setTimeout(() => {
      const activeModel = modelRef.current;
      if (!activeModel || activeModel !== model) return;
      const idleRequestGeneration = motionRequestGenerationRef.current + 1;
      motionRequestGenerationRef.current = idleRequestGeneration;
      try { activeModel.internalModel.motionManager.stopAllMotions(); } catch {}
      if (voiceStateRef.current === "idle") {
        playRandomMotion(
          activeModel,
          "Idle",
          MOTION_PRIORITY_IDLE,
          () => modelRef.current === activeModel
            && voiceStateRef.current === "idle"
            && motionRequestGenerationRef.current === idleRequestGeneration,
        );
      }
      actionReturnTimerRef.current = null;
    }, getAvatarActionDuration(avatarAction));

    return () => {
      motionRequestGenerationRef.current += 1;
      if (actionReturnTimerRef.current) clearTimeout(actionReturnTimerRef.current);
      actionReturnTimerRef.current = null;
    };
  }, [avatarAction, modelPath, status]);

  // Listening/thinking/speaking preempts decorative authored idles even when
  // the semantic action arrives a frame later. Restart idle only after the
  // interaction is over; an active gesture remains the sole motion owner.
  useEffect(() => {
    const model = modelRef.current;
    if (!model || status !== "loaded") return;
    if (isAvatarActionActive(
      avatarActionRef.current,
      avatarActionStartedAtRef.current,
      performance.now(),
    )) return;

    const requestGeneration = motionRequestGenerationRef.current + 1;
    motionRequestGenerationRef.current = requestGeneration;
    try { model.internalModel.motionManager.stopAllMotions(); } catch {}
    if (voiceState !== "idle") return;
    playRandomMotion(
      model,
      "Idle",
      MOTION_PRIORITY_IDLE,
      () => modelRef.current === model
        && voiceStateRef.current === "idle"
        && motionRequestGenerationRef.current === requestGeneration,
    );
  }, [status, voiceState]);

  // ========================================================================== 
  // Viewport controls — the only pointer authority exposed to the user.
  // Dragging moves the rendered character and the wheel changes camera zoom;
  // neither input is forwarded to Live2D face, eye, head, or body parameters.
  // ==========================================================================
  useEffect(() => {
    const container = containerRef.current;
    if (!container || status !== "loaded") return;

    let drag: { pointerId: number; lastX: number; lastY: number } | null = null;

    const updateCursor = (dragging: boolean) => {
      container.style.cursor = dragging ? "grabbing" : "grab";
    };

    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || !modelRef.current) return;
      event.preventDefault();
      drag = { pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY };
      try { container.setPointerCapture(event.pointerId); } catch {}
      updateCursor(true);
    };

    const handlePointerMove = (event: PointerEvent) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      event.preventDefault();
      viewportRef.current.panX += event.clientX - drag.lastX;
      viewportRef.current.panY += event.clientY - drag.lastY;
      drag.lastX = event.clientX;
      drag.lastY = event.clientY;
      const model = modelRef.current;
      const app = appRef.current;
      if (model && app) {
        applyViewportTransform(model, app.screen.width, app.screen.height, viewportRef.current);
      }
    };

    const finishDrag = (event: PointerEvent) => {
      if (!drag || event.pointerId !== drag.pointerId) return;
      try { container.releasePointerCapture(event.pointerId); } catch {}
      drag = null;
      updateCursor(false);
    };

    const handleWheel = (event: WheelEvent) => {
      const model = modelRef.current;
      const app = appRef.current;
      if (!model || !app) return;
      event.preventDefault();

      const viewport = viewportRef.current;
      const previousZoom = viewport.zoom;
      const nextZoom = clamp(previousZoom * Math.exp(-event.deltaY * 0.0012), 0.35, 4);
      if (nextZoom === previousZoom) return;

      // Keep the point beneath the cursor stationary while scaling so zooming
      // feels like a camera operation instead of snapping around the center.
      const rect = container.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const pointerY = event.clientY - rect.top;
      const currentX = app.screen.width / 2 + viewport.panX;
      const currentY = app.screen.height / 2 + viewport.panY;
      const ratio = nextZoom / previousZoom;
      viewport.panX = pointerX - app.screen.width / 2 - (pointerX - currentX) * ratio;
      viewport.panY = pointerY - app.screen.height / 2 - (pointerY - currentY) * ratio;
      viewport.zoom = nextZoom;
      applyViewportTransform(model, app.screen.width, app.screen.height, viewport);
    };

    updateCursor(false);
    container.style.touchAction = "none";
    container.addEventListener("pointerdown", handlePointerDown);
    container.addEventListener("pointermove", handlePointerMove);
    container.addEventListener("pointerup", finishDrag);
    container.addEventListener("pointercancel", finishDrag);
    container.addEventListener("wheel", handleWheel, { passive: false });
    return () => {
      container.removeEventListener("pointerdown", handlePointerDown);
      container.removeEventListener("pointermove", handlePointerMove);
      container.removeEventListener("pointerup", finishDrag);
      container.removeEventListener("pointercancel", finishDrag);
      container.removeEventListener("wheel", handleWheel);
      container.style.cursor = "";
      container.style.touchAction = "";
    };
  }, [status]);

  // ==========================================================================
  // Public API
  // ==========================================================================
  const triggerMotion = useCallback((group: string = "Tap") => {
    const model = modelRef.current;
    if (!model) return;
    const groups = getAvailableMotionGroups(model);
    const resolvedGroup = groups.includes(group)
      ? group
      : groups.find((candidate) => candidate !== "Idle");
    if (resolvedGroup === undefined) return;
    playRandomMotion(model, resolvedGroup, MOTION_PRIORITY_FORCE);
    if (actionReturnTimerRef.current) clearTimeout(actionReturnTimerRef.current);
    actionReturnTimerRef.current = setTimeout(() => {
      const activeModel = modelRef.current;
      if (!activeModel) return;
      try { activeModel.internalModel.motionManager.stopAllMotions(); } catch {}
      playRandomMotion(activeModel, "Idle", MOTION_PRIORITY_IDLE);
      actionReturnTimerRef.current = null;
    }, 1800);
  }, []);

  const setExpression = useCallback((name: string) => {
    const model = modelRef.current;
    if (!model) return;
    try {
      // pixi-live2d-display exposes expressionManager on the motionManager
      const em = model.internalModel.motionManager.expressionManager;
      if (em && typeof em.setExpression === "function") {
        em.setExpression(name);
      }
    } catch {}
  }, []);

  return { containerRef, status, triggerMotion, setExpression };
}
