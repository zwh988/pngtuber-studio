/**
 * Manual take trim (M5-0): pure helpers for the trimmer in the take picker.
 * Times are raw take milliseconds. The backend (`backend/audio/trim.py`) is the truth;
 * `MIN_KEEP_MS` and `trimTag` mirror it.
 */

/** A trim must keep at least this much of the take (`MANUAL_MIN_KEEP_MS`). */
export const MIN_KEEP_MS = 200;

/** The two cut points as the handles hold them: always numbers, 0 and the take length = no cut. */
export interface Cuts {
  start: number;
  end: number;
}

/** Stored cut points (null = no cut) as handle positions. */
export function cutsFrom(start: number | null, end: number | null, durationMs: number): Cuts {
  return { start: start ?? 0, end: end ?? durationMs };
}

/** Handle positions as the op wants them: whole ms, a cut at either end of the take becomes null. */
export function cutsToOp(cuts: Cuts, durationMs: number): { start_ms: number | null; end_ms: number | null } {
  const start = Math.round(cuts.start);
  const end = Math.round(cuts.end);
  return {
    start_ms: start <= 0 ? null : start,
    end_ms: end >= durationMs ? null : end,
  };
}

/**
 * Move one handle to `ms`, kept inside the take and at least `minKeep` from the other handle
 * (or the whole take, if it is shorter than that).
 */
export function moveHandle(
  cuts: Cuts,
  which: "start" | "end",
  ms: number,
  durationMs: number,
  minKeep = MIN_KEEP_MS,
): Cuts {
  const keep = Math.min(minKeep, durationMs);
  const value = Math.round(ms);
  if (which === "start") {
    const start = Math.max(0, Math.min(value, cuts.end - keep));
    return { start: Math.max(0, start), end: cuts.end };
  }
  const end = Math.min(durationMs, Math.max(value, cuts.start + keep));
  return { start: cuts.start, end: Math.min(durationMs, end) };
}

/** Same tag as `trim_tag` in `backend/project/timeline.py`: "" without a cut, else "start-end". */
export function trimTag(start: number | null, end: number | null): string {
  if (start === null && end === null) {
    return "";
  }
  return `${start ?? ""}-${end ?? ""}`;
}

/** True when the handles differ from the stored cut points. */
export function cutsChanged(
  cuts: Cuts,
  storedStart: number | null,
  storedEnd: number | null,
  durationMs: number,
): boolean {
  const op = cutsToOp(cuts, durationMs);
  return op.start_ms !== storedStart || op.end_ms !== storedEnd;
}

/** Pixel x for a time on a canvas `width` px wide showing the whole take. */
export function msToX(ms: number, durationMs: number, width: number): number {
  return durationMs <= 0 ? 0 : (ms / durationMs) * width;
}

/** Time for a pixel x (clamped to the take). */
export function xToMs(x: number, durationMs: number, width: number): number {
  if (width <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(durationMs, (x / width) * durationMs));
}
