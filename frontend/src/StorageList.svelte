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
  import { Star, Trash2 } from "@lucide/svelte";
  import Badge from "./ui/Badge.svelte";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";
  import IconButton from "./ui/IconButton.svelte";

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
    return `seed ${take.seed} · ${(take.duration_ms / 1000).toFixed(1)} s · ${formatBytes(take.size_bytes)}`;
  }
</script>

{#if error !== null}
  <Banner kind="error" onclose={() => (error = null)}>{error}</Banner>
{/if}
{#if notice !== null}
  <Banner kind="success" onclose={() => (notice = null)}>{notice}</Banner>
{/if}

{#if report === null}
  <p class="hint">Loading...</p>
{:else}
  <div class="summary">
    <span class="total num">{takeCountText(report.take_count)} · {formatBytes(report.total_bytes)} on disk</span>
    {#if report.missing_file_count > 0}
      <Badge kind="error">{report.missing_file_count} take file(s) missing</Badge>
    {/if}
  </div>
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
            <span class="meta num">{takeCountText(line.take_count)} · {formatBytes(line.size_bytes)}</span>
            {#if pendingKey === `line:${line.line_id}`}
              <div class="confirm">
                <span>
                  Delete this line and {takeCountText(line.take_count)} for good, freeing
                  {formatBytes(line.size_bytes)}?
                </span>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy}
                  onclick={() => void remove(() => deleteLine(line.line_id))}
                >
                  Delete
                </Button>
                <Button size="sm" disabled={busy} onclick={() => (pendingKey = null)}>Keep</Button>
              </div>
            {:else}
              <IconButton
                icon={Trash2}
                size="sm"
                variant="danger"
                label="Delete this line and all its takes"
                disabled={busy}
                onclick={() => (pendingKey = `line:${line.line_id}`)}
              />
            {/if}
          </div>

          {#if line.takes.length > 0}
            <ul class="takes">
              {#each line.takes as take (take.take_id)}
                <li>
                  <span class="take-info num">{takeLabel(take)}</span>
                  {#if take.active}<Badge kind="accent">Active</Badge>{/if}
                  {#if take.starred}
                    <span class="star" title="Starred"
                      ><Star size={14} strokeWidth={1.75} fill="currentColor" aria-label="Starred" /></span
                    >
                  {/if}
                  {#if !take.file_exists}<Badge kind="error">file missing</Badge>{/if}
                  {#if pendingKey === `take:${take.take_id}`}
                    <div class="confirm">
                      <span>
                        Delete this take for good, freeing {formatBytes(take.size_bytes)}?
                        {#if take.active}The line will have no active take.{/if}
                      </span>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={busy}
                        onclick={() => void remove(() => deleteTake(take.take_id))}
                      >
                        Delete
                      </Button>
                      <Button size="sm" disabled={busy} onclick={() => (pendingKey = null)}>Keep</Button>
                    </div>
                  {:else}
                    <IconButton
                      icon={Trash2}
                      size="sm"
                      variant="danger"
                      label="Delete this take"
                      disabled={busy}
                      onclick={() => (pendingKey = `take:${take.take_id}`)}
                    />
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
    <h4>
      Unreferenced files <Badge>{report.unreferenced.length} · {formatBytes(report.unreferenced_bytes)}</Badge>
    </h4>
    <p class="hint">
      These files in media\takes_raw belong to no take, for example after a crash. The app never
      deletes them. You can delete them yourself in File Explorer.
    </p>
    <ul class="plain">
      {#each report.unreferenced as file (file.path)}
        <li><span class="path">{file.path}</span> <span class="meta num">{formatBytes(file.size_bytes)}</span></li>
      {/each}
    </ul>
  {/if}
{/if}

<style>
  .summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin: 4px 0 2px;
  }
  .total {
    font-weight: 600;
  }
  .lines,
  .takes,
  .plain {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .lines {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 10px;
  }
  .lines > li {
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
  }
  .head,
  .takes li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    padding: 6px 8px 6px 10px;
  }
  .head {
    background: var(--surface-2);
    font-weight: 600;
  }
  .takes li {
    border-top: 1px solid var(--border);
  }
  .text {
    flex: 1;
    min-width: 10rem;
  }
  .text.empty {
    font-style: italic;
    color: var(--text-3);
  }
  .take-info {
    flex: 1;
    min-width: 10rem;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .meta {
    color: var(--text-2);
    font-size: var(--fs-sm);
    font-weight: normal;
  }
  .hint {
    margin: 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  .star {
    display: inline-flex;
    color: var(--warning);
  }
  .confirm {
    display: flex;
    flex-basis: 100%;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 8px;
    padding: 6px 8px;
    border-radius: var(--r-sm);
    background: var(--danger-soft);
    font-size: var(--fs-sm);
    font-weight: normal;
  }
  .confirm span {
    flex: 1;
    min-width: 10rem;
  }
  h4 {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 18px 0 4px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .plain li {
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
    font-size: var(--fs-sm);
  }
  .path {
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }
</style>
