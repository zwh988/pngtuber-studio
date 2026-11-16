import { describe, expect, it } from "vitest";
import type { FrameTrack } from "./api";
import fixture from "./avatarLayout.fixture.json";
import { frameIndex, frameRect, hitTest, layout, poseAt, resizeFactor, spriteAt, toLocal } from "./avatarTrack";

function track(): FrameTrack {
  return {
    version: "v",
    fps: 30,
    duration_ms: 1000,
    frame_count: 31,
    height_fraction: 0.6,
    sprites: ["smile/oicm", "smile/oiom"],
    sprite_runs: [
      [0, 0],
      [10, 1],
      [20, -1],
      [25, 0],
    ],
    x: Array.from({ length: 31 }, (_, k) => k / 100),
    y: Array(31).fill(0.75),
    scale: Array(31).fill(1),
    rotation: Array(31).fill(0),
    squash: Array(31).fill(0),
  };
}

describe("frameIndex / spriteAt / poseAt", () => {
  it("shows the frame that started last and clamps", () => {
    const t = track();
    expect(frameIndex(t, 0)).toBe(0);
    expect(frameIndex(t, 33)).toBe(0);
    expect(frameIndex(t, 49)).toBe(1);
    expect(frameIndex(t, 51)).toBe(1);
    expect(frameIndex(t, 100)).toBe(3); // exactly on a frame
    expect(frameIndex(t, 1000 / 30)).toBe(1);
    expect(frameIndex(t, -10)).toBe(0);
    expect(frameIndex(t, 99_999)).toBe(30);
  });
  it("finds the run a frame is in", () => {
    const t = track();
    expect(spriteAt(t, 0)).toBe("smile/oicm");
    expect(spriteAt(t, 9)).toBe("smile/oicm");
    expect(spriteAt(t, 10)).toBe("smile/oiom");
    expect(spriteAt(t, 22)).toBeNull();
    expect(spriteAt(t, 30)).toBe("smile/oicm");
    expect(poseAt(t, 12).x).toBeCloseTo(0.12);
  });
});

describe("frameRect", () => {
  it("letterboxes a tall box and pillarboxes a wide one", () => {
    expect(frameRect(1600, 1200)).toEqual({ left: 0, top: 150, width: 1600, height: 900 });
    expect(frameRect(2000, 900)).toEqual({ left: 200, top: 0, width: 1600, height: 900 });
  });
});

describe("layout matches the export compositor (shared fixture)", () => {
  for (const [i, c] of fixture.cases.entries()) {
    it(`case ${i}`, () => {
      const l = layout({ sprite: "s", ...c.pose }, c.frame, c.imageAspect, c.heightFraction);
      for (const name of ["ax", "ay", "w", "h", "rot", "sx", "sy"] as const) {
        expect(l[name]).toBeCloseTo(c.expected[name], 6);
      }
    });
  }
});

describe("layout, hitTest, resizeFactor", () => {
  const frame = { left: 0, top: 0, width: 1600, height: 900 };
  const pose = { sprite: "s", x: 0.5, y: 1, scale: 1, rotation: 0, squash: 0 };
  const l = layout(pose, frame, 0.5, 0.6);
  it("anchors at the bottom centre", () => {
    expect([l.ax, l.ay, l.h, l.w]).toEqual([800, 900, 540, 270]);
    expect(toLocal(800, 900, l)).toEqual([0, 0]);
  });
  it("hits the body and the handle", () => {
    expect(hitTest(800, 700, l)).toBe("body");
    expect(hitTest(935, 360, l)).toBe("handle");
    expect(hitTest(1000, 700, l)).toBeNull();
    expect(hitTest(800, 950, l)).toBeNull();
  });
  it("follows rotation", () => {
    const turned = layout({ ...pose, rotation: 90 }, frame, 0.5, 0.6);
    expect(hitTest(1000, 900, turned)).toBe("body"); // the top now points right
    expect(hitTest(800, 700, turned)).toBeNull();
  });
  it("scales by distance from the anchor", () => {
    expect(resizeFactor(l, 800, 600, 800, 300)).toBeCloseTo(2);
    expect(resizeFactor(l, 800, 900, 800, 300)).toBe(1);
  });
});
