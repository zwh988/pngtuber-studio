import { describe, expect, it } from "vitest";
import {
  LUFS_FLOOR,
  lufsFromPower,
  lufsText,
  meanSquareTail,
  momentaryLufs,
  windowSamples,
} from "./loudness";

function constant(value: number, length: number): Float32Array {
  return new Float32Array(length).fill(value);
}

describe("windowSamples", () => {
  it("is 400 ms of samples", () => {
    expect(windowSamples(48000)).toBe(19200);
    expect(windowSamples(1000)).toBe(400);
  });
  it("is at least one sample", () => {
    expect(windowSamples(1, 1)).toBe(1);
  });
});

describe("meanSquareTail", () => {
  it("uses only the last `count` samples", () => {
    const samples = new Float32Array([1, 1, 0, 0]);
    expect(meanSquareTail(samples, 2)).toBe(0);
    expect(meanSquareTail(samples, 4)).toBeCloseTo(0.5, 6);
  });
  it("uses everything when the buffer is shorter than the window", () => {
    expect(meanSquareTail(constant(0.5, 10), 100)).toBeCloseTo(0.25, 6);
  });
  it("is 0 for an empty buffer or a zero count", () => {
    expect(meanSquareTail(new Float32Array(0), 10)).toBe(0);
    expect(meanSquareTail(constant(1, 10), 0)).toBe(0);
  });
});

describe("lufsFromPower", () => {
  it("applies the -0.691 offset", () => {
    expect(lufsFromPower(1)).toBeCloseTo(-0.691, 6);
    expect(lufsFromPower(0.01)).toBeCloseTo(-20.691, 6);
  });
  it("is -Infinity for silence", () => {
    expect(lufsFromPower(0)).toBe(-Infinity);
    expect(lufsFromPower(-1)).toBe(-Infinity);
    expect(lufsFromPower(Number.NaN)).toBe(-Infinity);
  });
});

describe("momentaryLufs", () => {
  it("reads silence as -Infinity", () => {
    expect(momentaryLufs([constant(0, 1000), constant(0, 1000)], 1000)).toBe(-Infinity);
  });
  it("sums the channels: two equal channels read 3.01 LU above one", () => {
    const one = momentaryLufs([constant(0.1, 1000)], 1000);
    const two = momentaryLufs([constant(0.1, 1000), constant(0.1, 1000)], 1000);
    expect(two - one).toBeCloseTo(3.0103, 3);
  });
  it("looks only at the last 400 ms", () => {
    // 1000 Hz sample rate: the window is the last 400 samples.
    const loudThenQuiet = new Float32Array(1000);
    loudThenQuiet.fill(1, 0, 600);
    expect(momentaryLufs([loudThenQuiet], 1000)).toBe(-Infinity);
    const quietThenLoud = new Float32Array(1000);
    quietThenLoud.fill(1, 600, 1000);
    expect(momentaryLufs([quietThenLoud], 1000)).toBeCloseTo(-0.691, 6);
  });
  it("a full-scale square wave in one channel reads -0.691 LUFS", () => {
    const wave = new Float32Array(2000);
    for (let i = 0; i < wave.length; i += 1) {
      wave[i] = i % 2 === 0 ? 1 : -1;
    }
    expect(momentaryLufs([wave], 1000)).toBeCloseTo(-0.691, 6);
  });
});

describe("lufsText", () => {
  it("formats one decimal", () => {
    expect(lufsText(-16.234)).toBe("-16.2 LUFS");
  });
  it("shows silence below the floor", () => {
    expect(lufsText(-Infinity)).toBe("silent");
    expect(lufsText(LUFS_FLOOR - 1)).toBe("silent");
    expect(lufsText(LUFS_FLOOR)).toBe("-70.0 LUFS");
  });
});
