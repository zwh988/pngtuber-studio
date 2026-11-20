import { describe, expect, it } from "vitest";
import type { TimelineLaneClip } from "./api";
import {
  VIDEO_ADD_H,
  VIDEO_GAP,
  VIDEO_LANE_H,
  dragVideoLaneIndex,
  laneEndMs,
  laneTrimTarget,
  videoLaneAt,
  videoLayout,
  withLaneTrim,
} from "./videoLanes";

function clip(id: string, lane: string, start: number, inMs: number, outMs: number, over: Partial<TimelineLaneClip> = {}): TimelineLaneClip {
  return {
    id,
    lane_id: lane,
    source_id: "s",
    image_id: null,
    name: id,
    timeline_ms: start,
    end_ms: start + outMs - inMs,
    in_ms: inMs,
    out_ms: outMs,
    source_duration_ms: 10_000,
    x: 0.5,
    y: 0.5,
    scale: 1,
    opacity: 1,
    gain_db: 0,
    mute: false,
    missing: false,
    ...over,
  };
}

const ROW = VIDEO_LANE_H + VIDEO_GAP;
const FIRST = 100 + VIDEO_ADD_H + VIDEO_GAP;

describe("layout", () => {
  it("draws the highest lane first, under the add row", () => {
    const layout = videoLayout(100, 3);
    expect(layout.addY).toBe(100);
    expect(layout.laneY(2)).toBe(FIRST);
    expect(layout.laneY(0)).toBe(FIRST + 2 * ROW);
    expect(layout.bottom).toBe(FIRST + 3 * ROW);
    expect(videoLayout(100, 0).bottom).toBe(FIRST);
  });

  it("finds the lane under a point", () => {
    expect(videoLaneAt(99, 100, 3)).toBeNull();
    expect(videoLaneAt(101, 100, 3)).toBe("add");
    expect(videoLaneAt(FIRST + 1, 100, 3)).toBe(2);
    expect(videoLaneAt(FIRST + 2 * ROW + 1, 100, 3)).toBe(0);
    expect(videoLaneAt(FIRST + 3 * ROW, 100, 3)).toBeNull();
    expect(videoLaneAt(101, 100, 0)).toBe("add");
  });

  it("clamps a vertical drag", () => {
    expect(dragVideoLaneIndex(0, 100, 3)).toBe(2);
    expect(dragVideoLaneIndex(9999, 100, 3)).toBe(0);
  });
});

describe("trim", () => {
  it("stops a recording at its ends and its neighbours", () => {
    const a = clip("a", "L", 1000, 2000, 4000); // 1000..3000, file starts at timeline -1000
    const b = clip("b", "L", 5000, 0, 1000);
    expect(laneTrimTarget(a, "start", -5000, [a, b])).toBe(0);
    expect(laneTrimTarget(a, "end", 99_999, [a, b])).toBe(5000);
    expect(laneTrimTarget(a, "end", 99_999, [a])).toBe(9000); // file end: 1000 + (10000 - 2000)
    expect(laneTrimTarget(a, "end", 0, [a])).toBe(1040);
  });

  it("lets a still be any length", () => {
    const s = clip("s", "L", 1000, 0, 5000, { source_id: null, image_id: "i", source_duration_ms: 0 });
    expect(laneTrimTarget(s, "end", 99_999, [s])).toBe(99_999);
    expect(laneTrimTarget(s, "start", 0, [s])).toBe(0);
    expect(withLaneTrim(s, "start", 0)).toMatchObject({ timeline_ms: 0, in_ms: 0, out_ms: 6000 });
  });

  it("applies a recording trim", () => {
    const a = clip("a", "L", 1000, 2000, 4000);
    expect(withLaneTrim(a, "start", 1500)).toMatchObject({ timeline_ms: 1500, in_ms: 2500 });
    expect(withLaneTrim(a, "end", 2500)).toMatchObject({ end_ms: 2500, out_ms: 3500 });
    expect(laneEndMs([a, clip("b", "L", 5000, 0, 1000)])).toBe(6000);
  });
});
