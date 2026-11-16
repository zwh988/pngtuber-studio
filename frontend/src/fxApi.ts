// Voice FX endpoints (M4 S4). Shapes are listed in docs/API_MODELS.md, "Voice chain".
// Kept apart from api.ts so that file stays unchanged; the helper below is the same pattern.

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // keep the HTTP status message
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export interface CompressorSettings {
  enabled: boolean;
  threshold_db: number;
  ratio: number;
  attack_ms: number;
  release_ms: number;
}

export interface EffectSpec {
  type: string;
  /** A parameter left out takes its default. */
  params: Record<string, number>;
}

export interface FxChain {
  eq_bass_db: number;
  eq_mid_db: number;
  eq_treble_db: number;
  compressor: CompressorSettings;
  effects: EffectSpec[];
  loudness_target_lufs: number;
}

export interface FxPreset {
  name: string;
  chain: FxChain;
}

export interface EffectParamInfo {
  name: string;
  label: string;
  kind: "float" | "int";
  default: number;
  minimum: number;
  maximum: number;
  unit: string | null;
}

export interface EffectInfo {
  type: string;
  label: string;
  params: EffectParamInfo[];
}

export interface FxLimits {
  eq_gain_limit_db: number;
  compressor: {
    threshold_db: [number, number];
    ratio: [number, number];
    attack_ms: [number, number];
    release_ms: [number, number];
  };
  loudness_min_lufs: number;
  loudness_max_lufs: number;
  game_audio_min_db: number;
  game_audio_max_db: number;
}

export interface FxProcessing {
  total: number;
  ready: number;
  /** The first render problem since the last change; stop waiting when set. */
  error: string | null;
}

export interface FxState {
  chain: FxChain;
  /** 8 hex characters; "invalid" when the chain cannot be used. */
  fx_version: string;
  problem: string | null;
  game_audio_db: number;
  presets: FxPreset[];
  effects: EffectInfo[];
  limits: FxLimits;
  processing: FxProcessing;
  can_undo: boolean;
  can_redo: boolean;
  undo_label: string | null;
  redo_label: string | null;
  save_error: string | null;
}

export type FxEditOp =
  | { op: "set_fx_chain"; chain: FxChain }
  | { op: "set_game_audio_db"; db: number };

export function getFx(): Promise<FxState> {
  return call<FxState>("/api/fx");
}

/** One op without a label is one undo step; several ops or a label are one group. */
export function editFx(ops: FxEditOp[], label?: string): Promise<FxState> {
  return call<FxState>("/api/fx/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ops, label }),
  });
}

/** A take through the open project's chain (rendered on the first request, no GPU). */
export function processedTakeUrl(
  takeId: string,
  stretch: number,
  version: string,
  trim = "",
): string {
  const base = `/media/take/${encodeURIComponent(takeId)}`;
  const t = trim === "" ? "" : `&t=${encodeURIComponent(trim)}`;
  return `${base}?processed=1&stretch=${stretch}&v=${encodeURIComponent(version)}${t}`;
}
