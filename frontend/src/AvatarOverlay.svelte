<script lang="ts">
  import { untrack } from "svelte";
  import { avatarSpriteUrl, type EditOp, type FrameTrack } from "./api";
  import {
    frameIndex,
    frameRect,
    hitTest,
    layout,
    poseAt,
    resizeFactor,
    type Layout,
    type Pose,
  } from "./avatarTrack";

  /**
   * The avatar over the preview video (M5-6). Draws the nearest sample of the frame track the
   * Python solver made; never computes motion (rule 5). Dragging the avatar moves it, the corner
   * handle resizes it; on release one batch keys x and y (or scale) at the playhead: one undo
   * step (decision 14). While a drag is in progress, and until the new track arrives, the
   * dragged pose is drawn locally so nothing waits for the backend (decision 13).
   */
  let {
    track,
    playheadMs,
    editable,
    oncommit,
  }: {
    track: FrameTrack | null;
    playheadMs: number;
    /** False while playing or busy: no dragging. */
    editable: boolean;
    /** Send a labelled batch; resolves true when it was saved. */
    oncommit: (label: string, ops: EditOp[]) => Promise<boolean>;
  } = $props();

  const MAX_IMAGES = 16;

  let host = $state<HTMLDivElement | null>(null);
  let canvas = $state<HTMLCanvasElement | null>(null);
  let boxW = $state(0);
  let boxH = $state(0);
  let loaded = $state(0); // bumped when a sprite finishes loading, to redraw
  let hover = $state<"handle" | "body" | null>(null);

  type Drag = {
    mode: "move" | "resize";
    startX: number;
    startY: number;
    pose: Pose;
    layout: Layout;
    dx: number;
    dy: number;
    factor: number;
    timelineMs: number;
  };
  let drag = $state<Drag | null>(null);
  /** A committed gesture shown until a track with another version arrives. */
  let held = $state<{ version: string; pose: Pose; timelineMs: number } | null>(null);

  const images = new Map<string, HTMLImageElement>();
  let lastDrawn: HTMLImageElement | null = null;

  function image(key: string): HTMLImageElement {
    let img = images.get(key);
    if (img === undefined) {
      img = new Image();
      img.decoding = "async";
      img.onload = () => {
        loaded += 1;
      };
      img.src = avatarSpriteUrl(key);
      images.set(key, img);
      if (images.size > MAX_IMAGES) {
        const oldest = images.keys().next().value;
        if (oldest !== undefined && oldest !== key) {
          images.delete(oldest);
        }
      }
    } else {
      images.delete(key); // most recently used goes last
      images.set(key, img);
    }
    return img;
  }

  /** Load the other states of the expression shown, so blinks and the mouth never wait. */
  function preloadSiblings(key: string): void {
    const cut = key.lastIndexOf("/");
    const expression = key.slice(0, cut);
    for (const state of ["oicm", "oiom", "cicm", "ciom"]) {
      const sibling = `${expression}/${state}`;
      if (sibling !== key && track?.sprites.includes(sibling)) {
        image(sibling);
      }
    }
  }

  $effect(() => {
    const el = host;
    if (el === null) return;
    const measure = (): void => {
      boxW = el.clientWidth;
      boxH = el.clientHeight;
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  });

  // A new track version replaces the locally held pose.
  $effect(() => {
    const version = track?.version;
    untrack(() => {
      if (held !== null && version !== held.version) {
        held = null;
      }
    });
  });

  function currentPose(): { pose: Pose; k: number } | null {
    if (track === null || track.frame_count === 0) return null;
    const k = frameIndex(track, playheadMs);
    let pose = poseAt(track, k);
    if (held !== null && Math.abs(held.timelineMs - playheadMs) < 1) {
      pose = { ...pose, x: held.pose.x, y: held.pose.y, scale: held.pose.scale };
    }
    if (drag !== null) {
      pose =
        drag.mode === "move"
          ? { ...pose, x: drag.pose.x + drag.dx, y: drag.pose.y + drag.dy }
          : { ...pose, scale: drag.pose.scale * drag.factor };
    }
    return { pose, k };
  }

  function currentLayout(pose: Pose, img: HTMLImageElement | null): Layout | null {
    if (track === null) return null;
    const aspect = img !== null && img.naturalHeight > 0 ? img.naturalWidth / img.naturalHeight : 0.5628;
    return layout(pose, frameRect(boxW, boxH), aspect, track.height_fraction);
  }

  let shownLayout: Layout | null = null;

  $effect(() => {
    void loaded;
    const el = canvas;
    if (el === null) return;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(boxW * dpr);
    const h = Math.round(boxH * dpr);
    if (el.width !== w) el.width = w;
    if (el.height !== h) el.height = h;
    const ctx = el.getContext("2d");
    if (ctx === null) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.scale(dpr, dpr);
    const found = currentPose();
    shownLayout = null;
    if (found === null || found.pose.sprite === null) return;
    const img = image(found.pose.sprite);
    preloadSiblings(found.pose.sprite);
    const ready = img.complete && img.naturalWidth > 0 ? img : lastDrawn;
    const l = currentLayout(found.pose, ready);
    if (l === null) return;
    shownLayout = l;
    if (ready !== null) {
      ctx.save();
      ctx.translate(l.ax, l.ay);
      ctx.rotate(l.rot);
      ctx.scale(l.sx, l.sy);
      ctx.drawImage(ready, -l.w / 2, -l.h, l.w, l.h);
      ctx.restore();
      if (ready === img) lastDrawn = img;
    }
    if (editable && (hover !== null || drag !== null)) {
      ctx.save();
      ctx.translate(l.ax, l.ay);
      ctx.rotate(l.rot);
      ctx.scale(l.sx, l.sy);
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 1;
      // Editing chrome only (the sprite above is solver output and is never restyled).
      const styles = canvas === null ? null : getComputedStyle(canvas);
      ctx.strokeStyle = styles?.getPropertyValue("--selected").trim() || "white";
      ctx.globalAlpha = 0.7;
      ctx.strokeRect(-l.w / 2, -l.h, l.w, l.h);
      ctx.globalAlpha = 1;
      ctx.setLineDash([]);
      ctx.fillStyle = styles?.getPropertyValue("--accent").trim() || "royalblue";
      ctx.fillRect(l.w / 2 - 6, -l.h - 6, 12, 12);
      ctx.restore();
    }
  });

  function point(e: PointerEvent): [number, number] {
    const rect = canvas?.getBoundingClientRect();
    return rect === undefined ? [0, 0] : [e.clientX - rect.left, e.clientY - rect.top];
  }

  function onMove(e: PointerEvent): void {
    const [px, py] = point(e);
    if (drag !== null) {
      const frame = frameRect(boxW, boxH);
      if (drag.mode === "move") {
        drag.dx = frame.width > 0 ? (px - drag.startX) / frame.width : 0;
        drag.dy = frame.height > 0 ? (py - drag.startY) / frame.height : 0;
      } else {
        drag.factor = resizeFactor(drag.layout, drag.startX, drag.startY, px, py);
      }
      return;
    }
    hover = editable && shownLayout !== null ? hitTest(px, py, shownLayout) : null;
  }

  function onDown(e: PointerEvent): void {
    if (!editable || e.button !== 0 || shownLayout === null) return;
    const [px, py] = point(e);
    const hit = hitTest(px, py, shownLayout);
    const found = currentPose();
    if (hit === null || found === null) return;
    e.preventDefault();
    e.stopPropagation();
    try {
      canvas?.setPointerCapture(e.pointerId);
    } catch {
      // not a live pointer (synthetic event): the drag still works inside the canvas
    }
    drag = {
      mode: hit === "handle" ? "resize" : "move",
      startX: px,
      startY: py,
      pose: found.pose,
      layout: shownLayout,
      dx: 0,
      dy: 0,
      factor: 1,
      timelineMs: Math.round(playheadMs),
    };
  }

  async function onUp(e: PointerEvent): Promise<void> {
    if (canvas?.hasPointerCapture(e.pointerId)) {
      canvas.releasePointerCapture(e.pointerId);
    }
    const done = drag;
    drag = null;
    if (done === null || track === null) return;
    const t = done.timelineMs;
    let label: string;
    let ops: EditOp[];
    let pose: Pose;
    if (done.mode === "move") {
      if (Math.abs(done.dx) < 0.001 && Math.abs(done.dy) < 0.001) return;
      label = "Move avatar";
      ops = [];
      if (Math.abs(done.dx) >= 0.001) {
        ops.push({ op: "key_lane_by", lane_id: "x", timeline_ms: t, delta: done.dx });
      }
      if (Math.abs(done.dy) >= 0.001) {
        ops.push({ op: "key_lane_by", lane_id: "y", timeline_ms: t, delta: done.dy });
      }
      pose = { ...done.pose, x: done.pose.x + done.dx, y: done.pose.y + done.dy };
    } else {
      if (Math.abs(done.factor - 1) < 0.005) return;
      label = "Resize avatar";
      ops = [{ op: "key_lane_by", lane_id: "scale", timeline_ms: t, factor: done.factor }];
      pose = { ...done.pose, scale: done.pose.scale * done.factor };
    }
    held = { version: track.version, pose, timelineMs: t };
    const ok = await oncommit(label, ops);
    if (!ok) held = null;
  }
</script>

<div class="overlay" bind:this={host}>
  <canvas
    bind:this={canvas}
    class:grab={editable && hover === "body"}
    class:resize={editable && hover === "handle"}
    class:dragging={drag !== null}
    onpointermove={onMove}
    onpointerdown={onDown}
    onpointerup={(e) => void onUp(e)}
    onpointercancel={() => (drag = null)}
    onpointerleave={() => {
      if (drag === null) hover = null;
    }}
  ></canvas>
</div>

<style>
  .overlay {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }
  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: auto;
  }
  canvas.grab {
    cursor: move;
  }
  canvas.resize {
    cursor: nwse-resize;
  }
  canvas.dragging {
    cursor: grabbing;
  }
</style>
