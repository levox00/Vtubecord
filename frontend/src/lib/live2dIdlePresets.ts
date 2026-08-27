export type Live2DIdleMicroActionId =
  | "small_nod"
  | "double_nod"
  | "glance_left"
  | "glance_right"
  | "curious_tilt"
  | "shy_dip"
  | "double_blink"
  | "friendly_wink"
  | "posture_shift";

export type Live2DIdlePresetId =
  | "dynamic"
  | "neuro_subtle"
  | "neuro_classic"
  | "neuro_playful"
  | "neuro_focused"
  | "cozy"
  | "minimal";

export interface Live2DIdlePresetDefinition {
  id: Live2DIdlePresetId;
  name: string;
  shortLabel: string;
  description: string;
  energy: "Minimal" | "Low" | "Medium" | "High";
  variantNames: readonly string[];
  faceScale: number;
  motionScale: number;
  speedScale: number;
  gazeScale: number;
  variantHoldMs: readonly [number, number];
  microIntervalMs: readonly [number, number];
  microActions: readonly Live2DIdleMicroActionId[];
  largerMicroActions: readonly Live2DIdleMicroActionId[];
  largerActionChance: number;
  previewAction: Live2DIdleMicroActionId;
}

const GENTLE_MICRO_ACTIONS: readonly Live2DIdleMicroActionId[] = [
  "small_nod",
  "glance_left",
  "glance_right",
  "double_blink",
  "posture_shift",
];

const EXPRESSIVE_MICRO_ACTIONS: readonly Live2DIdleMicroActionId[] = [
  "double_nod",
  "curious_tilt",
  "shy_dip",
  "friendly_wink",
];

/** Selectable portable animation directors for every installed Cubism rig. */
export const LIVE2D_IDLE_PRESETS: readonly Live2DIdlePresetDefinition[] = [
  {
    id: "dynamic",
    name: "Current Varied Director",
    shortLabel: "Current",
    description: "The current full repertoire: twelve rotating moods, broad gaze changes, and every autonomous micro-fidget.",
    energy: "Medium",
    variantNames: [
      "calm_breathing", "curious_lean", "daydreaming", "attentive", "shy_sway", "sleepy_drift",
      "playful_peek", "thoughtful_scan", "confident_pose", "gentle_groove", "star_gazing", "room_watch",
    ],
    faceScale: 1,
    motionScale: 1,
    speedScale: 1,
    gazeScale: 1,
    variantHoldMs: [7500, 13500],
    microIntervalMs: [4000, 11500],
    microActions: [...GENTLE_MICRO_ACTIONS, ...EXPRESSIVE_MICRO_ACTIONS],
    largerMicroActions: [],
    largerActionChance: 0,
    previewAction: "curious_tilt",
  },
  {
    id: "neuro_subtle",
    name: "Neuro Subtle & Alive",
    shortLabel: "Neuro Subtle",
    description: "Gentle breathing, irregular body sway, slow head drift, natural eyes and blinks, tiny facial changes, and rare larger fidgets.",
    energy: "Low",
    variantNames: ["calm_breathing", "attentive", "curious_lean", "thoughtful_scan", "room_watch", "shy_sway"],
    faceScale: 0.62,
    motionScale: 0.55,
    speedScale: 0.82,
    gazeScale: 0.68,
    variantHoldMs: [11000, 20000],
    microIntervalMs: [6500, 14500],
    microActions: GENTLE_MICRO_ACTIONS,
    largerMicroActions: ["double_nod", "curious_tilt", "friendly_wink", "shy_dip"],
    largerActionChance: 0.14,
    previewAction: "posture_shift",
  },
  {
    id: "neuro_classic",
    name: "Neuro Classic Fidget",
    shortLabel: "Neuro Classic",
    description: "Viewer-facing and lightly restless: frequent eye checks, small nods, head tilts, posture shifts, and occasional playful reactions.",
    energy: "Medium",
    variantNames: ["attentive", "calm_breathing", "curious_lean", "playful_peek", "room_watch", "shy_sway", "confident_pose"],
    faceScale: 0.78,
    motionScale: 0.78,
    speedScale: 1.05,
    gazeScale: 0.9,
    variantHoldMs: [8500, 14500],
    microIntervalMs: [3800, 8500],
    microActions: GENTLE_MICRO_ACTIONS,
    largerMicroActions: EXPRESSIVE_MICRO_ACTIONS,
    largerActionChance: 0.24,
    previewAction: "glance_right",
  },
  {
    id: "neuro_playful",
    name: "Neuro Playful Energy",
    shortLabel: "Playful",
    description: "A livelier stream idle with bouncy posture, quick glances, curious tilts, winks, and more noticeable upper-body motion.",
    energy: "High",
    variantNames: ["playful_peek", "curious_lean", "gentle_groove", "confident_pose", "room_watch", "shy_sway"],
    faceScale: 0.95,
    motionScale: 1.18,
    speedScale: 1.28,
    gazeScale: 1.05,
    variantHoldMs: [6000, 10500],
    microIntervalMs: [2600, 6200],
    microActions: ["small_nod", "glance_left", "glance_right", "double_blink", "posture_shift"],
    largerMicroActions: ["double_nod", "curious_tilt", "friendly_wink"],
    largerActionChance: 0.38,
    previewAction: "friendly_wink",
  },
  {
    id: "neuro_focused",
    name: "Neuro Stream Focus",
    shortLabel: "Stream Focus",
    description: "Mostly faces the viewer and stays readable on stream, with restrained breathing, attentive eye movement, and sparse fidgets.",
    energy: "Low",
    variantNames: ["attentive", "room_watch", "confident_pose", "calm_breathing"],
    faceScale: 0.48,
    motionScale: 0.42,
    speedScale: 0.86,
    gazeScale: 0.5,
    variantHoldMs: [13000, 22000],
    microIntervalMs: [8500, 17000],
    microActions: ["small_nod", "glance_left", "glance_right", "double_blink", "posture_shift"],
    largerMicroActions: ["curious_tilt"],
    largerActionChance: 0.08,
    previewAction: "small_nod",
  },
  {
    id: "cozy",
    name: "Cozy / Sleepy",
    shortLabel: "Cozy",
    description: "Slow breathing and soft drifting with lowered eyes, sleepy nods, shy dips, and occasional daydreaming looks.",
    energy: "Low",
    variantNames: ["sleepy_drift", "daydreaming", "star_gazing", "calm_breathing", "shy_sway"],
    faceScale: 0.78,
    motionScale: 0.62,
    speedScale: 0.68,
    gazeScale: 0.55,
    variantHoldMs: [12000, 21000],
    microIntervalMs: [7500, 15500],
    microActions: ["small_nod", "double_blink", "shy_dip", "posture_shift"],
    largerMicroActions: ["double_nod", "glance_left", "glance_right"],
    largerActionChance: 0.12,
    previewAction: "shy_dip",
  },
  {
    id: "minimal",
    name: "Minimal Breathing",
    shortLabel: "Minimal",
    description: "Near-static presentation with natural blinking, very gentle breathing, tiny gaze drift, and rare posture corrections.",
    energy: "Minimal",
    variantNames: ["calm_breathing", "attentive"],
    faceScale: 0.28,
    motionScale: 0.24,
    speedScale: 0.72,
    gazeScale: 0.28,
    variantHoldMs: [18000, 30000],
    microIntervalMs: [15000, 28000],
    microActions: ["double_blink", "small_nod", "posture_shift"],
    largerMicroActions: [],
    largerActionChance: 0,
    previewAction: "double_blink",
  },
] as const;

export const DEFAULT_LIVE2D_IDLE_PRESET: Live2DIdlePresetId = "dynamic";

export function getLive2DIdlePreset(value?: string | null): Live2DIdlePresetDefinition {
  return LIVE2D_IDLE_PRESETS.find((preset) => preset.id === value)
    ?? LIVE2D_IDLE_PRESETS[0];
}
