<!--
  Settings (M7 S5, decision 4). Adds what had no home: emotion preset editing
  (app-wide), the open project's export defaults (one undo step), the keyboard
  shortcuts map, and the tools and folders. Links to what already has a home.
-->
<script lang="ts">
  import { FolderOpen, RotateCcw } from "@lucide/svelte";
  import {
    editBatch,
    getSettings,
    openSettingsPath,
    resetPresets,
    savePresets,
    type AppSettings,
    type EditOp,
    type ExportSettings,
    type PresetItem,
    type PresetsState,
  } from "./api";
  import ShortcutsList from "./ShortcutsList.svelte";
  import Badge from "./ui/Badge.svelte";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";
  import IconButton from "./ui/IconButton.svelte";

  type Props = {
    /** Name of the open project, or null. */
    projectName: string | null;
    onopenproject: () => void;
  };

  let { projectName, onopenproject }: Props = $props();

  type Row = { name: string; exaggeration: number; cfg_weight: number; expression: string };

  let settings = $state<AppSettings | null>(null);
  let rows = $state<Row[]>([]);
  let exportDraft = $state<ExportSettings | null>(null);
  let error = $state<string | null>(null);
  let notice = $state<string | null>(null);
  let busy = $state(false);

  const presets = $derived<PresetsState | null>(settings?.presets ?? null);

  function rowsFrom(state: PresetsState): Row[] {
    return state.presets.map((p) => ({
      name: p.name,
      exaggeration: p.exaggeration,
      cfg_weight: p.cfg_weight,
      expression: p.expression,
    }));
  }

  function item(name: string): PresetItem | undefined {
    return presets?.presets.find((p) => p.name === name);
  }

  function differs(a: number, b: number): boolean {
    return Math.abs(a - b) > 1e-9;
  }

  const presetsDirty = $derived(
    presets !== null &&
      rows.some((row) => {
        const saved = item(row.name);
        return (
          saved === undefined ||
          differs(row.exaggeration, saved.exaggeration) ||
          differs(row.cfg_weight, saved.cfg_weight) ||
          row.expression.trim() !== saved.expression
        );
      }),
  );

  function changedFromBuiltin(row: Row): boolean {
    const p = item(row.name);
    return (
      p !== undefined &&
      (differs(row.exaggeration, p.builtin_exaggeration) ||
        differs(row.cfg_weight, p.builtin_cfg_weight) ||
        row.expression.trim() !== p.builtin_expression)
    );
  }

  const exportDirty = $derived(
    settings?.export != null &&
      exportDraft !== null &&
      JSON.stringify(exportDraft) !== JSON.stringify(settings.export),
  );

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  async function load(): Promise<void> {
    try {
      settings = await getSettings();
      rows = settings.presets === null ? [] : rowsFrom(settings.presets);
      exportDraft = settings.export === null ? null : { ...settings.export };
    } catch (err) {
      error = message(err);
    }
  }

  async function run(action: () => Promise<void>): Promise<void> {
    busy = true;
    error = null;
    notice = null;
    try {
      await action();
    } catch (err) {
      error = message(err);
    } finally {
      busy = false;
    }
  }

  function applyPresets(state: PresetsState): void {
    if (settings !== null) {
      settings = { ...settings, presets: state };
    }
    rows = rowsFrom(state);
  }

  const savePresetRows = () =>
    run(async () => {
      applyPresets(
        await savePresets(
          rows.map((r) => ({ ...r, expression: r.expression.trim() })),
        ),
      );
      notice = "Presets saved. They apply to every project from the next Generate.";
    });

  const resetAll = () =>
    run(async () => {
      applyPresets(await resetPresets());
      notice = "Presets reset to the built-in values.";
    });

  function resetRow(row: Row): void {
    const p = item(row.name);
    if (p !== undefined) {
      row.exaggeration = p.builtin_exaggeration;
      row.cfg_weight = p.builtin_cfg_weight;
      row.expression = p.builtin_expression;
    }
  }

  function number(value: string, fallback: number): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  const saveExport = () =>
    run(async () => {
      if (exportDraft === null || settings?.export == null) {
        return;
      }
      const before = settings.export;
      const draft = exportDraft;
      const op: Extract<EditOp, { op: "set_export_settings" }> = { op: "set_export_settings" };
      if (draft.height !== before.height) op.height = draft.height;
      if (draft.fps !== before.fps) op.fps = draft.fps;
      if (draft.include_avatar_overlay !== before.include_avatar_overlay) {
        op.include_avatar_overlay = draft.include_avatar_overlay;
      }
      if (draft.include_raw_video_link !== before.include_raw_video_link) {
        op.include_raw_video_link = draft.include_raw_video_link;
      }
      if (draft.unload_tts_before_export !== before.unload_tts_before_export) {
        op.unload_tts_before_export = draft.unload_tts_before_export;
      }
      await editBatch("Change export defaults", [op]);
      await load();
      notice = "Export defaults saved to the project. Ctrl+Z in the editor undoes it.";
    });

  const open = (key: string) =>
    run(async () => {
      await openSettingsPath(key);
    });

  void load();
</script>

<div class="page-head">
  <div class="title">
    <h1>Settings</h1>
    <div class="muted">
      Emotion presets and shortcuts apply to every project; export defaults belong to the open
      project.
    </div>
  </div>
</div>

{#if error !== null}
  <Banner kind="error" onclose={() => (error = null)}>{error}</Banner>
{/if}
{#if notice !== null}
  <Banner kind="success" onclose={() => (notice = null)}>{notice}</Banner>
{/if}

{#if settings === null}
  <p class="muted">Loading...</p>
{:else}
  <section class="card">
    <div class="card-head">
      <h2>Emotion presets</h2>
      {#if presets?.customized}<Badge kind="accent">edited</Badge>{/if}
      <span class="spacer"></span>
      {#if presets?.customized}
        <Button size="sm" variant="ghost" icon={RotateCcw} onclick={resetAll} disabled={busy}>
          Reset all to built-in
        </Button>
      {/if}
    </div>
    <div class="body">
      {#if settings.presets_error !== null}
        <Banner kind="error">{settings.presets_error}</Banner>
      {:else if presets !== null}
        {#if presets.problem !== null}<Banner kind="warning">{presets.problem}</Banner>{/if}
        <p class="muted small">
          The starting delivery of each emotion. A line's own sliders still override them. Changing a
          preset gives lines that use it a new take on their next Generate; existing takes are kept.
        </p>
        <table class="presets">
          <thead>
            <tr>
              <th>Emotion</th>
              <th title="How dramatic the delivery is ({presets.exaggeration_min} to {presets.exaggeration_max})">
                Exaggeration
              </th>
              <th title="Lower is slower and more deliberate ({presets.cfg_weight_min} to {presets.cfg_weight_max})">
                Pacing
              </th>
              <th title="The avatar expression keyed when a placed line has this emotion">Avatar expression</th>
              <th><span class="sr">Reset</span></th>
            </tr>
          </thead>
          <tbody>
            {#each rows as row (row.name)}
              <tr>
                <td class="name">
                  {row.name}
                  {#if changedFromBuiltin(row)}<span class="dot" title="Differs from the built-in value"></span>{/if}
                </td>
                <td>
                  <input
                    class="num"
                    type="number"
                    min={presets.exaggeration_min}
                    max={presets.exaggeration_max}
                    step="0.05"
                    value={row.exaggeration}
                    aria-label={`${row.name} exaggeration`}
                    oninput={(e) => (row.exaggeration = number(e.currentTarget.value, row.exaggeration))}
                  />
                </td>
                <td>
                  <input
                    class="num"
                    type="number"
                    min={presets.cfg_weight_min}
                    max={presets.cfg_weight_max}
                    step="0.05"
                    value={row.cfg_weight}
                    aria-label={`${row.name} pacing`}
                    oninput={(e) => (row.cfg_weight = number(e.currentTarget.value, row.cfg_weight))}
                  />
                </td>
                <td>
                  <input type="text" bind:value={row.expression} aria-label={`${row.name} avatar expression`} />
                </td>
                <td>
                  <IconButton
                    icon={RotateCcw}
                    size="sm"
                    label={`Built-in values for ${row.name}`}
                    onclick={() => resetRow(row)}
                    disabled={busy || !changedFromBuiltin(row)}
                  />
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        <div class="actions">
          <Button variant="primary" onclick={savePresetRows} disabled={busy || !presetsDirty}>Save presets</Button>
          <Button
            variant="ghost"
            onclick={() => presets !== null && (rows = rowsFrom(presets))}
            disabled={busy || !presetsDirty}
          >
            Discard changes
          </Button>
          <span class="muted small path">Saved in {presets.path}</span>
        </div>
      {/if}
    </div>
  </section>

  <section class="card">
    <div class="card-head">
      <h2>Export defaults</h2>
      {#if projectName !== null}<span class="muted small">for {projectName}</span>{/if}
    </div>
    <div class="body">
      {#if exportDraft === null}
        <p class="muted">Open a project to set its export defaults. The export screen starts from them.</p>
      {:else}
        <div class="form">
          <label>
            <span>Resolution</span>
            <select
              value={String(exportDraft.height)}
              onchange={(e) => exportDraft !== null && (exportDraft.height = Number(e.currentTarget.value))}
            >
              <option value="1080">1080p</option>
              <option value="720">720p</option>
            </select>
          </label>
          <label>
            <span>Frame rate</span>
            <select
              value={String(exportDraft.fps)}
              onchange={(e) => {
                if (exportDraft !== null) {
                  const v = e.currentTarget.value;
                  exportDraft.fps = v === "match" ? "match" : Number(v);
                }
              }}
            >
              <option value="match">Match the footage</option>
              <option value="30">30 fps</option>
              <option value="60">60 fps</option>
              {#if exportDraft.fps !== "match" && exportDraft.fps !== 30 && exportDraft.fps !== 60}
                <option value={String(exportDraft.fps)}>{exportDraft.fps} fps</option>
              {/if}
            </select>
          </label>
          <label class="check">
            <input type="checkbox" bind:checked={exportDraft.include_avatar_overlay} />
            <span>Transparent avatar overlay (PNG sequence)</span>
          </label>
          <label class="check">
            <input type="checkbox" bind:checked={exportDraft.include_raw_video_link} />
            <span>Link the raw recordings into the bundle</span>
          </label>
          <label class="check">
            <input type="checkbox" bind:checked={exportDraft.unload_tts_before_export} />
            <span>Unload the voice model before exporting (frees GPU memory)</span>
          </label>
        </div>
        <div class="actions">
          <Button variant="primary" onclick={saveExport} disabled={busy || !exportDirty}>Save export defaults</Button>
          <Button
            variant="ghost"
            onclick={() => settings?.export != null && (exportDraft = { ...settings.export })}
            disabled={busy || !exportDirty}
          >
            Discard changes
          </Button>
        </div>
      {/if}
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Keyboard shortcuts</h2><span class="muted small">press ? in the editor</span></div>
    <div class="body"><ShortcutsList /></div>
  </section>

  <section class="card">
    <div class="card-head">
      <h2>Tools and folders</h2>
      {#if settings.tools_problem === null}<Badge kind="ok">video export ready</Badge>{:else}<Badge
          kind="error">video export not ready</Badge
        >{/if}
    </div>
    <div class="body">
      {#if settings.tools_problem !== null}<Banner kind="error">{settings.tools_problem}</Banner>{/if}
      <ul class="paths">
        {#each settings.paths as p (p.key)}
          <li>
            <div class="info">
              <div>{p.label} {#if !p.exists}<Badge kind="warning">not there yet</Badge>{/if}</div>
              <code class="path">{p.path}</code>
            </div>
            <IconButton
              icon={FolderOpen}
              label={`Open the folder of: ${p.label}`}
              onclick={() => void open(p.key)}
              disabled={busy || (p.folder && !p.exists)}
            />
          </li>
        {/each}
      </ul>
    </div>
  </section>

  <section class="card">
    <div class="card-head"><h2>Elsewhere</h2></div>
    <div class="body">
      <ul class="elsewhere">
        <li>
          <strong>Voice reference and avatar art folder:</strong> the project page.
          {#if projectName !== null}<Button size="sm" variant="ghost" onclick={onopenproject}>Open project page</Button>{/if}
        </li>
        <li><strong>Voice FX presets and game audio level:</strong> the editor's Voice FX tab.</li>
        <li><strong>Takes and disk space:</strong> the editor's Line bank tab.</li>
        <li><strong>Avatar base motion and placement:</strong> the editor's Avatar tab.</li>
        <li><strong>Voice model download:</strong> the Voice model page in the sidebar.</li>
      </ul>
    </div>
  </section>
{/if}

<style>
  .page-head {
    margin-bottom: 16px;
  }
  h1 {
    margin: 0 0 4px;
    font-size: var(--fs-xl);
    font-weight: 600;
  }
  h2 {
    margin: 0;
    font-size: var(--fs-lg);
    font-weight: 600;
  }
  .muted {
    color: var(--text-2);
  }
  .small {
    font-size: var(--fs-sm);
  }
  .card {
    max-width: 980px;
    margin-bottom: 16px;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--surface-1);
  }
  .card-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    padding: 8px 14px;
    border-bottom: 1px solid var(--border);
  }
  .spacer {
    flex: 1;
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px;
  }
  .body p {
    margin: 0;
  }
  .presets {
    border-collapse: collapse;
    width: 100%;
  }
  .presets th {
    text-align: left;
    font-weight: 500;
    font-size: var(--fs-sm);
    color: var(--text-2);
    padding: 0 8px 6px 0;
  }
  .presets td {
    padding: 3px 8px 3px 0;
  }
  .presets input[type="number"] {
    width: 90px;
  }
  .presets input[type="text"] {
    width: 100%;
    min-width: 120px;
  }
  .name {
    white-space: nowrap;
  }
  .dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    margin-left: 6px;
    border-radius: 50%;
    background: var(--accent);
    vertical-align: middle;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .path {
    font-family: var(--font-mono);
    font-size: var(--fs-sm);
    overflow-wrap: anywhere;
  }
  .form {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 10px 20px;
  }
  .form label {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .form label.check {
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }
  .paths,
  .elsewhere {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .paths li {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .paths .info {
    flex: 1;
    min-width: 0;
  }
  .paths code {
    color: var(--text-2);
  }
  .elsewhere li {
    color: var(--text-2);
  }
  .elsewhere strong {
    color: var(--text-1);
    font-weight: 500;
  }
</style>
