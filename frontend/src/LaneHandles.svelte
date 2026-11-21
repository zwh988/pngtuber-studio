<script lang="ts">
  /**
   * Drag handles for the selected video-lane clip in the preview (M8-2 addition, 2026-11-20).
   * Drag the picture to move it, drag a corner to resize it around its centre. While dragging,
   * `draft` holds the new values (LaneLayers draws them); on release one `set_lane_clip` is sent,
   * so each drag is one undo step. Shown only while paused, for a clip at the playhead on a lane
   * that is visible and unlocked. It sits above the avatar overlay, so while a lane clip is
   * selected its box wins over the avatar where they overlap. The box starts from the clip's
   * keyed values at the playhead; the editor keys the keyed properties there (keyframes step 7).
   */
  import type { TimelineLaneClip, VideoLane } from "./api";
  import { clipValuesAt, isKeyed } from "./clipKeys";
  import { activeLaneClips, movedCentre, pipRect, resizedScale } from "./videoLanes";

  export type LaneDraft = { id: string; x: number; y: number; scale: number };

  let {
    clips,
    lanes,
    selectedId,
    playheadMs,
    editable,
    draft = $bindable(null),
    oncommit,
  }: {
    clips: TimelineLaneClip[];
    lanes: VideoLane[];
    selectedId: string | null;
    playheadMs: number;
    editable: boolean;
    draft?: LaneDraft | null;
    oncommit: (clipId: string, change: { x: number; y: number; scale: number }) => Promise<void>;
  } = $props();

  let boxW = $state(0);
  let boxH = $state(0);
  let wrap: HTMLDivElement | null = $state(null);

  const clip = $derived.by(() => {
    if (!editable || selectedId === null) return null;
    const shown = activeLaneClips(clips, lanes, playheadMs).find((c) => c.id === selectedId);
    if (shown === undefined) return null;
    return lanes.find((lane) => lane.id === shown.lane_id)?.locked ? null : shown;
  });
  const values = $derived(
    clip === null ? null : draft !== null && draft.id === clip.id ? draft : clipValuesAt(clip, playheadMs),
  );
  const keyed = $derived(clip !== null && (isKeyed(clip, "x") || isKeyed(clip, "y") || isKeyed(clip, "scale")));
  const rect = $derived(
    clip === null || values === null ? null : pipRect(boxW, boxH, clip.media_width, clip.media_height, values),
  );

  type Grab = {
    kind: "move" | "resize";
    from: { x: number; y: number };
    start: { x: number; y: number; scale: number };
    centre: { x: number; y: number };
  };
  let grab: Grab | null = null;

  function point(e: PointerEvent): { x: number; y: number } {
    const box = wrap?.getBoundingClientRect();
    return { x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0) };
  }

  function down(e: PointerEvent, kind: "move" | "resize"): void {
    if (clip === null || values === null || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    grab = {
      kind,
      from: point(e),
      start: { ...values },
      centre: { x: values.x * boxW, y: values.y * boxH },
    };
  }

  function move(e: PointerEvent): void {
    if (grab === null || clip === null) return;
    const now = point(e);
    if (grab.kind === "move") {
      const c = movedCentre(grab.start, now.x - grab.from.x, now.y - grab.from.y, boxW, boxH);
      draft = { id: clip.id, x: c.x, y: c.y, scale: grab.start.scale };
    } else {
      const scale = resizedScale(grab.start.scale, grab.centre, grab.from, now);
      draft = { id: clip.id, x: grab.start.x, y: grab.start.y, scale };
    }
  }

  // A corner captures the pointer; its move and up events bubble to the box's handlers.
  function up(): void {
    const g = grab;
    grab = null;
    const d = draft;
    if (g === null || d === null || clip === null || d.id !== clip.id) {
      draft = null;
      return;
    }
    if (d.x === g.start.x && d.y === g.start.y && d.scale === g.start.scale) {
      draft = null;
      return;
    }
    void oncommit(d.id, { x: d.x, y: d.y, scale: d.scale }).finally(() => {
      if (draft === d) draft = null;
    });
  }
</script>

<div class="handles" bind:this={wrap} bind:clientWidth={boxW} bind:clientHeight={boxH}>
  {#if rect !== null}
    <div
      class="box"
      role="presentation"
      title={keyed
        ? "Drag to move, drag a corner to resize: keyed values get a key at the playhead"
        : "Drag to move, drag a corner to resize"}
      style:left="{rect.left}px"
      style:top="{rect.top}px"
      style:width="{rect.width}px"
      style:height="{rect.height}px"
      onpointerdown={(e) => down(e, "move")}
      onpointermove={move}
      onpointerup={up}
      onpointercancel={up}
    >
      {#each ["nw", "ne", "sw", "se"] as corner (corner)}
        <span
          class="corner {corner}"
          role="presentation"
          onpointerdown={(e) => down(e, "resize")}
        ></span>
      {/each}
    </div>
  {/if}
</div>

<style>
  .handles {
    position: absolute;
    inset: 0;
    overflow: hidden;
    pointer-events: none;
  }
  /* The avatar's editing outline: a white dashed line (with a dark edge so it shows on
     light pictures too) and accent squares to grab. */
  .box {
    position: absolute;
    box-sizing: border-box;
    border: 2px dashed var(--selected);
    outline: 1px solid rgba(0, 0, 0, 0.45);
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.35);
    pointer-events: auto;
    cursor: move;
    touch-action: none;
  }
  .corner {
    position: absolute;
    width: 12px;
    height: 12px;
    box-sizing: border-box;
    background: var(--accent);
    border: 2px solid var(--bg);
    border-radius: 2px;
  }
  .nw {
    left: -6px;
    top: -6px;
    cursor: nwse-resize;
  }
  .se {
    right: -6px;
    bottom: -6px;
    cursor: nwse-resize;
  }
  .ne {
    right: -6px;
    top: -6px;
    cursor: nesw-resize;
  }
  .sw {
    left: -6px;
    bottom: -6px;
    cursor: nesw-resize;
  }
</style>
