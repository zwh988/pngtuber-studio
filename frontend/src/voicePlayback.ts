import { processedTakeUrl } from "./api";
import type { AudioGraph } from "./audioGraph";

/**
 * The part of a timeline placement that voice playback needs. `TimelineState.placements`
 * items fit this shape. Times are timeline ms, computed by the backend from the anchor.
 */
export interface PlayablePlacement {
  id: string;
  take_id: string | null;
  start_ms: number | null;
  duration_ms: number | null;
  orphaned: boolean;
  /** Speed-up of the audio (1 or missing: as recorded). `duration_ms` is the length that plays. */
  stretch?: number;
}

/** One take to start: `delayMs` after "now", `offsetMs` into the take's audio. */
export interface VoiceStart {
  placementId: string;
  takeId: string;
  delayMs: number;
  offsetMs: number;
}

/**
 * Which placed takes sound from timeline time `fromMs` on, and when each one starts.
 * A block that began before `fromMs` and is still running starts at once, part way in.
 * Skipped: orphaned blocks, blocks without a start or a take, and blocks already over.
 * Voice always plays at 1x (a clip's speed does not change it), so `duration_ms` is real length.
 * Overlapping blocks are all returned; the audio is mixed (CLAUDE.md rule 10).
 */
export function planVoices(placements: PlayablePlacement[], fromMs: number): VoiceStart[] {
  const starts: VoiceStart[] = [];
  for (const p of placements) {
    if (p.orphaned || p.take_id === null || p.start_ms === null || p.duration_ms === null) {
      continue;
    }
    const endMs = p.start_ms + p.duration_ms;
    if (endMs <= fromMs) {
      continue;
    }
    const ahead = p.start_ms - fromMs;
    starts.push({
      placementId: p.id,
      takeId: p.take_id,
      delayMs: Math.max(ahead, 0),
      offsetMs: Math.max(-ahead, 0),
    });
  }
  return starts.sort((a, b) => a.delayMs - b.delayMs || a.placementId.localeCompare(b.placementId));
}

/**
 * Cache key of one decoded audio file: the take, the stretch, and the voice chain version
 * (`fx_version`). A chain edit changes the version, so the old audio is never played again.
 */
function bufferKey(takeId: string, stretch: number, fxVersion: string): string {
  return `${takeId}@${stretch}@${fxVersion}`;
}

/** How far the voice clock may drift from the player's playhead before it is restarted. */
export const DRIFT_MS = 120;

/**
 * Plays the placed takes (the processed audio of the voice chain) through the shared audio
 * graph's voice bus, in time with the video.
 *
 * Each (take, stretch, fx_version) is fetched from `/media/take/{id}?processed=1...` and decoded
 * once and kept while a placement still needs it. `setFxVersion` drops everything decoded when
 * the chain changes. `start(ms)` schedules every take that still sounds from that timeline time;
 * the schedule runs on the audio clock. The editor calls `sync(ms)` with the player's playhead
 * while it plays, and any drift beyond `DRIFT_MS` restarts the schedule at the playhead.
 * `stop()` silences everything. The audio context belongs to the graph, not to this class.
 */
export class VoicePlayback {
  private readonly graph: AudioGraph;
  /** Decoded audio, keyed by take id, stretch and fx_version. */
  private readonly buffers = new Map<string, AudioBuffer>();
  private readonly loading = new Set<string>();
  private readonly failed = new Set<string>();
  private placements: PlayablePlacement[] = [];
  private fxVersion = "";
  private nodes: AudioBufferSourceNode[] = [];
  private baseCtxSec = 0;
  private baseMs = 0;
  private active = false;
  private disposed = false;
  private readonly onError: (message: string) => void;

  constructor(onError: (message: string) => void, graph: AudioGraph) {
    this.onError = onError;
    this.graph = graph;
  }

  /** True between `start` and `stop`. */
  get running(): boolean {
    return this.active;
  }

  /** Timeline time (ms) the voice clock is at now; only meaningful while running. */
  now(): number {
    const ctx = this.graph.contextIfBuilt;
    return ctx === null ? this.baseMs : this.baseMs + (ctx.currentTime - this.baseCtxSec) * 1000;
  }

  /** New placement list (after any edit or undo): load the takes, and re-plan if playing. */
  setPlacements(placements: PlayablePlacement[]): void {
    this.placements = placements;
    this.prune();
    this.loadAll();
    if (this.active) {
      this.start(this.now());
    }
  }

  /**
   * The voice chain changed (`TimelineState.fx_version`): drop all decoded audio and load the
   * placed takes again from the new processed files. "" (not known yet) and "invalid" (the chain
   * cannot be used) load nothing.
   */
  setFxVersion(version: string): void {
    if (version === this.fxVersion) {
      return;
    }
    this.fxVersion = version;
    this.buffers.clear();
    this.failed.clear();
    this.loadAll();
    if (this.active) {
      this.start(this.now());
    }
  }

  /** Start sounding from timeline time `timelineMs` (replaces any running schedule). */
  start(timelineMs: number): void {
    const ctx = this.graph.context;
    this.silence();
    this.active = true;
    this.graph.resume();
    this.baseCtxSec = ctx.currentTime;
    this.baseMs = timelineMs;
    const byId = new Map(this.placements.map((p) => [p.id, p]));
    for (const item of planVoices(this.placements, timelineMs)) {
      const stretch = byId.get(item.placementId)?.stretch ?? 1;
      const buffer = this.buffers.get(bufferKey(item.takeId, stretch, this.fxVersion));
      if (buffer === undefined) {
        continue; // still decoding: `load` re-plans when it lands
      }
      if (item.offsetMs / 1000 >= buffer.duration) {
        continue;
      }
      const node = ctx.createBufferSource();
      node.buffer = buffer;
      node.connect(this.graph.voiceInput);
      node.start(this.baseCtxSec + item.delayMs / 1000, item.offsetMs / 1000);
      this.nodes.push(node);
    }
  }

  /** Called with the player's playhead while it plays: restart when the clocks have drifted. */
  sync(playheadMs: number): void {
    if (this.active && Math.abs(this.now() - playheadMs) > DRIFT_MS) {
      this.start(playheadMs);
    }
  }

  stop(): void {
    this.silence();
    this.active = false;
  }

  /** Silence and forget the decoded audio. The graph (and its context) is closed by its owner. */
  dispose(): void {
    this.disposed = true;
    this.stop();
    this.buffers.clear();
    this.loading.clear();
    this.failed.clear();
  }

  private silence(): void {
    for (const node of this.nodes) {
      try {
        node.stop();
      } catch {
        // already ended
      }
      node.disconnect();
    }
    this.nodes = [];
  }

  /** Keys of the audio the current placements need at the current chain version. */
  private wantedKeys(): Set<string> {
    const wanted = new Set<string>();
    for (const p of this.placements) {
      if (p.take_id !== null && !p.orphaned) {
        wanted.add(bufferKey(p.take_id, p.stretch ?? 1, this.fxVersion));
      }
    }
    return wanted;
  }

  /** Drop decoded audio no placement uses any more (an old stretch, a removed line). */
  private prune(): void {
    const wanted = this.wantedKeys();
    for (const key of [...this.buffers.keys()]) {
      if (!wanted.has(key)) {
        this.buffers.delete(key);
      }
    }
    for (const key of [...this.failed]) {
      if (!wanted.has(key)) {
        this.failed.delete(key);
      }
    }
  }

  private loadAll(): void {
    if (this.fxVersion === "" || this.fxVersion === "invalid") {
      return;
    }
    for (const p of this.placements) {
      if (p.take_id !== null && !p.orphaned) {
        void this.load(p.take_id, p.stretch ?? 1);
      }
    }
  }

  /** Fetch and decode one processed take (once). A take that fails is reported once and left silent. */
  private async load(takeId: string, stretch: number): Promise<void> {
    const version = this.fxVersion;
    const key = bufferKey(takeId, stretch, version);
    if (this.buffers.has(key) || this.loading.has(key) || this.failed.has(key)) {
      return;
    }
    this.loading.add(key);
    try {
      const response = await fetch(processedTakeUrl(takeId, stretch, version));
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.arrayBuffer();
      if (this.disposed) {
        return;
      }
      const buffer = await this.graph.context.decodeAudioData(data);
      if (version !== this.fxVersion) {
        return; // the chain changed while this was loading: the result is stale
      }
      this.buffers.set(key, buffer);
      if (this.active) {
        this.start(this.now()); // a take that was still decoding can sound now
      }
    } catch (err) {
      if (version !== this.fxVersion) {
        return;
      }
      this.failed.add(key);
      const reason = err instanceof Error ? err.message : String(err);
      this.onError(`A placed take could not be loaded for playback (${reason}).`);
    } finally {
      this.loading.delete(key);
    }
  }
}
