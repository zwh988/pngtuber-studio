/**
 * Pure helpers for the video lanes on the timeline (M8-2). The lanes sit above the main
 * footage; `TimelineState.video_lanes` is bottom to top, so the LAST lane is drawn first,
 * under the "+ Video lane" row at the top. Lane clips sit at TIMELINE times and never
 * overlap on one lane (the backend refuses that too).
 */

import type { TimelineLaneClip } from "./api";

export const VIDEO_LANE_H = 34;
export const VIDEO_GAP = 2;
/** The "+ Video lane" row above the top lane (also a drop target for a new lane). */
export const VIDEO_ADD_H = 18;
/** Shortest clip a trim may leave, in ms (the backend's MIN_LANE_CLIP_MS). */
export const MIN_LANE_CLIP_MS = 40;
/** Drag type of a recording dragged from the Footage tab (its source id). */
export const FOOTAGE_DRAG_TYPE = "application/x-pngtuber-footage";

export type VideoLayout = {
  addY: number;
  /** Top of lane `index` (0 = the lowest lane, drawn last). */
  laneY: (index: number) => number;
  /** First y under the video block. */
  bottom: number;
};

export function videoLayout(top: number, laneCount: number): VideoLayout {
  const first = top + VIDEO_ADD_H + VIDEO_GAP;
  const laneY = (index: number): number => first + (laneCount - 1 - index) * (VIDEO_LANE_H + VIDEO_GAP);
  return { addY: top, laneY, bottom: first + laneCount * (VIDEO_LANE_H + VIDEO_GAP) };
}

/** The lane index under `y`, "add" for the add row, or null outside the video block. */
export function videoLaneAt(y: number, top: number, laneCount: number): number | "add" | null {
  const { bottom } = videoLayout(top, laneCount);
  if (y < top || y >= bottom) {
    return null;
  }
  const first = top + VIDEO_ADD_H + VIDEO_GAP;
  if (y < first) {
    return "add";
  }
  const row = Math.min(laneCount - 1, Math.floor((y - first) / (VIDEO_LANE_H + VIDEO_GAP)));
  return laneCount - 1 - row;
}

/** Lane index for a vertical drag: the lane under `y`, clamped to the lanes there are. */
export function dragVideoLaneIndex(y: number, top: number, laneCount: number): number {
  const first = top + VIDEO_ADD_H + VIDEO_GAP;
  const row = Math.min(Math.max(Math.floor((y - first) / (VIDEO_LANE_H + VIDEO_GAP)), 0), Math.max(0, laneCount - 1));
  return laneCount - 1 - row;
}

/**
 * Where a dragged clip edge may go, as a TIMELINE time: a recording stops at its start and
 * end; a still can be any length. Never into the neighbouring clips, never shorter than
 * MIN_LANE_CLIP_MS, never before 0.
 */
export function laneTrimTarget(
  clip: TimelineLaneClip,
  edge: "start" | "end",
  ms: number,
  clips: TimelineLaneClip[],
): number {
  const still = clip.image_id !== null;
  const neighbours = clips.filter((c) => c.lane_id === clip.lane_id && c.id !== clip.id);
  if (edge === "start") {
    const prevEnd = Math.max(0, ...neighbours.filter((c) => c.end_ms <= clip.timeline_ms).map((c) => c.end_ms));
    const lowest = still ? prevEnd : Math.max(clip.timeline_ms - clip.in_ms, prevEnd);
    return Math.round(Math.min(Math.max(ms, lowest), clip.end_ms - MIN_LANE_CLIP_MS));
  }
  const nextStart = Math.min(
    Infinity,
    ...neighbours.filter((c) => c.timeline_ms >= clip.end_ms).map((c) => c.timeline_ms),
  );
  const fileEnd = still ? Infinity : clip.timeline_ms + (clip.source_duration_ms - clip.in_ms);
  return Math.round(Math.max(Math.min(ms, fileEnd, nextStart), clip.timeline_ms + MIN_LANE_CLIP_MS));
}

/** The clip as it looks with an edge dragged to `ms` (already clamped by laneTrimTarget). */
export function withLaneTrim(clip: TimelineLaneClip, edge: "start" | "end", ms: number): TimelineLaneClip {
  if (edge === "end") {
    return { ...clip, end_ms: ms, out_ms: clip.in_ms + (ms - clip.timeline_ms) };
  }
  const delta = ms - clip.timeline_ms;
  if (clip.image_id !== null) {
    return { ...clip, timeline_ms: ms, out_ms: clip.out_ms - delta };
  }
  return { ...clip, timeline_ms: ms, in_ms: clip.in_ms + delta };
}

/** Last TIMELINE time any lane clip shows (0 with none). */
export function laneEndMs(clips: TimelineLaneClip[]): number {
  return Math.max(0, ...clips.map((c) => c.end_ms));
}
