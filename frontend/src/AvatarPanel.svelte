<script lang="ts">
  import { onMount } from "svelte";
  import {
    getAvatar,
    type AvatarSettings,
    type EditOp,
    type Interpolation,
    type TimelineKeyframe,
    type TimelineReaction,
  } from "./api";
  import { LANE_INFO, REACTION_TYPES, laneInfo, laneLabel, reactionLabel } from "./avatarLanes";
  import { clock } from "./format";
  import FxSlider from "./FxSlider.svelte";
  import { Diamond, LocateFixed, Trash2, Zap } from "@lucide/svelte";
  import Banner from "./ui/Banner.svelte";
  import Button from "./ui/Button.svelte";
  import IconButton from "./ui/IconButton.svelte";
  import Section from "./ui/Section.svelte";

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
  {#if artProblem !== null}<Banner kind="warning">{artProblem}</Banner>{/if}

  <Section title="Selected" collapsible={false}>
    {#if selectedKey !== null}
      {@const key = selectedKey}
      <p class="what"><strong>{laneLabel(key.lane_id)} key</strong> at <span class="num">{when(key.t_ms, key.orphaned)}</span></p>
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
                  interpolation: e.currentTarget.value as Interpolation,
                },
              ])}
          >
            <option value="ease_in_out">Ease in and out</option>
            <option value="ease_in">Ease in (starts slow)</option>
            <option value="ease_out">Ease out (ends slow)</option>
            <option value="linear">Linear</option>
            <option value="hold">Hold (jump at the next key)</option>
          </select>
        </label>
        {#if key.interpolation !== "hold" && key.interpolation !== "linear"}
          <FxSlider
            label="Ease strength"
            min={0}
            max={2}
            step={0.05}
            value={key.ease_strength}
            disabled={busy}
            oncommit={async (v) => {
              await oncommit("Change key easing", [
                { op: "set_keyframe_interpolation", keyframe_id: key.id, ease_strength: v },
              ]);
            }}
          />
          <p class="hint">0 is linear, 1 normal, 2 strong.</p>
        {/if}
      {/if}
      <div class="row">
        <Button
          size="sm"
          icon={LocateFixed}
          disabled={busy}
          onclick={() => void oncommit("Move key", [{ op: "move_keyframe", keyframe_id: key.id, timeline_ms: at }])}
        >
          Move to playhead
        </Button>
        <Button size="sm" variant="danger" icon={Trash2} disabled={busy} onclick={() => void deleteSelected()}>
          Delete
        </Button>
      </div>
    {:else if selectedReaction !== null}
      {@const r = selectedReaction}
      <p class="what"><strong>{reactionLabel(r.type)}</strong> at <span class="num">{when(r.t_ms, r.orphaned)}</span></p>
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
        <Button
          size="sm"
          icon={LocateFixed}
          disabled={busy}
          onclick={() =>
            void oncommit("Move reaction", [{ op: "move_reaction", reaction_id: r.id, timeline_ms: at }])}
        >
          Move to playhead
        </Button>
        <Button size="sm" variant="danger" icon={Trash2} disabled={busy} onclick={() => void deleteSelected()}>
          Delete
        </Button>
      </div>
    {:else}
      <p class="hint">Click a key or reaction in the timeline's avatar rows to edit it here.</p>
    {/if}
  </Section>

  <Section title={`At the playhead · ${clock(at)}`} collapsible={false}>
    <div class="row">
      <label class="inline">
        Expression
        <select bind:value={keyExpression} disabled={expressions.length === 0}>
          {#each expressions as name (name)}
            <option value={name}>{name}{name === defaultExpression ? " (default)" : ""}</option>
          {/each}
        </select>
      </label>
      <Button icon={Diamond} disabled={busy || keyExpression === ""} onclick={() => void addExpressionKey()}>
        Add expression key <span class="kbd">E</span>
      </Button>
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
      <Button icon={Zap} disabled={busy} onclick={() => void dropReaction()}>
        Drop reaction <span class="kbd">R</span>
      </Button>
    </div>
  </Section>

  <Section title="Base motion and placement">
    <p class="hint">
      Used wherever a lane has no keys. The diamond button keys the lane at the playhead so it can
      change over time (open the lanes in the timeline to see every lane).
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
        <IconButton
          icon={Diamond}
          size="sm"
          variant="secondary"
          label={`Key ${info.label} at the playhead`}
          disabled={busy}
          onclick={() => void keyHere(info.id)}
        />
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
  </Section>
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .what {
    margin: 0;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 8px;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: var(--text-2);
    font-size: var(--fs-sm);
  }
  label.inline input {
    width: 5rem;
  }
  select {
    min-width: 8rem;
  }
  .lane {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .lane :global(> :first-child) {
    flex: 1;
  }
  .check {
    flex-direction: row;
    align-items: flex-start;
    gap: 8px;
    font-size: var(--fs-md);
  }
  .check input {
    margin: 2px 0 0;
  }
  .hint {
    margin: 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
