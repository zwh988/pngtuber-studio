/**
 * Snapping for clips dragged on the audio and video lanes (M8-2 addition, 2026-11-20).
 * Pure: the edges a dragged clip can snap to, and the snapped times.
 */

/** How close (in screen pixels) an edge must come to a snap point to jump to it. */
export const SNAP_PX = 8;

type Span = { id: string; start: number | null; end: number | null };

/**
 * Every time a dragged clip may snap to: the start and end of each span (main footage
 * clips, voice blocks, audio clips, lane clips) except the dragged clip, plus the playhead.
 * Sorted, without repeats.
 */
export function snapPoints(spans: Span[], playheadMs: number, exceptId: string): number[] {
  const points = new Set<number>([playheadMs]);
  for (const span of spans) {
    if (span.id === exceptId) continue;
    if (span.start !== null) points.add(span.start);
    if (span.end !== null) points.add(span.end);
  }
  return [...points].sort((a, b) => a - b);
}

/** The snap point nearest `ms` within `thresholdMs`, or null when none is that close. */
export function nearestPoint(ms: number, points: number[], thresholdMs: number): number | null {
  let best: number | null = null;
  for (const point of points) {
    const gap = Math.abs(point - ms);
    if (gap <= thresholdMs && (best === null || gap < Math.abs(best - ms))) best = point;
  }
  return best;
}

/** A dragged edge (a trim): the nearest snap point, or `ms` unchanged. */
export function snapEdge(ms: number, points: number[], thresholdMs: number): number {
  return nearestPoint(ms, points, thresholdMs) ?? ms;
}

/**
 * A moved clip: its start or its end snaps, whichever is closer to a point; the length
 * stays. Never before 0.
 */
export function snapMove(startMs: number, lengthMs: number, points: number[], thresholdMs: number): number {
  const byStart = nearestPoint(startMs, points, thresholdMs);
  const byEnd = nearestPoint(startMs + lengthMs, points, thresholdMs);
  const startGap = byStart === null ? Infinity : Math.abs(byStart - startMs);
  const endGap = byEnd === null ? Infinity : Math.abs(byEnd - (startMs + lengthMs));
  if (startGap === Infinity && endGap === Infinity) return startMs;
  const snapped = startGap <= endGap ? (byStart as number) : (byEnd as number) - lengthMs;
  return Math.max(0, snapped);
}
