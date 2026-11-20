/**
 * Previous / next avatar key from the playhead (keyframes task, decision 1). Pure.
 *
 * Steps to the nearest key time strictly before or after the playhead (keys within
 * `KEY_NEAR_MS` of it count as "here", so a playhead parked on a key moves on). At that
 * time the key on `preferLane` is picked when there is one, else the first key there.
 */

/** Same as `KEY_NEAR_MS` in `backend/project/avatar_commands.py`: one 30 fps frame. */
export const KEY_NEAR_MS = 34;

export type NavKey = { id: string; lane_id: string; t_ms: number | null; orphaned: boolean };

export function stepKey<K extends NavKey>(
  keys: readonly K[],
  playheadMs: number,
  direction: 1 | -1,
  preferLane: string | null = null,
): K | null {
  let bestT: number | null = null;
  for (const key of keys) {
    if (key.t_ms === null || key.orphaned) continue;
    const gap = (key.t_ms - playheadMs) * direction;
    if (gap <= KEY_NEAR_MS) continue;
    if (bestT === null || (key.t_ms - bestT) * direction < 0) bestT = key.t_ms;
  }
  if (bestT === null) return null;
  const at = keys.filter((k) => k.t_ms === bestT && !k.orphaned);
  return at.find((k) => k.lane_id === preferLane) ?? at[0] ?? null;
}

/** The key on `laneId` nearest `ms`, within `KEY_NEAR_MS` (the backend's `key_near`). */
export function keyNear<K extends NavKey>(keys: readonly K[], laneId: string, ms: number): K | null {
  let best: K | null = null;
  for (const key of keys) {
    if (key.lane_id !== laneId || key.orphaned || key.t_ms === null) continue;
    const gap = Math.abs(key.t_ms - ms);
    if (gap <= KEY_NEAR_MS && (best === null || gap < Math.abs((best.t_ms ?? 0) - ms))) best = key;
  }
  return best;
}

/**
 * Several selected keys (keyframes decision 1). `primary` is the key the inspector shows;
 * `ids` the whole selection, which counts only while it holds `primary` (anything that
 * sets `primary` alone, such as the Avatar tab, collapses the selection to that key).
 */
export function keySelection(primary: string | null, ids: readonly string[]): string[] {
  if (primary === null) return [];
  return ids.includes(primary) ? [...ids] : [primary];
}

/**
 * The keys a click on `key` picks: on the collapsed Motion row every motion key at that
 * time (x, y and scale from one drag sit on one spot), else the key alone.
 */
export function keyGroup<K extends NavKey>(keys: readonly K[], key: K, collapsed: boolean): K[] {
  if (!collapsed || key.lane_id === "expression" || key.t_ms === null) return [key];
  return keys.filter((k) => k.t_ms === key.t_ms && k.lane_id !== "expression" && !k.orphaned);
}

/** The lanes the inspector shows together for one moment (keyframes decision 1). */
export const MOMENT_LANES = ["x", "y", "scale", "rotation"] as const;

/**
 * For a motion key at `ms`: each moment lane's key within `KEY_NEAR_MS` of it, or null
 * where that lane has no key then (so x, y and size of one drag are edited together).
 */
export function momentKeys<K extends NavKey>(
  keys: readonly K[],
  ms: number,
  lanes: readonly string[] = MOMENT_LANES,
): { laneId: string; key: K | null }[] {
  return lanes.map((laneId) => ({ laneId, key: keyNear(keys, laneId, ms) }));
}

/** A typed number: rounded to `step` and kept in the range; null when it is not a number. */
export function typedValue(text: string, min: number, max: number, step: number): number | null {
  const v = Number(text.trim().replace(",", "."));
  if (text.trim() === "" || !Number.isFinite(v)) return null;
  const clamped = Math.min(max, Math.max(min, v));
  const places = String(step).includes(".") ? String(step).length - String(step).indexOf(".") - 1 : 0;
  return Number((Math.round(clamped / step) * step).toFixed(places));
}

/** Shift-click: add the group to the selection, or take it out when all of it is in. */
export function toggleGroup(selection: readonly string[], group: readonly string[]): string[] {
  const all = group.every((id) => selection.includes(id));
  if (all) return selection.filter((id) => !group.includes(id));
  return [...selection, ...group.filter((id) => !selection.includes(id))];
}

/** A shift of several keys, cut down so none goes below `minMs` or above `maxMs`. */
export function clampShift(times: readonly number[], deltaMs: number, minMs: number, maxMs: number): number {
  if (times.length === 0) return deltaMs;
  const lo = Math.min(...times);
  const hi = Math.max(...times);
  return Math.min(Math.max(deltaMs, minMs - lo), maxMs - hi);
}
