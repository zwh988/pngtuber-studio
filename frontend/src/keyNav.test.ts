import { describe, expect, it } from "vitest";
import { KEY_NEAR_MS, clampShift, keyGroup, keyNear, keySelection, stepKey, toggleGroup, type NavKey } from "./keyNav";

const k = (id: string, lane_id: string, t_ms: number | null, orphaned = false): NavKey => ({
  id,
  lane_id,
  t_ms,
  orphaned,
});

const KEYS = [k("x1", "x", 1000), k("y1", "y", 1000), k("x2", "x", 3000), k("o", "x", 2000, true), k("n", "x", null)];

describe("stepKey", () => {
  it("goes to the next and previous key time", () => {
    expect(stepKey(KEYS, 0, 1)?.id).toBe("x1");
    expect(stepKey(KEYS, 1000, 1)?.id).toBe("x2"); // parked on a key: moves on
    expect(stepKey(KEYS, 1000 + KEY_NEAR_MS, 1)?.id).toBe("x2");
    expect(stepKey(KEYS, 3000, -1)?.id).toBe("x1"); // skips the orphan
    expect(stepKey(KEYS, 3000, 1)).toBeNull();
    expect(stepKey(KEYS, 1000, -1)).toBeNull();
  });

  it("prefers the selected key's lane at that time", () => {
    expect(stepKey(KEYS, 0, 1, "y")?.id).toBe("y1");
    expect(stepKey(KEYS, 0, 1, "scale")?.id).toBe("x1");
  });
});

describe("keyNear", () => {
  it("finds the lane's key within one frame", () => {
    expect(keyNear(KEYS, "x", 1020)?.id).toBe("x1");
    expect(keyNear(KEYS, "y", 1000 - KEY_NEAR_MS)?.id).toBe("y1");
    expect(keyNear(KEYS, "x", 1000 + KEY_NEAR_MS + 1)).toBeNull();
    expect(keyNear(KEYS, "x", 2000)).toBeNull(); // orphan
  });
});

describe("selection", () => {
  it("counts the selection only while it holds the primary key", () => {
    expect(keySelection(null, ["a"])).toEqual([]);
    expect(keySelection("a", ["a", "b"])).toEqual(["a", "b"]);
    expect(keySelection("c", ["a", "b"])).toEqual(["c"]);
  });

  it("groups motion keys at one time on the collapsed row", () => {
    const keys = [...KEYS, k("e", "expression", 1000)];
    expect(keyGroup(keys, keys[0], true).map((x) => x.id)).toEqual(["x1", "y1"]);
    expect(keyGroup(keys, keys[0], false).map((x) => x.id)).toEqual(["x1"]);
    expect(keyGroup(keys, keys[5], true).map((x) => x.id)).toEqual(["e"]);
  });

  it("shift-click adds a group or takes it out", () => {
    expect(toggleGroup(["a"], ["b", "c"])).toEqual(["a", "b", "c"]);
    expect(toggleGroup(["a", "b", "c"], ["b", "c"])).toEqual(["a"]);
    expect(toggleGroup(["a", "b"], ["b", "c"])).toEqual(["a", "b", "c"]);
  });

  it("keeps a shifted group inside the range", () => {
    expect(clampShift([100, 500], -300, 0, 1000)).toBe(-100);
    expect(clampShift([100, 500], 800, 0, 1000)).toBe(500);
    expect(clampShift([100, 500], 50, 0, 1000)).toBe(50);
  });
});
