import type { AudioLane, TimelineAudioClip } from "./api";
import { audioClipSource } from "./api";
import type { AudioGraph } from "./audioGraph";
import { gainAt, planClips } from "./audioMix";
import { DRIFT_MS } from "./voicePlayback";

/**
 * Plays the music and sound-effect clips of the audio lanes (M8-1) through the shared audio
 * graph's music bus, in time with the video, the same way `VoicePlayback` plays the voice.
 *
 * Each imported file's decoded WAV (`/media/audio/{id}`, the file the export reads too) is
 * fetched and decoded once; a clip with FX (M8-4) plays its rendered file instead
 * (`/media/audioclip/{id}`, one per file and chain, the file the export mixes). `start(ms)` schedules every clip still sounding from that timeline
 * time, each through its own gain node carrying the clip's level and linear fades
 * (`audioMix.ts`). `sync(ms)` restarts the schedule when it drifts past DRIFT_MS from the
 * player's playhead. A change of clips or lanes (an edit, mute, solo, undo) re-plans while playing.
 */
export class AudioClipPlayback {
  private readonly graph: AudioGraph;
  private readonly buffers = new Map<string, AudioBuffer>();
  private readonly loading = new Set<string>();
  private readonly failed = new Set<string>();
  private clips: TimelineAudioClip[] = [];
  /** Buffer key of each clip (its file, or its file through its FX). */
  private sourceOf = new Map<string, string>();
  private lanes: AudioLane[] = [];
  private nodes: { source: AudioBufferSourceNode; gain: GainNode }[] = [];
  private baseCtxSec = 0;
  private baseMs = 0;
  private active = false;
  private disposed = false;
  private readonly onError: (message: string) => void;

  constructor(onError: (message: string) => void, graph: AudioGraph) {
    this.onError = onError;
    this.graph = graph;
  }

  get running(): boolean {
    return this.active;
  }

  now(): number {
    const ctx = this.graph.contextIfBuilt;
    return ctx === null ? this.baseMs : this.baseMs + (ctx.currentTime - this.baseCtxSec) * 1000;
  }

  /** New clips and lanes (after any edit or undo): load new files, re-plan if playing. */
  setClips(clips: TimelineAudioClip[], lanes: AudioLane[]): void {
    this.clips = clips;
    this.lanes = lanes;
    const sources = new Map(clips.map((c) => [c.id, audioClipSource(c)]));
    this.sourceOf = new Map([...sources].map(([id, s]) => [id, s.key]));
    const wanted = new Map([...sources.values()].map((s) => [s.key, s.url]));
    for (const key of [...this.buffers.keys()]) {
      if (!wanted.has(key)) this.buffers.delete(key);
    }
    for (const [key, url] of wanted) {
      void this.load(key, url);
    }
    if (this.active) {
      this.start(this.now());
    }
  }

  start(timelineMs: number): void {
    const ctx = this.graph.context;
    this.silence();
    this.active = true;
    this.graph.resume();
    this.baseCtxSec = ctx.currentTime;
    this.baseMs = timelineMs;
    for (const item of planClips(this.clips, this.lanes, timelineMs)) {
      const buffer = this.buffers.get(this.sourceOf.get(item.clipId) ?? item.fileId);
      if (buffer === undefined) {
        continue; // still decoding: `load` re-plans when it lands
      }
      const fileOffsetSec = (item.inMs + item.offsetMs) / 1000;
      if (fileOffsetSec >= buffer.duration) {
        continue;
      }
      const startSec = this.baseCtxSec + item.delayMs / 1000;
      const gain = ctx.createGain();
      // Level automation from where this clip starts sounding (part way in when it already runs).
      gain.gain.setValueAtTime(gainAt(item.points, item.offsetMs), startSec);
      for (const [ms, value] of item.points) {
        if (ms > item.offsetMs) {
          gain.gain.linearRampToValueAtTime(value, startSec + (ms - item.offsetMs) / 1000);
        }
      }
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(gain);
      gain.connect(this.graph.musicInput);
      source.start(startSec, fileOffsetSec, item.durationMs / 1000);
      this.nodes.push({ source, gain });
    }
  }

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
    this.disposed = true;
    this.stop();
    this.buffers.clear();
    this.loading.clear();
    this.failed.clear();
  }

  private silence(): void {
    for (const { source, gain } of this.nodes) {
      try {
        source.stop();
      } catch {
        // already ended
      }
      source.disconnect();
      gain.disconnect();
    }
    this.nodes = [];
  }

  /** Fetch and decode one file (once). A file that fails is reported once and left silent. */
  private async load(fileId: string, url: string): Promise<void> {
    if (this.buffers.has(fileId) || this.loading.has(fileId) || this.failed.has(fileId)) {
      return;
    }
    this.loading.add(fileId);
    try {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.arrayBuffer();
      if (this.disposed) {
        return;
      }
      const buffer = await this.graph.context.decodeAudioData(data);
      this.buffers.set(fileId, buffer);
      if (this.active) {
        this.start(this.now());
      }
    } catch (err) {
      this.failed.add(fileId);
      const reason = err instanceof Error ? err.message : String(err);
      // A clip whose FX cannot be rendered says why (the route answers 400 with the reason).
      this.onError(`An audio clip could not be loaded for playback (${reason}).`);
    } finally {
      this.loading.delete(fileId);
    }
  }
}
