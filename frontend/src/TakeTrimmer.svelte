<script lang="ts">
  import { untrack } from "svelte";
  import {
    getTakePeaks,
    getTakeTrim,
    processedTakeUrl,
    takeMediaUrl,
    type PeaksReport,
    type TakeItem,
    type TakeTrimInfo,
  } from "./api";
  import {
    cutsChanged,
    cutsFrom,
    cutsToOp,
    moveHandle,
    msToX,
    trimTag,
    xToMs,
    type Cuts,
  } from "./trim";

  /**
   * Manual take trim (M5-0): the raw waveform of one take with two handles. Darkened: what
   * the manual cut removes. Hatched: what the automatic silence trim also removes inside it.
   * Apply commits one undo step; the raw file is never changed.
   */
  let {
    take,
    fxVersion,
    onapply,
    onclose,
  }: {
    take: TakeItem;
    /** `TimelineState.fx_version`, for the processed audio URL. */
    fxVersion: string;
    /** Save the cut points (null = no cut on that side); true when saved. */
    onapply: (startMs: number | null, endMs: number | null) => Promise<boolean>;
    onclose: () => void;
  } = $props();

  const WIDTH = 560;
  const HEIGHT = 96;
  const GRAB_PX = 8;

  let canvas = $state<HTMLCanvasElement | null>(null);
  let peaks = $state<PeaksReport | null>(null);
  let info = $state<TakeTrimInfo | null>(null);
  let cuts = $state<Cuts>({ start: 0, end: 0 });
  let error = $state<string | null>(null);
  let busy = $state(false);
  let dragging: "start" | "end" | null = null;
  let playMode = $state<"raw" | "processed" | null>(null);
  let playMs = $state<number | null>(null);
  let audio: HTMLAudioElement | null = null;
  let frame = 0;

  const duration = $derived(take.duration_ms);
  const storedTag = $derived(trimTag(take.trim_start_ms, take.trim_end_ms));
  const changed = $derived(cutsChanged(cuts, take.trim_start_ms, take.trim_end_ms, duration));
  const keptMs = $derived(info === null ? null : Math.max(0, info.auto_end_ms - info.auto_start_ms));

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  // A new take, or its stored trim changed (Apply, undo, redo): start from the stored cuts.
  $effect(() => {
    const id = take.id;
    void storedTag;
    untrack(() => {
      stop();
      cuts = cutsFrom(take.trim_start_ms, take.trim_end_ms, duration);
      void loadPeaks(id);
    });
  });

  async function loadPeaks(id: string): Promise<void> {
    if (peaks !== null && peaks.take_id === id) {
      return;
    }
    try {
      const report = await getTakePeaks(id, WIDTH);
      if (id === take.id) {
        peaks = report;
      }
    } catch (err) {
      error = message(err);
    }
  }

  // Where the automatic trim lands inside the handles: asked shortly after they stop moving.
  let previewTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const id = take.id;
    const op = cutsToOp(cuts, duration);
    const isStored = !changed;
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => {
      void (async () => {
        try {
          const next = isStored ? await getTakeTrim(id) : await getTakeTrim(id, op);
          if (id === take.id) {
            info = next;
            error = null;
          }
        } catch (err) {
          error = message(err);
        }
      })();
    }, 150);
    return () => clearTimeout(previewTimer);
  });

  $effect(() => () => stop());

  // ---- drawing ------------------------------------------------------------------

  $effect(() => {
    const el = canvas;
    if (el === null) {
      return;
    }
    const ctx = el.getContext("2d");
    if (ctx === null) {
      return;
    }
    const styles = getComputedStyle(el);
    const accent = styles.getPropertyValue("--accent").trim() || "#4a90e2";
    const text = styles.getPropertyValue("--text").trim() || "#ddd";
    ctx.clearRect(0, 0, WIDTH, HEIGHT);
    ctx.fillStyle = "#0004";
    ctx.fillRect(0, 0, WIDTH, HEIGHT);

    const mid = HEIGHT / 2;
    if (peaks !== null && peaks.buckets > 0) {
      ctx.fillStyle = accent;
      const step = WIDTH / peaks.buckets;
      for (let i = 0; i < peaks.buckets; i++) {
        const hi = peaks.highs[i] ?? 0;
        const lo = peaks.lows[i] ?? 0;
        const top = mid - hi * mid;
        const h = Math.max(1, (hi - lo) * mid);
        ctx.fillRect(i * step, top, Math.max(1, step), h);
      }
    }

    const sx = msToX(cuts.start, duration, WIDTH);
    const ex = msToX(cuts.end, duration, WIDTH);
    // Removed by the manual cut.
    ctx.fillStyle = "#000b";
    ctx.fillRect(0, 0, sx, HEIGHT);
    ctx.fillRect(ex, 0, WIDTH - ex, HEIGHT);
    // Also removed by the automatic trim (inside the cut).
    if (info !== null) {
      ctx.fillStyle = "#0007";
      const ax = msToX(info.auto_start_ms, duration, WIDTH);
      const bx = msToX(info.auto_end_ms, duration, WIDTH);
      if (ax > sx) ctx.fillRect(sx, 0, ax - sx, HEIGHT);
      if (bx < ex) ctx.fillRect(bx, 0, ex - bx, HEIGHT);
      ctx.strokeStyle = "#fff6";
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(ax + 0.5, 0);
      ctx.lineTo(ax + 0.5, HEIGHT);
      ctx.moveTo(bx - 0.5, 0);
      ctx.lineTo(bx - 0.5, HEIGHT);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Handles.
    ctx.fillStyle = text;
    for (const x of [sx, ex]) {
      ctx.fillRect(Math.round(x) - 1, 0, 2, HEIGHT);
      ctx.fillRect(Math.round(x) - 5, 0, 10, 10);
      ctx.fillRect(Math.round(x) - 5, HEIGHT - 10, 10, 10);
    }
    if (playMs !== null) {
      const px = msToX(playMs, duration, WIDTH);
      ctx.fillStyle = "#ff5252";
      ctx.fillRect(Math.round(px), 0, 1, HEIGHT);
    }
  });

  // ---- handles ------------------------------------------------------------------

  function canvasX(e: PointerEvent): number {
    const el = canvas;
    if (el === null) return 0;
    const rect = el.getBoundingClientRect();
    return ((e.clientX - rect.left) / rect.width) * WIDTH;
  }

  function onDown(e: PointerEvent): void {
    if (e.button !== 0) return;
    const x = canvasX(e);
    const sx = msToX(cuts.start, duration, WIDTH);
    const ex = msToX(cuts.end, duration, WIDTH);
    const ds = Math.abs(x - sx);
    const de = Math.abs(x - ex);
    // Grab the nearer handle (a click away from both moves the nearer one there).
    dragging = ds <= de ? "start" : "end";
    if (Math.min(ds, de) > GRAB_PX) {
      cuts = moveHandle(cuts, dragging, xToMs(x, duration, WIDTH), duration);
    }
    canvas?.setPointerCapture(e.pointerId);
  }

  function onMove(e: PointerEvent): void {
    if (dragging === null) return;
    cuts = moveHandle(cuts, dragging, xToMs(canvasX(e), duration, WIDTH), duration);
  }

  function onUp(e: PointerEvent): void {
    dragging = null;
    if (canvas?.hasPointerCapture(e.pointerId)) {
      canvas.releasePointerCapture(e.pointerId);
    }
  }

  function setField(which: "start" | "end", value: string): void {
    const ms = Number(value);
    if (Number.isFinite(ms)) {
      cuts = moveHandle(cuts, which, ms, duration);
    }
  }

  // ---- playback -----------------------------------------------------------------

  function stop(): void {
    cancelAnimationFrame(frame);
    if (audio !== null) {
      audio.pause();
      audio = null;
    }
    playMode = null;
    playMs = null;
  }

  /** Play the raw take between the handles (before Apply), with a moving line. */
  function playRaw(): void {
    if (playMode !== null) {
      stop();
      return;
    }
    const player = new Audio(takeMediaUrl(take.id));
    const from = cuts.start;
    const to = cuts.end;
    audio = player;
    playMode = "raw";
    const tickFrame = (): void => {
      if (audio !== player) return;
      const now = player.currentTime * 1000;
      playMs = now;
      if (now >= to || player.ended) {
        stop();
        return;
      }
      frame = requestAnimationFrame(tickFrame);
    };
    player.onloadedmetadata = () => {
      player.currentTime = from / 1000;
      void player
        .play()
        .then(() => {
          frame = requestAnimationFrame(tickFrame);
        })
        .catch(fail);
    };
    const fail = (): void => {
      if (audio === player) {
        stop();
        error = "Could not play this take.";
      }
    };
    player.onerror = fail;
  }

  /** Play the processed result (the saved trim through the voice chain): what the mix plays. */
  function playProcessed(): void {
    if (playMode !== null) {
      stop();
      return;
    }
    const player = new Audio(processedTakeUrl(take.id, 1, fxVersion, storedTag));
    audio = player;
    playMode = "processed";
    const fail = (): void => {
      if (audio === player) {
        stop();
        error = "Could not play the processed take (is the voice chain usable?).";
      }
    };
    player.onended = () => {
      if (audio === player) stop();
    };
    player.onerror = fail;
    void player.play().catch(fail);
  }

  async function apply(): Promise<void> {
    const op = cutsToOp(cuts, duration);
    busy = true;
    stop();
    try {
      await onapply(op.start_ms, op.end_ms);
    } finally {
      busy = false;
    }
  }

  function reset(): void {
    cuts = { start: 0, end: duration };
  }
</script>

<div class="trimmer">
  <div class="head">
    <strong>Trim take</strong>
    <span class="hint">{(duration / 1000).toFixed(2)} s recorded</span>
    <button type="button" class="close" onclick={() => { stop(); onclose(); }}>Close</button>
  </div>
  <canvas
    bind:this={canvas}
    width={WIDTH}
    height={HEIGHT}
    onpointerdown={onDown}
    onpointermove={onMove}
    onpointerup={onUp}
    onpointercancel={onUp}
  ></canvas>
  <div class="fields">
    <label>
      Start (ms)
      <input
        type="number"
        min="0"
        max={duration}
        step="1"
        value={Math.round(cuts.start)}
        onchange={(e) => setField("start", e.currentTarget.value)}
      />
    </label>
    <label>
      End (ms)
      <input
        type="number"
        min="0"
        max={duration}
        step="1"
        value={Math.round(cuts.end)}
        onchange={(e) => setField("end", e.currentTarget.value)}
      />
    </label>
    {#if keptMs !== null}
      <span class="hint">
        plays {(keptMs / 1000).toFixed(2)} s{info?.silent ? " (nothing loud found: kept whole)" : ""}
      </span>
    {/if}
  </div>
  <div class="buttons">
    <button type="button" onclick={playRaw} disabled={!take.file_exists}>
      {playMode === "raw" ? "Stop" : "Play cut"}
    </button>
    <button
      type="button"
      onclick={playProcessed}
      disabled={!take.file_exists || changed || fxVersion === "" || fxVersion === "invalid"}
      title={changed ? "Apply first" : "The saved trim through the voice chain"}
    >
      {playMode === "processed" ? "Stop" : "Play result"}
    </button>
    <button type="button" onclick={reset} disabled={cuts.start === 0 && cuts.end === duration}>
      Reset
    </button>
    <button type="button" class="primary" onclick={() => void apply()} disabled={!changed || busy}>
      Apply
    </button>
    {#if changed}<span class="hint">Not applied yet.</span>{/if}
  </div>
  <p class="hint">
    Drag the handles to cut the take at either end. Dark: cut away. Shaded: silence the automatic
    trim also removes. The recorded file is never changed; Ctrl+Z undoes a trim.
  </p>
  {#if error !== null}<p class="error">{error}</p>{/if}
</div>

<style>
  .trimmer {
    border: 1px solid #8886;
    padding: 0.5rem;
    margin: 0.25rem 0 0.75rem;
    background: #0002;
  }
  .head {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    margin-bottom: 0.35rem;
  }
  .close {
    margin-left: auto;
  }
  canvas {
    display: block;
    width: 100%;
    height: auto;
    cursor: ew-resize;
    touch-action: none;
  }
  .fields,
  .buttons {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    margin-top: 0.4rem;
  }
  .fields input {
    width: 6rem;
    margin-left: 0.25rem;
  }
  .primary {
    font-weight: bold;
  }
  .hint {
    font-size: 0.85rem;
    opacity: 0.7;
  }
  .error {
    color: var(--danger, #b00020);
  }
</style>
