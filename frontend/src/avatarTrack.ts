/**
 * Drawing the avatar frame track (M5-6). Pure helpers: the canvas only DRAWS what the Python
 * solver sampled (rule 5); nothing here computes motion. Placement (backend `track.py`): the
 * sprite's bottom centre sits at (x * frame width, y * frame height); at scale 1 the sprite is
 * `height_fraction` of the frame height; rotation turns about that point; squash scales the
 * width by (1 + squash) and the height by (1 - squash).
 */
import type { FrameTrack } from "./api";

/** The output frame's shape (1080p export). The preview letterboxes the video to it. */
export const FRAME_ASPECT = 16 / 9;

/** Added before flooring a frame position, so 100 ms at 30 fps is frame 3, not 2.9999. */
export const FRAME_EPSILON = 1e-6;

export interface Pose {
  sprite: string | null;
  x: number;
  y: number;
  scale: number;
  rotation: number;
  squash: number;
}

export interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Where a sprite lands on screen: anchor (bottom centre), size, rotation (radians), squash. */
export interface Layout {
  ax: number;
  ay: number;
  w: number;
  h: number;
  rot: number;
  sx: number;
  sy: number;
}

/**
 * The sampled frame shown at a timeline time: the last one that started (floor), clamped to
 * the track. The export uses the same rule (M6 decision 2: how ffmpeg holds a slower overlay
 * and how an editor shows a 30 fps PNG sequence). The tiny epsilon absorbs float error at an
 * exact frame time. Same as `track_frame_at` in `backend/avatar/track.py`.
 */
export function frameIndex(track: FrameTrack, ms: number): number {
  if (track.frame_count <= 0) {
    return 0;
  }
  const k = Math.floor((ms * track.fps) / 1000 + FRAME_EPSILON);
  return Math.min(Math.max(k, 0), track.frame_count - 1);
}

/** Sprite key shown at frame `k` (null: nothing to draw). */
export function spriteAt(track: FrameTrack, k: number): string | null {
  const runs = track.sprite_runs;
  let lo = 0;
  let hi = runs.length - 1;
  let found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (runs[mid][0] <= k) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (found < 0) {
    return null;
  }
  const index = runs[found][1];
  return index >= 0 ? (track.sprites[index] ?? null) : null;
}

export function poseAt(track: FrameTrack, k: number): Pose {
  return {
    sprite: spriteAt(track, k),
    x: track.x[k] ?? 0,
    y: track.y[k] ?? 0,
    scale: track.scale[k] ?? 1,
    rotation: track.rotation[k] ?? 0,
    squash: track.squash[k] ?? 0,
  };
}

/** The largest `aspect` rectangle centred in a box (like `object-fit: contain`). */
export function frameRect(boxW: number, boxH: number, aspect = FRAME_ASPECT): Rect {
  if (boxW <= 0 || boxH <= 0) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  if (boxW / boxH > aspect) {
    const width = boxH * aspect;
    return { left: (boxW - width) / 2, top: 0, width, height: boxH };
  }
  const height = boxW / aspect;
  return { left: 0, top: (boxH - height) / 2, width: boxW, height };
}

export function layout(pose: Pose, frame: Rect, imageAspect: number, heightFraction: number): Layout {
  const h = heightFraction * frame.height * pose.scale;
  return {
    ax: frame.left + pose.x * frame.width,
    ay: frame.top + pose.y * frame.height,
    w: h * imageAspect,
    h,
    rot: (pose.rotation * Math.PI) / 180,
    sx: 1 + pose.squash,
    sy: 1 - pose.squash,
  };
}

/** A screen point in the sprite's own frame: (0, 0) bottom centre, y up is negative. */
export function toLocal(px: number, py: number, l: Layout): [number, number] {
  const dx = px - l.ax;
  const dy = py - l.ay;
  const cos = Math.cos(-l.rot);
  const sin = Math.sin(-l.rot);
  const rx = dx * cos - dy * sin;
  const ry = dx * sin + dy * cos;
  return [l.sx === 0 ? 0 : rx / l.sx, l.sy === 0 ? 0 : ry / l.sy];
}

/** What a pointer is over: the resize handle (top-right corner), the body, or nothing. */
export function hitTest(px: number, py: number, l: Layout, handlePx = 10): "handle" | "body" | null {
  const [x, y] = toLocal(px, py, l);
  if (Math.abs(x - l.w / 2) <= handlePx && Math.abs(y + l.h) <= handlePx) {
    return "handle";
  }
  if (x >= -l.w / 2 && x <= l.w / 2 && y >= -l.h && y <= 0) {
    return "body";
  }
  return null;
}

/** Scale factor of a resize drag: how much farther from the anchor the pointer now is. */
export function resizeFactor(l: Layout, fromX: number, fromY: number, toX: number, toY: number): number {
  const before = Math.hypot(fromX - l.ax, fromY - l.ay);
  const after = Math.hypot(toX - l.ax, toY - l.ay);
  if (before < 1) {
    return 1;
  }
  return Math.min(Math.max(after / before, 0.05), 20);
}
