<!--
  Titled group for panels (UI-2 S3). Collapsible by default; `open` is bindable.
  `actions` renders on the right of the header and does not toggle the section.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import { ChevronRight } from "@lucide/svelte";

  type Props = {
    title: string;
    open?: boolean;
    collapsible?: boolean;
    actions?: Snippet;
    children: Snippet;
  };

  let { title, open = $bindable(true), collapsible = true, actions, children }: Props = $props();
</script>

<section class="section">
  <div class="head">
    {#if collapsible}
      <button type="button" class="toggle" aria-expanded={open} onclick={() => (open = !open)}>
        <span class="chev" class:open><ChevronRight size={14} strokeWidth={2} aria-hidden="true" /></span>
        {title}
      </button>
    {:else}
      <span class="toggle static">{title}</span>
    {/if}
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
  </div>
  {#if open || !collapsible}
    <div class="body">{@render children()}</div>
  {/if}
</section>

<style>
  .section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 24px;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 4px 2px 0;
    border: none;
    border-radius: var(--r-sm);
    background: none;
    color: var(--text-3);
    font: 600 var(--fs-xs) var(--font);
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
  }
  .toggle:hover {
    color: var(--text-2);
  }
  .toggle.static {
    cursor: default;
  }
  .toggle:focus-visible {
    outline: none;
    box-shadow: var(--focus-ring);
  }
  .chev {
    display: inline-flex;
    transition: transform 0.12s ease;
  }
  .chev.open {
    transform: rotate(90deg);
  }
  .actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .body {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>
