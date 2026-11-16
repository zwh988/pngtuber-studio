<script lang="ts">
  import { onMount } from "svelte";
  import {
    getAvatar,
    type AvatarSettings,
    type EditOp,
    type TimelineKeyframe,
    type TimelineReaction,
  } from "./api";
  import { LANE_INFO, REACTION_TYPES, laneInfo, laneLabel, reactionLabel } from "./avatarLanes";
  import { clock } from "./format";
  import FxSlider from "./FxSlider.svelte";

  /**
   * Avatar tab (M5 S11): the base motion and placement (used wherever a lane has no keys),
   * the tools behind the E and R hotkeys, and an inspector for the selected key or reaction.
   * Every change is one labelled batch on the shared undo stack.
   */
  let {
    avatar,
    keyframes,
    reactions,
    playheadMs,
    busy,
    selectedKeyId = $bindable(null),
    selectedReactionId = $bindable(null),
    oncommit,
  }: {
    avatar: AvatarSettings;
    keyframes: TimelineKeyframe[];
    reactions: TimelineReaction[];
    playheadMs: number;
    busy: boolean;
    selectedKeyId?: string | null;
    selectedReactionId?: string | null;
    oncommit: (label: string, ops: EditOp[]) => Promise<boolean>;
  } = $props();

  let expressions = $state<string[]>([]);
  let defaultExpression = $state<string | null>(null);
  let artProblem = $state<string | null>(null);
  let keyExpression = $state<string>("");
  let reactionType = $state<string>("hop");
  let reactionIntensity = $state(1);
  let reactionDuration = $state(500);

  const selectedKey = $derived(keyframes.find((k) => k.id === selectedKeyId) ?? null);
  const selectedReaction = $derived(reactions.find((r) => r.id === selectedReactionId) ?? null);
  const at = $derived(Math.round(playheadMs));

  onMount(() => {
    void (async () => {
      try {
        const state = await getAvatar();
        expressions = state.expressions.map((e) => e.id);
        defaultExpression = state.default_expression;
        keyExpression = state.default_expression ?? expressions[0] ?? "";
        artProblem =
          state.status === "ready" ? null : "No usable avatar art: choose the art folder on the project screen.";
      } catch (err) {
        artProblem = err instanceof Error ? err.message : String(err);
      }
    })();
  });

  async function setting(name: string, value: number | boolean): Promise<void> {
    await oncommit("Change avatar settings", [{ op: "set_avatar_settings", [name]: value } as EditOp]);
  }

  /** E: an expression key at the playhead (changes the one already there). */
  export async function addExpressionKey(): Promise<void> {
    if (keyExpression === "") return;
    await oncommit("Add expression key", [
      { op: "key_lane", lane_id: "expression", timeline_ms: at, value: keyExpression },
    ]);
  }

  /** R: a reaction at the playhead with the type, intensity and length chosen here. */
  export async function dropReaction(): Promise<void> {
    await oncommit("Add reaction", [
      {
        op: "add_reaction",
        type: reactionType,
        timeline_ms: at,
        intensity: reactionIntensity,
        duration_ms: Math.round(reactionDuration),
      },
    ]);
  }

  /** Delete: remove the selected key or reaction; false when neither is selected. */
  export async function deleteSelected(): Promise<boolean> {
    if (selectedKey !== null) {
      const id = selectedKey.id;
      if (await oncommit("Remove key", [{ op: "remove_keyframe", keyframe_id: id }])) selectedKeyId = null;
      return true;
    }
    if (selectedReaction !== null) {
      const id = selectedReaction.id;
      if (await oncommit("Remove reaction", [{ op: "remove_reaction", reaction_id: id }])) {
        selectedReactionId = null;
      }
      return true;
    }
    return false;
  }

  /** Key a motion lane at the playhead with the value it already has there. */
  async function keyHere(laneId: string): Promise<void> {
    await oncommit(`Key ${laneLabel(laneId)}`, [{ op: "key_lane_by", lane_id: laneId, timeline_ms: at }]);
    const key = keyframes.find((k) => k.lane_id === laneId && k.t_ms === at);
    if (key !== undefined) {
      selectedKeyId = key.id;
      selectedReactionId = null;
    }
  }

  function settingValue(name: string): number {
    const value = (avatar as unknown as Record<string, unknown>)[name];
    return typeof value === "number" ? value : 0;
  }

  function when(t: number | null, orphaned: boolean): string {
    if (orphaned) return "orphaned (its footage was cut away; move it to settle it)";
    return t === null ? "not on the timeline" : clock(t);
  }
</script>

<div class="panel">
  {#if artProblem !== null}<p class="warn">{artProblem}</p>{/if}

  <section>
    <h4>Selected</h4>
    {#if selectedKey !== null}
      {@const key = selectedKey}
      <p><strong>{laneLabel(key.lane_id)} key</strong> at {when(key.t_ms, key.orphaned)}</p>
      {#if key.lane_id === "expression"}
        <label>
          Expression
          <select
            value={String(key.value)}
            disabled={busy}
            onchange={(e) =>
              void oncommit("Change key", [
                { op: "set_keyframe_value", keyframe_id: key.id, value: e.currentTarget.value },
              ])}
          >
            {#if !expressions.includes(String(key.value))}
              <option value={String(key.value)}>{key.value} (not in the art)</option>
            {/if}
            {#each expressions as name (name)}<option value={name}>{name}</option>{/each}
          </select>
        </label>
      {:else}
        {@const info = laneInfo(key.lane_id)}
        {#if info !== undefined}
          <FxSlider
            label={info.label}
            min={info.min}
            max={info.max}
            step={info.step}
            unit={info.unit ?? ""}
            value={Number(key.value)}
            disabled={busy}
            oncommit={async (v) => {
              await oncommit("Change key", [{ op: "set_keyframe_value", keyframe_id: key.id, value: v }]);
            }}
          />
        {/if}
        <label>
          Easing to the next key
          <select
            value={key.interpolation}
            disabled={busy}
            onchange={(e) =>
              void oncommit("Change key easing", [
                {
                  op: "set_keyframe_interpolation",
                  keyframe_id: key.id,
                  interpolation: e.currentTarget.value as "hold" | "smooth",
                },
              ])}
          >
            <option value="smooth">Smooth</option>
            <option value="hold">Hold (jump at the next key)</option>
          </select>
        </label>
      {/if}
      <div class="row">
        <button
          type="button"
          disabled={busy}
          onclick={() => void oncommit("Move key", [{ op: "move_keyframe", keyframe_id: key.id, timeline_ms: at }])}
        >
          Move to playhead
        </button>
        <button type="button" disabled={busy} onclick={() => void deleteSelected()}>Delete</button>
      </div>
    {:else if selectedReaction !== null}
      {@const r = selectedReaction}
      <p><strong>{reactionLabel(r.type)}</strong> at {when(r.t_ms, r.orphaned)}</p>
      <label>
        Type
        <select
          value={r.type}
          disabled={busy}
          onchange={(e) =>
            void oncommit("Change reaction", [
              { op: "set_reaction", reaction_id: r.id, type: e.currentTarget.value },
            ])}
        >
          {#each REACTION_TYPES as type (type)}<option value={type}>{reactionLabel(type)}</option>{/each}
        </select>
      </label>
      <FxSlider
        label="Intensity"
        min={0}
        max={3}
        step={0.05}
        value={r.intensity}
        disabled={busy}
        oncommit={async (v) => {
          await oncommit("Change reaction", [{ op: "set_reaction", reaction_id: r.id, intensity: v }]);
        }}
      />
      <FxSlider
        label="Length"
        min={100}
        max={3000}
        step={50}
        unit="ms"
        value={r.duration_ms}
        disabled={busy}
        oncommit={async (v) => {
          await oncommit("Change reaction", [
            { op: "set_reaction", reaction_id: r.id, duration_ms: Math.round(v) },
          ]);
        }}
      />
      <div class="row">
        <button
          type="button"
          disabled={busy}
          onclick={() =>
            void oncommit("Move reaction", [{ op: "move_reaction", reaction_id: r.id, timeline_ms: at }])}
        >
          Move to playhead
        </button>
        <button type="button" disabled={busy} onclick={() => void deleteSelected()}>Delete</button>
      </div>
    {:else}
      <p class="hint">Click a key or reaction in the timeline's avatar rows to edit it here.</p>
    {/if}
  </section>

  <section>
    <h4>At the playhead ({clock(at)})</h4>
    <div class="row">
      <label class="inline">
        Expression
        <select bind:value={keyExpression} disabled={expressions.length === 0}>
          {#each expressions as name (name)}
            <option value={name}>{name}{name === defaultExpression ? " (default)" : ""}</option>
          {/each}
        </select>
      </label>
      <button type="button" disabled={busy || keyExpression === ""} onclick={() => void addExpressionKey()}>
        Add expression key (E)
      </button>
    </div>
    <div class="row">
      <label class="inline">
        Reaction
        <select bind:value={reactionType}>
          {#each REACTION_TYPES as type (type)}<option value={type}>{reactionLabel(type)}</option>{/each}
        </select>
      </label>
      <label class="inline">
        Intensity
        <input type="number" min="0" max="3" step="0.1" bind:value={reactionIntensity} />
      </label>
      <label class="inline">
        Length (ms)
        <input type="number" min="100" max="10000" step="50" bind:value={reactionDuration} />
      </label>
      <button type="button" disabled={busy} onclick={() => void dropReaction()}>Drop reaction (R)</button>
    </div>
  </section>

  <section>
    <h4>Base motion and placement</h4>
    <p class="hint">
      Used wherever a lane has no keys. ◆ keys the lane at the playhead so it can change over time
      (open "▸ Lanes" in the timeline to see every lane).
    </p>
    {#each LANE_INFO as info (info.id)}
      <div class="lane">
        <FxSlider
          label={info.label}
          min={info.min}
          max={info.max}
          step={info.step}
          unit={info.unit ?? ""}
          value={settingValue(info.setting)}
          disabled={busy}
          oncommit={(v) => setting(info.setting, v)}
        />
        <button
          type="button"
          class="key"
          title="Key {info.label} at the playhead"
          disabled={busy}
          onclick={() => void keyHere(info.id)}>◆</button
        >
      </div>
    {/each}
    <div class="lane">
      <FxSlider
        label="Float direction"
        min={-180}
        max={180}
        step={5}
        unit="°"
        value={avatar.float_angle_deg}
        disabled={busy}
        oncommit={(v) => setting("float_angle_deg", v)}
      />
    </div>
    <p class="hint">Float direction: 0° drifts up and down, 90° side to side, 45° diagonally.</p>
    <label class="check">
      <input
        type="checkbox"
        checked={avatar.auto_key_expression}
        disabled={busy}
        onchange={(e) => void setting("auto_key_expression", e.currentTarget.checked)}
      />
      Auto-key the expression from each placed line's emotion (only where the art has a matching
      expression, or avatar.json maps it)
    </label>
  </section>
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  section {
    border-bottom: 1px solid #8884;
    padding-bottom: 0.5rem;
  }
  h4 {
    margin: 0.4rem 0;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 0.5rem;
    margin: 0.35rem 0;
  }
  label {
    display: block;
    margin: 0.3rem 0;
  }
  label.inline {
    display: inline-block;
    margin: 0;
  }
  label.inline input {
    width: 5rem;
  }
  select {
    display: block;
    margin-top: 0.15rem;
  }
  .lane {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }
  .lane :global(> :first-child) {
    flex: 1;
  }
  .key {
    padding: 0.1rem 0.4rem;
  }
  .check {
    display: flex;
    gap: 0.4rem;
    align-items: start;
  }
  .hint {
    font-size: 0.85rem;
    opacity: 0.7;
    margin: 0.2rem 0;
  }
  .warn {
    color: #d9a441;
  }
</style>
