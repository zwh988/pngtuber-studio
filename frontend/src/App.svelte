<script lang="ts">
  import {
    getFootage,
    getProject,
    getRecent,
    newProject,
    openProject,
    pickFolder,
    removeRecent,
    rescanFootage,
    type FootageReport,
    type ProjectSummary,
    type RecentItem,
  } from "./api";

  let current = $state<ProjectSummary | null>(null);
  let footage = $state<FootageReport | null>(null);
  let recent = $state<RecentItem[]>([]);
  let error = $state<string | null>(null);
  let busy = $state(false);

  let newName = $state("");
  let newParent = $state("");
  let openPath = $state("");

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function refreshProject(): Promise<void> {
    current = await getProject();
    footage = current === null ? null : await getFootage();
  }

  async function run(action: () => Promise<ProjectSummary>): Promise<void> {
    busy = true;
    error = null;
    try {
      current = await action();
      footage = await getFootage();
      recent = await getRecent();
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  async function rescan(): Promise<void> {
    busy = true;
    error = null;
    try {
      footage = await rescanFootage();
      current = await getProject();
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  async function forget(folder: string): Promise<void> {
    error = null;
    try {
      recent = await removeRecent(folder);
    } catch (err) {
      error = message(err);
    }
  }

  async function browse(setter: (path: string) => void): Promise<void> {
    const path = await pickFolder();
    if (path !== null) {
      setter(path);
    }
  }

  async function restore(): Promise<void> {
    try {
      await refreshProject();
      recent = await getRecent();
    } catch (err) {
      error = message(err);
    }
  }

  function when(iso: string): string {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
  }

  function duration(ms: number): string {
    const total = Math.round(ms / 1000);
    const minutes = Math.floor(total / 60);
    const seconds = String(total % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
  }

  void restore();
</script>

<main>
  <h1>PNGtuber Studio</h1>

  {#if error !== null}
    <p class="error">{error}</p>
  {/if}

  {#if current !== null}
    {#if current.save_error !== null}
      <p class="error">Could not save the project: {current.save_error}</p>
    {/if}
    <section>
      <h2>Open project: {current.name}</h2>
      <dl>
        <dt>Folder</dt>
        <dd>{current.folder}</dd>
        <dt>Schema version</dt>
        <dd>{current.schema_version}</dd>
        <dt>Footage sources</dt>
        <dd>{current.source_count}</dd>
        <dt>Clips</dt>
        <dd>{current.clip_count}</dd>
        <dt>Voice profile</dt>
        <dd>{current.voice_status}</dd>
        <dt>Avatar art</dt>
        <dd>{current.avatar_status}</dd>
      </dl>
    </section>

    <section>
      <h2>Footage</h2>
      <p class="hint">
        Put recordings in <code>{current.folder}\footage</code>, then click Rescan.
      </p>
      <button type="button" onclick={rescan} disabled={busy}>Rescan</button>
      {#if footage !== null && footage.added > 0}
        <span class="note">Added {footage.added} new file(s).</span>
      {/if}
      {#if footage !== null && footage.errors.length > 0}
        <ul class="error">
          {#each footage.errors as item}
            <li>{item}</li>
          {/each}
        </ul>
      {/if}
      {#if footage === null || footage.items.length === 0}
        <p>No footage found yet.</p>
      {:else}
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Resolution</th>
              <th>FPS</th>
              <th>Length</th>
              <th>Audio</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {#each footage.items as item (item.id)}
              <tr class:missing={!item.exists}>
                <td class="file">{item.path}</td>
                <td>{item.width}x{item.height}</td>
                <td>{Number(item.fps.toFixed(3))}</td>
                <td>{duration(item.duration_ms)}</td>
                <td>{item.audio_tracks}</td>
                <td>{item.exists ? "ok" : "missing"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  {/if}

  <section>
    <h2>Recent projects</h2>
    {#if recent.length === 0}
      <p>No recent projects yet.</p>
    {:else}
      <ul class="recent">
        {#each recent as item (item.folder)}
          <li class:missing={!item.exists}>
            <div class="info">
              <strong>{item.name}</strong>
              {#if !item.exists}<span class="tag">missing</span>{/if}
              <div class="path">{item.folder}</div>
              <div class="path">Last opened {when(item.last_opened)}</div>
            </div>
            <button
              type="button"
              onclick={() => run(() => openProject(item.folder))}
              disabled={busy || !item.exists}
            >
              Open
            </button>
            <button type="button" onclick={() => forget(item.folder)} disabled={busy}>
              Remove
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <section>
    <h2>New project</h2>
    <label>
      Name
      <input bind:value={newName} placeholder="My Rack" disabled={busy} />
    </label>
    <label>
      Parent folder
      <input bind:value={newParent} placeholder="D:\Projects" disabled={busy} />
    </label>
    <button type="button" onclick={() => browse((p) => (newParent = p))} disabled={busy}>
      Browse...
    </button>
    <button
      type="button"
      onclick={() => run(() => newProject(newName, newParent))}
      disabled={busy}
    >
      Create
    </button>
  </section>

  <section>
    <h2>Open project</h2>
    <label>
      Project folder
      <input bind:value={openPath} placeholder="D:\Projects\My Rack" disabled={busy} />
    </label>
    <button type="button" onclick={() => browse((p) => (openPath = p))} disabled={busy}>
      Browse...
    </button>
    <button type="button" onclick={() => run(() => openProject(openPath))} disabled={busy}>
      Open
    </button>
  </section>
</main>

<style>
  main {
    font-family: system-ui, sans-serif;
    padding: 2rem;
    max-width: 52rem;
  }
  section {
    margin-bottom: 1.5rem;
  }
  label {
    display: block;
    margin-bottom: 0.5rem;
  }
  input {
    display: block;
    width: 100%;
    padding: 0.35rem;
  }
  button {
    margin-right: 0.5rem;
  }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 0.25rem 1rem;
  }
  dt {
    font-weight: 600;
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.75rem;
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
  tr.missing td {
    color: #b00020;
  }
  .hint,
  .note {
    opacity: 0.75;
  }
  .recent {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .recent li {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid #8884;
  }
  .info {
    flex: 1;
    min-width: 0;
  }
  .path {
    font-size: 0.85rem;
    opacity: 0.7;
    overflow-wrap: anywhere;
  }
  .recent li.missing .info {
    opacity: 0.6;
  }
  .tag {
    margin-left: 0.5rem;
    color: #b00020;
    font-size: 0.8rem;
  }
  .error {
    color: #b00020;
  }
</style>
