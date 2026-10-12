<script lang="ts">
  import {
    addClip,
    getFootage,
    getTimeline,
    redoEdit,
    undoEdit,
    type EditResult,
    type FootageItem,
    type TimelineState,
  } from "./api";
  import { clock } from "./format";
  import Player from "./Player.svelte";

  let { onclose }: { onclose: () => void } = $props();

  let timeline = $state<TimelineState | null>(null);
  let sources = $state<FootageItem[]>([]);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);
  let busy = $state(false);
  let selectedId = $state<string | null>(null);

  /** The selected clip, or the first one when nothing (or a vanished clip) is selected. */
  const selected = $derived(
    timeline?.clips.find((c) => c.id === selectedId) ?? timeline?.clips[0] ?? null,
  );

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
      notice = result.label === null ? nothing : `${verb}: ${result.label}`;
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  void load();
</script>

<div class="editor">
  <header>
    <button type="button" onclick={onclose}>Back to project</button>
    <h2>Editor</h2>
    <div class="spacer"></div>
    <button
      type="button"
      disabled={busy || timeline === null || !timeline.can_undo}
      onclick={() => history(undoEdit, "Undid", "Nothing to undo")}
      title={timeline?.undo_label ?? ""}
    >
      Undo
    </button>
    <button
      type="button"
      disabled={busy || timeline === null || !timeline.can_redo}
      onclick={() => history(redoEdit, "Redid", "Nothing to redo")}
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
    {#if selected !== null}
      <section>
        <Player clip={selected} />
      </section>
    {/if}

    <section>
      <h3>Footage</h3>
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
            {#each timeline.clips as clip (clip.id)}
              <tr
                class:missing={clip.source?.file_missing ?? true}
                class:selected={selected !== null && clip.id === selected.id}
              >
                <td>{clip.position + 1}</td>
                <td class="file">
                  <button type="button" class="pick" onclick={() => (selectedId = clip.id)}>
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
  tr.selected td {
    background: #4a90e233;
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
