import { momentaryLufs } from "./loudness";

/** Master limiter settings (a DynamicsCompressorNode used as a limiter). */
const LIMITER_THRESHOLD_DB = -1;
const LIMITER_RATIO = 20;
const LIMITER_ATTACK_S = 0.001;
const LIMITER_RELEASE_S = 0.05;

/** K-weighting, stage 1 (high shelf) and stage 2 (high-pass), BS.1770 values. */
const K_SHELF_HZ = 1681.974450955533;
const K_SHELF_GAIN_DB = 3.999843853973347;
const K_HIGHPASS_HZ = 38.13547087602444;
/** Q 0.5003 as the dB value a Web Audio high-pass wants: 20 * log10(0.5003). */
const K_HIGHPASS_Q_DB = -6.0153;

/** Time constant of the game level change, so a slider drag does not click. */
const GAIN_SMOOTH_S = 0.015;

/**
 * The shared Web Audio graph of the editor (spec 7 "Mix").
 *
 *   <video> -> gameGain ----\
 *                            +-> limiter -> destination
 *   voice sources -> voiceBus/   (audio-lane clips -> musicBus join the limiter too, M8-1)                 |
 *                                              +-> K-weighting -> splitter -> 2 analysers (meter)
 *
 * One AudioContext for everything, so the voice and the footage share one clock. The nodes are
 * built on the first use of `context`. The limiter is an approximation of the export's
 * Pedalboard limiter (each voice is already limited at -1 dBFS, so it should rarely act).
 */
export class AudioGraph {
  private ctx: AudioContext | null = null;
  private gameGain: GainNode | null = null;
  private voiceBus: GainNode | null = null;
  /** Music and sound effects from the audio lanes (M8-1). */
  private musicBus: GainNode | null = null;
  private analysers: [AnalyserNode, AnalyserNode] | null = null;
  private scratch: [Float32Array, Float32Array] | null = null;
  private videoEl: HTMLMediaElement | null = null;
  private videoSource: MediaElementAudioSourceNode | null = null;
  private gameDb = 0;

  /** The shared context; built (with all nodes) on first use. */
  get context(): AudioContext {
    return this.build().ctx;
  }

  /** The context if it was already built, else null (does not build it). */
  get contextIfBuilt(): AudioContext | null {
    return this.ctx;
  }

  /** Where voice sources connect. */
  get voiceInput(): AudioNode {
    const bus = this.build().voiceBus;
    return bus;
  }

  /** Where audio-clip sources connect (M8-1). */
  get musicInput(): AudioNode {
    this.build();
    return this.musicBus as GainNode;
  }

  /** Start the context if the browser suspended it (call from a play action). */
  resume(): void {
    const ctx = this.context;
    if (ctx.state !== "running") {
      void ctx.resume().catch(() => undefined);
    }
  }

  /**
   * Route a media element's sound through the game bus. Safe to call again with the same
   * element; a different element replaces the old one. Throws if the browser refuses.
   */
  attachVideo(element: HTMLMediaElement): void {
    if (this.videoEl === element) {
      return;
    }
    const built = this.build();
    this.detachVideo();
    const source = built.ctx.createMediaElementSource(element);
    source.connect(built.gameGain);
    this.videoEl = element;
    this.videoSource = source;
  }

  /** Set the footage level in dB (`Project.game_audio_db`). Applied at once, or when built. */
  setGameDb(db: number): void {
    this.gameDb = db;
    if (this.ctx !== null && this.gameGain !== null) {
      this.gameGain.gain.setTargetAtTime(Math.pow(10, db / 20), this.ctx.currentTime, GAIN_SMOOTH_S);
    }
  }

  /** Momentary loudness (LUFS, 400 ms, K-weighted) of the master bus; null before the graph exists. */
  momentaryLufs(): number | null {
    if (this.ctx === null || this.analysers === null || this.scratch === null) {
      return null;
    }
    const [left, right] = this.analysers;
    left.getFloatTimeDomainData(this.scratch[0]);
    right.getFloatTimeDomainData(this.scratch[1]);
    return momentaryLufs(this.scratch, this.ctx.sampleRate);
  }

  dispose(): void {
    this.detachVideo();
    const ctx = this.ctx;
    this.ctx = null;
    this.gameGain = null;
    this.voiceBus = null;
    this.musicBus = null;
    this.analysers = null;
    this.scratch = null;
    if (ctx !== null) {
      void ctx.close().catch(() => undefined);
    }
  }

  private detachVideo(): void {
    if (this.videoSource !== null) {
      this.videoSource.disconnect();
    }
    this.videoSource = null;
    this.videoEl = null;
  }

  private build(): { ctx: AudioContext; gameGain: GainNode; voiceBus: GainNode } {
    if (this.ctx !== null && this.gameGain !== null && this.voiceBus !== null) {
      return { ctx: this.ctx, gameGain: this.gameGain, voiceBus: this.voiceBus };
    }
    const ctx = new AudioContext();
    const gameGain = ctx.createGain();
    const voiceBus = ctx.createGain();
    const musicBus = ctx.createGain();

    const limiter = ctx.createDynamicsCompressor();
    limiter.threshold.value = LIMITER_THRESHOLD_DB;
    limiter.knee.value = 0;
    limiter.ratio.value = LIMITER_RATIO;
    limiter.attack.value = LIMITER_ATTACK_S;
    limiter.release.value = LIMITER_RELEASE_S;

    gameGain.connect(limiter);
    voiceBus.connect(limiter);
    musicBus.connect(limiter);
    limiter.connect(ctx.destination);

    // Meter tap: K-weighted, kept in stereo (explicit 2 channels) so the two channels can be
    // summed as BS.1770 does.
    const highpass = ctx.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = K_HIGHPASS_HZ;
    highpass.Q.value = K_HIGHPASS_Q_DB;
    const shelf = ctx.createBiquadFilter();
    shelf.type = "highshelf";
    shelf.frequency.value = K_SHELF_HZ;
    shelf.gain.value = K_SHELF_GAIN_DB;
    for (const node of [highpass, shelf]) {
      node.channelCount = 2;
      node.channelCountMode = "explicit";
    }
    const splitter = ctx.createChannelSplitter(2);
    const left = ctx.createAnalyser();
    const right = ctx.createAnalyser();
    left.fftSize = 32768;
    right.fftSize = 32768;
    limiter.connect(highpass);
    highpass.connect(shelf);
    shelf.connect(splitter);
    splitter.connect(left, 0);
    splitter.connect(right, 1);

    this.ctx = ctx;
    this.gameGain = gameGain;
    this.voiceBus = voiceBus;
    this.musicBus = musicBus;
    this.analysers = [left, right];
    this.scratch = [new Float32Array(left.fftSize), new Float32Array(right.fftSize)];
    gameGain.gain.value = Math.pow(10, this.gameDb / 20);
    return { ctx, gameGain, voiceBus };
  }
}
