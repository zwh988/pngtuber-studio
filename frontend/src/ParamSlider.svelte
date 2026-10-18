<script lang="ts">
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
    <span class="head">{label}: <strong>{show2(shown)}</strong> <span class="src">({source})</span></span>
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
      <button type="button" onclick={() => void commit(null)}>Reset to preset</button>
    {/if}
  </div>
</div>

<style>
  .param {
    margin-bottom: 0.75rem;
  }
  label {
    display: block;
  }
  .head {
    display: block;
    margin-bottom: 0.2rem;
  }
  .src {
    opacity: 0.7;
    font-size: 0.85rem;
  }
  input {
    width: 100%;
  }
  .foot {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .hint {
    flex: 1;
    font-size: 0.85rem;
    opacity: 0.7;
  }
</style>
