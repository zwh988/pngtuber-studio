// Pure helpers for the Voice FX tab: no fetch, no DOM.

import type { EffectInfo, EffectParamInfo, FxChain, FxPreset, FxProcessing } from "./fxApi";

/** Digits after the point for a slider step (0.5 -> 1, 0.01 -> 2, 1 -> 0). */
export function decimals(step: number): number {
  const text = String(step);
  const dot = text.indexOf(".");
  return dot < 0 ? 0 : text.length - dot - 1;
}

/** Round to the step's precision so float noise (0.30000000000000004) is not sent. */
export function roundTo(value: number, step: number): number {
  return Number(value.toFixed(decimals(step)));
}

/** A slider step for an effect parameter, from its kind and range. */
export function paramStep(param: EffectParamInfo): number {
  if (param.kind === "int") {
    return 1;
  }
  const range = param.maximum - param.minimum;
  if (range <= 2) {
    return 0.01;
  }
  return range <= 20 ? 0.1 : 1;
}

/** Every parameter at its default, for a newly added effect. */
export function defaultParams(info: EffectInfo): Record<string, number> {
  const params: Record<string, number> = {};
  for (const param of info.params) {
    params[param.name] = param.default;
  }
  return params;
}

/** A copy of the list with the item at `index` moved by `delta` (no change at the ends). */
export function moveItem<T>(list: readonly T[], index: number, delta: number): T[] {
  const target = index + delta;
  const copy = [...list];
  if (index < 0 || index >= copy.length || target < 0 || target >= copy.length) {
    return copy;
  }
  const [item] = copy.splice(index, 1);
  copy.splice(target, 0, item as T);
  return copy;
}

/** A stable text form (object keys sorted) so two equal chains compare equal. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonical).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}

export function sameChain(a: FxChain, b: FxChain): boolean {
  return canonical(a) === canonical(b);
}

/** The name of the preset the chain equals exactly, or null when it is customised. */
export function matchingPreset(chain: FxChain, presets: readonly FxPreset[]): string | null {
  return presets.find((preset) => sameChain(preset.chain, chain))?.name ?? null;
}

/** The "processing N of M" line under the tab heading. */
export function processingText(processing: FxProcessing): string {
  if (processing.error !== null) {
    return `Processing stopped: ${processing.error}`;
  }
  if (processing.total === 0) {
    return "No placed lines to process yet.";
  }
  if (processing.ready >= processing.total) {
    return processing.total === 1
      ? "The placed take is processed."
      : `All ${processing.total} placed takes are processed.`;
  }
  return `Processing ${processing.ready} of ${processing.total}`;
}
