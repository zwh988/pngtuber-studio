/**
 * Several lane clips moved together (keyframes polish, user 2026-11-23). Pure.
 *
 * Video-lane and audio-lane clips can be box-selected, Shift-clicked and dragged as one
 * group: every clip shifts by the same time and stays on its own lane. A group move must
 * not push a clip before 0 or onto a clip outside the group on its lane.
 */

export type GroupClip = { id: string; lane_id: string; timeline_ms: number; end_ms: number };

/** The shift, cut down so no clip of the group starts before 0. */
export function clampGroupShift(clips: readonly GroupClip[], ids: readonly string[], deltaMs: number): number {
  const starts = clips.filter((c) => ids.includes(c.id)).map((c) => c.timeline_ms);
  if (starts.length === 0) return deltaMs;
  return Math.max(deltaMs, -Math.min(...starts));
}

/** True when every clip of the group fits on its lane after the shift (the group's own clips do not block it). */
export function groupFits(clips: readonly GroupClip[], ids: readonly string[], deltaMs: number): boolean {
  const moving = clips.filter((c) => ids.includes(c.id));
  const staying = clips.filter((c) => !ids.includes(c.id));
  return moving.every((m) => {
    const start = m.timeline_ms + deltaMs;
    const end = m.end_ms + deltaMs;
    return start >= 0 && !staying.some((s) => s.lane_id === m.lane_id && s.timeline_ms < end && start < s.end_ms);
  });
}

/**
 * The group's clips in the order their moves can be applied one by one without one
 * moved clip landing on another that has not moved yet: the last first when moving
 * later, the first first when moving earlier.
 */
export function groupMoveOrder<C extends GroupClip>(clips: readonly C[], ids: readonly string[], deltaMs: number): C[] {
  const moving = clips.filter((c) => ids.includes(c.id));
  return moving.sort((a, b) => (deltaMs > 0 ? b.timeline_ms - a.timeline_ms : a.timeline_ms - b.timeline_ms));
}

/** Clips whose span overlaps `[loMs, hiMs]` on one of the given lanes (a selection box). */
export function clipsInBox<C extends GroupClip>(clips: readonly C[], laneIds: ReadonlySet<string>, loMs: number, hiMs: number): C[] {
  return clips.filter((c) => laneIds.has(c.lane_id) && c.timeline_ms <= hiMs && loMs <= c.end_ms);
}
