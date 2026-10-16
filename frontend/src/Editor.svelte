<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import {
    addClip,
    cancelJob,
    getFootage,
    getJobs,
    getTimeline,
    redoEdit,
    removeClip,
    reorderClip,
    setClipSpeed,
    splitClip,
    trimClip,
    undoEdit,
    type EditResult,
    type FootageItem,
    type JobStatus,
    type TimelineState,
  } from "./api";
  import { clock } from "./format";
  import LineBank from "./LineBank.svelte";
  import Player from "./Player.svelte";
  import Timeline from "./Timeline.svelte";
  import { clipIndexAt, stepFrame } from "./timeline";
  import { isLive, jobText, workerText } from "./voice";

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
  let player = $state<ReturnType<typeof Player> | null>(null);
  /** Which tab of the footage / line bank panel is showing. */
  let tab = $state<"footage" | "lines">("footage");
  /** Bumped after an undo or redo so the line bank reloads. */
  let lineReload = $state(0);
  let lineBank = $state<ReturnType<typeof LineBank> | null>(null);
  /** The voice job list; refreshed every 500 ms while a job is queued or running. */
  let jobs = $state<JobStatus | null>(null);
  let pollTimer: number | undefined;

  const liveJobs = $derived(jobs === null ? [] : jobs.jobs.filter(isLive));
  const lastJob = $derived.by(() => {
    const finished = jobs === null ? [] : jobs.jobs.filter((j) => !isLive(j));
    return finished[finished.length - 1];
  });

  const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 8];

  /** The selected clip; null when nothing is selected or the clip is gone (after an edit or undo). */
  const selectedClip = $derived(timeline?.clips.find((c) => c.id === selectedId) ?? null);

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
      }
    } catch (err) {
      error = message(err);
    }
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

  onDestroy(() => window.clearTimeout(pollTimer));

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

  function removeSelected(): void {
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
      case "n":
      case "N":
        e.preventDefault();
        if (canEdit) {
          newLine();
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

  void load();
  void refreshJobs();
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
    <p class="error">{error}</p>
  {/if}
  {#if notice !== null}
    <p class="note">{notice}</p>
  {/if}
  {#if timeline !== null && timeline.save_error !== null}
    <p class="error">Could not save the project: {timeline.save_error}</p>
  {/if}

  {#if timeline === null}
    <p>Loading...</p>
  {:else}
    {#if timeline.clips.length > 0}
      <section>
        <Player
          bind:this={player}
          clips={timeline.clips}
          durationMs={timeline.duration_ms}
          bind:playheadMs
        />
      </section>
      <section>
        <Timeline
          clips={timeline.clips}
          durationMs={timeline.duration_ms}
          bind:playheadMs
          bind:selectedId
          locked={busy}
          label={(clip) => sourceName(clip.source_id)}
          ontrim={trimByDrag}
          onreorder={reorderByDrag}
        />
      </section>
      <section class="clipbar">
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
        {:else}
          <span class="hint">No clip selected. Click a clip on the timeline.</span>
        {/if}
        <p class="keys">
          Space play/pause, , and . step a frame, S split at playhead, N new voice line, Delete remove selected clip,
          [ and ] cut the selected clip's in/out at the playhead, Ctrl+Z / Ctrl+Y undo / redo.
          Drag a clip's edge to trim it, drag a clip sideways to reorder; each drag is one undo step.
        </p>
      </section>
    {/if}

    <section>
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
      </div>
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
    </section>

    <section>
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
      {#if timeline.clips.length === 0}
        <p>The timeline is empty. Add a recording above.</p>
      {:else}
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
    </section>

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
    </footer>
  {/if}
</div>

<style>
  .editor {
    font-family: system-ui, sans-serif;
    padding: 1rem 1.5rem;
  }
  header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  header h2 {
    margin: 0 0 0 0.5rem;
  }
  .spacer {
    flex: 1;
  }
  section {
    margin-top: 1.25rem;
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
    border-bottom: 1px solid #8884;
  }
  .sources .name {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .meta {
    opacity: 0.7;
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
    border-bottom: 1px solid #8884;
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
  }
  .keys {
    flex-basis: 100%;
    margin: 0;
    font-size: 0.85rem;
    opacity: 0.7;
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
    position: sticky;
    bottom: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 1.25rem;
    margin-top: 1rem;
    padding: 0.4rem 0;
    border-top: 1px solid #8884;
    background: Canvas;
    font-size: 0.9rem;
  }
  .tabs {
    display: flex;
    gap: 0.25rem;
    border-bottom: 1px solid #8884;
  }
  .tabs button {
    margin: 0 0 -1px;
    padding: 0.35rem 0.9rem;
    border: 1px solid transparent;
    border-bottom: none;
    background: none;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }
  .tabs button.on {
    border-color: #8884;
    background: #4a90e233;
    font-weight: 600;
  }
  tr.missing td,
  li.missing {
    color: #b00020;
  }
  .hint,
  .note {
    opacity: 0.75;
  }
  .error {
    color: #b00020;
  }
</style>
