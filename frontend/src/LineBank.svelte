<script lang="ts">
  import { tick, untrack } from "svelte";
  import {
    CFG_WEIGHT_MAX,
    CFG_WEIGHT_MIN,
    EXAGGERATION_MAX,
    EXAGGERATION_MIN,
    cancelJob,
    editLines,
    generateLine,
    getLines,
    getTakes,
    rerollLine,
    takeMediaUrl,
    type JobItem,
    type JobStatus,
    type LineBankState,
    type LineEditOp,
    type LineItem,
    type TakeItem,
  } from "./api";
  import ParamSlider from "./ParamSlider.svelte";
  import TakeTrimmer from "./TakeTrimmer.svelte";
  import { Dices, Pause, Play, Plus, Scissors, Sparkles, Star, Trash2, X } from "@lucide/svelte";
  import Badge from "./ui/Badge.svelte";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";
  import IconButton from "./ui/IconButton.svelte";
  import { LINE_DRAG_TYPE } from "./timeline";
  import {
    isBlank,
    jobText,
    latestJobFor,
    liveJobFor,
    newLineId,
    normalizeText,
    show2,
    takeCountText,
  } from "./voice";

  let {
    reloadToken = 0,
    onedited,
    jobs,
    onjobchange,
    fxVersion = "",
  }: {
    /** Change this number to make the bank reload (after an undo or redo elsewhere). */
    reloadToken?: number;
    /** Called after every edit that was saved, so the editor can refresh its undo buttons. */
    onedited: () => void;
    /** The latest job list from the editor (it polls while a job is active). */
    jobs: JobStatus | null;
    /** Ask the editor to refresh the job list now (after starting or cancelling a job). */
    onjobchange: () => void;
    /** `TimelineState.fx_version`, so the trimmer can play the processed result. */
    fxVersion?: string;
  } = $props();

  let bank = $state<LineBankState | null>(null);
  let selectedId = $state<string | null>(null);
  let error = $state<string | null>(null);
  let saving = $state(false);
  let textEl = $state<HTMLTextAreaElement | null>(null);

  /** Edits run one after another, so a blur and a click right after it cannot overlap. */
  let chain: Promise<unknown> = Promise.resolve();

  const selected = $derived(bank?.lines.find((l) => l.id === selectedId) ?? null);
  // Plain values, so the takes list only reloads when one of these really changes.
  const selLineId = $derived(selected?.id ?? null);
  const selTakeCount = $derived(selected?.take_count ?? 0);
  const selActiveTake = $derived(selected?.active_take_id ?? null);

  const liveJob = $derived(
    selected === null || jobs === null ? undefined : liveJobFor(jobs.jobs, selected.id),
  );
  const lastJob = $derived(
    selected === null || jobs === null ? undefined : latestJobFor(jobs.jobs, selected.id),
  );

  let takes = $state<TakeItem[]>([]);
  /** The take whose trimmer is open (M5-0), if any. */
  let trimmingId = $state<string | null>(null);
  let playingId = $state<string | null>(null);
  let audio: HTMLAudioElement | null = null;

  /** Newest first; the backend sends them oldest first. */
  const takesNewestFirst = $derived([...takes].reverse());

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function reload(): Promise<void> {
    try {
      bank = await getLines();
      error = null;
    } catch (err) {
      error = message(err);
    }
  }

  $effect(() => {
    void reloadToken;
    untrack(() => {
      void reload();
    });
  });

  async function reloadTakes(lineId: string): Promise<void> {
    try {
      const list = await getTakes(lineId);
      if (selLineId === lineId) {
        takes = list;
      }
    } catch (err) {
      error = message(err);
    }
  }

  $effect(() => {
    const id = selLineId;
    void selTakeCount;
    void selActiveTake;
    void reloadToken;
    untrack(() => {
      stopAudio();
      if (trimmingId !== null && !takes.some((t) => t.id === trimmingId && t.line_id === id)) {
        trimmingId = null;
      }
      if (id === null) {
        takes = [];
      } else {
        void reloadTakes(id);
      }
    });
  });

  $effect(() => () => stopAudio());

  function stopAudio(): void {
    if (audio !== null) {
      audio.pause();
      audio = null;
    }
    playingId = null;
  }

  function togglePlay(take: TakeItem): void {
    if (playingId === take.id) {
      stopAudio();
      return;
    }
    stopAudio();
    const player = new Audio(takeMediaUrl(take.id));
    audio = player;
    playingId = take.id;
    const fail = (): void => {
      if (audio === player) {
        stopAudio();
        error = "Could not play this take.";
      }
    };
    player.onended = () => {
      if (audio === player) {
        stopAudio();
      }
    };
    player.onerror = fail;
    void player.play().catch(fail);
  }

  async function startGenerate(line: LineItem, reroll: boolean): Promise<void> {
    error = null;
    try {
      if (reroll) {
        await rerollLine(line.id);
      } else {
        await generateLine(line.id);
      }
    } catch (err) {
      error = message(err);
    }
    onjobchange();
  }

  async function cancel(job: JobItem): Promise<void> {
    try {
      await cancelJob(job.id);
    } catch (err) {
      error = message(err);
    }
    onjobchange();
  }

  /** Start dragging a line onto the voice lane: selects it and carries its id. */
  function startDrag(e: DragEvent, line: LineItem): void {
    selectedId = line.id;
    if (e.dataTransfer !== null) {
      e.dataTransfer.setData(LINE_DRAG_TYPE, line.id);
      e.dataTransfer.effectAllowed = "copy";
    }
  }

  /** Hotkey M: the id of the selected line, or null when none is selected. */
  export function selectedLineId(): string | null {
    return selected === null ? null : selected.id;
  }

  /** Hotkeys G (generate) and Shift+G (reroll) for the selected line. */
  export async function generateSelected(reroll: boolean): Promise<void> {
    const line = selected;
    if (line === null) {
      error = "Select a line first.";
      return;
    }
    if (isBlank(line)) {
      error = "Write some text for this line first.";
      return;
    }
    if (!line.emotion_known) {
      error = "Pick an emotion that is in the presets first.";
      return;
    }
    if (liveJob === undefined) {
      await startGenerate(line, reroll);
    }
  }

  async function useTake(line: LineItem, take: TakeItem): Promise<void> {
    await apply([{ op: "set_active_take", line_id: line.id, take_id: take.id }]);
  }

  /** Save a take's manual trim (one undo step), then refresh its row. */
  async function applyTrim(
    take: TakeItem,
    startMs: number | null,
    endMs: number | null,
  ): Promise<boolean> {
    const ok = await apply([
      { op: "set_take_trim", take_id: take.id, start_ms: startMs, end_ms: endMs },
    ]);
    if (ok) {
      await reloadTakes(take.line_id);
    }
    return ok;
  }

  function trimText(take: TakeItem): string | null {
    if (take.trim_start_ms === null && take.trim_end_ms === null) {
      return null;
    }
    const start = ((take.trim_start_ms ?? 0) / 1000).toFixed(2);
    const end = ((take.trim_end_ms ?? take.duration_ms) / 1000).toFixed(2);
    return `trimmed ${start} to ${end} s`;
  }

  async function toggleStar(take: TakeItem): Promise<void> {
    const ok = await apply([{ op: "star_take", take_id: take.id, starred: !take.starred }]);
    if (ok) {
      await reloadTakes(take.line_id);
    }
  }

  /** Send edit ops; true when they were saved. A failure shows the backend's message. */
  function apply(ops: LineEditOp[]): Promise<boolean> {
    const run = async (): Promise<boolean> => {
      saving = true;
      error = null;
      try {
        bank = await editLines(ops);
        onedited();
        return true;
      } catch (err) {
        error = message(err);
        return false;
      } finally {
        saving = false;
      }
    };
    const result = chain.then(run, run);
    chain = result;
    return result;
  }

  /** Add an empty line at the end, select it and put the cursor in its text box. */
  export async function addLine(): Promise<void> {
    const id = newLineId();
    const emotions = bank?.emotions ?? [];
    const emotion = emotions.includes("neutral") ? "neutral" : (emotions[0] ?? "neutral");
    const ok = await apply([{ op: "add_line", text: "", emotion, line_id: id }]);
    if (ok) {
      selectedId = id;
      await tick();
      textEl?.focus();
    }
  }

  async function removeSelected(): Promise<void> {
    const line = selected;
    if (line === null || bank === null) {
      return;
    }
    const index = bank.lines.findIndex((l) => l.id === line.id);
    const ok = await apply([{ op: "remove_line", line_id: line.id }]);
    if (ok) {
      const lines = bank?.lines ?? [];
      selectedId = lines.length === 0 ? null : lines[Math.min(index, lines.length - 1)].id;
    }
  }

  async function commitText(line: LineItem, value: string): Promise<void> {
    if (value !== line.text) {
      await apply([{ op: "set_line_text", line_id: line.id, text: value }]);
    }
  }

  function preview(line: LineItem): string {
    return line.text.trim() === "" ? "(empty line)" : line.text;
  }
</script>

<div class="toolbar">
  <Button size="sm" icon={Plus} onclick={() => void addLine()}>
    Add line <span class="kbd">N</span>
  </Button>
  <span class="spacer"></span>
  {#if saving}<span class="hint">Saving...</span>{/if}
  {#if bank !== null && bank.lines.length > 0}
    <span class="hint num">
      {bank.lines.length} line{bank.lines.length === 1 ? "" : "s"} ·
      {bank.lines.filter((l) => l.placement_count > 0).length} placed
    </span>
  {/if}
</div>

{#if error !== null}
  <Banner kind="error">{error}</Banner>
{/if}
{#if bank !== null && bank.save_error !== null}
  <Banner kind="error">Could not save the project: {bank.save_error}</Banner>
{/if}

{#if bank === null}
  <p class="hint">Loading...</p>
{:else}
  <div class="bank">
    <div>
      {#if bank.lines.length === 0}
        <p class="empty">
          No lines yet. Add one, write what you want to say, then generate it in the voice.
        </p>
      {:else}
        <ul class="list">
          {#each bank.lines as line, i (line.id)}
            <li>
              <button
                type="button"
                class="row"
                class:selected={line.id === selectedId}
                draggable="true"
                title="Drag onto the voice lane to place it"
                ondragstart={(e) => startDrag(e, line)}
                onclick={() => (selectedId = line.id)}
              >
                <span class="idx num">{i + 1}</span>
                <span class="preview" class:empty-text={line.text.trim() === ""}>{preview(line)}</span>
                <Badge kind={line.emotion_known ? "neutral" : "error"}>{line.emotion}</Badge>
                <span class="meta num">{takeCountText(line.take_count)}</span>
                {#if line.placement_count > 0}<Badge kind="ok">placed</Badge>{/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="inspector">
      {#if selected === null}
        <p class="hint">Select a line to edit it.</p>
      {:else}
        {@const line = selected}
        <label class="field">
          <span class="label">Text</span>
          {#key `${line.id}|${line.text}`}
            <textarea
              bind:this={textEl}
              rows="3"
              value={line.text}
              onblur={(e) => void commitText(line, e.currentTarget.value)}
              onkeydown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  e.currentTarget.blur();
                } else if (e.key === "Escape") {
                  e.currentTarget.value = line.text;
                  e.currentTarget.blur();
                }
              }}
            ></textarea>
          {/key}
          <span class="hint">Enter saves, Escape undoes your typing. Extra spaces are ignored.</span>
        </label>

        <div class="emotion-row">
          <label class="field grow">
            <span class="label">Emotion</span>
            <select
              value={line.emotion}
              onchange={(e) => {
                const emotion = e.currentTarget.value;
                e.currentTarget.blur();
                void apply([{ op: "set_line_emotion", line_id: line.id, emotion }]);
              }}
            >
              {#if !line.emotion_known}
                <option value={line.emotion}>{line.emotion} (not in the presets)</option>
              {/if}
              {#each bank.emotions as emotion}
                <option value={emotion}>{emotion}</option>
              {/each}
            </select>
          </label>
          <div class="gen">
            <Button
              variant="primary"
              icon={Sparkles}
              title="Generate (G). Reuses an existing take when nothing has changed, so it costs no GPU time."
              disabled={isBlank(line) || !line.emotion_known || liveJob !== undefined}
              onclick={() => void startGenerate(line, false)}
            >
              Generate <span class="kbd on-primary">G</span>
            </Button>
            <Button
              icon={Dices}
              title="Reroll (Shift+G): always makes a new variation"
              disabled={isBlank(line) || !line.emotion_known || liveJob !== undefined}
              onclick={() => void startGenerate(line, true)}
            >
              Reroll
            </Button>
            {#if liveJob !== undefined}
              {@const job = liveJob}
              <Button variant="danger" icon={X} onclick={() => void cancel(job)}>Cancel</Button>
            {/if}
          </div>
        </div>
        {#if !line.emotion_known}
          <Banner kind="error">
            This emotion is not in the presets file any more. Pick another one before generating.
          </Banner>
        {/if}
        {#if liveJob !== undefined}
          <p class="job">{jobText(liveJob)}</p>
        {:else if lastJob !== undefined}
          <p class="hint" class:error={lastJob.state === "failed"}>Last job: {jobText(lastJob)}</p>
        {/if}

        <ParamSlider
          label="Exaggeration"
          hint="Higher adds emotion, but above about 1.0 the voice can garble."
          min={EXAGGERATION_MIN}
          max={EXAGGERATION_MAX}
          step={0.05}
          override={line.exaggeration}
          effective={line.effective_exaggeration}
          fallback={0.5}
          onset={async (value) => {
            await apply([{ op: "set_line_exaggeration", line_id: line.id, value }]);
          }}
        />
        <ParamSlider
          label="Pacing (cfg weight)"
          hint="Lower is slower and more deliberate. It is not a speed control."
          min={CFG_WEIGHT_MIN}
          max={CFG_WEIGHT_MAX}
          step={0.05}
          override={line.cfg_weight}
          effective={line.effective_cfg_weight}
          fallback={0.5}
          onset={async (value) => {
            await apply([{ op: "set_line_cfg_weight", line_id: line.id, value }]);
          }}
        />

        <label class="check">
          <input
            type="checkbox"
            checked={line.allow_overlap}
            onchange={(e) => {
              const value = e.currentTarget.checked;
              e.currentTarget.blur();
              void apply([{ op: "set_allow_overlap", line_id: line.id, value }]);
            }}
          />
          Allow this line to overlap the next one (no overflow warning)
        </label>

        <h4>Takes <Badge>{takes.length}</Badge></h4>
        {#if takes.length === 0}
          <p class="hint">No takes yet. Generate this line to make one.</p>
        {:else}
          <ul class="takes">
            {#each takesNewestFirst as take (take.id)}
              <li class:active={take.active}>
                <IconButton
                  icon={playingId === take.id ? Pause : Play}
                  size="sm"
                  label={playingId === take.id ? "Stop" : "Play this take"}
                  disabled={!take.file_exists}
                  onclick={() => togglePlay(take)}
                />
                <span class="take-info">
                  <span class="take-len num">{(take.duration_ms / 1000).toFixed(1)} s</span>
                  <span class="take-meta num">
                    seed {take.seed} · exag {show2(take.exaggeration)} · pacing {show2(take.cfg_weight)}
                  </span>
                  {#if normalizeText(take.text) !== normalizeText(line.text) || trimText(take) !== null || !take.file_exists}
                    <span class="take-tags">
                      {#if normalizeText(take.text) !== normalizeText(line.text)}
                        <Badge kind="warning">older text</Badge>
                      {/if}
                      {#if trimText(take) !== null}<Badge>{trimText(take)}</Badge>{/if}
                      {#if !take.file_exists}<Badge kind="error">file missing</Badge>{/if}
                    </span>
                  {/if}
                </span>
                {#if take.active}
                  <Badge kind="accent">Active</Badge>
                {:else}
                  <Button size="sm" title="Use this take for the line" onclick={() => void useTake(line, take)}>
                    Use
                  </Button>
                {/if}
                <IconButton
                  icon={Scissors}
                  size="sm"
                  label={trimmingId === take.id ? "Close the trimmer" : "Trim this take"}
                  pressed={trimmingId === take.id}
                  disabled={!take.file_exists}
                  onclick={() => {
                    stopAudio();
                    trimmingId = trimmingId === take.id ? null : take.id;
                  }}
                />
                <IconButton
                  icon={Star}
                  size="sm"
                  class={take.starred ? "starred" : ""}
                  iconFill={take.starred ? "currentColor" : "none"}
                  label={take.starred ? "Starred (click to unstar)" : "Star this take"}
                  pressed={take.starred}
                  onclick={() => void toggleStar(take)}
                />
                {#if trimmingId === take.id}
                  <div class="trim-slot">
                    <TakeTrimmer
                      {take}
                      {fxVersion}
                      onapply={(s, e) => applyTrim(take, s, e)}
                      onclose={() => (trimmingId = null)}
                    />
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}

        <div class="actions">
          <Button
            size="sm"
            variant="danger"
            icon={Trash2}
            disabled={line.take_count > 0 || line.placement_count > 0}
            onclick={() => void removeSelected()}
          >
            Remove line
          </Button>
          {#if line.take_count > 0 || line.placement_count > 0}
            <span class="hint">
              A line with takes or placements cannot be removed here. Takes are deleted in the
              Storage tab.
            </span>
          {/if}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 10px;
  }
  .spacer {
    flex: 1;
  }
  .bank {
    display: grid;
    grid-template-columns: minmax(16rem, 2fr) 3fr;
    gap: 14px;
    align-items: start;
  }
  .empty {
    margin: 0;
    color: var(--text-2);
  }
  .list {
    list-style: none;
    padding: 0;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    max-height: 26rem;
    overflow-y: auto;
  }
  .list li + li .row {
    border-top: 1px solid var(--border);
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    margin: 0;
    padding: 7px 10px;
    border: none;
    border-radius: 0;
    background: none;
    color: var(--text-1);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .row:hover {
    background: var(--surface-2);
  }
  .row.selected {
    background: var(--accent-soft);
    box-shadow: inset 2px 0 0 var(--accent);
  }
  .idx {
    min-width: 1.25rem;
    color: var(--text-3);
  }
  .preview {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .preview.empty-text {
    font-style: italic;
    color: var(--text-3);
  }
  .meta {
    color: var(--text-2);
    font-size: var(--fs-sm);
    white-space: nowrap;
  }
  .inspector {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-width: 0;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .label {
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  textarea,
  select {
    display: block;
    width: 100%;
    box-sizing: border-box;
    font: inherit;
  }
  textarea {
    resize: vertical;
  }
  .emotion-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 8px 12px;
  }
  .grow {
    flex: 1 1 140px;
  }
  .gen {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .kbd.on-primary {
    border-color: rgba(255, 255, 255, 0.45);
    background: transparent;
    color: var(--on-accent);
  }
  .job {
    margin: 0;
    color: var(--accent-hover);
  }
  .check {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    color: var(--text-2);
  }
  .check input {
    margin: 2px 0 0;
  }
  h4 {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 4px 0 0;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .takes {
    list-style: none;
    padding: 0;
    margin: 0;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
  }
  .takes li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
  }
  .takes li + li {
    border-top: 1px solid var(--border);
  }
  .takes li.active {
    background: var(--accent-soft);
  }
  .trim-slot {
    flex-basis: 100%;
  }
  .take-info {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 8rem;
  }
  .take-len {
    font-weight: 600;
  }
  .take-meta {
    overflow: hidden;
    color: var(--text-3);
    font-size: var(--fs-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .take-tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 2px;
  }
  .takes :global(.starred) {
    color: var(--warning);
    background: none;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .hint {
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  p.hint {
    margin: 0;
  }
  .error {
    color: var(--danger);
  }
</style>
