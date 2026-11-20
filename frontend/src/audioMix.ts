/**
 * The level of audio clips over time (M8-1), pure. The export uses the same rules
 * (backend/export/audioclips.py), so what is heard in the preview is what is exported (rule 5):
 *
 * - A clip plays at clip gain + lane gain (dB), and not at all when its lane is muted, or when
 *   some lane is soloed and its lane is not.
 * - Fades are linear in amplitude: from 0 at the clip start to full level at `fade_in_ms`, and
 *   from full level at `length - fade_out_ms` down to 0 at the clip end.
 */

import type { AudioLane, TimelineAudioClip } from "./api";
import { laneAudible } from "./audioLanes";

export function dbToGain(db: number): number {
  return Math.pow(10, db / 20);
}

/** Level points of a clip: [ms from the clip start, linear gain], in time order. */
export function gainPoints(clip: TimelineAudioClip, laneGainDb: number): [number, number][] {
  const length = clip.end_ms - clip.timeline_ms;
  const g = dbToGain(clip.gain_db + laneGainDb);
  const points: [number, number][] = [];
  points.push([0, clip.fade_in_ms > 0 ? 0 : g]);
  if (clip.fade_in_ms > 0) {
    points.push([clip.fade_in_ms, g]);
  }
  if (clip.fade_out_ms > 0) {
    const outStart = length - clip.fade_out_ms;
    if (outStart > (points[points.length - 1]?.[0] ?? 0)) {
      points.push([outStart, g]);
    }
    points.push([length, 0]);
  } else {
    points.push([length, g]);
  }
  return points;
}

/** Linear gain at `ms` from the clip start (0 outside the clip). */
export function gainAt(points: [number, number][], ms: number): number {
  const first = points[0];
  const last = points[points.length - 1];
  if (first === undefined || last === undefined || ms < first[0] || ms > last[0]) {
    return 0;
  }
  for (let i = 1; i < points.length; i += 1) {
    const [t0, v0] = points[i - 1]!;
    const [t1, v1] = points[i]!;
    if (ms <= t1) {
      return t1 === t0 ? v1 : v0 + ((v1 - v0) * (ms - t0)) / (t1 - t0);
    }
  }
  return last[1];
}

/** One audio clip to start: `delayMs` after "now", `offsetMs` into the clip. */
export interface ClipStart {
  clipId: string;
  fileId: string;
  delayMs: number;
  /** Into the clip (not the file): the file position is `in_ms + offsetMs`. */
  offsetMs: number;
  /** How long it sounds from there. */
  durationMs: number;
  inMs: number;
  points: [number, number][];
}

/**
 * Which audio clips sound from timeline time `fromMs` on, and when each starts. A clip that
 * began before `fromMs` and is still running starts at once, part way in. Clips on lanes that
 * are not heard (mute, solo), clips on unknown lanes and clips already over are skipped.
 */
export function planClips(clips: TimelineAudioClip[], lanes: AudioLane[], fromMs: number): ClipStart[] {
  const laneById = new Map(lanes.map((lane) => [lane.id, lane]));
  const starts: ClipStart[] = [];
  for (const clip of clips) {
    const lane = laneById.get(clip.lane_id);
    if (lane === undefined || !laneAudible(lane, lanes) || clip.end_ms <= fromMs) {
      continue;
    }
    const ahead = clip.timeline_ms - fromMs;
    const offsetMs = Math.max(-ahead, 0);
    starts.push({
      clipId: clip.id,
      fileId: clip.file_id,
      delayMs: Math.max(ahead, 0),
      offsetMs,
      durationMs: clip.end_ms - clip.timeline_ms - offsetMs,
      inMs: clip.in_ms,
      points: gainPoints(clip, lane.gain_db),
    });
  }
  return starts.sort((a, b) => a.delayMs - b.delayMs || a.clipId.localeCompare(b.clipId));
}
