<script lang="ts">
  import { onDestroy, untrack } from "svelte";
  import { defaultParams, matchingPreset, moveItem, paramStep, processingText } from "./fx";
  import {
    editFx,
    getFx,
    processedTakeUrl,
    type FxChain,
    type FxEditOp,
    type FxPreset,
    type FxState,
  } from "./fxApi";
  import FxSlider from "./FxSlider.svelte";

  /** The part of a timeline placement the audition needs. */
  interface AuditionPlacement {
    id: string;
    take_id: string | null;
    stretch?: number;
    orphaned: boolean;
  }

  let {
    active,
    reloadToken,
    placements,
    selectedPlacementId,
    onedited,
  }: {
    /** True while this tab is showing; the chain is fetched and polled only then. */
    active: boolean;
    /** Bumped by the editor after undo, redo, finished jobs and deleted takes. */
    reloadToken: number;
    placements: AuditionPlacement[];
    selectedPlacementId: string | null;
    /** An edit went onto the shared undo stack: refresh the undo and redo buttons. */
    onedited: () => void;
  } = $props();

  let fx = $state<FxState | null>(null);
  let error = $state<string | null>(null);
  /** Bumped after a refused edit so every control is rebuilt from the stored chain. */
  let resync = $state(0);
  let addType = $state("");

  let generation = 0;
  let pollTimer: number | undefined;
  let queue: Promise<void> = Promise.resolve();

  function message(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
  }

  /** Poll about every 500 ms while the background render is still catching up. */
  function schedulePoll(state: FxState): void {
    window.clearTimeout(pollTimer);
    const waiting =
      state.problem === null &&
      state.processing.error === null &&
      state.processing.ready < state.processing.total;
    if (active && waiting) {
      pollTimer = window.setTimeout(() => void load(), 500);
    }
  }

  async function load(): Promise<void> {
    window.clearTimeout(pollTimer);
    generation += 1;
    const mine = generation;
    try {
      const next = await getFx();
      if (mine !== generation) {
        return;
      }
      fx = next;
      schedulePoll(next);
    } catch (err) {
      if (mine === generation) {
        error = message(err);
      }
    }
  }

  $effect(() => {
    void reloadToken;
    void placements;
    if (active) {
      untrack(() => void load());
    }
  });

  /** Edits run one after another, each built from the newest stored chain. */
  function send(build: (state: FxState) => FxEditOp | null): Promise<void> {
    queue = queue.then(async () => {
      const state = fx;
      if (state === null) {
        return;
      }
      const op = build(state);
      if (op === null) {
        return;
      }
      error = null;
      try {
        const next = await editFx([op]);
        generation += 1;
        fx = next;
        schedulePoll(next);
        onedited();
      } catch (err) {
        error = message(err);
        resync += 1;
      }
    });
    return queue;
  }

  function editChain(mutate: (chain: FxChain) => void): Promise<void> {
    return send((state) => {
      const chain = $state.snapshot(state.chain) as FxChain;
      mutate(chain);
      return { op: "set_fx_chain", chain };
    });
  }

  function applyPreset(preset: FxPreset): Promise<void> {
    return send(() => ({ op: "set_fx_chain", chain: $state.snapshot(preset.chain) as FxChain }));
  }

  function setGameAudio(db: number): Promise<void> {
    return send(() => ({ op: "set_game_audio_db", db }));
  }

  function addEffect(type: string): Promise<void> {
    return editChain((chain) => {
      const info = fx?.effects.find((e) => e.type === type);
      if (info !== undefined) {
        chain.effects.push({ type, params: defaultParams($state.snapshot(info)) });
      }
    });
  }

  // Audition: play one placed take through the chain.
  let audio: HTMLAudioElement | null = null;
  let auditionState = $state<"idle" | "loading" | "playing">("idle");

  const auditionTarget = $derived.by(() => {
    const usable = placements.filter((p) => !p.orphaned && p.take_id !== null);
    return usable.find((p) => p.id === selectedPlacementId) ?? usable[0] ?? null;
  });
  const auditionText = $derived(
    auditionTarget === null
      ? "Place a line on the timeline to audition it here."
      : auditionTarget.id === selectedPlacementId
        ? "Plays the selected placed line."
        : "Plays the first placed line (click a block on the voice lane to pick another).",
  );

  function stopAudition(): void {
    const el = audio;
    audio = null;
    auditionState = "idle";
    if (el !== null) {
      el.pause();
      el.removeAttribute("src");
      el.load();
    }
  }

  function failAudition(el: HTMLAudioElement): void {
    if (audio === el) {
      stopAudition();
      error = "The processed take could not be played. See the processing line above.";
    }
  }

  function audition(): void {
    const target = auditionTarget;
    if (fx === null || target === null || target.take_id === null) {
      return;
    }
    stopAudition();
    error = null;
    const el = new Audio(processedTakeUrl(target.take_id, target.stretch ?? 1, fx.fx_version));
    audio = el;
    auditionState = "loading";
    el.onplaying = () => {
      if (audio === el) {
        auditionState = "playing";
      }
    };
    el.onended = () => {
      if (audio === el) {
        stopAudition();
      }
    };
    el.onerror = () => failAudition(el);
    el.play().catch(() => failAudition(el));
  }

  onDestroy(() => {
    window.clearTimeout(pollTimer);
    stopAudition();
  });

  const current = $derived(fx === null ? null : matchingPreset(fx.chain, fx.presets));
  const chosenType = $derived(addType !== "" ? addType : (fx?.effects[0]?.type ?? ""));
</script>

<div class="fx">
  {#if fx === null}
    <p class={error === null ? "hint" : "bad"}>{error ?? "Loading the voice chain..."}</p>
  {:else}
    {@const state = fx}
    {@const limits = state.limits}
    <p class="status">{processingText(state.processing)}</p>
    {#if state.problem !== null}
      <p class="bad">{state.problem}</p>
    {/if}
    {#if error !== null}
      <p class="bad">{error}</p>
    {/if}

    {#key resync}
      <section>
        <h3>Presets</h3>
        <div class="presets">
          {#each state.presets as preset (preset.name)}
            <button
              type="button"
              class:on={current === preset.name}
              onclick={() => void applyPreset(preset)}
            >
              {preset.name}
            </button>
          {/each}
        </div>
        <p class="hint">{current === null ? "Custom chain." : `${current} preset.`}</p>
      </section>

      <section>
        <h3>Audition</h3>
        <div class="row">
          {#if auditionState === "idle"}
            <button
              type="button"
              disabled={auditionTarget === null || state.problem !== null}
              onclick={audition}
            >
              Play through the chain
            </button>
          {:else}
            <button type="button" onclick={stopAudition}>Stop</button>
            {#if auditionState === "loading"}
              <span class="hint">Rendering...</span>
            {/if}
          {/if}
        </div>
        <p class="hint">{auditionText}</p>
      </section>

      <section>
        <h3>Equaliser</h3>
        <FxSlider
          label="Bass"
          min={-limits.eq_gain_limit_db}
          max={limits.eq_gain_limit_db}
          step={0.5}
          value={state.chain.eq_bass_db}
          unit="dB"
          signed
          oncommit={(v) =>
            editChain((c) => {
              c.eq_bass_db = v;
            })}
        />
        <FxSlider
          label="Mid"
          min={-limits.eq_gain_limit_db}
          max={limits.eq_gain_limit_db}
          step={0.5}
          value={state.chain.eq_mid_db}
          unit="dB"
          signed
          oncommit={(v) =>
            editChain((c) => {
              c.eq_mid_db = v;
            })}
        />
        <FxSlider
          label="Treble"
          min={-limits.eq_gain_limit_db}
          max={limits.eq_gain_limit_db}
          step={0.5}
          value={state.chain.eq_treble_db}
          unit="dB"
          signed
          oncommit={(v) =>
            editChain((c) => {
              c.eq_treble_db = v;
            })}
        />
      </section>

      <section>
        <h3>Compressor</h3>
        <label class="check">
          <input
            type="checkbox"
            checked={state.chain.compressor.enabled}
            onchange={(e) => {
              const on = e.currentTarget.checked;
              void editChain((c) => {
                c.compressor.enabled = on;
              });
            }}
          />
          Compressor on
        </label>
        <FxSlider
          label="Threshold"
          min={limits.compressor.threshold_db[0]}
          max={limits.compressor.threshold_db[1]}
          step={1}
          value={state.chain.compressor.threshold_db}
          unit="dB"
          disabled={!state.chain.compressor.enabled}
          oncommit={(v) =>
            editChain((c) => {
              c.compressor.threshold_db = v;
            })}
        />
        <FxSlider
          label="Ratio"
          min={limits.compressor.ratio[0]}
          max={limits.compressor.ratio[1]}
          step={0.5}
          value={state.chain.compressor.ratio}
          unit=": 1"
          disabled={!state.chain.compressor.enabled}
          oncommit={(v) =>
            editChain((c) => {
              c.compressor.ratio = v;
            })}
        />
        <FxSlider
          label="Attack"
          min={limits.compressor.attack_ms[0]}
          max={limits.compressor.attack_ms[1]}
          step={1}
          value={state.chain.compressor.attack_ms}
          unit="ms"
          disabled={!state.chain.compressor.enabled}
          oncommit={(v) =>
            editChain((c) => {
              c.compressor.attack_ms = v;
            })}
        />
        <FxSlider
          label="Release"
          min={limits.compressor.release_ms[0]}
          max={limits.compressor.release_ms[1]}
          step={5}
          value={state.chain.compressor.release_ms}
          unit="ms"
          disabled={!state.chain.compressor.enabled}
          oncommit={(v) =>
            editChain((c) => {
              c.compressor.release_ms = v;
            })}
        />
      </section>

      <section>
        <h3>Effects</h3>
        {#if state.chain.effects.length === 0}
          <p class="hint">No effects. They run in the order listed, after the compressor.</p>
        {/if}
        {#each state.chain.effects as spec, i (i)}
          {@const info = state.effects.find((e) => e.type === spec.type)}
          <div class="effect">
            <div class="effect-head">
              <strong>{info?.label ?? spec.type}</strong>
              <span class="spacer"></span>
              <button
                type="button"
                disabled={i === 0}
                onclick={() =>
                  void editChain((c) => {
                    c.effects = moveItem(c.effects, i, -1);
                  })}
              >
                Up
              </button>
              <button
                type="button"
                disabled={i === state.chain.effects.length - 1}
                onclick={() =>
                  void editChain((c) => {
                    c.effects = moveItem(c.effects, i, 1);
                  })}
              >
                Down
              </button>
              <button
                type="button"
                onclick={() =>
                  void editChain((c) => {
                    c.effects.splice(i, 1);
                  })}
              >
                Remove
              </button>
            </div>
            {#if info === undefined}
              <p class="bad">This server does not offer the effect "{spec.type}".</p>
            {:else}
              {#each info.params as param (param.name)}
                <FxSlider
                  label={param.label}
                  min={param.minimum}
                  max={param.maximum}
                  step={paramStep(param)}
                  value={spec.params[param.name] ?? param.default}
                  unit={param.unit ?? ""}
                  oncommit={(v) =>
                    editChain((c) => {
                      const target = c.effects[i];
                      if (target !== undefined) {
                        target.params[param.name] = v;
                      }
                    })}
                />
              {/each}
            {/if}
          </div>
        {/each}
        {#if state.effects.length > 0}
          <div class="row">
            <select
              value={chosenType}
              onchange={(e) => (addType = e.currentTarget.value)}
              aria-label="Effect to add"
            >
              {#each state.effects as info (info.type)}
                <option value={info.type}>{info.label}</option>
              {/each}
            </select>
            <button type="button" onclick={() => void addEffect(chosenType)}>Add effect</button>
          </div>
        {/if}
      </section>

      <section>
        <h3>Loudness</h3>
        <FxSlider
          label="Voice target"
          min={limits.loudness_min_lufs}
          max={limits.loudness_max_lufs}
          step={0.5}
          value={state.chain.loudness_target_lufs}
          unit="LUFS"
          oncommit={(v) =>
            editChain((c) => {
              c.loudness_target_lufs = v;
            })}
        />
        <p class="hint">Each take is normalised to this. Takes under about 0.4 s use a rougher estimate.</p>
        <FxSlider
          label="Game audio"
          min={limits.game_audio_min_db}
          max={limits.game_audio_max_db}
          step={0.5}
          value={state.game_audio_db}
          unit="dB"
          signed
          oncommit={setGameAudio}
        />
        <p class="hint">The recording's own sound, relative to its original level.</p>
      </section>
    {/key}
  {/if}
</div>

<style>
  .fx {
    padding-bottom: 1rem;
  }
  section {
    margin-bottom: 1.1rem;
  }
  h3 {
    margin: 0 0 0.4rem;
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }
  .status {
    margin: 0 0 0.5rem;
  }
  .presets,
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
  }
  .presets button.on {
    font-weight: 600;
    border-color: var(--text);
  }
  .check {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.5rem;
  }
  .effect {
    margin-bottom: 0.75rem;
    padding: 0.5rem 0.6rem;
    border: 1px solid var(--line);
    border-radius: 6px;
  }
  .effect-head {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    margin-bottom: 0.4rem;
  }
  .spacer {
    flex: 1;
  }
  .hint {
    margin: 0.3rem 0 0;
    font-size: 0.85rem;
  }
</style>
