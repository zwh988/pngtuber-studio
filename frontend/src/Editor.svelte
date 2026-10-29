<script module lang="ts">
  /** Pane sizes in px; they survive leaving and re-entering the editor during one app session. */
  const layout = { sideW: 520, topH: 360 };
</script>

<script lang="ts">
  import { onDestroy, tick, untrack } from "svelte";
  import {
    addClip,
    cancelJob,
    getFootage,
    getJobs,
    getStorage,
    getTakePeaks,
    getTimeline,
    movePlacement,
    placeLine,
    redoEdit,
    removeClip,
    removePlacement,
    reorderClip,
    setClipSpeed,
    setPlacementStretch,
    splitClip,
    trimClip,
    undoEdit,
    type EditResult,
    type FootageItem,
    type JobStatus,
    type PeaksReport,
    type StorageReport,
    type TimelineState,
  } from "./api";
  import { clock } from "./format";
  import LineBank from "./LineBank.svelte";
  import StorageList from "./StorageList.svelte";
  import Player from "./Player.svelte";
  import Timeline from "./Timeline.svelte";
  import { STRETCH_MAX, STRETCH_MIN, STRETCH_WARN, stretchText, tightenTarget } from "./stretch";
  import { clipIndexAt, stepFrame } from "./timeline";
  import { formatBytes, isLive, jobText, newLineId, workerText } from "./voice";
  import { VoicePlayback } from "./voicePlayback";

  let { onclose }: { onclose: () => void } = $props();

  let timeline = $state<TimelineState | null>(null);
  let sources = $state<FootageItem[]>([]);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);
  let busy = $state(false);
  /** Playhead on the timeline, in ms. The player moves it while playing. */
  let playheadMs = $state(0);
  /** Selected clip id (click a clip on the timeline). */
  let selectedId = $state<string | null>(null);
  /** Selected placed line (click a block on the voice lane). Never set together with `selectedId`. */
  let selectedPlacementId = $state<string | null>(null);
  /** Waveform peaks by take id, loaded once per take (a take's audio never changes). */
  let peaks = $state<Record<string, PeaksReport>>({});
  const peaksRequested = new Set<string>();
  let player = $state<ReturnType<typeof Player> | null>(null);
  /** True while the player plays (bound from `Player`). */
  let playing = $state(false);
  /** Plays the placed takes in time with the video (Web Audio). */
  const voice = new VoicePlayback((text) => {
    error = text;
  });
  /** Playback began but the playhead has not moved yet; the voice starts on the first real advance. */
  let voiceArmed = false;
  let voiceArmedMs = 0;
  /** Which tab of the footage / line bank panel is showing. */
  let tab = $state<"footage" | "lines" | "storage">("footage");
  /** Bumped after an undo or redo so the line bank reloads. */
  let lineReload = $state(0);
  let lineBank = $state<ReturnType<typeof LineBank> | null>(null);
  /** The voice job list; refreshed every 500 ms while a job is queued or running. */
  let jobs = $state<JobStatus | null>(null);
  let pollTimer: number | undefined;
  /** Disk usage of the takes; refreshed when takes are made or deleted. */
  let storage = $state<StorageReport | null>(null);

  const liveJobs = $derived(jobs === null ? [] : jobs.jobs.filter(isLive));
  const lastJob = $derived.by(() => {
    const finished = jobs === null ? [] : jobs.jobs.filter((j) => !isLive(j));
    return finished[finished.length - 1];
  });

  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 8];

  /** The selected clip; null when nothing is selected or the clip is gone (after an edit or undo). */
  const selectedClip = $derived(timeline?.clips.find((c) => c.id === selectedId) ?? null);
  const selectedPlacement = $derived(
    timeline?.placements.find((p) => p.id === selectedPlacementId) ?? null,
  );

  /** Index of the clip under the playhead (highlighted in the table). */
  const activeIndex = $derived(timeline === null ? -1 : clipIndexAt(timeline.clips, playheadMs));

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  function fileName(path: string): string {
    return path.split(/[\\/]/).pop() ?? path;
  }

  function sourceName(sourceId: string): string {
    const item = sources.find((s) => s.id === sourceId);
    return item === undefined ? sourceId : fileName(item.path);
  }

  async function load(): Promise<void> {
    try {
      const [state, footage] = await Promise.all([getTimeline(), getFootage()]);
      timeline = state;
      sources = footage.items;
    } catch (err) {
      error = message(err);
    }
  }

  /** Run an edit that returns the new timeline; the screen always redraws from it. */
  async function edit(action: () => Promise<TimelineState>): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      timeline = await action();
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  async function history(
    action: () => Promise<EditResult>,
    verb: string,
    nothing: string,
  ): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      const result = await action();
      timeline = result.timeline;
      lineReload += 1;
      notice = result.label === null ? nothing : `${verb}: ${result.label}`;
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  function speedChoices(current: number): number[] {
    return SPEEDS.includes(current) ? SPEEDS : [...SPEEDS, current].sort((a, b) => a - b);
  }

  /** A trim drag ended: one edit, one undo step. */
  async function trimByDrag(clipId: string, edge: "in" | "out", sourceMs: number): Promise<void> {
    player?.pause();
    await edit(() => trimClip(clipId, edge, sourceMs));
  }

  /** A reorder drag ended: one edit, one undo step. */
  async function reorderByDrag(clipId: string, newPosition: number): Promise<void> {
    player?.pause();
    await edit(() => reorderClip(clipId, newPosition));
  }

  /**
   * A line edit went onto the shared undo stack. Refresh only the undo and redo fields,
   * so the player and the timeline are not redrawn.
   */
  async function syncHistory(): Promise<void> {
    try {
      const state = await getTimeline();
      if (timeline !== null) {
        timeline.can_undo = state.can_undo;
        timeline.can_redo = state.can_redo;
        timeline.undo_label = state.undo_label;
        timeline.redo_label = state.redo_label;
        timeline.save_error = state.save_error;
        // Line edits and finished jobs change what a placement plays (active take, length,
        // allow overlap), so refresh the placements too.
        timeline.placements = state.placements;
      }
    } catch (err) {
      error = message(err);
    }
  }

  async function refreshStorage(): Promise<void> {
    try {
      storage = await getStorage();
    } catch (err) {
      error = message(err);
    }
  }

  /** Takes were deleted: reload the lines, the undo state and the disk usage. */
  function takesDeleted(): void {
    lineReload += 1;
    void syncHistory();
    void refreshStorage();
  }

  /** Fetch the job list; keeps polling while a job is active and reloads the lines when one ends. */
  async function refreshJobs(): Promise<void> {
    window.clearTimeout(pollTimer);
    const before = jobs === null ? [] : jobs.jobs.filter(isLive).map((j) => j.id);
    try {
      const next = await getJobs();
      jobs = next;
      const ended = before.some((id) => {
        const job = next.jobs.find((j) => j.id === id);
        return job === undefined || !isLive(job);
      });
      if (ended) {
        lineReload += 1;
        void syncHistory();
        void refreshStorage();
      }
      if (next.active) {
        pollTimer = window.setTimeout(() => void refreshJobs(), 500);
      }
    } catch (err) {
      error = message(err);
      if (jobs !== null && jobs.active) {
        pollTimer = window.setTimeout(() => void refreshJobs(), 2000);
      }
    }
  }

  /** A job was started or cancelled: refresh the list, then the lines (a reused take finishes at once). */
  async function jobsChanged(): Promise<void> {
    await refreshJobs();
    lineReload += 1;
    void syncHistory();
    void refreshStorage();
  }

  async function cancelFirstJob(): Promise<void> {
    const job = liveJobs[0];
    if (job === undefined) {
      return;
    }
    try {
      jobs = await cancelJob(job.id);
    } catch (err) {
      error = message(err);
    }
    await jobsChanged();
  }

  onDestroy(() => {
    window.clearTimeout(pollTimer);
    voice.dispose();
  });

  /** Keep the voice engine's placement list current (it loads new takes and re-plans while playing). */
  $effect(() => {
    const list = timeline?.placements ?? [];
    untrack(() => voice.setPlacements(list));
  });

  /**
   * Voice follows the player. When playback begins the voice waits for the playhead to actually
   * move (the video may still be seeking), then starts there; after that every playhead change
   * is checked for drift. Pause, an edit or the end of the timeline sets `playing` to false.
   */
  $effect(() => {
    const isPlaying = playing;
    const ms = playheadMs;
    untrack(() => {
      if (!isPlaying) {
        voiceArmed = false;
        voice.stop();
      } else if (voice.running) {
        voice.sync(ms);
      } else if (!voiceArmed) {
        voiceArmed = true;
        voiceArmedMs = ms;
      } else if (ms !== voiceArmedMs) {
        voice.start(ms);
      }
    });
  });

  /** Hotkey N: show the line bank and add a line. */
  function newLine(): void {
    tab = "lines";
    void tick().then(() => lineBank?.addLine());
  }

  function undo(): void {
    void history(undoEdit, "Undid", "Nothing to undo");
  }

  function redo(): void {
    void history(redoEdit, "Redid", "Nothing to redo");
  }

  function stepBy(direction: 1 | -1): void {
    if (timeline === null) {
      return;
    }
    player?.pause();
    playheadMs = stepFrame(timeline.clips, playheadMs, direction);
  }

  function splitAtPlayhead(): void {
    const at = playheadMs;
    player?.pause();
    void edit(() => splitClip(at));
  }

  /** Fetch the waveform of every placed take that has none yet. A failure leaves a plain block. */
  $effect(() => {
    for (const placement of timeline?.placements ?? []) {
      const takeId = placement.take_id;
      if (takeId === null || peaksRequested.has(takeId)) {
        continue;
      }
      peaksRequested.add(takeId);
      getTakePeaks(takeId)
        .then((report) => {
          peaks[takeId] = report;
        })
        .catch(() => undefined);
    }
  });

  /** Place a line so that it starts at a timeline time, then select the new block. */
  async function placeAt(lineId: string, timelineMs: number): Promise<void> {
    const placementId = newLineId();
    player?.pause();
    await edit(() => placeLine(lineId, Math.round(timelineMs), placementId));
    if (error === null) {
      selectedPlacementId = placementId;
      selectedId = null;
      lineReload += 1;
    }
  }

  /** Hotkey M: put the line selected in the bank at the playhead. */
  function placeSelected(): void {
    const lineId = lineBank?.selectedLineId() ?? null;
    if (lineId === null) {
      error = "Select a line in the line bank first.";
      return;
    }
    void placeAt(lineId, playheadMs);
  }

  /** A voice block was dragged to a new start time (one undo step). */
  async function movePlacementByDrag(placementId: string, timelineMs: number): Promise<void> {
    player?.pause();
    await edit(() => movePlacement(placementId, timelineMs));
  }

  /** Nudge earlier: move a block up by the overflow, or by the slack when that is less. */
  function nudgeEarlier(placementId: string): void {
    const placed = timeline?.placements.find((p) => p.id === placementId);
    if (placed === undefined || placed.start_ms === null) {
      return;
    }
    const amount = Math.min(placed.overflow_ms, placed.slack_ms);
    if (amount <= 0) {
      return;
    }
    player?.pause();
    void edit(() => movePlacement(placementId, (placed.start_ms ?? 0) - amount));
  }

  /** Tighten and the speed slider: set how much faster a placed line plays (one undo step). */
  function setStretch(placementId: string, stretch: number): void {
    const placed = timeline?.placements.find((p) => p.id === placementId);
    if (placed === undefined || Math.abs(placed.stretch - stretch) < 0.0005) {
      return;
    }
    player?.pause();
    void edit(() => setPlacementStretch(placementId, stretch));
  }

  function removePlaced(placementId: string): void {
    player?.pause();
    void edit(() => removePlacement(placementId)).then(() => {
      if (error === null) {
        selectedPlacementId = null;
        lineReload += 1;
      }
    });
  }

  /** Delete: remove the selected placed line, or else the selected clip. */
  function removeSelected(): void {
    const placed = selectedPlacement;
    if (placed !== null) {
      removePlaced(placed.id);
      return;
    }
    const clip = selectedClip;
    if (clip === null) {
      error = "Select a clip first (click it on the timeline).";
      return;
    }
    player?.pause();
    void edit(() => removeClip(clip.id));
  }

  /** `[` and `]`: cut the selected clip's in or out edge at the playhead (in SOURCE time). */
  function setEdge(edge: "in" | "out"): void {
    const clip = selectedClip;
    if (clip === null) {
      error = "Select a clip first (click it on the timeline).";
      return;
    }
    if (playheadMs < clip.start_ms || playheadMs > clip.end_ms) {
      error = "Move the playhead inside the selected clip first.";
      return;
    }
    const sourceMs = Math.round(clip.in_ms + (playheadMs - clip.start_ms) * clip.speed);
    player?.pause();
    void edit(() => trimClip(clip.id, edge, sourceMs)).then(() => {
      // Cutting the in edge at the playhead makes that frame the clip's first frame.
      if (edge === "in" && error === null) {
        playheadMs = clip.start_ms;
      }
    });
  }

  function isTyping(target: EventTarget | null): boolean {
    return (
      target instanceof Element &&
      target.closest("input:not([type=range]), textarea, select, [contenteditable]") !== null
    );
  }

  function onKeyDown(e: KeyboardEvent): void {
    if (timeline === null || isTyping(e.target)) {
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      const key = e.key.toLowerCase();
      if (key === "z" && !e.shiftKey) {
        e.preventDefault();
        if (!busy) {
          undo();
        }
      } else if (key === "y" || (key === "z" && e.shiftKey)) {
        e.preventDefault();
        if (!busy) {
          redo();
        }
      }
      return;
    }
    if (e.altKey) {
      return;
    }
    const canEdit = !busy && !e.repeat;
    switch (e.key) {
      case " ":
        e.preventDefault();
        if (!e.repeat) {
          player?.toggle();
        }
        break;
      case ",":
        e.preventDefault();
        stepBy(-1);
        break;
      case ".":
        e.preventDefault();
        stepBy(1);
        break;
      case "g":
      case "G":
        e.preventDefault();
        if (canEdit) {
          tab = "lines";
          void lineBank?.generateSelected(e.shiftKey);
        }
        break;
      case "n":
      case "N":
        e.preventDefault();
        if (canEdit) {
          newLine();
        }
        break;
      case "m":
      case "M":
        e.preventDefault();
        if (canEdit) {
          placeSelected();
        }
        break;
      case "s":
      case "S":
        e.preventDefault();
        if (canEdit) {
          splitAtPlayhead();
        }
        break;
      case "Delete":
        e.preventDefault();
        if (canEdit) {
          removeSelected();
        }
        break;
      case "[":
        e.preventDefault();
        if (canEdit) {
          setEdge("in");
        }
        break;
      case "]":
        e.preventDefault();
        if (canEdit) {
          setEdge("out");
        }
        break;
      default:
        break;
    }
  }

  /** Space on a focused button would click it on key release; the hotkey already handled it. */
  function onKeyUp(e: KeyboardEvent): void {
    if (e.key === " " && !isTyping(e.target)) {
      e.preventDefault();
    }
  }

  const SIDE_MIN = 320;
  const TOP_MIN = 180;
  let sideW = $state(layout.sideW);
  let topH = $state(layout.topH);
  let divider: { axis: "v" | "h"; startPos: number; startSize: number } | null = null;

  function clampSide(px: number): number {
    return Math.min(Math.max(px, SIDE_MIN), Math.max(SIDE_MIN, window.innerWidth - 360));
  }

  function clampTop(px: number): number {
    return Math.min(Math.max(px, TOP_MIN), Math.max(TOP_MIN, window.innerHeight - 320));
  }

  function startDivider(e: PointerEvent, axis: "v" | "h"): void {
    e.preventDefault();
    if (e.currentTarget instanceof HTMLElement) {
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    divider = {
      axis,
      startPos: axis === "v" ? e.clientX : e.clientY,
      startSize: axis === "v" ? sideW : topH,
    };
  }

  function moveDivider(e: PointerEvent): void {
    if (divider === null) {
      return;
    }
    if (divider.axis === "v") {
      // The side panel is on the right: dragging left makes it wider.
      sideW = clampSide(divider.startSize - (e.clientX - divider.startPos));
    } else {
      topH = clampTop(divider.startSize + (e.clientY - divider.startPos));
    }
  }

  function endDivider(): void {
    if (divider !== null) {
      layout.sideW = sideW;
      layout.topH = topH;
      divider = null;
    }
  }

  /** Arrow keys resize a focused divider (Shift for bigger steps). */
  function nudgeDivider(e: KeyboardEvent, axis: "v" | "h"): void {
    const step = e.shiftKey ? 80 : 24;
    if (axis === "v" && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      sideW = clampSide(sideW + (e.key === "ArrowLeft" ? step : -step));
    } else if (axis === "h" && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      topH = clampTop(topH + (e.key === "ArrowDown" ? step : -step));
    } else {
      return;
    }
    e.preventDefault();
    layout.sideW = sideW;
    layout.topH = topH;
  }

  void load();
  void refreshJobs();
  void refreshStorage();
</script>

<svelte:window onkeydown={onKeyDown} onkeyup={onKeyUp} />

<div class="editor">
  <header>
    <button type="button" onclick={onclose}>Back to project</button>
    <h2>Editor</h2>
    <div class="spacer"></div>
    <button
      type="button"
      disabled={busy || timeline === null || !timeline.can_undo}
      onclick={undo}
      title={timeline?.undo_label ?? ""}
    >
      Undo
    </button>
    <button
      type="button"
      disabled={busy || timeline === null || !timeline.can_redo}
      onclick={redo}
      title={timeline?.redo_label ?? ""}
    >
      Redo
    </button>
  </header>

  {#if error !== null}
    <p class="error msg">{error}</p>
  {/if}
  {#if notice !== null}
    <p class="note msg">{notice}</p>
  {/if}
  {#if timeline !== null && timeline.save_error !== null}
    <p class="error msg">Could not save the project: {timeline.save_error}</p>
  {/if}

  {#if timeline === null}
    <p class="msg">Loading...</p>
  {:else}
    <div class="workspace">
      <div class="top" style:height="{topH}px" style:--top-h="{topH}px">
        <div class="preview">
          {#if timeline.clips.length > 0}
            <Player
              bind:this={player}
              clips={timeline.clips}
              durationMs={timeline.duration_ms}
              bind:playheadMs
              bind:playing
            />
          {:else}
            <p class="hint">The timeline is empty. Add a recording from the Footage tab.</p>
          {/if}
        </div>
        <div
          class="divider v"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the side panel"
          tabindex="0"
          onpointerdown={(e) => startDivider(e, "v")}
          onpointermove={moveDivider}
          onpointerup={endDivider}
          onpointercancel={endDivider}
          onkeydown={(e) => nudgeDivider(e, "v")}
        ></div>
        <div class="side" style:width="{sideW}px">
          <div class="tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "footage"}
              class:on={tab === "footage"}
              onclick={() => (tab = "footage")}
            >
              Footage
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "lines"}
              class:on={tab === "lines"}
              onclick={() => (tab = "lines")}
            >
              Line bank
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "storage"}
              class:on={tab === "storage"}
              onclick={() => {
                tab = "storage";
                void refreshStorage();
              }}
            >
              Storage
            </button>
          </div>
          <div class="pane">
            <div hidden={tab !== "footage"}>
              {#if sources.length === 0}
                <p class="hint">No footage in this project yet. Go back and rescan.</p>
              {:else}
                <ul class="sources">
                  {#each sources as item (item.id)}
                    <li class:missing={!item.exists}>
                      <span class="name">{fileName(item.path)}</span>
                      <span class="meta">{clock(item.duration_ms)}</span>
                      <button
                        type="button"
                        disabled={busy || !item.exists}
                        onclick={() => edit(() => addClip(item.id))}
                      >
                        Add to timeline
                      </button>
                    </li>
                  {/each}
                </ul>
              {/if}
            </div>
            <div hidden={tab !== "lines"}>
              <LineBank
                bind:this={lineBank}
                reloadToken={lineReload}
                onedited={() => void syncHistory()}
                {jobs}
                onjobchange={() => void jobsChanged()}
              />
            </div>
            <div hidden={tab !== "storage"}>
              <StorageList report={storage} onchanged={takesDeleted} />
            </div>
          </div>
        </div>
      </div>

      <div
        class="divider h"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize the preview and the timeline"
        tabindex="0"
        onpointerdown={(e) => startDivider(e, "h")}
        onpointermove={moveDivider}
        onpointerup={endDivider}
        onpointercancel={endDivider}
        onkeydown={(e) => nudgeDivider(e, "h")}
      ></div>

      <div class="bottom">
        {#if timeline.clips.length > 0}
          <Timeline
            clips={timeline.clips}
            durationMs={timeline.duration_ms}
            bind:playheadMs
            bind:selectedId
            bind:selectedPlacementId
            placements={timeline.placements}
            {peaks}
            locked={busy}
            label={(clip) => sourceName(clip.source_id)}
            ontrim={trimByDrag}
            onreorder={reorderByDrag}
            onplace={placeAt}
            onmoveplacement={movePlacementByDrag}
          />
          <div class="clipbar">
            {#if selectedClip !== null}
              {@const clip = selectedClip}
              <strong>Clip {clip.position + 1}: {sourceName(clip.source_id)}</strong>
              <label>
                Speed
                <select
                  value={String(clip.speed)}
                  disabled={busy}
                  onchange={(e) => {
                    const speed = Number(e.currentTarget.value);
                    e.currentTarget.blur();
                    void edit(() => setClipSpeed(clip.id, speed));
                  }}
                >
                  {#each speedChoices(clip.speed) as speed}
                    <option value={String(speed)}>{speed}x</option>
                  {/each}
                </select>
              </label>
              <button type="button" disabled={busy} onclick={removeSelected}>Remove clip</button>
            {:else if selectedPlacement === null}
              <span class="hint">No clip selected. Click a clip on the timeline.</span>
            {/if}
            {#if selectedPlacement !== null}
              {@const placed = selectedPlacement}
              <strong>Placed line: {placed.line_text === "" ? "(line gone)" : placed.line_text}</strong>
              {#if placed.orphaned}
                <span class="hint">Its footage was cut away; it is parked at a clip edge.</span>
              {/if}
              {#if placed.take_id === null}
                <span class="hint">This line has no take to play.</span>
              {/if}
              {#if placed.overflow_ms > 0 && !placed.allow_overlap}
                <span class="error">
                  Runs {(placed.overflow_ms / 1000).toFixed(2)} s into the next line.
                  Tick "Allow overlap" for this line in the Line bank if that is intended.
                </span>
                {@const tighten = tightenTarget(placed.fit_stretch, placed.stretch)}
                {#if tighten !== null}
                  <button type="button" disabled={busy} onclick={() => setStretch(placed.id, tighten)}>
                    Tighten {stretchText(tighten)}
                    {placed.fit_stretch !== null && placed.fit_stretch > tighten + 0.0005
                      ? `(clearing it needs ${stretchText(placed.fit_stretch)}: use the slider)`
                      : ""}
                  </button>
                {/if}
                {#if placed.fit_stretch !== null && placed.fit_stretch > STRETCH_MAX}
                  <span class="hint">Even {stretchText(STRETCH_MAX)} would not clear it: also nudge or shorten the line.</span>
                {/if}
                {#if placed.slack_ms > 0}
                  <button type="button" disabled={busy} onclick={() => nudgeEarlier(placed.id)}>
                    Nudge earlier {(Math.min(placed.overflow_ms, placed.slack_ms) / 1000).toFixed(2)} s
                    {placed.slack_ms < placed.overflow_ms ? "(not enough room to clear it)" : ""}
                  </button>
                {:else}
                  <span class="hint">No room to nudge earlier: the previous line ends where this one starts.</span>
                {/if}
              {/if}
              {#if placed.take_id !== null}
                <label class="stretch">
                  Speed up
                  <input
                    type="range"
                    min={STRETCH_MIN}
                    max={STRETCH_MAX}
                    step="0.01"
                    value={placed.stretch}
                    disabled={busy}
                    onchange={(event) => setStretch(placed.id, event.currentTarget.valueAsNumber)}
                  />
                  {placed.stretch === 1 ? "as recorded" : stretchText(placed.stretch)}
                </label>
                {#if placed.stretch > STRETCH_WARN}
                  <span class="hint">Above +15% the voice may sound unnatural.</span>
                {/if}
              {/if}
              <button type="button" disabled={busy} onclick={removeSelected}>Remove placed line</button>
            {/if}
          </div>
          <details class="keys">
            <summary>Shortcuts</summary>
            <p>
              Space play/pause, , and . step a frame, S split at playhead, N new voice line, G generate, Shift+G reroll, M place the selected line at the playhead, Delete remove the selected clip or placed line,
              [ and ] cut the selected clip's in/out at the playhead, Ctrl+Z / Ctrl+Y undo / redo.
              Drag a clip's edge to trim it, drag a clip sideways to reorder, drag a voice block to move it, drag a line from the bank onto the timeline to place it; each drag is one undo step.
              Drag the thin bars between the panels to resize them (arrow keys work when a bar is focused).
            </p>
          </details>
        {/if}

        <h3>Timeline: {timeline.clips.length} clip(s), {clock(timeline.duration_ms)}</h3>
        {#if timeline.other_track_clips > 0}
          <p class="hint">{timeline.other_track_clips} clip(s) on other tracks are not shown.</p>
        {/if}
        {#if timeline.orphan_count > 0}
          <p class="error">{timeline.orphan_count} item(s) lost their footage (orphaned).</p>
        {/if}
        {#each timeline.problems as problem}
          <p class="error">{problem.message}</p>
        {/each}
        {#if timeline.clips.length > 0}
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Source</th>
                <th>Timeline</th>
                <th>Length</th>
                <th>Source in..out</th>
                <th>Speed</th>
              </tr>
            </thead>
            <tbody>
              {#each timeline.clips as clip, i (clip.id)}
                <tr
                  class:missing={clip.source?.file_missing ?? true}
                  class:selected={clip.id === selectedId}
                  class:active={i === activeIndex}
                >
                  <td>{clip.position + 1}</td>
                  <td class="file">
                    <button type="button" class="pick" onclick={() => {
                        selectedId = clip.id;
                        selectedPlacementId = null;
                        playheadMs = clip.start_ms;
                      }}>
                      {sourceName(clip.source_id)}
                    </button>
                  </td>
                  <td>{clock(clip.start_ms)} to {clock(clip.end_ms)}</td>
                  <td>{clock(clip.duration_ms)}</td>
                  <td>{clock(clip.in_ms)} to {clock(clip.out_ms)}</td>
                  <td>{clip.speed}x</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    </div>

    <footer class="statusbar">
      <span>Voice model: {workerText(jobs)}</span>
      <span>
        GPU queue:
        {#if liveJobs.length === 0}
          idle
        {:else}
          {jobText(liveJobs[0])}{#if liveJobs.length > 1} (+{liveJobs.length - 1} waiting){/if}
        {/if}
      </span>
      {#if liveJobs.length > 0}
        <button type="button" onclick={() => void cancelFirstJob()}>Cancel</button>
      {:else if lastJob !== undefined}
        <span>Last job: {jobText(lastJob)}</span>
      {/if}
      {#if storage !== null}
        <span>Takes on disk: {formatBytes(storage.total_bytes)} ({storage.take_count})</span>
        {#if storage.missing_file_count > 0}
          <span class="missing">{storage.missing_file_count} take file(s) missing</span>
        {/if}
      {/if}
    </footer>
  {/if}
</div>

<style>
  .editor {
    --bg: #15161a;
    --panel: #1d1f25;
    --panel-2: #262932;
    --line: #353944;
    --text: #e7e8ec;
    --muted: #9ca0ab;
    --accent: #4a90e2;
    --danger: #ff7a7a;
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    color-scheme: dark;
    background: var(--bg);
    color: var(--text);
    font-family: system-ui, sans-serif;
  }
  header {
    flex: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.75rem;
    border-bottom: 1px solid var(--line);
    background: var(--panel);
  }
  header h2 {
    margin: 0 0 0 0.5rem;
    font-size: 1.05rem;
    font-weight: 600;
  }
  .spacer {
    flex: 1;
  }
  .msg {
    flex: none;
    margin: 0;
    padding: 0.35rem 0.75rem;
  }
  .workspace {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .top {
    flex: none;
    min-height: 0;
    max-height: 65%;
    display: flex;
  }
  .preview {
    flex: 1;
    min-width: 0;
    padding: 0.5rem 0.75rem;
    overflow: auto;
  }
  .preview :global(.player) {
    max-width: none;
  }
  .preview :global(video) {
    max-height: calc(var(--top-h) - 5.5rem);
  }
  .side {
    flex: none;
    max-width: 70%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: var(--panel);
    border-left: 1px solid var(--line);
  }
  .pane {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 0.5rem 0.75rem;
  }
  .side :global(.bank) {
    grid-template-columns: minmax(0, 1fr);
  }
  .divider {
    flex: none;
    background: var(--line);
    touch-action: none;
  }
  .divider:hover,
  .divider:focus-visible {
    background: var(--accent);
    outline: none;
  }
  .divider.v {
    width: 6px;
    cursor: col-resize;
  }
  .divider.h {
    height: 6px;
    cursor: row-resize;
  }
  .bottom {
    flex: 1;
    min-height: 0;
    overflow: auto;
    padding: 0.5rem 0.75rem 1rem;
    background: var(--bg);
  }
  .bottom h3 {
    margin: 1rem 0 0;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--muted);
  }
  .sources {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .sources li {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--line);
  }
  .sources .name {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .meta {
    color: var(--muted);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.5rem;
  }
  th,
  td {
    text-align: left;
    padding: 0.3rem 0.5rem;
    border-bottom: 1px solid var(--line);
  }
  th {
    color: var(--muted);
    font-weight: 500;
  }
  td.file {
    overflow-wrap: anywhere;
  }
  tr.active td {
    background: #4a90e222;
  }
  tr.selected td {
    background: #4a90e255;
  }
  .clipbar {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-top: 0.5rem;
    min-height: 2rem;
  }
  .keys {
    margin-top: 0.4rem;
    font-size: 0.85rem;
    color: var(--muted);
  }
  .keys summary {
    cursor: pointer;
  }
  .keys p {
    margin: 0.4rem 0 0;
  }
  .pick {
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    color: inherit;
    font: inherit;
    text-align: left;
    text-decoration: underline;
    cursor: pointer;
  }
  .statusbar {
    flex: none;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 1.25rem;
    padding: 0.35rem 0.75rem;
    border-top: 1px solid var(--line);
    background: var(--panel);
    font-size: 0.85rem;
    color: var(--muted);
  }
  .tabs {
    flex: none;
    display: flex;
    gap: 0.25rem;
    padding: 0.35rem 0.5rem 0;
    border-bottom: 1px solid var(--line);
  }
  .tabs button {
    margin: 0 0 -1px;
    padding: 0.35rem 0.9rem;
    border: 1px solid transparent;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    background: none;
    color: var(--muted);
    font: inherit;
    cursor: pointer;
  }
  .tabs button.on {
    border-color: var(--line);
    background: var(--panel-2);
    color: var(--text);
    font-weight: 600;
  }
  .editor :global(.error),
  .editor :global(.missing),
  .editor :global(.bad) {
    color: var(--danger);
  }
  .hint,
  .note {
    color: var(--muted);
  }
  .stretch {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
</style>
