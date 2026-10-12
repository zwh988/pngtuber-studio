<script lang="ts">
  import { untrack } from "svelte";
  import type { TimelineClip } from "./api";
  import { clock } from "./format";
  import { clipIndexAt } from "./timeline";

  let {
    clips,
    durationMs,
    playheadMs = $bindable(0),
    selectedId = $bindable(null),
    label,
  }: {
    clips: TimelineClip[];
    durationMs: number;
    playheadMs?: number;
    selectedId?: string | null;
    label: (clip: TimelineClip) => string;
  } = $props();

  const RULER_H = 26;
  const LANE_Y = 32;
  const LANE_H = 60;
  const HEIGHT = 100;
  /** Empty space kept to the right of the last clip, in pixels. */
  const GUTTER = 40;
  const MIN_PX = 0.0005;
  const MAX_PX = 2;
  const STEPS = [
    10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000, 30000, 60000, 120000, 300000,
    600000,
  ];

  let canvasEl = $state<HTMLCanvasElement | null>(null);
  let viewWidth = $state(0);
  /** Zoom: pixels per millisecond. */
  let pxPerMs = $state(0.1);
  /** Timeline time at the left edge of the view (ms). */
  let scrollMs = $state(0);
  let dragging = false;
  let fitted = false;

  const viewMs = $derived(viewWidth / pxPerMs);
  const maxScrollMs = $derived(Math.max(0, durationMs - (viewWidth - GUTTER) / pxPerMs));

  function clampPx(px: number): number {
    return Math.min(Math.max(px, MIN_PX), MAX_PX);
  }

  function setScroll(ms: number): void {
    scrollMs = Math.min(Math.max(ms, 0), maxScrollMs);
  }

  function fit(): void {
    if (viewWidth <= 0 || durationMs <= 0) {
      return;
    }
    pxPerMs = clampPx((viewWidth - GUTTER) / durationMs);
    scrollMs = 0;
  }

  /** Zoom by `factor`, keeping the time under view-x `x` where it is. */
  function zoomAt(factor: number, x: number): void {
    const anchorMs = scrollMs + x / pxPerMs;
    pxPerMs = clampPx(pxPerMs * factor);
    setScroll(anchorMs - x / pxPerMs);
  }

  function rulerLabel(t: number, step: number): string {
    const m = Math.floor(t / 60000);
    const s = String(Math.floor((t % 60000) / 1000)).padStart(2, "0");
    if (step >= 1000) {
      return `${m}:${s}`;
    }
    return `${m}:${s}.${String(t % 1000).padStart(3, "0")}`;
  }

  function draw(): void {
    const canvas = canvasEl;
    if (canvas === null || viewWidth <= 0) {
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(viewWidth * dpr);
    canvas.height = Math.round(HEIGHT * dpr);
    const ctx = canvas.getContext("2d");
    if (ctx === null) {
      return;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const xOf = (ms: number): number => (ms - scrollMs) * pxPerMs;

    ctx.fillStyle = "#1e1e24";
    ctx.fillRect(0, 0, viewWidth, HEIGHT);

    // Ruler
    ctx.fillStyle = "#2a2a33";
    ctx.fillRect(0, 0, viewWidth, RULER_H);
    const step = STEPS.find((s) => s * pxPerMs >= 90) ?? STEPS[STEPS.length - 1] ?? 1000;
    const minor = step / 5;
    ctx.font = "11px system-ui, sans-serif";
    ctx.textBaseline = "top";
    ctx.lineWidth = 1;
    const endMs = scrollMs + viewMs;
    for (let t = Math.floor(scrollMs / minor) * minor; t <= endMs; t += minor) {
      const x = Math.round(xOf(t)) + 0.5;
      const major = t % step === 0;
      ctx.strokeStyle = major ? "#9a9aa8" : "#5a5a66";
      ctx.beginPath();
      ctx.moveTo(x, RULER_H);
      ctx.lineTo(x, RULER_H - (major ? 10 : 5));
      ctx.stroke();
      if (major && t >= 0) {
        ctx.fillStyle = "#c8c8d2";
        ctx.fillText(rulerLabel(t, step), x + 3, 4);
      }
    }

    // Video strip lane
    const hues = new Map<string, number>();
    for (const clip of clips) {
      if (!hues.has(clip.source_id)) {
        hues.set(clip.source_id, (hues.size * 70 + 210) % 360);
      }
    }
    for (const clip of clips) {
      const x0 = xOf(clip.start_ms);
      const w = Math.max(1, clip.duration_ms * pxPerMs);
      if (x0 + w < 0 || x0 > viewWidth) {
        continue;
      }
      const missing = clip.source?.file_missing ?? true;
      const selected = clip.id === selectedId;
      ctx.fillStyle = `hsl(${hues.get(clip.source_id) ?? 210} 45% ${selected ? 50 : 38}%)`;
      ctx.fillRect(x0, LANE_Y, Math.max(1, w - 1), LANE_H);
      if (selected) {
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.strokeRect(x0 + 1, LANE_Y + 1, Math.max(1, w - 3), LANE_H - 2);
      }
      if (missing) {
        ctx.strokeStyle = "#ff5a5a";
        ctx.lineWidth = 2;
        ctx.strokeRect(x0 + 1, LANE_Y + 1, Math.max(1, w - 3), LANE_H - 2);
      }
      if (w > 30) {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x0, LANE_Y, w - 1, LANE_H);
        ctx.clip();
        ctx.fillStyle = "#ffffff";
        ctx.textBaseline = "top";
        ctx.fillText(missing ? `${label(clip)} (missing)` : label(clip), x0 + 6, LANE_Y + 6);
        ctx.fillStyle = "#ffffffaa";
        ctx.fillText(clock(clip.duration_ms), x0 + 6, LANE_Y + 22);
        ctx.restore();
      }
      if (clip.speed !== 1 && w > 40) {
        const text = `${clip.speed}x`;
        const tw = ctx.measureText(text).width;
        ctx.fillStyle = "#f5c542";
        ctx.fillRect(x0 + w - tw - 14, LANE_Y + 4, tw + 10, 16);
        ctx.fillStyle = "#1e1e24";
        ctx.textBaseline = "top";
        ctx.fillText(text, x0 + w - tw - 9, LANE_Y + 6);
      }
    }

    // Cut markers between clips
    ctx.strokeStyle = "#ffffffcc";
    ctx.lineWidth = 1.5;
    for (let i = 1; i < clips.length; i += 1) {
      const clip = clips[i];
      if (clip === undefined) {
        continue;
      }
      const x = Math.round(xOf(clip.start_ms));
      if (x < -2 || x > viewWidth + 2) {
        continue;
      }
      ctx.beginPath();
      ctx.moveTo(x, LANE_Y - 4);
      ctx.lineTo(x, LANE_Y + LANE_H + 4);
      ctx.stroke();
    }

    // Playhead
    const px = xOf(playheadMs);
    if (px >= -6 && px <= viewWidth + 6) {
      ctx.strokeStyle = "#ff4d4d";
      ctx.fillStyle = "#ff4d4d";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, HEIGHT);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(px - 6, 0);
      ctx.lineTo(px + 6, 0);
      ctx.lineTo(px, 9);
      ctx.closePath();
      ctx.fill();
    }
  }

  // Redraw whenever anything it reads changes.
  $effect(() => {
    draw();
  });

  // Fit the whole timeline into view the first time there is a width.
  $effect(() => {
    if (!fitted && viewWidth > 0 && durationMs > 0) {
      fitted = true;
      untrack(fit);
    }
  });

  // Keep the scroll position valid after a zoom, resize or edit.
  $effect(() => {
    const max = maxScrollMs;
    untrack(() => {
      if (scrollMs > max) {
        scrollMs = max;
      }
    });
  });

  // Follow the playhead when it leaves the view (playback, seeking from elsewhere).
  $effect(() => {
    const ms = playheadMs;
    untrack(() => {
      if (viewWidth <= 0) {
        return;
      }
      const x = (ms - scrollMs) * pxPerMs;
      if (x < 0 || x > viewWidth - GUTTER / 2) {
        setScroll(ms - viewMs * 0.1);
      }
    });
  });

  // Pointer (click or drag to seek) and wheel (scroll, Ctrl+wheel to zoom). Plain listeners:
  // the wheel one must not be passive so the window itself does not zoom.
  $effect(() => {
    const canvas = canvasEl;
    if (canvas === null) {
      return;
    }
    function seek(e: PointerEvent): void {
      if (canvas === null) {
        return;
      }
      const rect = canvas.getBoundingClientRect();
      const x = Math.min(Math.max(e.clientX - rect.left, 0), viewWidth);
      const ms = Math.round(scrollMs + x / pxPerMs);
      playheadMs = Math.min(Math.max(ms, 0), durationMs);
    }
    function down(e: PointerEvent): void {
      if (e.button !== 0 || canvas === null) {
        return;
      }
      canvas.setPointerCapture(e.pointerId);
      dragging = true;
      seek(e);
      // A click in the video lane also selects the clip under it (empty space clears).
      const rect = canvas.getBoundingClientRect();
      const y = e.clientY - rect.top;
      if (y >= LANE_Y && y <= LANE_Y + LANE_H) {
        const ms = scrollMs + (e.clientX - rect.left) / pxPerMs;
        const clip = ms <= durationMs ? clips[clipIndexAt(clips, ms)] : undefined;
        selectedId = clip === undefined ? null : clip.id;
      }
    }
    function move(e: PointerEvent): void {
      if (dragging) {
        seek(e);
      }
    }
    function up(): void {
      dragging = false;
    }
    function wheel(e: WheelEvent): void {
      if (canvas === null) {
        return;
      }
      e.preventDefault();
      if (e.ctrlKey) {
        const x = e.clientX - canvas.getBoundingClientRect().left;
        zoomAt(Math.exp(-e.deltaY * 0.0015), x);
      } else {
        setScroll(scrollMs + (e.deltaX !== 0 ? e.deltaX : e.deltaY) / pxPerMs);
      }
    }
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    canvas.addEventListener("wheel", wheel, { passive: false });
    return () => {
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointercancel", up);
      canvas.removeEventListener("wheel", wheel);
    };
  });
</script>

<div class="timeline">
  <div class="bar">
    <button type="button" onclick={() => zoomAt(1 / 1.5, viewWidth / 2)}>Zoom out</button>
    <button type="button" onclick={() => zoomAt(1.5, viewWidth / 2)}>Zoom in</button>
    <button type="button" onclick={fit}>Fit</button>
    <span class="hint">Click or drag to seek, click a clip to select it. Wheel scrolls, Ctrl+wheel zooms.</span>
  </div>
  <div class="view" bind:clientWidth={viewWidth}>
    <canvas bind:this={canvasEl} style:width="{viewWidth}px" style:height="{HEIGHT}px"></canvas>
  </div>
  {#if maxScrollMs > 0}
    <input
      class="scroll"
      type="range"
      min="0"
      max={maxScrollMs}
      step="1"
      value={scrollMs}
      oninput={(e) => setScroll(e.currentTarget.valueAsNumber)}
    />
  {/if}
</div>

<style>
  .timeline {
    width: 100%;
  }
  .bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.4rem;
  }
  .hint {
    opacity: 0.7;
    font-size: 0.85rem;
  }
  .view {
    width: 100%;
  }
  canvas {
    display: block;
    cursor: pointer;
    touch-action: none;
  }
  .scroll {
    display: block;
    width: 100%;
    margin: 0.4rem 0 0;
  }
</style>
