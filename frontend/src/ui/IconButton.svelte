<!--
  Icon-only button (UI-2 S3). `label` is required: it becomes the tooltip and the aria-label.
  `pressed` turns it into a toggle (aria-pressed, accent tint).
-->
<script lang="ts">
  import type { HTMLButtonAttributes } from "svelte/elements";
  import type { LucideIcon } from "@lucide/svelte";

  type Props = HTMLButtonAttributes & {
    icon: LucideIcon;
    label: string;
    variant?: "ghost" | "secondary" | "primary" | "danger";
    size?: "sm" | "md";
    pressed?: boolean;
    /** Fill colour for the icon (for example a filled star); none by default. */
    iconFill?: string;
  };

  let {
    icon: Icon,
    label,
    variant = "ghost",
    size = "md",
    pressed,
    iconFill = "none",
    type = "button",
    class: extra = "",
    ...rest
  }: Props = $props();
</script>

<button
  {type}
  class="ib {variant} {size} {extra}"
  class:on={pressed === true}
  title={label}
  aria-label={label}
  aria-pressed={pressed}
  {...rest}
>
  <Icon size={size === "sm" ? 14 : 16} strokeWidth={1.75} fill={iconFill} aria-hidden="true" />
</button>

<style>
  .ib {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: 1px solid transparent;
    border-radius: var(--r-md);
    background: transparent;
    color: var(--text-2);
    cursor: pointer;
    flex: none;
  }
  .ib.sm {
    width: 24px;
    height: 24px;
  }
  .ib:hover:not(:disabled) {
    background: var(--surface-3);
    color: var(--text-1);
  }
  .secondary {
    border-color: var(--border-strong);
    background: var(--surface-3);
    color: var(--text-1);
  }
  .secondary:hover:not(:disabled) {
    background: var(--hover);
  }
  .primary {
    border-color: var(--accent);
    background: var(--accent);
    color: var(--on-accent);
  }
  .primary:hover:not(:disabled) {
    background: var(--accent-hover);
    color: var(--on-accent);
  }
  .danger {
    color: var(--danger);
  }
  .danger:hover:not(:disabled) {
    background: var(--danger-soft);
    color: var(--danger);
  }
  .on {
    background: var(--accent-soft);
    color: var(--accent-hover);
  }
  .ib:disabled {
    opacity: 0.4;
    cursor: default;
  }
  .ib:focus-visible {
    outline: none;
    box-shadow: var(--focus-ring);
  }
</style>
