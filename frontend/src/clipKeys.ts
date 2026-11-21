import type { ClipKey, ClipKeyProp, Interpolation, TimelineLaneClip } from "./api";

/**
 * Keyed values of an image lane clip (keyframes task, step 6). Pure.
 *
 * The same evaluation as `backend/export/clip_keys.py` and the lane maths in
 * `backend/avatar/lanes.py` (`ease`, `Lane.value_at`); both are checked against
 * `tests/fixtures/clip_key_cases.json`, so the preview draws what the export renders.
 */

export const CLIP_KEY_PROPS: readonly ClipKeyProp[] = ["x", "y", "scale", "opacity"];

export type ClipValues = Record<ClipKeyProp, number>;

const STRENGTH_MIN = 0;
const STRENGTH_MAX = 2;

function clamp01(u: number): number {
  return Math.min(1, Math.max(0, u));
}

function smoothstep(u: number): number {
  const v = clamp01(u);
  return v * v * (3 - 2 * v);
}

/** The full-strength curve of an easing kind: power 2 normal, 3 strong. */
function curve(kind: Interpolation, u: number, power: 2 | 3): number {
  if (kind === "ease_in") return u ** power;
  if (kind === "ease_out") return 1 - (1 - u) ** power;
  if (power === 2) return smoothstep(u);
  return u * u * u * (u * (6 * u - 15) + 10); // smootherstep
}

/** Progress (0 to 1) along a segment at fraction `u` (Python `ease`). */
export function ease(kind: Interpolation, u: number, strength = 1): number {
  const v = clamp01(u);
  if (kind === "hold") return 0;
  if (kind === "linear") return v;
  const s = Math.min(STRENGTH_MAX, Math.max(STRENGTH_MIN, strength));
  const normal = curve(kind, v, 2);
  if (s <= 1) return v + (normal - v) * s;
  return normal + (curve(kind, v, 3) - normal) * (s - 1);
}

type LaneKey = { t_ms: number; value: number; interpolation: Interpolation; strength: number };

/** Python `Lane(keys, base).value_at(t)`: keys at one time, the last one wins. */
export function laneValue(keys: readonly LaneKey[], t: number, base: number): number {
  const ordered = keys.map((key, index) => ({ key, index })).sort((a, b) => a.key.t_ms - b.key.t_ms || a.index - b.index);
  const merged: LaneKey[] = [];
  for (const { key } of ordered) {
    if (merged.length > 0 && merged[merged.length - 1].t_ms === key.t_ms) merged[merged.length - 1] = key;
    else merged.push(key);
  }
  if (merged.length === 0) return base;
  let i = -1;
  while (i + 1 < merged.length && merged[i + 1].t_ms <= t) i += 1;
  if (i < 0) return merged[0].value;
  const key = merged[i];
  if (key.interpolation === "hold" || i + 1 >= merged.length) return key.value;
  const next = merged[i + 1];
  const u = (t - key.t_ms) / (next.t_ms - key.t_ms);
  return key.value + (next.value - key.value) * ease(key.interpolation, u, key.strength);
}

function propKeys(keys: readonly ClipKey[], prop: ClipKeyProp): LaneKey[] {
  return keys
    .filter((k) => k.prop === prop)
    .map((k) => ({ t_ms: k.t_ms, value: k.value, interpolation: k.interpolation, strength: k.ease_strength }));
}

type KeyedClip = Pick<TimelineLaneClip, "timeline_ms" | "x" | "y" | "scale" | "opacity" | "keys">;

/** One property of the clip at a timeline time: its keys, or the clip's own value. */
export function clipValueAt(clip: KeyedClip, prop: ClipKeyProp, timelineMs: number): number {
  return laneValue(propKeys(clip.keys ?? [], prop), timelineMs - clip.timeline_ms, clip[prop]);
}

/** The clip's x, y, scale and opacity at a timeline time (Python `clip_values_at`). */
export function clipValuesAt(clip: KeyedClip, timelineMs: number): ClipValues {
  return {
    x: clipValueAt(clip, "x", timelineMs),
    y: clipValueAt(clip, "y", timelineMs),
    scale: clipValueAt(clip, "scale", timelineMs),
    opacity: clipValueAt(clip, "opacity", timelineMs),
  };
}

/** Whether the property has keys (then preview drags and the clip bar key it). */
export function isKeyed(clip: Pick<TimelineLaneClip, "keys">, prop: ClipKeyProp): boolean {
  return (clip.keys ?? []).some((k) => k.prop === prop);
}
