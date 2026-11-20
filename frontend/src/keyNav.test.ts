import { describe, expect, it } from "vitest";
import { KEY_NEAR_MS, keyNear, stepKey, type NavKey } from "./keyNav";

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
