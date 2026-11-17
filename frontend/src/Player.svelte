<script lang="ts">
  import { onDestroy, untrack, type Snippet } from "svelte";
  import { sourceMediaUrl, type TimelineClip } from "./api";
  import type { AudioGraph } from "./audioGraph";
  import { clock } from "./format";
  import { clipIndexAt, toSource } from "./timeline";
  import { ChevronLeft, ChevronRight, Pause, Play } from "@lucide/svelte";
  import IconButton from "./ui/IconButton.svelte";

  let {
    clips,
    durationMs,
    playheadMs = $bindable(0),
    playing = $bindable(false),
    graph = null,
    overlay,
    onstep,
  }: {
    clips: TimelineClip[];
    durationMs: number;
    playheadMs?: number;
    /** True while the video is playing; the editor reads it to start and stop the voice. */
    playing?: boolean;
    /** The shared audio graph: the video's sound goes through its game bus (mix, limiter, meter). */
    graph?: AudioGraph | null;
    /** Drawn over the video, filling its box (the avatar, M5-6). */
    overlay?: Snippet;
    /** Step one frame (the same as the , and . hotkeys); the buttons are hidden without it. */
    onstep?: (direction: 1 | -1) => void;
  } = $props();

  let video = $state<HTMLVideoElement | null>(null);
  /** The source the <video> element currently has loaded (or is loading). */
  let activeSourceId = $state<string | null>(null);
  let curIdx = $state(0);
  let error = $state<string | null>(null);

  let frame = 0;
  /** What to do once the video can be seeked (after a source swap or before metadata). */
  let pending: { sourceMs: number; thenPlay: boolean; speed: number } | null = null;
  /** The last playhead value this component wrote itself, so it can tell an outside seek from its own. */
  let selfPlayhead = -1;
  let lastSig = "";

  const url = $derived(activeSourceId === null ? undefined : sourceMediaUrl(activeSourceId));

  function setPlayhead(ms: number): void {
    const rounded = Math.round(ms);
    selfPlayhead = rounded;
    playheadMs = rounded;
  }

  function stop(): void {
    cancelAnimationFrame(frame);
    pending = null;
    playing = false;
    video?.pause();
  }

  function fail(err: unknown): void {
    error = err instanceof Error ? err.message : String(err);
    stop();
  }

  /** Seek (and optionally play) once the video has metadata. */
  function apply(): void {
    if (video === null || pending === null || video.readyState < 1) {
      return;
    }
    const job = pending;
    pending = null;
    video.playbackRate = job.speed;
    video.preservesPitch = true;
    video.currentTime = job.sourceMs / 1000;
    if (job.thenPlay) {
      video.play().catch(fail);
    }
  }

  /** Put `clip` on screen at `sourceMs`, swapping the video source when it differs. */
  function show(clip: TimelineClip, sourceMs: number, thenPlay: boolean): void {
    if (clip.source === null || clip.source.file_missing) {
      error = `The footage for clip ${clip.position + 1} is missing. Relink it on the project screen.`;
      stop();
      return;
    }
    pending = { sourceMs, thenPlay, speed: clip.speed };
    if (clip.source_id !== activeSourceId) {
      activeSourceId = clip.source_id;
      return;
    }
    apply();
  }

  function cueTo(timelineMs: number): void {
    const i = clipIndexAt(clips, timelineMs);
    const clip = clips[i];
    if (clip === undefined) {
      return;
    }
    curIdx = i;
    show(clip, toSource(clip, timelineMs), false);
  }

  function hop(clip: TimelineClip, sourceMs: number): void {
    if (video === null) {
      return;
    }
    const next = clips[curIdx + 1];
    if (next === undefined) {
      stop();
      video.currentTime = (clip.out_ms - 1) / 1000;
      setPlayhead(durationMs);
      return;
    }
    curIdx += 1;
    if (next.source_id === clip.source_id && next.in_ms === clip.out_ms) {
      // The next clip continues right where this one ends (for example after a split): no seek.
      video.playbackRate = next.speed;
      setPlayhead(next.start_ms + (sourceMs - next.in_ms) / next.speed);
      return;
    }
    setPlayhead(next.start_ms);
    show(next, next.in_ms, true);
  }

  function tick(): void {
    if (video === null || !playing) {
      return;
    }
    frame = requestAnimationFrame(tick);
    if (pending !== null) {
      return; // waiting for a source swap or a seek to land
    }
    const clip = clips[curIdx];
    if (clip === undefined) {
      stop();
      return;
    }
    const ms = video.currentTime * 1000;
    if (ms >= clip.out_ms) {
      hop(clip, ms);
      return;
    }
    setPlayhead(clip.start_ms + (ms - clip.in_ms) / clip.speed);
  }

  /**
   * Send the video's sound through the shared audio graph (game bus, limiter, meter) and make
   * sure the audio context runs. Done on the first play, from the user's click. If the browser
   * refuses, the video keeps playing straight to the speakers, without the mix.
   */
  function routeAudio(): void {
    if (graph === null || video === null) {
      return;
    }
    try {
      graph.attachVideo(video);
      graph.resume();
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      error = `The footage sound could not be routed through the mixer (${reason}).`;
    }
  }

  function play(): void {
    if (clips.length === 0) {
      return;
    }
    error = null;
    routeAudio();
    const t = playheadMs >= durationMs - 1 ? 0 : Math.max(0, playheadMs);
    const i = clipIndexAt(clips, t);
    const clip = clips[i];
    if (clip === undefined) {
      return;
    }
    curIdx = i;
    playing = true;
    setPlayhead(t);
    show(clip, toSource(clip, t), true);
    if (playing) {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(tick);
    }
  }

  export function toggle(): void {
    if (playing) {
      stop();
    } else {
      play();
    }
  }

  export function pause(): void {
    if (playing) {
      stop();
    }
  }

  function scrub(ms: number): void {
    if (playing) {
      stop();
    }
    playheadMs = ms;
  }

  // Show the frame under the playhead whenever something other than playback moves it,
  // or the clip layout changes (an edit). An edit also stops playback.
  $effect(() => {
    const sig = clips
      .map((c) => `${c.id}:${c.source_id}:${c.in_ms}:${c.out_ms}:${c.speed}`)
      .join("|");
    const ms = playheadMs;
    untrack(() => {
      const changed = sig !== lastSig;
      lastSig = sig;
      if (playing) {
        if (!changed && ms === selfPlayhead) {
          return; // playback itself moved the playhead
        }
        stop(); // an edit or an outside seek pauses playback
      }
      if (clips.length === 0) {
        return;
      }
      if (!changed && ms === selfPlayhead) {
        return;
      }
      const t = Math.min(Math.max(0, ms), durationMs);
      if (t !== ms) {
        setPlayhead(t);
      }
      cueTo(t);
    });
  });

  onDestroy(() => cancelAnimationFrame(frame));
</script>

<div class="player">
  <div class="stage">
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      bind:this={video}
      src={url}
      preload="auto"
      onloadedmetadata={apply}
      onerror={() => {
        error = video?.error?.message || "The video could not be loaded.";
      }}
    ></video>
    {@render overlay?.()}
  </div>
  <div class="controls">
    {#if onstep}
      <IconButton
        icon={ChevronLeft}
        label="Previous frame (,)"
        onclick={() => onstep(-1)}
        disabled={clips.length === 0}
      />
    {/if}
    <IconButton
      icon={playing ? Pause : Play}
      variant="primary"
      label={playing ? "Pause (Space)" : "Play (Space)"}
      onclick={toggle}
      disabled={clips.length === 0}
    />
    {#if onstep}
      <IconButton
        icon={ChevronRight}
        label="Next frame (.)"
        onclick={() => onstep(1)}
        disabled={clips.length === 0}
      />
    {/if}
    <input
      type="range"
      aria-label="Playhead"
      min="0"
      max={durationMs}
      step="1"
      value={playheadMs}
      oninput={(e) => scrub(e.currentTarget.valueAsNumber)}
    />
    <span class="time num"><strong>{clock(playheadMs)}</strong> / {clock(durationMs)}</span>
    <span class="info num" title="The clip under the playhead and its speed">
      Clip {Math.min(curIdx + 1, clips.length)} of {clips.length} · {clips[curIdx]?.speed ?? 1}x
    </span>
  </div>
  {#if error !== null}
    <p class="error">{error}</p>
  {/if}
</div>

<style>
  .player {
    max-width: 48rem;
  }
  .stage {
    position: relative;
  }
  video {
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    border-radius: var(--r-md);
    background: #000;
    object-fit: contain;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
  }
  .controls input[type="range"] {
    flex: 1;
    min-width: 60px;
    margin: 0 8px;
  }
  .time {
    color: var(--text-2);
    font-size: var(--fs-sm);
    white-space: nowrap;
  }
  .time strong {
    color: var(--text-1);
    font-weight: 600;
  }
  .info {
    margin-left: 8px;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--surface-3);
    color: var(--text-2);
    font-size: var(--fs-xs);
    white-space: nowrap;
  }
  .error {
    color: var(--danger);
  }
</style>
