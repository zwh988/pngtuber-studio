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
