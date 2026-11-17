<script lang="ts">
  import { RotateCcw } from "@lucide/svelte";
  import Button from "./ui/Button.svelte";
  import { show2, sliderValue } from "./voice";

  let {
    label,
    hint,
    min,
    max,
    step,
    override,
    effective,
    fallback,
    onset,
  }: {
    label: string;
    hint: string;
    min: number;
    max: number;
    step: number;
    /** The stored value; null means "use the emotion preset". */
    override: number | null;
    /** What generation would use now; null when the emotion is unknown. */
    effective: number | null;
    /** Where the thumb sits when there is neither. */
    fallback: number;
    /** Called once when the drag ends (one undo step); null resets to the preset. */
    onset: (value: number | null) => Promise<void>;
  } = $props();

  /** The value while the thumb is being dragged. */
  let dragging = $state<number | null>(null);

  const shown = $derived(dragging ?? sliderValue(override, effective, fallback));
  const source = $derived(
    override !== null || dragging !== null
      ? "custom"
      : effective === null
        ? "no preset for this emotion"
        : "from the emotion preset",
  );

  async function commit(value: number | null): Promise<void> {
    try {
      await onset(value);
    } finally {
      dragging = null;
    }
  }
</script>

<div class="param">
  <label>
    <span class="head">
      <span class="name">{label}</span>
      <span class="src">{source}</span>
      <strong class="val num">{show2(shown)}</strong>
    </span>
    <input
      type="range"
      {min}
      {max}
      {step}
      value={shown}
      oninput={(e) => (dragging = Number(e.currentTarget.value))}
      onchange={(e) => void commit(Math.round(Number(e.currentTarget.value) * 100) / 100)}
    />
  </label>
  <div class="foot">
    <span class="hint">{hint}</span>
    {#if override !== null}
      <Button size="sm" variant="ghost" icon={RotateCcw} onclick={() => void commit(null)}>
        Reset to preset
      </Button>
    {/if}
  </div>
</div>

<style>
  .param {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  label {
    display: block;
  }
  .head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 2px;
  }
  .name {
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  .src {
    flex: 1;
    color: var(--text-3);
    font-size: var(--fs-xs);
  }
  .val {
    font-size: var(--fs-sm);
  }
  input {
    width: 100%;
  }
  .foot {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 24px;
  }
  .hint {
    flex: 1;
    color: var(--text-3);
    font-size: var(--fs-xs);
  }
</style>
