<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import {
    cancelExport,
    getExportPreflight,
    getExportStatus,
    getTimeline,
    openExportFolder,
    pickFolder,
    startExport,
    type ExportStatus,
    type PreflightReport,
  } from "./api";
  import { clock } from "./format";

  /**
   * Export screen (M6-7, spec 4.3): the pre-flight checklist, the bundle choices, progress with
   * cancel, and the result. The export itself runs on the backend; this page polls its status.
   */
  let { onclose }: { onclose: () => void } = $props();

  // Measured on the user's footage (M6 S6, S7): MB per minute of video.
  const MB_PER_MIN = { videos: 138 + 131, voice: 12, overlay: 421 };
  const POLL_MS = 500;

  let preflight = $state<PreflightReport | null>(null);
  let status = $state<ExportStatus | null>(null);
  let durationMs = $state(0);
  let error = $state<string | null>(null);
  let busy = $state(false);

  let folder = $state<string | null>(null); // null: the project's exports folder
  let includeOverlay = $state(false);
  let includeRawLinks = $state(true);
  let unloadVoice = $state(false);
  let testExport = $state(false);
  let testSeconds = $state(60);
  let acceptWarnings = $state(false);

  let timer: ReturnType<typeof setInterval> | null = null;

  const running = $derived(status?.state === "running");
  const errors = $derived(preflight?.issues.filter((i) => i.severity === "error") ?? []);
  const warnings = $derived(preflight?.issues.filter((i) => i.severity === "warning") ?? []);
  const exportMinutes = $derived(
    (testExport ? Math.min(testSeconds * 1000, durationMs) : durationMs) / 60_000,
  );
  const estimateGb = $derived(
    (exportMinutes * (MB_PER_MIN.videos + MB_PER_MIN.voice + (includeOverlay ? MB_PER_MIN.overlay : 0))) /
      1000,
  );
  const canStart = $derived(
    preflight !== null &&
      preflight.ok &&
      !running &&
      !busy &&
      (warnings.length === 0 || acceptWarnings) &&
      (!testExport || testSeconds > 0),
  );

  onMount(() => {
    void (async () => {
      await run(async () => {
        const [s, p, t] = await Promise.all([getExportStatus(), getExportPreflight(), getTimeline()]);
        status = s;
        preflight = p;
        durationMs = t.duration_ms;
        if (s.defaults !== null) {
          includeOverlay = s.defaults.include_overlay;
          includeRawLinks = s.defaults.include_raw_links;
          unloadVoice = s.defaults.unload_voice;
        }
        if (s.state === "running") startPolling();
      });
    })();
  });

  onDestroy(stopPolling);

  async function run(action: () => Promise<void>): Promise<void> {
    busy = true;
    error = null;
    try {
      await action();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }

  function startPolling(): void {
    stopPolling();
    timer = setInterval(() => {
      void (async () => {
        try {
          status = await getExportStatus();
          if (status.state !== "running") stopPolling();
        } catch (err) {
          error = err instanceof Error ? err.message : String(err);
          stopPolling();
        }
      })();
    }, POLL_MS);
  }

  function stopPolling(): void {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  async function recheck(): Promise<void> {
    await run(async () => {
      preflight = await getExportPreflight();
    });
  }

  async function chooseFolder(): Promise<void> {
    const picked = await pickFolder();
    if (picked !== null) folder = picked;
  }

  async function begin(): Promise<void> {
    await run(async () => {
      status = await startExport({
        folder,
        include_overlay: includeOverlay,
        include_raw_links: includeRawLinks,
        unload_voice: unloadVoice,
        limit_seconds: testExport ? testSeconds : null,
        accept_warnings: acceptWarnings,
      });
      startPolling();
    });
  }

  async function cancel(): Promise<void> {
    await run(async () => {
      status = await cancelExport();
    });
  }

  async function reveal(): Promise<void> {
    await run(async () => {
      await openExportFolder();
    });
  }

  /** Whole minutes and seconds ("1:05"), for elapsed time, time left and lengths. */
  function seconds(s: number): string {
    const total = Math.max(0, Math.round(s));
    const m = Math.floor(total / 60);
    return `${m}:${String(total % 60).padStart(2, "0")}`;
  }

  function size(bytes: number | null, files: number | null): string {
    if (files !== null) return files === 1 ? "1 file" : `${files} files`;
    if (bytes === null) return "";
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
  }

  const STAGES: Record<string, string> = {
    prepare: "Preparing",
    unload: "Unloading the voice model",
    voice: "Writing the voice tracks",
    render: "Rendering the video",
    finish: "Finishing the bundle",
    done: "Done",
  };
</script>

<div class="screen">
<main>
  <header>
    <button type="button" onclick={onclose} disabled={busy}>Back to editor</button>
    <h1>Export</h1>
  </header>

  {#if error !== null}<p class="error">{error}</p>{/if}

  <section>
    <h2>Pre-flight</h2>
    {#if preflight === null}
      <p>Checking...</p>
    {:else}
      {#if preflight.issues.length === 0}
        <p class="ok">Everything is ready to export.</p>
      {/if}
      <ul class="issues">
        {#each errors as issue, i (i)}
          <li class="error-item">
            <strong>Error</strong>
            {#if issue.t_ms !== null}<span class="time">{clock(issue.t_ms)}</span>{/if}
            {issue.message}
          </li>
        {/each}
        {#each warnings as issue, i (i)}
          <li class="warn-item">
            <strong>Warning</strong>
            {#if issue.t_ms !== null}<span class="time">{clock(issue.t_ms)}</span>{/if}
            {issue.message}
          </li>
        {/each}
      </ul>
      {#if errors.length > 0}
        <p class="hint">Fix the errors in the editor or on the project screen, then check again.</p>
      {/if}
      <button type="button" onclick={() => void recheck()} disabled={busy || running}>Check again</button>
    {/if}
  </section>

  <section>
    <h2>Bundle</h2>
    {#if status?.defaults}
      <p class="hint">
        {status.defaults.height}p, {status.defaults.fps === "match"
          ? "at the footage's frame rate"
          : `${status.defaults.fps} fps`}. Timeline length {seconds(durationMs / 1000)}.
      </p>
    {/if}
    <div class="row">
      <span>Folder:</span>
      <code>{folder ?? status?.defaults?.folder ?? "the project's exports folder"}</code>
    </div>
    <div class="row">
      <button type="button" onclick={() => void chooseFolder()} disabled={busy || running}>Choose...</button>
      {#if folder !== null}
        <button type="button" onclick={() => (folder = null)} disabled={busy || running}>Use the default</button>
      {/if}
    </div>
    <p class="hint">Each export gets its own dated folder inside it.</p>

    <label class="check">
      <input type="checkbox" bind:checked={includeOverlay} disabled={running} />
      <span>
        Transparent avatar overlay (PNG sequence, 30 fps)
        <span class="hint">
          About {MB_PER_MIN.overlay} MB per minute of video. In DaVinci Resolve, add the folder to the Media
          Pool: it shows up as one clip.
        </span>
      </span>
    </label>
    <label class="check">
      <input type="checkbox" bind:checked={includeRawLinks} disabled={running} />
      <span>
        Link the raw recording
        <span class="hint">A hard link: no extra disk space. On another drive, a text file with its path.</span>
      </span>
    </label>
    <label class="check">
      <input type="checkbox" bind:checked={unloadVoice} disabled={running} />
      <span>
        Unload the voice model first
        <span class="hint">Frees about 3 GB of video memory; the next generation loads it again.</span>
      </span>
    </label>
    <label class="check">
      <input type="checkbox" bind:checked={testExport} disabled={running} />
      <span>
        Test export: only the first
        <input class="num" type="number" min="1" step="1" bind:value={testSeconds} disabled={running || !testExport} />
        seconds
      </span>
    </label>
    <p class="hint">Estimated size: about {estimateGb < 0.1 ? "0.1" : estimateGb.toFixed(1)} GB.</p>
  </section>

  <section>
    <h2>Export</h2>
    {#if warnings.length > 0 && !running}
      <label class="check">
        <input type="checkbox" bind:checked={acceptWarnings} />
        <span>Export anyway, with the {warnings.length} warning{warnings.length === 1 ? "" : "s"} above</span>
      </label>
    {/if}
    <div class="row">
      <button type="button" class="primary" onclick={() => void begin()} disabled={!canStart}>Export</button>
      {#if running}
        <button type="button" onclick={() => void cancel()} disabled={busy}>Cancel</button>
      {/if}
    </div>

    {#if status !== null && status.state !== "idle"}
      <div class="progress">
        <div class="bar"><div class="fill" style:width="{Math.round(status.fraction * 100)}%"></div></div>
        <p>
          {#if status.state === "running"}
            {STAGES[status.stage] ?? status.stage}: {Math.round(status.fraction * 100)}%,
            {seconds(status.elapsed_s)} so far{#if status.eta_s !== null}, about {seconds(status.eta_s)} left{/if}.
          {:else if status.state === "done"}
            Done in {seconds(status.elapsed_s)}{#if status.video_ms !== null}&nbsp;for {seconds(
                status.video_ms / 1000,
              )} of video{/if}.
          {:else if status.state === "cancelled"}
            Cancelled. What was written so far is kept in the folder below.
          {:else}
            Failed: {status.message}
          {/if}
        </p>
        {#if status.state === "running"}
          <p class="hint">
            If it is slow, close programs that record or stream (Discord, NVIDIA Instant Replay, OBS): they use
            the same video encoder.
          </p>
        {/if}
      </div>
      {#if status.folder !== null && status.state !== "running"}
        <div class="row">
          <code>{status.folder}</code>
          <button type="button" onclick={() => void reveal()} disabled={busy}>Open folder</button>
        </div>
        {#if status.files.length > 0}
          <ul class="files">
            {#each status.files as file (file.name)}
              <li><span>{file.name}</span><span>{size(file.bytes, file.files)}</span></li>
            {/each}
          </ul>
        {/if}
      {/if}
    {/if}
  </section>
</main>
</div>

<style>
  /* The editor's dark theme (Editor.svelte), so the screen matches where it opens from. */
  .screen {
    --bg: #15161a;
    --panel: #1d1f25;
    --line: #353944;
    --text: #e7e8ec;
    --muted: #9ca0ab;
    --accent: #4a90e2;
    position: fixed;
    inset: 0;
    overflow: auto;
    background: var(--bg);
    color: var(--text);
    color-scheme: dark;
  }
  main {
    font-family: system-ui, sans-serif;
    padding: 1.5rem 2rem;
    max-width: 52rem;
  }
  button,
  input {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--line);
    border-radius: 4px;
    padding: 0.3rem 0.7rem;
    font: inherit;
  }
  button:disabled {
    opacity: 0.5;
  }
  input[type="checkbox"] {
    padding: 0;
    margin-top: 0.2rem;
  }
  header {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  h1 {
    margin: 0;
  }
  section {
    margin: 1.25rem 0;
  }
  h2 {
    margin: 0 0 0.5rem;
    font-size: 1.15rem;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin: 0.4rem 0;
  }
  code {
    word-break: break-all;
  }
  .check {
    display: flex;
    gap: 0.5rem;
    align-items: start;
    margin: 0.5rem 0;
  }
  .check .hint {
    display: block;
  }
  .num {
    width: 4.5rem;
  }
  .hint {
    font-size: 0.85rem;
    color: var(--muted);
    margin: 0.2rem 0;
  }
  .issues {
    list-style: none;
    padding: 0;
  }
  .issues li {
    padding: 0.3rem 0.5rem;
    margin: 0.2rem 0;
    border-left: 4px solid;
  }
  .error-item {
    border-color: #ff7a7a;
    background: #ff7a7a1a;
  }
  .warn-item {
    border-color: #d9a441;
    background: #d9a4411a;
  }
  .time {
    font-variant-numeric: tabular-nums;
    margin: 0 0.3rem;
    opacity: 0.8;
  }
  .ok {
    color: #6fcf97;
  }
  .error {
    color: #ff7a7a;
  }
  .primary {
    font-weight: 600;
    padding: 0.4rem 1.2rem;
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  .progress {
    margin-top: 0.75rem;
  }
  .bar {
    height: 0.8rem;
    background: var(--line);
    border-radius: 0.4rem;
    overflow: hidden;
  }
  .fill {
    height: 100%;
    background: #4a90e2;
    transition: width 0.4s linear;
  }
  .files {
    list-style: none;
    padding: 0;
    max-width: 30rem;
  }
  .files li {
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid var(--line);
    padding: 0.15rem 0;
  }
</style>
