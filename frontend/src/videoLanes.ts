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

/**
 * Lane clips showing at timeline time `t`, bottom lane first (so later ones draw on top).
 * Hidden lanes, missing files and clips not on a known lane are left out.
 */
export function activeLaneClips(
  clips: TimelineLaneClip[],
  lanes: { id: string; hidden: boolean }[],
  t: number,
): TimelineLaneClip[] {
  const order = new Map(lanes.filter((lane) => !lane.hidden).map((lane) => [lane.id, lanes.indexOf(lane)]));
  return clips
    .filter((c) => order.has(c.lane_id) && !c.missing && c.timeline_ms <= t && t < c.end_ms)
    .sort((a, b) => (order.get(a.lane_id) ?? 0) - (order.get(b.lane_id) ?? 0));
}

/** Lane clips (visible, file present) starting within `aheadMs` after `t`: worth preloading. */
export function upcomingLaneClips(
  clips: TimelineLaneClip[],
  lanes: { id: string; hidden: boolean }[],
  t: number,
  aheadMs: number,
): TimelineLaneClip[] {
  const shown = new Set(lanes.filter((lane) => !lane.hidden).map((lane) => lane.id));
  return clips.filter((c) => shown.has(c.lane_id) && !c.missing && c.timeline_ms > t && c.timeline_ms <= t + aheadMs);
}

/** Time in the recording (ms) a lane clip shows at timeline time `t`. */
export function laneSourceMs(clip: TimelineLaneClip, t: number): number {
  return clip.in_ms + (t - clip.timeline_ms);
}

export type PipRect = { left: number; top: number; width: number; height: number };

/**
 * Where a lane clip's picture goes in a frame `frameW` x `frameH` (px, frame at 0,0): fitted
 * into the frame (contain) like the main footage, times `scale`, centred at (x, y) as fractions
 * of the frame. The export uses the same maths (backend/export/lanes.py).
 */
export function pipRect(
  frameW: number,
  frameH: number,
  mediaW: number,
  mediaH: number,
  clip: { x: number; y: number; scale: number },
): PipRect {
  if (frameW <= 0 || frameH <= 0 || mediaW <= 0 || mediaH <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  const fit = Math.min(frameW / mediaW, frameH / mediaH) * clip.scale;
  const width = mediaW * fit;
  const height = mediaH * fit;
  return {
    left: clip.x * frameW - width / 2,
    top: clip.y * frameH - height / 2,
    width,
    height,
  };
}

/** Limits a lane clip's centre and size are kept in (as in the schema). */
export const LANE_POS_MIN = -1;
export const LANE_POS_MAX = 2;
export const LANE_SCALE_MIN = 0.05;
export const LANE_SCALE_MAX = 4;

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

/** The centre after dragging the picture by (dx, dy) pixels in a frame of the given size. */
export function movedCentre(
  start: { x: number; y: number },
  dxPx: number,
  dyPx: number,
  frameW: number,
  frameH: number,
): { x: number; y: number } {
  if (frameW <= 0 || frameH <= 0) return { x: start.x, y: start.y };
  const round = (v: number): number => Math.round(v * 10000) / 10000;
  return {
    x: round(clamp(start.x + dxPx / frameW, LANE_POS_MIN, LANE_POS_MAX)),
    y: round(clamp(start.y + dyPx / frameH, LANE_POS_MIN, LANE_POS_MAX)),
  };
}

/**
 * The size after dragging a corner from `from` to `to` (pixels), the centre staying put:
 * the scale grows with the pointer's distance from the centre.
 */
export function resizedScale(
  scale: number,
  centre: { x: number; y: number },
  from: { x: number; y: number },
  to: { x: number; y: number },
): number {
  const before = Math.hypot(from.x - centre.x, from.y - centre.y);
  if (before < 1) return scale;
  const after = Math.hypot(to.x - centre.x, to.y - centre.y);
  return Math.round(clamp((scale * after) / before, LANE_SCALE_MIN, LANE_SCALE_MAX) * 10000) / 10000;
}
