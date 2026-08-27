import type { AvatarGesture } from "../types";

export interface Live2DModelDefinition {
  id: string;
  name: string;
  modelPath: string;
  edition: "Free" | "Pro" | "Sample";
  description: string;
}

export const DEFAULT_LIVE2D_MODEL_PATH =
  "/live2d/shizuku_ja/runtime/shizuku.model3.json";

/** Every Cubism runtime installed in frontend/public/live2d. */
export const LIVE2D_MODELS: readonly Live2DModelDefinition[] = [
  {
    id: "shizuku_ja",
    name: "Shizuku",
    modelPath: DEFAULT_LIVE2D_MODEL_PATH,
    edition: "Sample",
    description: "Classic Live2D sample with four character motions.",
  },
  {
    id: "hiyori_pro",
    name: "Hiyori",
    modelPath: "/live2d/hiyori_pro/runtime/hiyori_pro_t11.model3.json",
    edition: "Pro",
    description: "Full Hiyori rig with three idles and body gestures.",
  },
  {
    id: "hiyori_free",
    name: "Hiyori",
    modelPath: "/live2d/hiyori_free/runtime/hiyori_free_t08.model3.json",
    edition: "Free",
    description: "Lightweight Hiyori rig with three idles and body gestures.",
  },
  {
    id: "mao_pro",
    name: "Niziiro Mao",
    modelPath: "/live2d/mao_pro/runtime/mao_pro.model3.json",
    edition: "Pro",
    description: "VTuber-focused Cubism 5 rig with expressions and special motions.",
  },
  {
    id: "miku_pro",
    name: "Miku",
    modelPath: "/live2d/miku_pro/runtime/miku_sample_t04.model3.json",
    edition: "Pro",
    description: "Full Miku sample with three idles and multiple gestures.",
  },
  {
    id: "miku_free",
    name: "Miku",
    modelPath: "/live2d/miku_free/runtime/miku.model3.json",
    edition: "Free",
    description: "Lightweight Miku sample with seven action motions.",
  },
] as const;

const LEGACY_MODEL_PATHS: Record<string, string> = {
  shizuku: DEFAULT_LIVE2D_MODEL_PATH,
  shizuku_ja: DEFAULT_LIVE2D_MODEL_PATH,
  ...Object.fromEntries(LIVE2D_MODELS.map((model) => [model.id, model.modelPath])),
};

/** Resolve old friendly IDs while preserving custom .model3.json URLs. */
export function resolveLive2DModelPath(pathOrId?: string | null): string {
  const value = pathOrId?.trim();
  if (!value) return DEFAULT_LIVE2D_MODEL_PATH;
  return LEGACY_MODEL_PATHS[value] ?? value;
}

export function findLive2DModel(pathOrId?: string | null): Live2DModelDefinition | undefined {
  const resolved = resolveLive2DModelPath(pathOrId);
  return LIVE2D_MODELS.find((model) => model.modelPath === resolved);
}

/**
 * Motion names are authored by the model creator and are not portable. These
 * ordered aliases translate the AI's semantic gesture into the best motion the
 * active rig actually exposes. The empty name is intentional: Mao's bundled
 * action motions are stored in an unnamed Cubism group.
 */
const MOTION_GROUP_CANDIDATES: Record<AvatarGesture, readonly string[]> = {
  wave: ["Tap@Body", "FlickUp", "Tap", "Flick@Body", ""],
  warm_nod: ["Tap", "FlickDown", "Tap@Body", "Flick", ""],
  celebrate: ["FlickUp", "Flick@Body", "Tap@Body", "Flick", "Tap", ""],
  dance: ["Flick@Body", "Tap@Body", "FlickUp", "Flick", "Tap", ""],
  bow: ["FlickDown", "Tap@Body", "Tap", "Flick", ""],
  wink: ["Tap", "Flick", "FlickUp", ""],
  look_down: ["FlickDown", "Flick3", "Flick", "Tap", ""],
  firm_shake: ["Flick@Body", "Flick3", "Flick", "Tap", ""],
  recoil: ["Flick3", "Flick", "FlickUp", "Tap", ""],
  head_tilt: ["Tap", "Flick", "FlickDown", ""],
  lean_in: ["Tap@Body", "Tap", "FlickUp", ""],
  look_away: ["Flick", "Flick3", "FlickDown", "Tap", ""],
  laugh: ["Tap", "FlickUp", "Flick@Body", ""],
};

export function resolveMotionGroup(
  gesture: AvatarGesture,
  availableGroups: readonly string[],
): string | undefined {
  const available = new Set(availableGroups);
  return MOTION_GROUP_CANDIDATES[gesture].find((group) => available.has(group));
}

/**
 * Mao stores unrelated basic and magic-effect clips in the same unnamed
 * motion group. Restrict semantic actions to the matching basic clip so a
 * request such as Dance can never randomly launch a heart/rabbit effect.
 * An empty list intentionally selects the portable parameter animation only.
 */
const MAO_PRO_MOTION_INDICES: Partial<Record<AvatarGesture, readonly number[]>> = {
  dance: [0],       // mtn_02: symmetric rhythmic arm movement
  celebrate: [1],   // mtn_03: raised-arm celebration
  wave: [2],        // mtn_04: alternate-arm greeting
};

export function resolveMotionIndices(
  gesture: AvatarGesture,
  group: string,
  modelPath?: string | null,
): readonly number[] | undefined {
  if (resolveLive2DModelPath(modelPath) !== "/live2d/mao_pro/runtime/mao_pro.model3.json" || group !== "") {
    return undefined;
  }
  return MAO_PRO_MOTION_INDICES[gesture] ?? [];
}
