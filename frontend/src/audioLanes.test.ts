import { describe, expect, it } from "vitest";
import type { AudioLane, TimelineAudioClip } from "./api";
import {
  ADD_ROW_H,
  AUDIO_GAP,
  AUDIO_LANE_H,
  audioEndMs,
  audioLayout,
  audioPeakBuckets,
  audioTrimTarget,
  dragLaneIndex,
  fitsOnLane,
  laneAt,
  laneAudible,
  peakWindow,
  withAudioTrim,
} from "./audioLanes";

function clip(id: string, lane: string, start: number, inMs: number, outMs: number, fileMs = 10_000): TimelineAudioClip {
  return {
    id,
    lane_id: lane,
    file_id: "f",
    name: id,
    timeline_ms: start,
    end_ms: start + (outMs - inMs),
    in_ms: inMs,
    out_ms: outMs,
    file_duration_ms: fileMs,
    gain_db: 0,
    fade_in_ms: 0,
    fade_out_ms: 0,
    fx: null,
    fx_key: null,
  };
}

function lane(id: string, mute = false, solo = false): AudioLane {
  return { id, name: id, gain_db: 0, mute, solo };
}

describe("layout", () => {
  it("stacks lanes, then the add row", () => {
    const layout = audioLayout(100, 2);
    expect(layout.laneY(1)).toBe(100 + AUDIO_LANE_H + AUDIO_GAP);
    expect(layout.addY).toBe(100 + 2 * (AUDIO_LANE_H + AUDIO_GAP));
    expect(layout.bottom).toBe(layout.addY + ADD_ROW_H);
  });

  it("finds the lane or the add row under a point", () => {
    expect(laneAt(99, 100, 2)).toBeNull();
    expect(laneAt(100, 100, 2)).toBe(0);
    expect(laneAt(100 + AUDIO_LANE_H + AUDIO_GAP + 1, 100, 2)).toBe(1);
    expect(laneAt(audioLayout(100, 2).addY + 1, 100, 2)).toBe("add");
    expect(laneAt(audioLayout(100, 2).bottom, 100, 2)).toBeNull();
  });

  it("clamps a vertical drag to the lanes", () => {
    expect(dragLaneIndex(0, 100, 3)).toBe(0);
    expect(dragLaneIndex(100 + 2.5 * (AUDIO_LANE_H + AUDIO_GAP), 100, 3)).toBe(2);
    expect(dragLaneIndex(9999, 100, 3)).toBe(2);
  });
});

describe("fitting and trimming", () => {
  const clips = [clip("a", "L1", 1000, 0, 2000), clip("b", "L1", 5000, 0, 1000), clip("c", "L2", 0, 0, 9000)];

  it("checks overlaps on one lane only", () => {
    expect(fitsOnLane(clips, "L1", 3000, 5000)).toBe(true);
    expect(fitsOnLane(clips, "L1", 2999, 3001)).toBe(false);
    expect(fitsOnLane(clips, "L1", 900, 1100, "a")).toBe(true);
    expect(fitsOnLane(clips, "L3", 0, 99999)).toBe(true);
  });

  it("stops the start edge at the file start and the clip before", () => {
    const b = clips[1]!;
    expect(audioTrimTarget(b, "start", 0, clips)).toBe(5000); // in_ms is 0: cannot reveal more
    const later = clip("d", "L1", 5000, 3000, 4000);
    expect(audioTrimTarget(later, "start", 0, [clips[0]!, later])).toBe(3000); // the clip before ends at 3000
    expect(audioTrimTarget(later, "start", 4500, [later])).toBe(4500);
    expect(audioTrimTarget(later, "start", 9000, [later])).toBe(5990);
  });

  it("stops the end edge at the file end and the clip after", () => {
    const a = clips[0]!;
    expect(audioTrimTarget(a, "end", 99999, clips)).toBe(5000); // b starts at 5000
    expect(audioTrimTarget(a, "end", 99999, [a])).toBe(11000); // file is 10 s from in 0
    expect(audioTrimTarget(a, "end", 0, [a])).toBe(1010);
  });

  it("applies a trim to the clip", () => {
    const a = clips[0]!;
    expect(withAudioTrim(a, "end", 2500)).toMatchObject({ end_ms: 2500, out_ms: 1500 });
    const late = clip("d", "L1", 5000, 3000, 4000);
    expect(withAudioTrim(late, "start", 4000)).toMatchObject({ timeline_ms: 4000, in_ms: 2000 });
  });
});

describe("misc", () => {
  it("gives the peak window of a clip", () => {
    expect(peakWindow(clip("a", "L", 0, 2500, 5000))).toEqual([0.25, 0.5]);
    expect(peakWindow(clip("a", "L", 0, 0, 10, 0))).toEqual([0, 1]);
  });

  it("follows mute and solo", () => {
    const lanes = [lane("a"), lane("b", true), lane("c")];
    expect(lanes.map((l) => laneAudible(l, lanes))).toEqual([true, false, true]);
    const soloed = [lane("a", false, true), lane("b", true, true), lane("c")];
    expect(soloed.map((l) => laneAudible(l, soloed))).toEqual([true, false, false]);
  });

  it("finds the end of the audio and the peak resolution", () => {
    expect(audioEndMs([])).toBe(0);
    expect(audioEndMs([clip("a", "L", 1000, 0, 500), clip("b", "L", 0, 0, 3000)])).toBe(3000);
    expect(audioPeakBuckets(1000)).toBe(64);
    expect(audioPeakBuckets(60_000)).toBe(1200);
    expect(audioPeakBuckets(3_600_000)).toBe(4000);
  });
});
