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
