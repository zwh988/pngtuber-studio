/**
 * Pure maths for the status bar loudness meter (BS.1770 momentary loudness, 400 ms).
 *
 * The K-weighting itself is done by filter nodes in `audioGraph.ts`; these functions take the
 * already weighted samples. No Web Audio, no DOM: tested in `loudness.test.ts`.
 * An approximation for the preview: the export measures with pyloudnorm.
 */

/** Length of the momentary loudness window. */
export const MOMENTARY_WINDOW_MS = 400;

/** Readings below this are shown as silence. */
export const LUFS_FLOOR = -70;

/** The BS.1770 offset that makes a 0 dBFS 997 Hz sine in one channel read -3.01 LUFS. */
const LUFS_OFFSET = -0.691;

/** Number of samples in a window of `windowMs` at `sampleRate` (at least 1). */
export function windowSamples(sampleRate: number, windowMs: number = MOMENTARY_WINDOW_MS): number {
  return Math.max(1, Math.round((sampleRate * windowMs) / 1000));
}

/** Mean of the squares of the last `count` samples (all of them when there are fewer). */
export function meanSquareTail(samples: Float32Array, count: number): number {
  const n = Math.min(Math.max(Math.floor(count), 0), samples.length);
  if (n === 0) {
    return 0;
  }
  let sum = 0;
  for (let i = samples.length - n; i < samples.length; i += 1) {
    const x = samples[i];
    sum += x * x;
  }
  return sum / n;
}

/** Loudness in LUFS of a summed mean square; -Infinity for silence. */
export function lufsFromPower(power: number): number {
  if (!Number.isFinite(power) || power <= 0) {
    return -Infinity;
  }
  return LUFS_OFFSET + 10 * Math.log10(power);
}

/**
 * Momentary loudness of K-weighted channels: the mean squares of the last window of each
 * channel are summed (channel weight 1, as BS.1770 does for left and right).
 */
export function momentaryLufs(
  channels: readonly Float32Array[],
  sampleRate: number,
  windowMs: number = MOMENTARY_WINDOW_MS,
): number {
  const count = windowSamples(sampleRate, windowMs);
  let power = 0;
  for (const channel of channels) {
    power += meanSquareTail(channel, count);
  }
  return lufsFromPower(power);
}

/** Text for the status bar: "-16.2 LUFS", or "silent" below the floor. */
export function lufsText(lufs: number): string {
  if (!Number.isFinite(lufs) || lufs < LUFS_FLOOR) {
    return "silent";
  }
  return `${lufs.toFixed(1)} LUFS`;
}
