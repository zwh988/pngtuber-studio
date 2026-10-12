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
