import { describe, expect, it } from "vitest";
import type { TimelineLaneClip } from "./api";
import {
  activeLaneClips,
  laneSourceMs,
  movedCentre,
  resizedScale,
  pipRect,
  upcomingLaneClips,
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
    media_width: 1920,
    media_height: 1080,
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

describe("preview", () => {
  const lanes = [
    { id: "L1", hidden: false },
    { id: "L2", hidden: false },
    { id: "L3", hidden: true },
  ];
  const clips = [
    clip("top", "L2", 1000, 0, 2000),
    clip("bottom", "L1", 0, 0, 5000),
    clip("hidden", "L3", 0, 0, 5000),
    clip("gone", "L1", 6000, 0, 1000, { missing: true }),
    clip("later", "L1", 5000, 0, 1000),
  ];

  it("lists the clips showing now, bottom lane first", () => {
    expect(activeLaneClips(clips, lanes, 1500).map((c) => c.id)).toEqual(["bottom", "top"]);
    expect(activeLaneClips(clips, lanes, 3000).map((c) => c.id)).toEqual(["bottom"]);
    expect(activeLaneClips(clips, lanes, 6500).map((c) => c.id)).toEqual([]);
    expect(upcomingLaneClips(clips, lanes, 4000, 1500).map((c) => c.id)).toEqual(["later"]);
  });

  it("maps timeline time into the recording", () => {
    expect(laneSourceMs(clip("a", "L", 1000, 2000, 4000), 1500)).toBe(2500);
  });

  it("fits the picture into the frame, scaled around its centre", () => {
    expect(pipRect(1920, 1080, 1280, 720, { x: 0.5, y: 0.5, scale: 1 })).toEqual({ left: 0, top: 0, width: 1920, height: 1080 });
    expect(pipRect(1920, 1080, 1000, 1000, { x: 0.5, y: 0.5, scale: 1 })).toEqual({ left: 420, top: 0, width: 1080, height: 1080 });
    expect(pipRect(1920, 1080, 1920, 1080, { x: 0.75, y: 0.25, scale: 0.5 })).toEqual({ left: 960, top: 0, width: 960, height: 540 });
    expect(pipRect(0, 1080, 1920, 1080, { x: 0.5, y: 0.5, scale: 1 }).width).toBe(0);
  });
});

describe("preview handles", () => {
  it("a drag moves the centre by the frame fraction, kept in limits", () => {
    expect(movedCentre({ x: 0.5, y: 0.5 }, 96, -54, 960, 540)).toEqual({ x: 0.6, y: 0.4 });
    expect(movedCentre({ x: 1.9, y: -0.9 }, 960, -540, 960, 540)).toEqual({ x: 2, y: -1 });
    expect(movedCentre({ x: 0.3, y: 0.3 }, 10, 10, 0, 0)).toEqual({ x: 0.3, y: 0.3 });
  });
  it("a corner drag scales with the distance from the centre", () => {
    const c = { x: 100, y: 100 };
    expect(resizedScale(0.5, c, { x: 150, y: 100 }, { x: 200, y: 100 })).toBe(1);
    expect(resizedScale(0.5, c, { x: 150, y: 100 }, { x: 100, y: 125 })).toBe(0.25);
    expect(resizedScale(1, c, { x: 150, y: 100 }, { x: 100, y: 100 })).toBe(0.05);
    expect(resizedScale(3, c, { x: 110, y: 100 }, { x: 900, y: 100 })).toBe(4);
    expect(resizedScale(0.7, c, c, { x: 300, y: 300 })).toBe(0.7);
  });
});
