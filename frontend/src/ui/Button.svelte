<!--
  Shared button (UI-2 S3). Variants: primary (one per screen), secondary (default), ghost, danger.
  Optional leading icon from @lucide/svelte. Extra attributes (title, aria-*) pass through.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLButtonAttributes } from "svelte/elements";
  import type { LucideIcon } from "@lucide/svelte";

  type Props = HTMLButtonAttributes & {
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "sm" | "md";
    icon?: LucideIcon;
    children?: Snippet;
  };

  let {
    variant = "secondary",
    size = "md",
    icon: Icon,
    type = "button",
    children,
    class: extra = "",
    ...rest
  }: Props = $props();
</script>

<button {type} class="btn {variant} {size} {extra}" {...rest}>
  {#if Icon}<Icon size={size === "sm" ? 14 : 16} strokeWidth={1.75} aria-hidden="true" />{/if}
  {#if children}{@render children()}{/if}
</button>

<style>
  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    height: 28px;
    padding: 0 10px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    background: var(--surface-3);
    color: var(--text-1);
    font: 500 var(--fs-md) var(--font);
    white-space: nowrap;
    cursor: pointer;
  }
  .btn.sm {
    height: 24px;
    padding: 0 8px;
    font-size: var(--fs-sm);
  }
  .btn:hover:not(:disabled) {
    background: var(--hover);
  }
  .primary {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }
  .primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  .ghost {
    border-color: transparent;
    background: transparent;
    color: var(--text-2);
  }
  .ghost:hover:not(:disabled) {
    background: var(--surface-3);
    color: var(--text-1);
  }
  .danger {
    border-color: color-mix(in srgb, var(--danger) 40%, transparent);
    background: transparent;
    color: var(--danger);
  }
  .danger:hover:not(:disabled) {
    background: var(--danger-soft);
  }
  .btn:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .btn:focus-visible {
    outline: none;
    box-shadow: var(--focus-ring);
  }
</style>
