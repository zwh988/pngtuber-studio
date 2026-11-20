/**
 * Pure helpers for the audio lanes on the timeline (M8-1): layout rows, which lane is under
 * a point, where a dragged clip edge may go, and whether a clip fits on a lane. Audio clips
 * sit at TIMELINE times and never overlap on one lane (the backend refuses that too).
 */

import type { AudioLane, TimelineAudioClip } from "./api";

/** Height of one audio lane row and the gap under it, in px. */
export const AUDIO_LANE_H = 40;
export const AUDIO_GAP = 2;
/** The "+ Audio lane" row under the last lane (also a drop target for a new lane). */
export const ADD_ROW_H = 18;
/** Shortest clip a trim may leave, in ms (the backend's MIN_AUDIO_CLIP_MS). */
export const MIN_AUDIO_CLIP_MS = 10;

export type AudioLayout = {
  /** Top of lane `index`. */
  laneY: (index: number) => number;
  addY: number;
  /** First y under the audio block. */
  bottom: number;
};

export function audioLayout(top: number, laneCount: number): AudioLayout {
  const laneY = (index: number): number => top + index * (AUDIO_LANE_H + AUDIO_GAP);
  const addY = laneY(laneCount);
  return { laneY, addY, bottom: addY + ADD_ROW_H };
}

/** The lane index under `y`, "add" for the add row, or null when `y` is outside the block. */
export function laneAt(y: number, top: number, laneCount: number): number | "add" | null {
  const { addY, bottom } = audioLayout(top, laneCount);
  if (y < top || y >= bottom) {
    return null;
  }
  if (y >= addY) {
    return "add";
  }
  return Math.min(laneCount - 1, Math.floor((y - top) / (AUDIO_LANE_H + AUDIO_GAP)));
}

/** Lane index for a vertical drag: the lane under `y`, clamped to the lanes there are. */
export function dragLaneIndex(y: number, top: number, laneCount: number): number {
  const index = Math.floor((y - top) / (AUDIO_LANE_H + AUDIO_GAP));
  return Math.min(Math.max(index, 0), Math.max(0, laneCount - 1));
}

/** True when `[startMs, endMs)` is free on the lane (ignoring clip `exceptId`). */
export function fitsOnLane(
  clips: TimelineAudioClip[],
  laneId: string,
  startMs: number,
  endMs: number,
  exceptId: string | null = null,
): boolean {
  return !clips.some(
    (c) => c.lane_id === laneId && c.id !== exceptId && c.timeline_ms < endMs && startMs < c.end_ms,
  );
}

/**
 * Where a dragged clip edge may go, as a TIMELINE time: not past the start or end of the
 * file, not shorter than MIN_AUDIO_CLIP_MS, not into the neighbouring clips on the lane,
 * not before 0.
 */
export function audioTrimTarget(
  clip: TimelineAudioClip,
  edge: "start" | "end",
  ms: number,
  clips: TimelineAudioClip[],
): number {
  const neighbours = clips.filter((c) => c.lane_id === clip.lane_id && c.id !== clip.id);
  if (edge === "start") {
    const prevEnd = Math.max(
      0,
      ...neighbours.filter((c) => c.end_ms <= clip.timeline_ms).map((c) => c.end_ms),
    );
    const lowest = Math.max(clip.timeline_ms - clip.in_ms, prevEnd);
    const highest = clip.end_ms - MIN_AUDIO_CLIP_MS;
    return Math.round(Math.min(Math.max(ms, lowest), highest));
  }
  const nextStart = Math.min(
    Infinity,
    ...neighbours.filter((c) => c.timeline_ms >= clip.end_ms).map((c) => c.timeline_ms),
  );
  const highest = Math.min(clip.timeline_ms + (clip.file_duration_ms - clip.in_ms), nextStart);
  const lowest = clip.timeline_ms + MIN_AUDIO_CLIP_MS;
  return Math.round(Math.max(Math.min(ms, highest), lowest));
}

/** The clip as it looks with an edge dragged to `ms` (already clamped by audioTrimTarget). */
export function withAudioTrim(clip: TimelineAudioClip, edge: "start" | "end", ms: number): TimelineAudioClip {
  if (edge === "start") {
    return { ...clip, timeline_ms: ms, in_ms: clip.in_ms + (ms - clip.timeline_ms) };
  }
  return { ...clip, end_ms: ms, out_ms: clip.in_ms + (ms - clip.timeline_ms) };
}

/** The part of the file's peaks a clip shows, as fractions of the file (for peakSpan). */
export function peakWindow(clip: TimelineAudioClip): [number, number] {
  const total = clip.file_duration_ms;
  if (total <= 0) {
    return [0, 1];
  }
  return [clip.in_ms / total, clip.out_ms / total];
}

/** Whether a lane is heard: not muted, and when any lane is soloed, soloed itself. */
export function laneAudible(lane: AudioLane, lanes: AudioLane[]): boolean {
  if (lane.mute) {
    return false;
  }
  return !lanes.some((l) => l.solo) || lane.solo;
}

/** Last TIMELINE time any audio clip plays to (0 with none). */
export function audioEndMs(clips: TimelineAudioClip[]): number {
  return Math.max(0, ...clips.map((c) => c.end_ms));
}

/** Waveform resolution for a file: about 20 buckets a second, within the backend's limits. */
export function audioPeakBuckets(durationMs: number): number {
  return Math.min(4000, Math.max(64, Math.round(durationMs / 50)));
}
