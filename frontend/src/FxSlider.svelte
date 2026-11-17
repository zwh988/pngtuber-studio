<script lang="ts">
  import { onDestroy } from "svelte";
  import { decimals, roundTo } from "./fx";

  let {
    label,
    min,
    max,
    step,
    value,
    unit = "",
    signed = false,
    disabled = false,
    oncommit,
  }: {
    label: string;
    min: number;
    max: number;
    step: number;
    /** The stored value; shown clamped into the range. */
    value: number;
    unit?: string;
    /** Show a plus sign for positive values (EQ gains). */
    signed?: boolean;
    disabled?: boolean;
    /** Called once after the thumb is released or the keys rest: one undo step. */
    oncommit: (value: number) => Promise<void>;
  } = $props();

  /** The value while the thumb is moving, before it is committed. */
  let dragging = $state<number | null>(null);
  let timer: number | undefined;

  const shown = $derived(dragging ?? Math.min(max, Math.max(min, value)));

  function text(v: number): string {
    const sign = signed && v > 0 ? "+" : "";
    return `${sign}${v.toFixed(decimals(step))}${unit === "" ? "" : ` ${unit}`}`;
  }

  async function commit(v: number): Promise<void> {
    try {
      await oncommit(v);
    } finally {
      // Keep the thumb where a newer drag put it.
      if (dragging === v) {
        dragging = null;
      }
    }
  }

  /** Mouse release fires once; held arrow keys fire often, so wait for a short rest. */
  function settle(v: number): void {
    dragging = v;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void commit(v), 250);
  }

  onDestroy(() => window.clearTimeout(timer));
</script>

<label class="slider" class:off={disabled}>
  <span class="head"><span class="name">{label}</span><strong class="num">{text(shown)}</strong></span>
  <input
    type="range"
    {min}
    {max}
    {step}
    {disabled}
    value={shown}
    oninput={(e) => (dragging = roundTo(Number(e.currentTarget.value), step))}
    onchange={(e) => settle(roundTo(Number(e.currentTarget.value), step))}
  />
</label>

<style>
  .slider {
    display: block;
    margin-bottom: 8px;
  }
  .slider.off {
    opacity: 0.55;
  }
  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 2px;
    font-size: var(--fs-sm);
  }
  .name {
    color: var(--text-2);
  }
  input {
    width: 100%;
  }
</style>
