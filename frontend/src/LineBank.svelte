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
  }: {
    /** Change this number to make the bank reload (after an undo or redo elsewhere). */
    reloadToken?: number;
    /** Called after every edit that was saved, so the editor can refresh its undo buttons. */
    onedited: () => void;
    /** The latest job list from the editor (it polls while a job is active). */
    jobs: JobStatus | null;
    /** Ask the editor to refresh the job list now (after starting or cancelling a job). */
    onjobchange: () => void;
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
  <button type="button" onclick={() => void addLine()}>Add line</button>
  <span class="hint">Hotkey N.</span>
  {#if saving}<span class="hint">Saving...</span>{/if}
</div>

{#if error !== null}
  <p class="error">{error}</p>
{/if}
{#if bank !== null && bank.save_error !== null}
  <p class="error">Could not save the project: {bank.save_error}</p>
{/if}

{#if bank === null}
  <p>Loading...</p>
{:else}
  <div class="bank">
    <div>
      {#if bank.lines.length === 0}
        <p>No lines yet. Add one, write what you want to say, then generate it in the voice.</p>
      {:else}
        <ul class="list">
          {#each bank.lines as line, i (line.id)}
            <li>
              <button
                type="button"
                class="row"
                class:selected={line.id === selectedId}
                onclick={() => (selectedId = line.id)}
              >
                <span class="num">{i + 1}</span>
                <span class="preview" class:empty={line.text.trim() === ""}>{preview(line)}</span>
                <span class="tag" class:bad={!line.emotion_known}>{line.emotion}</span>
                <span class="meta">{takeCountText(line.take_count)}</span>
                {#if line.placement_count > 0}<span class="meta">placed</span>{/if}
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
          Text
          {#key `${line.id}|${line.text}`}
            <textarea
              bind:this={textEl}
              rows="4"
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

        <label class="field">
          Emotion
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
        {#if !line.emotion_known}
          <p class="error">
            This emotion is not in the presets file any more. Pick another one before generating.
          </p>
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

        <div class="gen">
          <button
            type="button"
            disabled={isBlank(line) || !line.emotion_known || liveJob !== undefined}
            onclick={() => void startGenerate(line, false)}
          >
            Generate
          </button>
          <button
            type="button"
            disabled={isBlank(line) || !line.emotion_known || liveJob !== undefined}
            onclick={() => void startGenerate(line, true)}
          >
            Reroll
          </button>
          {#if liveJob !== undefined}
            {@const job = liveJob}
            <button type="button" onclick={() => void cancel(job)}>Cancel</button>
          {/if}
        </div>
        {#if liveJob !== undefined}
          <p>{jobText(liveJob)}</p>
        {:else if lastJob !== undefined}
          <p class="hint" class:error={lastJob.state === "failed"}>Last job: {jobText(lastJob)}</p>
        {/if}
        <p class="hint">
          Generate reuses an existing take when nothing has changed, so it costs no GPU time.
          Reroll always makes a new variation.
        </p>

        <h4>Takes ({takes.length})</h4>
        {#if takes.length === 0}
          <p class="hint">No takes yet. Generate this line to make one.</p>
        {:else}
          <ul class="takes">
            {#each takesNewestFirst as take (take.id)}
              <li class:active={take.active}>
                <button type="button" disabled={!take.file_exists} onclick={() => togglePlay(take)}>
                  {playingId === take.id ? "Stop" : "Play"}
                </button>
                <span class="take-info">
                  {(take.duration_ms / 1000).toFixed(1)} s, seed {take.seed}, exaggeration
                  {show2(take.exaggeration)}, pacing {show2(take.cfg_weight)}
                </span>
                {#if normalizeText(take.text) !== normalizeText(line.text)}
                  <span class="meta">older text</span>
                {/if}
                {#if !take.file_exists}<span class="bad">file missing</span>{/if}
                <button type="button" onclick={() => void toggleStar(take)}>
                  {take.starred ? "Starred" : "Star"}
                </button>
                {#if take.active}
                  <strong>Active</strong>
                {:else}
                  <button type="button" onclick={() => void useTake(line, take)}>Use this take</button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}

        <div class="actions">
          <button
            type="button"
            disabled={line.take_count > 0 || line.placement_count > 0}
            onclick={() => void removeSelected()}
          >
            Remove line
          </button>
          {#if line.take_count > 0 || line.placement_count > 0}
            <span class="hint">
              A line with takes or placements cannot be removed here. Takes are deleted in the
              storage list.
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
    gap: 0.75rem;
    margin: 0.5rem 0;
  }
  .bank {
    display: grid;
    grid-template-columns: minmax(16rem, 2fr) 3fr;
    gap: 1.25rem;
    align-items: start;
  }
  .list {
    list-style: none;
    padding: 0;
    margin: 0;
    border: 1px solid #8884;
    max-height: 26rem;
    overflow-y: auto;
  }
  .row {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    width: 100%;
    margin: 0;
    padding: 0.4rem 0.5rem;
    border: none;
    border-bottom: 1px solid #8884;
    background: none;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .row.selected {
    background: #4a90e255;
  }
  .num {
    min-width: 1.5rem;
    opacity: 0.6;
  }
  .preview {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .preview.empty {
    font-style: italic;
    opacity: 0.6;
  }
  .tag,
  .meta {
    font-size: 0.85rem;
    opacity: 0.75;
  }
  .tag.bad {
    color: #b00020;
    opacity: 1;
  }
  .field {
    display: block;
    margin-bottom: 0.75rem;
  }
  textarea,
  select {
    display: block;
    width: 100%;
    box-sizing: border-box;
    margin-top: 0.2rem;
    padding: 0.35rem;
    font: inherit;
  }
  .check {
    display: block;
    margin-bottom: 0.75rem;
  }
  .gen {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.4rem;
  }
  h4 {
    margin: 0.75rem 0 0.35rem;
  }
  .takes {
    list-style: none;
    padding: 0;
    margin: 0 0 0.75rem;
    border: 1px solid #8884;
  }
  .takes li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.5rem;
    border-bottom: 1px solid #8884;
  }
  .takes li.active {
    background: #4a90e233;
  }
  .take-info {
    flex: 1;
    min-width: 12rem;
  }
  .bad {
    color: #b00020;
    font-size: 0.85rem;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .hint {
    font-size: 0.85rem;
    opacity: 0.7;
  }
  .error {
    color: #b00020;
  }
</style>
