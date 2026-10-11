<script lang="ts">
  import {
    getProject,
    newProject,
    openProject,
    pickFolder,
    type ProjectSummary,
  } from "./api";

  let current = $state<ProjectSummary | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);

  let newName = $state("");
  let newParent = $state("");
  let openPath = $state("");

  async function run(action: () => Promise<ProjectSummary>): Promise<void> {
    busy = true;
    error = null;
    try {
      current = await action();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
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
      current = await getProject();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  void restore();
</script>

<main>
  <h1>PNGtuber Studio</h1>

  {#if error !== null}
    <p class="error">{error}</p>
  {/if}

  {#if current !== null}
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
  {/if}

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
    max-width: 48rem;
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
  }
  .error {
    color: #b00020;
  }
</style>
