<script lang="ts">
  import {
    deleteLine,
    deleteTake,
    type LineStorage,
    type StorageReport,
    type TakeDeleteReport,
    type TakeStorage,
  } from "./api";
  import { deleteReportText, formatBytes, takeCountText } from "./voice";

  let {
    report,
    onchanged,
  }: {
    /** The storage report from the editor; null while it loads. */
    report: StorageReport | null;
    /** Called after a delete, so the editor reloads lines, takes and disk usage. */
    onchanged: () => void;
  } = $props();

  /** Which delete is waiting for confirmation: "take:<id>" or "line:<id>". */
  let pendingKey = $state<string | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function remove(action: () => Promise<TakeDeleteReport>): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      notice = deleteReportText(await action());
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
      pendingKey = null;
    }
    onchanged();
  }

  function lineLabel(line: LineStorage): string {
    return line.text.trim() === "" ? "(empty line)" : line.text;
  }

  function takeLabel(take: TakeStorage): string {
    return `seed ${take.seed}, ${(take.duration_ms / 1000).toFixed(1)} s, ${formatBytes(take.size_bytes)}`;
  }
</script>

{#if error !== null}
  <p class="error">{error}</p>
{/if}
{#if notice !== null}
  <p class="notice">{notice}</p>
{/if}

{#if report === null}
  <p>Loading...</p>
{:else}
  <p>
    {takeCountText(report.take_count)}, {formatBytes(report.total_bytes)} on disk.
    {#if report.missing_file_count > 0}
      <span class="error">{report.missing_file_count} take file(s) are missing from the disk.</span>
    {/if}
  </p>
  <p class="hint">
    Takes are never deleted automatically. Deleting here is permanent and cannot be undone.
  </p>

  {#if report.lines.length === 0}
    <p class="hint">No lines yet.</p>
  {:else}
    <ul class="lines">
      {#each report.lines as line (line.line_id)}
        <li>
          <div class="head">
            <span class="text" class:empty={line.text.trim() === ""}>{lineLabel(line)}</span>
            <span class="meta">{takeCountText(line.take_count)}, {formatBytes(line.size_bytes)}</span>
            {#if pendingKey === `line:${line.line_id}`}
              <span class="confirm">
                Delete this line and {takeCountText(line.take_count)} for good, freeing
                {formatBytes(line.size_bytes)}?
              </span>
              <button type="button" disabled={busy} onclick={() => void remove(() => deleteLine(line.line_id))}>
                Delete
              </button>
              <button type="button" disabled={busy} onclick={() => (pendingKey = null)}>Keep</button>
            {:else}
              <button type="button" disabled={busy} onclick={() => (pendingKey = `line:${line.line_id}`)}>
                Delete line and takes
              </button>
            {/if}
          </div>

          {#if line.takes.length > 0}
            <ul class="takes">
              {#each line.takes as take (take.take_id)}
                <li>
                  <span class="take-info">{takeLabel(take)}</span>
                  {#if take.active}<strong>Active</strong>{/if}
                  {#if take.starred}<span class="meta">Starred</span>{/if}
                  {#if !take.file_exists}<span class="error">file missing</span>{/if}
                  {#if pendingKey === `take:${take.take_id}`}
                    <span class="confirm">
                      Delete this take for good, freeing {formatBytes(take.size_bytes)}?
                      {#if take.active}The line will have no active take.{/if}
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onclick={() => void remove(() => deleteTake(take.take_id))}
                    >
                      Delete
                    </button>
                    <button type="button" disabled={busy} onclick={() => (pendingKey = null)}>Keep</button>
                  {:else}
                    <button
                      type="button"
                      disabled={busy}
                      onclick={() => (pendingKey = `take:${take.take_id}`)}
                    >
                      Delete take
                    </button>
                  {/if}
                </li>
              {/each}
            </ul>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  {#if report.unreferenced.length > 0}
    <h4>Unreferenced files ({report.unreferenced.length}, {formatBytes(report.unreferenced_bytes)})</h4>
    <p class="hint">
      These files in media\takes_raw belong to no take, for example after a crash. The app never
      deletes them. You can delete them yourself in File Explorer.
    </p>
    <ul class="plain">
      {#each report.unreferenced as file (file.path)}
        <li>{file.path} <span class="meta">{formatBytes(file.size_bytes)}</span></li>
      {/each}
    </ul>
  {/if}
{/if}

<style>
  .lines,
  .takes,
  .plain {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .lines > li {
    border: 1px solid #8884;
    margin-bottom: 0.75rem;
  }
  .head,
  .takes li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    padding: 0.4rem 0.6rem;
  }
  .head {
    background: #8881;
    font-weight: 600;
  }
  .takes li {
    border-top: 1px solid #8884;
  }
  .text {
    flex: 1;
    min-width: 10rem;
  }
  .text.empty {
    font-style: italic;
    opacity: 0.6;
  }
  .take-info {
    flex: 1;
    min-width: 12rem;
  }
  .meta,
  .hint {
    font-size: 0.85rem;
    opacity: 0.75;
    font-weight: normal;
  }
  .confirm {
    font-weight: normal;
  }
  .error {
    color: #b00020;
  }
  .notice {
    color: #1b6e2d;
  }
  h4 {
    margin: 1rem 0 0.35rem;
  }
</style>
