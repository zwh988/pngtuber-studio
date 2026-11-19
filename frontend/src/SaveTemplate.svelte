<!--
  "Save as template" on the project page (M7 S6, decision 5): saves the open project's
  bookends, voice profile and reference clip, FX chain, avatar and export settings as a
  channel template that "New project" can start from.
-->
<script lang="ts">
  import { getTemplates, saveTemplate, type TemplateInfo } from "./api";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";

  /** `open` is set by the page's "Save as template" button; the panel shows under the header. */
  type Props = { suggestedName: string; open: boolean };

  let { suggestedName, open = $bindable(false) }: Props = $props();

  let name = $state("");
  let existing = $state<TemplateInfo[]>([]);
  let folder = $state<string | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let saved = $state<TemplateInfo | null>(null);

  const clash = $derived(
    existing.some((t) => !t.builtin && t.name.toLowerCase() === name.trim().replace(/\s+/g, " ").toLowerCase()),
  );

  let started = false;
  $effect(() => {
    if (open && !started) {
      started = true;
      void start();
    } else if (!open) {
      started = false;
    }
  });

  async function start(): Promise<void> {
    error = null;
    saved = null;
    name = suggestedName;
    try {
      const list = await getTemplates();
      existing = list.templates;
      folder = list.folder;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function save(): Promise<void> {
    busy = true;
    error = null;
    try {
      saved = await saveTemplate(name, clash);
      open = false;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }
</script>

{#if open || saved !== null || error !== null}
  <div class="panel">
    {#if error !== null}<Banner kind="error" onclose={() => (error = null)}>{error}</Banner>{/if}
    {#if saved !== null}
      <Banner kind="success" onclose={() => (saved = null)}>
        Saved the template "{saved.name}". New projects can start from it.
      </Banner>
    {/if}
    {#if open}
      <p class="muted small">
        Saves this project's intro and outro, voice profile and reference clip, voice FX, avatar art and
        placement, and export defaults. Footage, lines and takes are not included.
      </p>
      <div class="row">
        <input
          type="text"
          bind:value={name}
          aria-label="Template name"
          placeholder="Template name"
          maxlength="60"
          disabled={busy}
          onkeydown={(e) => {
            if (e.key === "Enter" && name.trim() !== "") void save();
            if (e.key === "Escape") open = false;
          }}
        />
        <Button variant={clash ? "danger" : "primary"} onclick={() => void save()} disabled={busy || name.trim() === ""}>
          {clash ? "Replace template" : "Save template"}
        </Button>
        <Button variant="ghost" onclick={() => (open = false)} disabled={busy}>Cancel</Button>
      </div>
      {#if clash}<p class="warn small">A saved template already has this name: saving replaces it.</p>{/if}
      {#if folder !== null}<p class="muted small">Saved in <code>{folder}</code></p>{/if}
    {/if}
  </div>
{/if}

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: -4px 0 16px;
    padding: 12px 14px;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--surface-1);
  }
  .panel p {
    margin: 0;
  }
  .row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .row input {
    flex: 1;
    max-width: 360px;
  }
  .muted {
    color: var(--text-2);
  }
  .warn {
    color: var(--warning);
  }
  .small {
    font-size: var(--fs-sm);
  }
  code {
    font-family: var(--font-mono);
    overflow-wrap: anywhere;
  }
</style>
