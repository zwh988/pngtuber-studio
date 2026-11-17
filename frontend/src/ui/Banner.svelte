<!--
  Message banner (UI-2 S3): info, success, warning, error. Errors use role="alert", the rest role="status".
  Optional `action` snippet (for example a Retry button) and an optional close button.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from "@lucide/svelte";

  type Props = {
    kind?: "info" | "success" | "warning" | "error";
    children: Snippet;
    action?: Snippet;
    onclose?: () => void;
  };

  let { kind = "info", children, action, onclose }: Props = $props();

  const ICONS = { info: Info, success: CircleCheck, warning: TriangleAlert, error: CircleAlert };
  const Icon = $derived(ICONS[kind]);
</script>

<div class="banner {kind}" role={kind === "error" ? "alert" : "status"}>
  <span class="icon"><Icon size={16} strokeWidth={1.75} aria-hidden="true" /></span>
  <div class="text">{@render children()}</div>
  {#if action}<div class="action">{@render action()}</div>{/if}
  {#if onclose}
    <button type="button" class="close" aria-label="Dismiss" title="Dismiss" onclick={onclose}>
      <X size={14} strokeWidth={2} aria-hidden="true" />
    </button>
  {/if}
</div>

<style>
  .banner {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    background: var(--surface-2);
    color: var(--text-1);
    font-size: var(--fs-md);
  }
  .icon {
    display: inline-flex;
    padding-top: 1px;
    color: var(--accent-hover);
  }
  .success {
    border-color: color-mix(in srgb, var(--success) 35%, transparent);
    background: var(--success-soft);
  }
  .success .icon {
    color: var(--success);
  }
  .warning {
    border-color: color-mix(in srgb, var(--warning) 35%, transparent);
    background: var(--warning-soft);
  }
  .warning .icon {
    color: var(--warning);
  }
  .error {
    border-color: color-mix(in srgb, var(--danger) 35%, transparent);
    background: var(--danger-soft);
  }
  .error .icon {
    color: var(--danger);
  }
  .text {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .action {
    flex: none;
    display: flex;
    gap: 4px;
  }
  .close {
    display: inline-flex;
    padding: 2px;
    border: none;
    border-radius: var(--r-sm);
    background: none;
    color: var(--text-2);
    cursor: pointer;
  }
  .close:hover {
    color: var(--text-1);
    background: var(--surface-3);
  }
  .close:focus-visible {
    outline: none;
    box-shadow: var(--focus-ring);
  }
</style>
