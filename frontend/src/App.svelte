<script lang="ts">
  import {
    getAvatar,
    getFootage,
    getProject,
    getRecent,
    getVoice,
    newProject,
    openProject,
    pickFile,
    pickFolder,
    relinkSource,
    removeRecent,
    rescanFootage,
    setAvatarFolder,
    setVoiceReference,
    type AvatarState,
    type FootageReport,
    type ProjectSummary,
    type RecentItem,
    type VoiceState,
  } from "./api";
  import Editor from "./Editor.svelte";
  import ExportScreen from "./ExportScreen.svelte";
  import { cleanPathInput, voiceStatusText } from "./voice";

  let current = $state<ProjectSummary | null>(null);
  let footage = $state<FootageReport | null>(null);
  let recent = $state<RecentItem[]>([]);
  let voice = $state<VoiceState | null>(null);
  let avatar = $state<AvatarState | null>(null);
  let artPath = $state("");
  let referencePath = $state("");
  let error = $state<string | null>(null);
  let busy = $state(false);
  let view = $state<"project" | "editor" | "export">("project");

  let newName = $state("");
  let newParent = $state("");
  let openPath = $state("");

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function refreshProject(): Promise<void> {
    current = await getProject();
    footage = current === null ? null : await getFootage();
    voice = current === null ? null : await getVoice();
    avatar = current === null ? null : await getAvatar();
  }

  async function run(action: () => Promise<ProjectSummary>): Promise<void> {
    busy = true;
    error = null;
    try {
      current = await action();
      view = "project";
      footage = await getFootage();
      voice = await getVoice();
      avatar = await getAvatar();
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

  async function relink(sourceId: string): Promise<void> {
    const path = await pickFile();
    if (path === null) {
      return;
    }
    busy = true;
    error = null;
    try {
      footage = await relinkSource(sourceId, path);
      current = await getProject();
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  /** Check the audio file, copy it into the project and make it the voice reference. */
  async function useReference(path: string): Promise<void> {
    const cleaned = cleanPathInput(path);
    if (cleaned === "") {
      error = "Enter or choose the path of an audio file first.";
      return;
    }
    busy = true;
    error = null;
    try {
      voice = await setVoiceReference(cleaned);
      current = await getProject();
      referencePath = "";
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  async function chooseReference(): Promise<void> {
    const path = await pickFile();
    if (path !== null) {
      await useReference(path);
    }
  }

  /** Point the project at an avatar art folder (null clears it). The art is not copied. */
  async function useArtFolder(path: string | null): Promise<void> {
    const cleaned = path === null ? null : cleanPathInput(path);
    if (cleaned === "") {
      error = "Enter or choose the avatar art folder first.";
      return;
    }
    busy = true;
    error = null;
    try {
      avatar = await setAvatarFolder(cleaned);
      current = await getProject();
      artPath = "";
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  async function chooseArtFolder(): Promise<void> {
    const path = await pickFolder();
    if (path !== null) {
      await useArtFolder(path);
    }
  }

  function avatarText(state: AvatarState): string {
    switch (state.status) {
      case "not_configured":
        return "No avatar art chosen yet.";
      case "folder_missing":
        return "The avatar art folder cannot be found.";
      case "no_art":
        return "The folder holds no usable avatar sprites.";
      default:
        return `${state.name}: ${state.expressions.length} expressions, default ${state.default_expression}.`;
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

{#if view === "export" && current !== null}
  <ExportScreen onclose={() => (view = "editor")} />
{:else if view === "editor" && current !== null}
  <Editor
    projectName={current?.name ?? null}
    onclose={() => {
      view = "project";
      void refreshProject();
    }}
    onexport={() => (view = "export")}
  />
{:else}
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
      <button type="button" onclick={() => (view = "editor")} disabled={busy}>
        Open editor
      </button>
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
              <th></th>
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
                <td>
                  {#if !item.exists && !item.external}
                    <button type="button" onclick={() => relink(item.id)} disabled={busy}>
                      Relink...
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section>
      <h2>Voice</h2>
      {#if voice !== null}
        <p class:error={!voice.ready}>{voiceStatusText(voice)}</p>
        {#if voice.reference_path !== null}
          <dl>
            <dt>Reference clip</dt>
            <dd>{voice.reference_path}</dd>
            {#if voice.duration_ms !== null}
              <dt>Length</dt>
              <dd>{(voice.duration_ms / 1000).toFixed(1)} s</dd>
            {/if}
            {#if voice.sample_rate !== null}
              <dt>Sample rate</dt>
              <dd>{voice.sample_rate} Hz</dd>
            {/if}
            {#if voice.hash !== null}
              <dt>Fingerprint</dt>
              <dd>{voice.hash.slice(0, 8)}</dd>
            {/if}
          </dl>
        {/if}
        {#each voice.problems as item}
          <p class="error">{item}</p>
        {/each}
        {#each voice.warnings as item}
          <p class="warn">{item}</p>
        {/each}
      {/if}
      <p class="hint">
        A clean recording of one voice, 5 to 30 seconds long, works best. Use only your own voice
        or a voice you have permission to use. The file is copied into the project. Changing the
        clip keeps every take you made; lines you generate again make new takes with the new clip.
      </p>
      <label>
        Reference clip path
        <input bind:value={referencePath} placeholder="D:\Voices\reference.wav" disabled={busy} />
      </label>
      <button type="button" onclick={chooseReference} disabled={busy}>Choose file...</button>
      <button type="button" onclick={() => useReference(referencePath)} disabled={busy}>
        Use this path
      </button>
    </section>

    <section>
      <h2>Avatar</h2>
      {#if avatar !== null}
        <p class:error={avatar.status === "folder_missing" || avatar.status === "no_art"}>
          {avatarText(avatar)}
        </p>
        {#if avatar.art_folder !== null}
          <dl>
            <dt>Art folder</dt>
            <dd>{avatar.resolved_folder}</dd>
            {#if avatar.expressions.length > 0}
              <dt>Expressions</dt>
              <dd>
                {#each avatar.expressions as expr, i (expr.id)}
                  <span class:warn={!expr.complete} title={expr.states.join(", ")}>
                    {expr.id}{expr.complete ? "" : " (incomplete)"}</span
                  >{i < avatar.expressions.length - 1 ? ", " : ""}
                {/each}
              </dd>
            {/if}
            {#if Object.keys(avatar.emotion_map).length > 0}
              <dt>Emotion map</dt>
              <dd>
                {Object.entries(avatar.emotion_map)
                  .map(([emotion, expr]) => `${emotion} → ${expr}`)
                  .join(", ")}
              </dd>
            {/if}
          </dl>
          {#if avatar.external}
            <p class="hint">
              The art stays in its own folder (it is not copied). Moving this project to another
              computer needs the art there too, then choose the folder again.
            </p>
          {/if}
        {/if}
        {#if avatar.problem !== null}<p class="error">{avatar.problem}</p>{/if}
        {#each avatar.warnings as item}
          <p class="warn">{item}</p>
        {/each}
      {/if}
      <p class="hint">
        One folder per expression named like <code>01_smile</code>, each with four PNGs such as
        <code>01a_smile_oicm.png</code> (<code>oi</code>/<code>ci</code> eyes open or closed,
        <code>om</code>/<code>cm</code> mouth open or closed).
      </p>
      <label>
        Art folder path
        <input bind:value={artPath} placeholder="D:\Avatars\my avatar" disabled={busy} />
      </label>
      <button type="button" onclick={chooseArtFolder} disabled={busy}>Choose folder...</button>
      <button type="button" onclick={() => useArtFolder(artPath)} disabled={busy}>
        Use this path
      </button>
      {#if avatar !== null && avatar.art_folder !== null}
        <button type="button" onclick={() => useArtFolder(null)} disabled={busy}>Clear</button>
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
{/if}

<style>
  main {
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
    border-bottom: 1px solid var(--border);
  }
  td.file {
    overflow-wrap: anywhere;
  }
  tr.missing td {
    color: var(--danger);
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
    border-bottom: 1px solid var(--border);
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
    color: var(--danger);
    font-size: 0.8rem;
  }
  .error {
    color: var(--danger);
  }
  .warn {
    color: var(--warning);
  }
</style>
