<!--
  Small status pill (UI-2 S4): neutral, ok, warning, error, accent.
-->
<script lang="ts">
  import type { Snippet } from "svelte";

  type Props = {
    kind?: "neutral" | "ok" | "warning" | "error" | "accent";
    title?: string;
    children: Snippet;
  };

  let { kind = "neutral", title, children }: Props = $props();
</script>

<span class="badge {kind}" {title}>{@render children()}</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 20px;
    padding: 0 7px;
    border-radius: 10px;
    background: var(--surface-3);
    color: var(--text-2);
    font-size: var(--fs-xs);
    font-weight: 600;
    white-space: nowrap;
    vertical-align: middle;
  }
  .ok {
    background: var(--success-soft);
    color: var(--success);
  }
  .warning {
    background: var(--warning-soft);
    color: var(--warning);
  }
  .error {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .accent {
    background: var(--accent-soft);
    color: var(--accent-hover);
  }
</style>
