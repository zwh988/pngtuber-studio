<script lang="ts">
  import { sourceMediaUrl, type TimelineClip } from "./api";
  import { clock } from "./format";

  let { clip }: { clip: TimelineClip } = $props();

  let video = $state<HTMLVideoElement | null>(null);
  let playing = $state(false);
  /** Current position in SOURCE time (ms). */
  let sourceMs = $state(0);
  let error = $state<string | null>(null);
  let frame = 0;

  const url = $derived(sourceMediaUrl(clip.source_id));
  const missing = $derived(clip.source === null || clip.source.file_missing);
  const key = $derived(`${clip.id}:${clip.source_id}:${clip.in_ms}:${clip.out_ms}`);
  /** Position inside the clip on the timeline (ms), speed taken into account. */
  const clipMs = $derived(Math.max(0, (sourceMs - clip.in_ms) / clip.speed));

  /** Pause and show the first frame of the clip. Needs the video metadata. */
  function cue(): void {
    if (video === null || video.readyState < 1) {
      return;
    }
    video.pause();
    video.currentTime = clip.in_ms / 1000;
    sourceMs = clip.in_ms;
  }

  // Re-cue when another clip is selected or the selected clip's in/out changes.
  $effect(() => {
    void key;
    cue();
  });

  function tick(): void {
    if (video === null) {
      return;
    }
    const ms = video.currentTime * 1000;
    if (ms >= clip.out_ms) {
      video.pause();
      video.currentTime = clip.out_ms / 1000;
      sourceMs = clip.out_ms;
      return;
    }
    sourceMs = ms;
    frame = requestAnimationFrame(tick);
  }

  function onplay(): void {
    playing = true;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(tick);
  }

  function onpause(): void {
    playing = false;
    cancelAnimationFrame(frame);
  }

  async function toggle(): Promise<void> {
    if (video === null) {
      return;
    }
    if (!video.paused) {
      video.pause();
      return;
    }
    error = null;
    const ms = video.currentTime * 1000;
    if (ms >= clip.out_ms - 1 || ms < clip.in_ms) {
      video.currentTime = clip.in_ms / 1000;
    }
    try {
      await video.play();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function scrub(ms: number): void {
    if (video === null) {
      return;
    }
    video.currentTime = ms / 1000;
    sourceMs = ms;
  }
</script>

<div class="player">
  {#if missing}
    <p class="error">The footage file for this clip is missing. Relink it on the project screen.</p>
  {:else}
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      bind:this={video}
      src={url}
      preload="auto"
      onloadedmetadata={cue}
      onplay={onplay}
      onpause={onpause}
      onseeked={() => {
        if (video !== null) {
          sourceMs = video.currentTime * 1000;
        }
      }}
      onerror={() => {
        error = video?.error?.message || "The video could not be loaded.";
      }}
    ></video>
    <div class="controls">
      <button type="button" onclick={toggle}>{playing ? "Pause" : "Play"}</button>
      <input
        type="range"
        min={clip.in_ms}
        max={clip.out_ms}
        step="1"
        value={sourceMs}
        oninput={(e) => scrub(e.currentTarget.valueAsNumber)}
      />
      <span class="time">{clock(clipMs)} / {clock(clip.duration_ms)}</span>
    </div>
    {#if error !== null}
      <p class="error">{error}</p>
    {/if}
  {/if}
</div>

<style>
  .player {
    max-width: 48rem;
  }
  video {
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    background: #000;
    object-fit: contain;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.5rem;
  }
  .controls input[type="range"] {
    flex: 1;
  }
  .time {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .error {
    color: #b00020;
  }
</style>
