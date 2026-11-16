import { describe, expect, it } from "vitest";
import { cutsChanged, cutsFrom, cutsToOp, moveHandle, msToX, trimTag, xToMs } from "./trim";

describe("cutsFrom / cutsToOp", () => {
  it("maps no cut to the take ends and back to null", () => {
    const cuts = cutsFrom(null, null, 2000);
    expect(cuts).toEqual({ start: 0, end: 2000 });
    expect(cutsToOp(cuts, 2000)).toEqual({ start_ms: null, end_ms: null });
  });
  it("keeps real cuts and rounds them", () => {
    expect(cutsToOp({ start: 120.4, end: 1799.6 }, 2000)).toEqual({ start_ms: 120, end_ms: 1800 });
  });
});

describe("moveHandle", () => {
  const cuts = { start: 100, end: 1500 };
  it("clamps to the take", () => {
    expect(moveHandle(cuts, "start", -50, 2000).start).toBe(0);
    expect(moveHandle(cuts, "end", 9999, 2000).end).toBe(2000);
  });
  it("keeps the minimum length between the handles", () => {
    expect(moveHandle(cuts, "start", 1450, 2000)).toEqual({ start: 1300, end: 1500 });
    expect(moveHandle(cuts, "end", 120, 2000)).toEqual({ start: 100, end: 300 });
  });
  it("copes with a take shorter than the minimum", () => {
    expect(moveHandle({ start: 0, end: 150 }, "start", 100, 150)).toEqual({ start: 0, end: 150 });
  });
});

describe("trimTag", () => {
  it("matches the backend tag", () => {
    expect(trimTag(null, null)).toBe("");
    expect(trimTag(800, null)).toBe("800-");
    expect(trimTag(null, 2000)).toBe("-2000");
    expect(trimTag(800, 2000)).toBe("800-2000");
  });
});

describe("cutsChanged", () => {
  it("compares in op form", () => {
    expect(cutsChanged({ start: 0, end: 2000 }, null, null, 2000)).toBe(false);
    expect(cutsChanged({ start: 100, end: 2000 }, null, null, 2000)).toBe(true);
    expect(cutsChanged({ start: 100, end: 1900 }, 100, 1900, 2000)).toBe(false);
  });
});

describe("msToX / xToMs", () => {
  it("round trips and clamps", () => {
    expect(msToX(500, 2000, 400)).toBe(100);
    expect(xToMs(100, 2000, 400)).toBe(500);
    expect(xToMs(-5, 2000, 400)).toBe(0);
    expect(xToMs(999, 2000, 400)).toBe(2000);
    expect(msToX(5, 0, 400)).toBe(0);
  });
});
