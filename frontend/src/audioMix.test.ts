import { describe, expect, it } from "vitest";
import type { AudioLane, TimelineAudioClip } from "./api";
import { dbToGain, gainAt, gainPoints, planClips } from "./audioMix";

function clip(over: Partial<TimelineAudioClip> = {}): TimelineAudioClip {
  return {
    id: "c1",
    lane_id: "L1",
    file_id: "f1",
    name: "x",
    timeline_ms: 1000,
    end_ms: 5000,
    in_ms: 500,
    out_ms: 4500,
    file_duration_ms: 10_000,
    gain_db: 0,
    fade_in_ms: 0,
    fade_out_ms: 0,
    ...over,
  };
}

function lane(id: string, over: Partial<AudioLane> = {}): AudioLane {
  return { id, name: id, gain_db: 0, mute: false, solo: false, ...over };
}

describe("gainPoints and gainAt", () => {
  it("is flat without fades, at clip plus lane gain", () => {
    const points = gainPoints(clip({ gain_db: -6 }), 0);
    expect(points).toEqual([
      [0, dbToGain(-6)],
      [4000, dbToGain(-6)],
    ]);
    expect(gainAt(gainPoints(clip({ gain_db: -3 }), -3), 2000)).toBeCloseTo(dbToGain(-6));
  });

  it("ramps linearly in and out", () => {
    const points = gainPoints(clip({ fade_in_ms: 1000, fade_out_ms: 2000 }), 0);
    expect(points).toEqual([
      [0, 0],
      [1000, 1],
      [2000, 1],
      [4000, 0],
    ]);
    expect(gainAt(points, 500)).toBeCloseTo(0.5);
    expect(gainAt(points, 1500)).toBe(1);
    expect(gainAt(points, 3000)).toBeCloseTo(0.5);
    expect(gainAt(points, 4001)).toBe(0);
    expect(gainAt(points, -1)).toBe(0);
  });

  it("joins fades that fill the whole clip", () => {
    const points = gainPoints(clip({ fade_in_ms: 2000, fade_out_ms: 2000 }), 0);
    expect(points).toEqual([
      [0, 0],
      [2000, 1],
      [4000, 0],
    ]);
  });
});

describe("planClips", () => {
  it("starts clips ahead later and running clips part way in", () => {
    const clips = [clip(), clip({ id: "c2", timeline_ms: 6000, end_ms: 7000, in_ms: 0, out_ms: 1000 })];
    const plan = planClips(clips, [lane("L1")], 2000);
    expect(plan.map((p) => [p.clipId, p.delayMs, p.offsetMs, p.durationMs, p.inMs])).toEqual([
      ["c1", 0, 1000, 3000, 500],
      ["c2", 4000, 0, 1000, 0],
    ]);
  });

  it("skips clips already over and clips on unknown lanes", () => {
    expect(planClips([clip()], [lane("L1")], 5000)).toEqual([]);
    expect(planClips([clip({ lane_id: "nope" })], [lane("L1")], 0)).toEqual([]);
  });

  it("follows mute and solo, and uses the lane level", () => {
    const clips = [clip(), clip({ id: "c2", lane_id: "L2" })];
    expect(planClips(clips, [lane("L1", { mute: true }), lane("L2")], 0).map((p) => p.clipId)).toEqual(["c2"]);
    expect(planClips(clips, [lane("L1"), lane("L2", { solo: true })], 0).map((p) => p.clipId)).toEqual(["c2"]);
    const [only] = planClips([clip()], [lane("L1", { gain_db: -6 })], 0);
    expect(only?.points[0]?.[1]).toBeCloseTo(dbToGain(-6));
  });
});
