import { describe, expect, it } from "vitest";
import { clampGroupShift, clipsInBox, groupFits, groupMoveOrder } from "./clipGroup";

const c = (id: string, lane: string, start: number, end: number) => ({ id, lane_id: lane, timeline_ms: start, end_ms: end });
// Lane A: a 0-1000, b 1000-2000, x 3000-4000; lane B: d 500-1500.
const CLIPS = [c("a", "A", 0, 1000), c("b", "A", 1000, 2000), c("x", "A", 3000, 4000), c("d", "B", 500, 1500)];

describe("group clip moves", () => {
  it("never moves a clip before 0", () => {
    expect(clampGroupShift(CLIPS, ["b", "d"], -900)).toBe(-500);
    expect(clampGroupShift(CLIPS, ["b", "d"], 300)).toBe(300);
  });

  it("checks each lane against the clips that stay", () => {
    expect(groupFits(CLIPS, ["a", "b"], 1000)).toBe(true); // a lands where b was
    expect(groupFits(CLIPS, ["a", "b"], 1500)).toBe(false); // b runs into x
    expect(groupFits(CLIPS, ["a", "b", "x"], 1500)).toBe(true);
    expect(groupFits(CLIPS, ["d"], -600)).toBe(false); // before 0
  });

  it("orders the moves so none lands on a clip that has not moved yet", () => {
    expect(groupMoveOrder(CLIPS, ["a", "b"], 500).map((m) => m.id)).toEqual(["b", "a"]);
    expect(groupMoveOrder(CLIPS, ["a", "b"], -500).map((m) => m.id)).toEqual(["a", "b"]);
  });

  it("finds the clips a box covers on its lanes", () => {
    expect(clipsInBox(CLIPS, new Set(["A"]), 900, 1100).map((m) => m.id)).toEqual(["a", "b"]);
    expect(clipsInBox(CLIPS, new Set(["A", "B"]), 2500, 3200).map((m) => m.id)).toEqual(["x"]);
  });
});
