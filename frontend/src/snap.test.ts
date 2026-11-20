import { describe, expect, it } from "vitest";
import { nearestPoint, snapEdge, snapMove, snapPoints } from "./snap";

describe("snapPoints", () => {
  it("collects edges and the playhead, skipping the dragged clip and missing times", () => {
    const spans = [
      { id: "a", start: 0, end: 1000 },
      { id: "b", start: 1000, end: 2500 },
      { id: "me", start: 300, end: 700 },
      { id: "v", start: null, end: null },
    ];
    expect(snapPoints(spans, 1800, "me")).toEqual([0, 1000, 1800, 2500]);
  });
});

describe("snapping", () => {
  const points = [0, 1000, 2500];
  it("an edge jumps to the nearest point only when close enough", () => {
    expect(nearestPoint(1040, points, 50)).toBe(1000);
    expect(nearestPoint(1060, points, 50)).toBeNull();
    expect(snapEdge(2460, points, 50)).toBe(2500);
    expect(snapEdge(1700, points, 50)).toBe(1700);
  });
  it("a moved clip snaps by whichever edge is closer and keeps its length", () => {
    expect(snapMove(1030, 400, points, 50)).toBe(1000); // start to 1000
    expect(snapMove(2080, 400, points, 50)).toBe(2100); // end to 2500
    expect(snapMove(1500, 400, points, 50)).toBe(1500); // nothing near
    expect(snapMove(20, 400, [-10, 0], 50)).toBe(0);
  });
});
