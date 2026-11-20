<script lang="ts">
  /**
   * The video lanes in the preview (M8-2): every lane clip showing at the playhead, drawn over
   * the main footage (and under the avatar) where `pipRect` puts it, at its opacity. Recordings
   * play in their own <video>, kept in step with the playhead; their sound goes through the
   * shared audio graph at the clip's level. Clips starting soon are loaded ahead, out of sight.
   */
  import { untrack } from "svelte";
  import { imageMediaUrl, sourceMediaUrl, type TimelineLaneClip, type VideoLane } from "./api";
  import type { AudioGraph } from "./audioGraph";
  import { dbToGain } from "./audioMix";
  import type { LaneDraft } from "./LaneHandles.svelte";
  import { activeLaneClips, laneSourceMs, pipRect, upcomingLaneClips } from "./videoLanes";

  let {
    clips,
    lanes,
    playheadMs,
    playing,
    graph = null,
    draft = null,
  }: {
    clips: TimelineLaneClip[];
    lanes: VideoLane[];
    playheadMs: number;
    playing: boolean;
    graph?: AudioGraph | null;
    /** The selected clip's position and size while it is dragged in the preview. */
    draft?: LaneDraft | null;
  } = $props();

  /** How far ahead a recording is loaded and parked at its first frame. */
  const PRELOAD_MS = 1500;
  /** Re-seek a playing recording when it drifts this far from the playhead (s). */
  const DRIFT_S = 0.15;

  let boxW = $state(0);
  let boxH = $state(0);
  const videos: Record<string, HTMLVideoElement | null> = $state({});
  /** Bumped when a recording has loaded enough to seek, so the sync runs again. */
  let loaded = $state(0);
  const gains = new WeakMap<HTMLMediaElement, GainNode>();

  const active = $derived(activeLaneClips(clips, lanes, playheadMs));
  const activeIds = $derived(new Set(active.map((c) => c.id)));
  const shown = $derived([...active, ...upcomingLaneClips(clips, lanes, playheadMs, PRELOAD_MS)]);
  const depth = $derived(new Map(lanes.map((lane, index) => [lane.id, index + 1])));

  /** Route a recording's sound through the graph once; null when the graph refuses. */
  function gainFor(el: HTMLVideoElement): GainNode | null {
    const known = gains.get(el);
    if (known !== undefined || graph === null) {
      return known ?? null;
    }
    try {
      const ctx = graph.context;
      const source = ctx.createMediaElementSource(el);
      const gain = ctx.createGain();
      source.connect(gain);
      gain.connect(graph.musicInput);
      gains.set(el, gain);
      return gain;
    } catch {
      return null;
    }
  }

  $effect(() => {
    const t = playheadMs;
    const isPlaying = playing;
    const list = shown;
    void loaded;
    untrack(() => {
      for (const clip of list) {
        const el = videos[clip.id];
        if (el === null || el === undefined || clip.source_id === null) continue;
        // A freeze frame holds one frame, silently.
        const frozen = clip.freeze_ms !== null;
        const level = clip.mute || frozen ? 0 : dbToGain(clip.gain_db);
        const gain = gainFor(el);
        if (gain !== null) {
          gain.gain.value = level;
        } else {
          el.volume = Math.min(1, level);
        }
        if (el.readyState < 1) continue;
        const now = clip.timeline_ms <= t && t < clip.end_ms;
        const target = (now || frozen ? laneSourceMs(clip, t) : clip.in_ms) / 1000;
        if (now && isPlaying && !frozen) {
          if (el.paused) {
            el.currentTime = target;
            graph?.resume();
            el.play().catch(() => undefined);
          } else if (Math.abs(el.currentTime - target) > DRIFT_S) {
            el.currentTime = target;
          }
        } else {
          if (!el.paused) el.pause();
          if (Math.abs(el.currentTime - target) > 0.02) el.currentTime = target;
        }
      }
    });
  });
</script>

<div class="lanes" bind:clientWidth={boxW} bind:clientHeight={boxH} aria-hidden="true">
  {#each shown as clip (clip.id)}
    {@const r = pipRect(boxW, boxH, clip.media_width, clip.media_height, draft !== null && draft.id === clip.id ? draft : clip)}
    {#if clip.image_id !== null}
      <img
        src={imageMediaUrl(clip.image_id)}
        alt=""
        style:left="{r.left}px"
        style:top="{r.top}px"
        style:width="{r.width}px"
        style:height="{r.height}px"
        style:opacity={clip.opacity}
        style:z-index={depth.get(clip.lane_id) ?? 0}
        style:visibility={activeIds.has(clip.id) ? "visible" : "hidden"}
      />
    {:else if clip.source_id !== null}
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={videos[clip.id]}
        src={sourceMediaUrl(clip.source_id)}
        preload="auto"
        playsinline
        onloadedmetadata={() => (loaded += 1)}
        style:left="{r.left}px"
        style:top="{r.top}px"
        style:width="{r.width}px"
        style:height="{r.height}px"
        style:opacity={clip.opacity}
        style:z-index={depth.get(clip.lane_id) ?? 0}
        style:visibility={activeIds.has(clip.id) ? "visible" : "hidden"}
      ></video>
    {/if}
  {/each}
</div>

<style>
  .lanes {
    position: absolute;
    inset: 0;
    overflow: hidden;
    border-radius: var(--r-md);
    pointer-events: none;
    /* Keep the per-lane z-indexes inside this layer, so the avatar and the drag
       handles drawn after it stay on top. */
    isolation: isolate;
  }
  img,
  video {
    position: absolute;
    display: block;
    max-width: none;
    object-fit: fill;
  }
</style>
