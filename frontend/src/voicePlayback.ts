import { takeMediaUrl } from "./api";

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

/** Cache key of one decoded audio file: the take, and the stretch it was sped up by. */
function bufferKey(takeId: string, stretch: number): string {
  return `${takeId}@${stretch}`;
}

/** How far the voice clock may drift from the player's playhead before it is restarted. */
export const DRIFT_MS = 120;

/**
 * Plays the placed takes through Web Audio, in time with the video.
 *
 * Takes are fetched and decoded once (they never change; keyed by take id) and kept.
 * `start(ms)` schedules every take that still sounds from that timeline time; the schedule
 * runs on the audio clock. The editor calls `sync(ms)` with the player's playhead while it plays,
 * and any drift beyond `DRIFT_MS` (a source swap hitch, a slow seek) restarts the schedule at the
 * playhead. `stop()` silences everything.
 */
export class VoicePlayback {
  private ctx: AudioContext | null = null;
  /** Decoded audio, keyed by take id and stretch (a stretched copy is a different file). */
  private readonly buffers = new Map<string, AudioBuffer>();
  private readonly loading = new Set<string>();
  private readonly failed = new Set<string>();
  private placements: PlayablePlacement[] = [];
  private nodes: AudioBufferSourceNode[] = [];
  private baseCtxSec = 0;
  private baseMs = 0;
  private active = false;
  private readonly onError: (message: string) => void;

  constructor(onError: (message: string) => void) {
    this.onError = onError;
  }

  /** True between `start` and `stop`. */
  get running(): boolean {
    return this.active;
  }

  /** Timeline time (ms) the voice clock is at now; only meaningful while running. */
  now(): number {
    return this.ctx === null ? this.baseMs : this.baseMs + (this.ctx.currentTime - this.baseCtxSec) * 1000;
  }

  /** New placement list (after any edit or undo): load the takes, and re-plan if playing. */
  setPlacements(placements: PlayablePlacement[]): void {
    this.placements = placements;
    for (const p of placements) {
      if (p.take_id !== null && !p.orphaned) {
        void this.load(p.take_id, p.stretch ?? 1);
      }
    }
    if (this.active) {
      this.start(this.now());
    }
  }

  /** Start sounding from timeline time `timelineMs` (replaces any running schedule). */
  start(timelineMs: number): void {
    const ctx = this.context();
    this.silence();
    this.active = true;
    if (ctx.state !== "running") {
      void ctx.resume().catch(() => undefined);
    }
    this.baseCtxSec = ctx.currentTime;
    this.baseMs = timelineMs;
    const byId = new Map(this.placements.map((p) => [p.id, p]));
    for (const item of planVoices(this.placements, timelineMs)) {
      const stretch = byId.get(item.placementId)?.stretch ?? 1;
      const buffer = this.buffers.get(bufferKey(item.takeId, stretch));
      if (buffer === undefined) {
        continue; // still decoding: `load` re-plans when it lands
      }
      if (item.offsetMs / 1000 >= buffer.duration) {
        continue;
      }
      const node = ctx.createBufferSource();
      node.buffer = buffer;
      node.connect(ctx.destination);
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

  dispose(): void {
    this.stop();
    const ctx = this.ctx;
    this.ctx = null;
    if (ctx !== null) {
      void ctx.close().catch(() => undefined);
    }
  }

  private context(): AudioContext {
    if (this.ctx === null) {
      this.ctx = new AudioContext();
    }
    return this.ctx;
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

  /** Fetch and decode one take (once). A take that fails is reported once and left silent. */
  private async load(takeId: string, stretch: number): Promise<void> {
    const key = bufferKey(takeId, stretch);
    if (this.buffers.has(key) || this.loading.has(key) || this.failed.has(key)) {
      return;
    }
    this.loading.add(key);
    try {
      const response = await fetch(takeMediaUrl(takeId, stretch));
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.arrayBuffer();
      const buffer = await this.context().decodeAudioData(data);
      this.buffers.set(key, buffer);
      if (this.active) {
        this.start(this.now()); // a take that was still decoding can sound now
      }
    } catch (err) {
      this.failed.add(key);
      const reason = err instanceof Error ? err.message : String(err);
      this.onError(`A placed take could not be loaded for playback (${reason}).`);
    } finally {
      this.loading.delete(key);
    }
  }
}
