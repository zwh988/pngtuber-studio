<script lang="ts">
  import {
    getAvatar,
    getFootage,
    getModelStatus,
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
    startModelDownload,
    type AvatarState,
    type FootageReport,
    type ModelStatus,
    type ProjectSummary,
    type RecentItem,
    type VoiceState,
  } from "./api";
  import Editor from "./Editor.svelte";
  import ExportScreen from "./ExportScreen.svelte";
  import ModelSetup from "./ModelSetup.svelte";
  import SettingsPage from "./SettingsPage.svelte";
  import { cleanPathInput, formatBytes, voiceStatusText } from "./voice";
  import {
    ArrowRight,
    Clapperboard,
    Film,
    Folder,
    FolderOpen,
    House,
    Link,
    Mic,
    Plus,
    AudioLines,
    RefreshCw,
    Settings,
    UserRound,
    X,
  } from "@lucide/svelte";
  import Badge from "./ui/Badge.svelte";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";
  import IconButton from "./ui/IconButton.svelte";
  import Section from "./ui/Section.svelte";

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
  /** Which page the project screen shows (UI-2 S4; "model" is the voice model page, M7 S3). */
  type Page = "home" | "project" | "new" | "open" | "model" | "settings";
  let page = $state<Page>("home");
  /** The voice model's files (M7 S3); polled while a download runs. */
  let model = $state<ModelStatus | null>(null);
  let modelTimer: ReturnType<typeof setTimeout> | null = null;

  let newName = $state("");
  let newParent = $state("");
  let openPath = $state("");

  const missingFootage = $derived(
    footage === null ? 0 : footage.items.filter((item) => !item.exists).length,
  );
  const avatarReady = $derived(
    avatar !== null &&
      avatar.status !== "not_configured" &&
      avatar.status !== "folder_missing" &&
      avatar.status !== "no_art",
  );

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  function show(next: Page): void {
    error = null;
    page = next;
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
      page = "project";
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
      page = current === null ? "home" : "project";
    } catch (err) {
      error = message(err);
    }
    await refreshModel();
    // First run (M7 S3): with no project open, a missing model gets its page first.
    if (model !== null && model.state !== "ready" && current === null) {
      page = "model";
    }
  }

  function scheduleModelPoll(): void {
    if (modelTimer !== null) {
      clearTimeout(modelTimer);
      modelTimer = null;
    }
    if (model?.state === "downloading") {
      modelTimer = setTimeout(() => void refreshModel(), 500);
    }
  }

  async function refreshModel(): Promise<void> {
    try {
      model = await getModelStatus();
    } catch (err) {
      error = message(err);
    }
    scheduleModelPoll();
  }

  async function downloadModel(): Promise<void> {
    error = null;
    try {
      model = await startModelDownload();
    } catch (err) {
      error = message(err);
    }
    scheduleModelPoll();
  }

  function modelTag(status: ModelStatus): string {
    if (status.state === "downloading") {
      return `${Math.floor((100 * status.bytes_done) / Math.max(1, status.bytes_total))}%`;
    }
    return status.state === "failed" ? "stopped" : "not set up";
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
  <ExportScreen projectName={current?.name ?? null} onclose={() => (view = "editor")} />
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
  <div class="screen">
    <nav class="sidebar" aria-label="Projects">
      <div class="brand">
        <img src="/logo.png" alt="" width="28" height="28" />
        <span>PNGtuber Studio</span>
      </div>

      <button type="button" class="nav-item" class:on={page === "home"} onclick={() => show("home")}>
        <House size={16} strokeWidth={1.75} aria-hidden="true" />
        Home
      </button>
      {#if model !== null}
        <button type="button" class="nav-item" class:on={page === "model"} onclick={() => show("model")}>
          <AudioLines size={16} strokeWidth={1.75} aria-hidden="true" />
          <span class="nav-text">Voice model</span>
          {#if model.state !== "ready"}<span class="nav-tag">{modelTag(model)}</span>{/if}
        </button>
      {/if}
      <button type="button" class="nav-item" class:on={page === "settings"} onclick={() => show("settings")}>
        <Settings size={16} strokeWidth={1.75} aria-hidden="true" />
        Settings
      </button>
      {#if current !== null}
        <button
          type="button"
          class="nav-item"
          class:on={page === "project"}
          onclick={() => show("project")}
        >
          <FolderOpen size={16} strokeWidth={1.75} aria-hidden="true" />
          <span class="nav-text">{current.name}</span>
          <span class="nav-tag">open</span>
        </button>
      {/if}

      <div class="nav-head">Recent</div>
      <div class="recent-nav">
        {#if recent.length === 0}
          <p class="nav-empty">No recent projects yet.</p>
        {/if}
        {#each recent as item (item.folder)}
          <div class="recent-row" class:missing={!item.exists}>
            <button
              type="button"
              class="nav-item"
              title={item.exists ? `${item.folder}\nLast opened ${when(item.last_opened)}` : `Missing: ${item.folder}`}
              onclick={() => run(() => openProject(item.folder))}
              disabled={busy || !item.exists}
            >
              <Folder size={16} strokeWidth={1.75} aria-hidden="true" />
              <span class="nav-text">{item.name}</span>
              {#if !item.exists}<span class="nav-tag">missing</span>{/if}
            </button>
            <span class="remove">
              <IconButton
                icon={X}
                size="sm"
                label={`Remove ${item.name} from the list (the folder is not touched)`}
                onclick={() => forget(item.folder)}
                disabled={busy}
              />
            </span>
          </div>
        {/each}
      </div>

      <div class="nav-actions">
        <Button icon={Plus} onclick={() => show("new")} disabled={busy}>New project</Button>
        <Button variant="ghost" icon={FolderOpen} onclick={() => show("open")} disabled={busy}>
          Open folder...
        </Button>
      </div>
    </nav>

    <main class="content">
      {#if error !== null}
        <Banner kind="error" onclose={() => (error = null)}>{error}</Banner>
      {/if}

      {#if page === "settings"}
        <SettingsPage projectName={current?.name ?? null} onopenproject={() => show("project")} />
      {:else if page === "model" && model !== null}
        <ModelSetup
          status={model}
          ondownload={() => void downloadModel()}
          onleave={() => show(current === null ? "home" : "project")}
        />
      {:else if page === "project" && current !== null}
        {#if current.save_error !== null}
          <Banner kind="error">Could not save the project: {current.save_error}</Banner>
        {/if}

        <div class="page-head">
          <div class="title">
            <h1>{current.name}</h1>
            <div class="path" title="Project folder">{current.folder}</div>
          </div>
          <Button variant="primary" onclick={() => (view = "editor")} disabled={busy}>
            Open editor
            <ArrowRight size={16} strokeWidth={1.75} aria-hidden="true" />
          </Button>
        </div>

        <div class="stats">
          <div class="stat">
            <div class="stat-k"><Film size={14} strokeWidth={1.75} aria-hidden="true" />Footage</div>
            <div class="stat-v num">
              {current.source_count} file{current.source_count === 1 ? "" : "s"}
            </div>
            {#if missingFootage > 0}
              <Badge kind="error">{missingFootage} missing</Badge>
            {:else if current.source_count === 0}
              <Badge kind="warning">none yet</Badge>
            {:else}
              <Badge kind="ok">all found</Badge>
            {/if}
          </div>
          <div class="stat">
            <div class="stat-k">
              <Clapperboard size={14} strokeWidth={1.75} aria-hidden="true" />Timeline
            </div>
            <div class="stat-v num">
              {current.clip_count} clip{current.clip_count === 1 ? "" : "s"}
            </div>
            {#if current.problem_count > 0}
              <Badge kind="warning">{current.problem_count} problem(s)</Badge>
            {:else if current.clip_count === 0}
              <Badge>empty</Badge>
            {:else}
              <Badge kind="ok">ok</Badge>
            {/if}
          </div>
          <div class="stat">
            <div class="stat-k"><Mic size={14} strokeWidth={1.75} aria-hidden="true" />Voice</div>
            <div class="stat-v">{voice?.ready ? "Ready" : "Not ready"}</div>
            {#if voice?.ready}
              <Badge kind="ok">reference set</Badge>
            {:else}
              <Badge kind="warning">{current.voice_status}</Badge>
            {/if}
          </div>
          <div class="stat">
            <div class="stat-k">
              <UserRound size={14} strokeWidth={1.75} aria-hidden="true" />Avatar
            </div>
            <div class="stat-v ellipsis">
              {avatarReady && avatar !== null ? avatar.name : "Not set"}
            </div>
            {#if avatarReady && avatar !== null}
              <Badge kind="ok">{avatar.expressions.length} expressions</Badge>
            {:else if avatar !== null && avatar.status !== "not_configured"}
              <Badge kind="error">problem</Badge>
            {:else}
              <Badge kind="warning">not configured</Badge>
            {/if}
          </div>
        </div>

        <section class="card">
          <div class="card-head">
            <h2>Footage</h2>
            <span class="muted small">in <code>footage\</code></span>
            {#if footage !== null && footage.added > 0}
              <Badge kind="accent">added {footage.added} new</Badge>
            {/if}
            <span class="spacer"></span>
            <Button size="sm" icon={RefreshCw} onclick={rescan} disabled={busy}>Rescan</Button>
          </div>
          {#if footage !== null && footage.errors.length > 0}
            <div class="card-pad">
              <Banner kind="error">
                <ul class="plain">
                  {#each footage.errors as item}<li>{item}</li>{/each}
                </ul>
              </Banner>
            </div>
          {/if}
          {#if footage === null || footage.items.length === 0}
            <p class="empty">
              No footage yet. Put recordings in <code>{current.folder}\footage</code>, then click
              Rescan.
            </p>
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
                    <td class="num">{item.width} x {item.height}</td>
                    <td class="num">{Number(item.fps.toFixed(3))}</td>
                    <td class="num">{duration(item.duration_ms)}</td>
                    <td class="num">{item.audio_tracks}</td>
                    <td>
                      {#if item.exists}<Badge kind="ok">ok</Badge>{:else}<Badge kind="error"
                          >missing</Badge
                        >{/if}
                    </td>
                    <td class="right">
                      {#if !item.exists && !item.external}
                        <Button size="sm" icon={Link} onclick={() => relink(item.id)} disabled={busy}>
                          Relink...
                        </Button>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </section>

        <div class="two">
          <section class="card">
            <div class="card-head">
              <h2>Voice</h2>
              {#if voice !== null}
                {#if voice.ready}<Badge kind="ok">ready</Badge>{:else}<Badge kind="warning"
                    >not ready</Badge
                  >{/if}
              {/if}
            </div>
            <div class="card-body">
              {#if voice !== null}
                <p class="status-line" class:error={!voice.ready}>{voiceStatusText(voice)}</p>
                {#if voice.reference_path !== null}
                  <dl class="kv">
                    <dt>Reference</dt>
                    <dd>{voice.reference_path}</dd>
                    {#if voice.duration_ms !== null}
                      <dt>Length</dt>
                      <dd class="num">{(voice.duration_ms / 1000).toFixed(1)} s</dd>
                    {/if}
                    {#if voice.sample_rate !== null}
                      <dt>Sample rate</dt>
                      <dd class="num">{voice.sample_rate} Hz</dd>
                    {/if}
                    {#if voice.hash !== null}
                      <dt>Fingerprint</dt>
                      <dd class="mono">{voice.hash.slice(0, 8)}</dd>
                    {/if}
                  </dl>
                {/if}
                {#each voice.problems as item}<Banner kind="error">{item}</Banner>{/each}
                {#each voice.warnings as item}<Banner kind="warning">{item}</Banner>{/each}
              {/if}
              <div class="field">
                <label for="ref-path">
                  {voice?.reference_path ? "Change the reference clip" : "Reference clip"}
                </label>
                <div class="input-row">
                  <input
                    id="ref-path"
                    bind:value={referencePath}
                    placeholder="D:\Voices\reference.wav"
                    disabled={busy}
                  />
                  <Button onclick={() => useReference(referencePath)} disabled={busy}>Use path</Button>
                  <Button onclick={chooseReference} disabled={busy}>Choose file...</Button>
                </div>
              </div>
              <Section title="About reference clips" open={false}>
                <p class="help">
                  A clean recording of one voice, 5 to 30 seconds long, works best. Use only your own
                  voice or a voice you have permission to use. The file is copied into the project.
                  Changing the clip keeps every take you made; lines you generate again make new
                  takes with the new clip.
                </p>
              </Section>
            </div>
          </section>

          <section class="card">
            <div class="card-head">
              <h2>Avatar</h2>
              {#if avatar !== null}
                {#if avatarReady}<Badge kind="ok">{avatar.expressions.length} expressions</Badge
                  >{:else if avatar.status === "not_configured"}<Badge kind="warning"
                    >not configured</Badge
                  >{:else}<Badge kind="error">problem</Badge>{/if}
              {/if}
              {#if avatar !== null && avatar.art_folder !== null}
                <span class="spacer"></span>
                <Button
                  size="sm"
                  variant="ghost"
                  title="Stop using this art folder (the files are not touched)"
                  onclick={() => useArtFolder(null)}
                  disabled={busy}
                >
                  Clear
                </Button>
              {/if}
            </div>
            <div class="card-body">
              {#if avatar !== null}
                <p
                  class="status-line"
                  class:error={avatar.status === "folder_missing" || avatar.status === "no_art"}
                >
                  {avatarText(avatar)}
                </p>
                {#if avatar.art_folder !== null}
                  <dl class="kv">
                    <dt>Art folder</dt>
                    <dd>{avatar.resolved_folder}</dd>
                    {#if avatar.expressions.length > 0}
                      <dt>Expressions</dt>
                      <dd class="chips">
                        {#each avatar.expressions as expr (expr.id)}
                          <Badge
                            kind={!expr.complete
                              ? "warning"
                              : expr.id === avatar.default_expression
                                ? "accent"
                                : "neutral"}
                            title={expr.complete
                              ? expr.states.join(", ")
                              : `Incomplete: ${expr.states.join(", ")}`}
                          >
                            {expr.id}{expr.complete ? "" : " (incomplete)"}
                          </Badge>
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
                {/if}
                {#if avatar.problem !== null}<Banner kind="error">{avatar.problem}</Banner>{/if}
                {#each avatar.warnings as item}<Banner kind="warning">{item}</Banner>{/each}
              {/if}
              <div class="field">
                <label for="art-path">
                  {avatar?.art_folder ? "Change the art folder" : "Art folder"}
                </label>
                <div class="input-row">
                  <input
                    id="art-path"
                    bind:value={artPath}
                    placeholder="D:\Avatars\my avatar"
                    disabled={busy}
                  />
                  <Button onclick={() => useArtFolder(artPath)} disabled={busy}>Use path</Button>
                  <Button onclick={chooseArtFolder} disabled={busy}>Choose folder...</Button>
                </div>
              </div>
              <Section title="How the art folder is laid out" open={false}>
                <p class="help">
                  One folder per expression named like <code>01_smile</code>, each with four PNGs
                  such as <code>01a_smile_oicm.png</code> (<code>oi</code>/<code>ci</code> eyes open
                  or closed, <code>om</code>/<code>cm</code> mouth open or closed).
                </p>
                {#if avatar !== null && avatar.external}
                  <p class="help">
                    The art stays in its own folder (it is not copied). Moving this project to another
                    computer needs the art there too, then choose the folder again.
                  </p>
                {/if}
              </Section>
            </div>
          </section>
        </div>

        <p class="foot muted small">Project schema version {current.schema_version}</p>
      {:else if page === "new"}
        <div class="page-head">
          <div class="title"><h1>New project</h1></div>
        </div>
        <section class="card form-card">
          <div class="card-body">
            <p class="muted">
              The project starts from the default channel template. Its folder is the parent folder
              plus the name.
            </p>
            <div class="field">
              <label for="new-name">Name</label>
              <input id="new-name" bind:value={newName} placeholder="My Rack" disabled={busy} />
            </div>
            <div class="field">
              <label for="new-parent">Parent folder</label>
              <div class="input-row">
                <input
                  id="new-parent"
                  bind:value={newParent}
                  placeholder="D:\Projects"
                  disabled={busy}
                />
                <Button onclick={() => browse((p) => (newParent = p))} disabled={busy}>
                  Browse...
                </Button>
              </div>
            </div>
            <div class="actions">
              <Button
                variant="primary"
                icon={Plus}
                onclick={() => run(() => newProject(newName, newParent))}
                disabled={busy}
              >
                Create project
              </Button>
            </div>
          </div>
        </section>
      {:else if page === "open"}
        <div class="page-head">
          <div class="title"><h1>Open project</h1></div>
        </div>
        <section class="card form-card">
          <div class="card-body">
            <div class="field">
              <label for="open-path">Project folder</label>
              <div class="input-row">
                <input
                  id="open-path"
                  bind:value={openPath}
                  placeholder="D:\Projects\My Rack"
                  disabled={busy}
                />
                <Button onclick={() => browse((p) => (openPath = p))} disabled={busy}>
                  Browse...
                </Button>
              </div>
            </div>
            <div class="actions">
              <Button
                variant="primary"
                icon={FolderOpen}
                onclick={() => run(() => openProject(openPath))}
                disabled={busy}
              >
                Open project
              </Button>
            </div>
          </div>
        </section>
      {:else}
        <div class="page-head">
          <div class="title">
            <h1>Projects</h1>
            <div class="muted">Open a recent project, or start a new one.</div>
          </div>
        </div>
        {#if model !== null && model.state !== "ready"}
          <Banner kind={model.state === "failed" ? "error" : "warning"}>
            {#if model.state === "downloading"}
              Downloading the voice model: {formatBytes(model.bytes_done)} of {formatBytes(model.bytes_total)}.
            {:else if model.state === "failed"}
              The voice model download stopped. Generating lines needs it.
            {:else}
              The voice model is not downloaded yet ({formatBytes(model.bytes_total)}). Generating lines
              needs it.
            {/if}
            {#snippet action()}
              <Button size="sm" onclick={() => show("model")}>
                {model?.state === "missing" ? "Set up" : "Details"}
              </Button>
            {/snippet}
          </Banner>
        {/if}
        <section class="card">
          <div class="card-head"><h2>Recent projects</h2></div>
          {#if recent.length === 0}
            <p class="empty">No recent projects yet. Create one, or open an existing project folder.</p>
          {:else}
            <ul class="recent">
              {#each recent as item (item.folder)}
                <li class:missing={!item.exists}>
                  <Folder size={18} strokeWidth={1.75} aria-hidden="true" />
                  <div class="info">
                    <div class="name">
                      {item.name}
                      {#if !item.exists}<Badge kind="error">missing</Badge>{/if}
                      {#if current !== null && current.folder === item.folder}<Badge kind="accent"
                          >open</Badge
                        >{/if}
                    </div>
                    <div class="path">{item.folder}</div>
                    <div class="muted small">Last opened {when(item.last_opened)}</div>
                  </div>
                  <Button
                    onclick={() => run(() => openProject(item.folder))}
                    disabled={busy || !item.exists}
                  >
                    Open
                  </Button>
                  <IconButton
                    icon={X}
                    label={`Remove ${item.name} from the list (the folder is not touched)`}
                    onclick={() => forget(item.folder)}
                    disabled={busy}
                  />
                </li>
              {/each}
            </ul>
          {/if}
        </section>
        <div class="two">
          <button type="button" class="action-card" onclick={() => show("new")} disabled={busy}>
            <Plus size={20} strokeWidth={1.75} aria-hidden="true" />
            <span><strong>New project</strong><span class="muted">From the channel template</span></span>
          </button>
          <button type="button" class="action-card" onclick={() => show("open")} disabled={busy}>
            <FolderOpen size={20} strokeWidth={1.75} aria-hidden="true" />
            <span><strong>Open project</strong><span class="muted">An existing project folder</span></span>
          </button>
        </div>
      {/if}
    </main>
  </div>
{/if}

<style>
  .screen {
    position: fixed;
    inset: 0;
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    background: var(--bg);
  }

  /* sidebar */
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-height: 0;
    padding: 12px;
    border-right: 1px solid var(--border);
    background: var(--surface-1);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 6px 14px;
    font-size: var(--fs-lg);
    font-weight: 600;
  }
  .brand img {
    border-radius: 7px;
  }
  .nav-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 7px 8px;
    border: none;
    border-radius: var(--r-md);
    background: none;
    color: var(--text-2);
    font: 500 var(--fs-md) var(--font);
    text-align: left;
  }
  .nav-item:hover:not(:disabled) {
    background: var(--surface-3);
    color: var(--text-1);
  }
  .nav-item.on {
    background: var(--surface-3);
    color: var(--text-1);
  }
  .nav-item:disabled {
    opacity: 1;
    color: var(--text-3);
  }
  .nav-text {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .nav-tag {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .missing .nav-tag {
    color: var(--danger);
  }
  .nav-head {
    margin: 16px 8px 4px;
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .nav-empty {
    margin: 4px 8px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  .recent-nav {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
  }
  .recent-row {
    position: relative;
    display: flex;
    align-items: center;
  }
  .recent-row .remove {
    position: absolute;
    right: 4px;
    opacity: 0;
  }
  .recent-row:hover .remove,
  .recent-row .remove:focus-within {
    opacity: 1;
  }
  .nav-actions {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-top: 10px;
  }

  /* content */
  .content {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-width: 0;
    padding: 24px 32px 32px;
    overflow-y: auto;
  }
  .page-head {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .title {
    flex: 1;
    min-width: 0;
  }
  h1 {
    margin: 0;
    font-size: var(--fs-xl);
  }
  h2 {
    margin: 0;
    font-size: var(--fs-lg);
  }
  .path {
    color: var(--text-3);
    font-family: var(--font-mono);
    font-size: var(--fs-sm);
    overflow-wrap: anywhere;
  }
  .muted {
    color: var(--text-2);
  }
  .small {
    font-size: var(--fs-sm);
  }
  .mono {
    font-family: var(--font-mono);
  }
  .spacer {
    flex: 1;
  }
  .ellipsis {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }
  .stat {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--surface-1);
    min-width: 0;
  }
  .stat-k {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .stat-v {
    max-width: 100%;
    font-size: var(--fs-lg);
    font-weight: 600;
  }

  .card {
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--surface-1);
    min-width: 0;
  }
  .card-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
  }
  .card-body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 12px 14px 14px;
  }
  .card-pad {
    padding: 12px 14px 0;
  }
  .form-card {
    max-width: 560px;
  }
  .two {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    align-items: start;
  }
  .empty {
    margin: 0;
    padding: 16px 14px;
    color: var(--text-2);
  }
  .status-line {
    margin: 0;
  }
  .help {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .foot {
    margin: 0;
  }
  .plain {
    margin: 0;
    padding-left: 1.1em;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }
  th {
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
    color: var(--text-3);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-align: left;
    text-transform: uppercase;
  }
  td {
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
  }
  tbody tr:last-child td {
    border-bottom: none;
  }
  td.file {
    overflow-wrap: anywhere;
  }
  tr.missing td.file {
    color: var(--danger);
  }
  td.right {
    text-align: right;
  }

  .kv {
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: 6px 12px;
    margin: 0;
  }
  .kv dt {
    color: var(--text-2);
  }
  .kv dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .field label {
    display: block;
    margin-bottom: 4px;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .field > input {
    width: 100%;
    box-sizing: border-box;
  }
  .input-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .input-row input {
    flex: 1 1 200px;
    min-width: 0;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  .recent {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .recent li {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    color: var(--text-2);
  }
  .recent li:last-child {
    border-bottom: none;
  }
  .recent .info {
    flex: 1;
    min-width: 0;
  }
  .recent .name {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-1);
    font-weight: 600;
  }
  .recent li.missing .info {
    opacity: 0.6;
  }
  .action-card {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px;
    border: 1px dashed var(--border-strong);
    border-radius: var(--r-lg);
    background: transparent;
    color: var(--text-1);
    text-align: left;
  }
  .action-card:hover:not(:disabled) {
    border-style: solid;
    background: var(--surface-1);
  }
  .action-card > span {
    display: flex;
    flex-direction: column;
  }
</style>
