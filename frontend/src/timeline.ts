import type { TimelineClip } from "./api";

/**
 * Index of the clip under a timeline time. Times past the end give the last clip,
 * negative times give the first, an empty list gives -1.
 * Display and playback only: the backend `timemap` module stays the source of truth.
 */
export function clipIndexAt(clips: TimelineClip[], timelineMs: number): number {
  if (clips.length === 0) {
    return -1;
  }
  for (let i = 0; i < clips.length; i += 1) {
    const clip = clips[i];
    if (clip !== undefined && timelineMs < clip.end_ms) {
      return i;
    }
  }
  return clips.length - 1;
}

/** Source time (ms) for a timeline time inside `clip`, kept to the clip's last included millisecond. */
export function toSource(clip: TimelineClip, timelineMs: number): number {
  const ms = clip.in_ms + (timelineMs - clip.start_ms) * clip.speed;
  return Math.min(Math.max(ms, clip.in_ms), clip.out_ms - 1);
}

/**
 * Timeline time one source frame before (-1) or after (+1) `timelineMs`.
 * Frames are counted on the grid of the source under the playhead (59.94 fps gives 16.683 ms
 * frames, rounded to the nearest). Stepping past a clip's edge lands on the neighbouring clip.
 */
export function stepFrame(clips: TimelineClip[], timelineMs: number, direction: 1 | -1): number {
  const i = clipIndexAt(clips, timelineMs);
  const clip = clips[i];
  if (clip === undefined) {
    return timelineMs;
  }
  const source = clip.source;
  const frameMs = source === null ? 1000 / 60 : (1000 * source.fps_den) / source.fps_num;
  const sourceMs = clip.in_ms + (timelineMs - clip.start_ms) * clip.speed;
  const target = Math.round(Math.round(sourceMs / frameMs) * frameMs + direction * frameMs);
  if (target >= clip.out_ms) {
    const next = clips[i + 1];
    return next === undefined ? clip.end_ms : next.start_ms;
  }
  if (target < clip.in_ms) {
    return i === 0 ? clip.start_ms : clip.start_ms - 1;
  }
  return Math.round(clip.start_ms + (target - clip.in_ms) / clip.speed);
}

/** Length of one source frame in ms (fractional), from the clip's source. */
function frameLength(clip: TimelineClip): number {
  const source = clip.source;
  return source === null ? 1000 / 60 : (1000 * source.fps_den) / source.fps_num;
}

/**
 * Source time for an edge dragged to `timelineMs`, as it will be sent to the backend:
 * snapped to the source's frame grid, never closer than one frame to the other edge,
 * and kept inside the source (0 to its duration). Dragging outward extends the clip.
 */
export function trimTarget(clip: TimelineClip, edge: "in" | "out", timelineMs: number): number {
  const frame = frameLength(clip);
  const minLength = Math.max(1, Math.round(frame));
  const raw = clip.in_ms + (timelineMs - clip.start_ms) * clip.speed;
  const snapped = Math.round(Math.round(raw / frame) * frame);
  if (edge === "in") {
    return Math.min(Math.max(snapped, 0), clip.out_ms - minLength);
  }
  const sourceEnd = clip.source === null ? clip.out_ms : clip.source.duration_ms;
  return Math.max(Math.min(snapped, sourceEnd), clip.in_ms + minLength);
}

/** The clip list as it would look with one edge moved: spans of that clip and the ones after it. */
export function withTrim(
  clips: TimelineClip[],
  clipId: string,
  edge: "in" | "out",
  sourceMs: number,
): TimelineClip[] {
  let shift = 0;
  return clips.map((clip) => {
    if (clip.id !== clipId) {
      return shift === 0
        ? clip
        : { ...clip, start_ms: clip.start_ms + shift, end_ms: clip.end_ms + shift };
    }
    const inMs = edge === "in" ? sourceMs : clip.in_ms;
    const outMs = edge === "out" ? sourceMs : clip.out_ms;
    const duration = Math.round((outMs - inMs) / clip.speed);
    shift = duration - clip.duration_ms;
    return {
      ...clip,
      in_ms: inMs,
      out_ms: outMs,
      duration_ms: duration,
      end_ms: clip.start_ms + duration,
    };
  });
}

/**
 * Where a dragged clip lands: its position AFTER the move (what `reorder_clip` takes).
 * Counts the other clips whose midpoint is before the pointer's timeline time.
 */
export function dropSlot(clips: TimelineClip[], draggedId: string, timelineMs: number): number {
  let slot = 0;
  for (const clip of clips) {
    if (clip.id !== draggedId && (clip.start_ms + clip.end_ms) / 2 < timelineMs) {
      slot += 1;
    }
  }
  return slot;
}
