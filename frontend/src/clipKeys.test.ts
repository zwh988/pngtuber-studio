import { describe, expect, it } from "vitest";
import type { ClipKey } from "./api";
import { clipEditOps, clipKeyNear, clipValuesAt, ease, hiddenClipKeys, isKeyed, keyCurve, laneValue, visibleClipKeys } from "./clipKeys";
import table from "../../tests/fixtures/clip_key_cases.json";

type Case = {
  name: string;
  clip: { timeline_ms: number; x: number; y: number; scale: number; opacity: number; keys: ClipKey[] };
  samples: { t: number; expect: Record<string, number> }[];
};

const cases = table.cases as Case[];

describe("clip keys match the Python evaluation (tests/fixtures/clip_key_cases.json)", () => {
  for (const c of cases) {
    it(c.name, () => {
      for (const s of c.samples) {
        const got = clipValuesAt(c.clip, s.t);
        for (const [prop, want] of Object.entries(s.expect)) {
          expect(got[prop as keyof typeof got], `${s.t} ${prop}`).toBeCloseTo(want, 12);
        }
      }
    });
  }
});

describe("ease and lanes", () => {
  it("matches the Python curves", () => {
    expect(ease("hold", 0.7)).toBe(0);
    expect(ease("linear", 1.5)).toBe(1);
    expect(ease("ease_in", 0.5, 2)).toBeCloseTo(0.125, 12);
    expect(ease("ease_in_out", 0.25, 2)).toBeCloseTo(0.103515625, 12);
    expect(ease("ease_in", 0.5, 9)).toBe(ease("ease_in", 0.5, 2));
  });

  it("holds outside the keys and uses the base without keys", () => {
    const keys = [
      { t_ms: 100, value: 1, interpolation: "linear" as const, strength: 1 },
      { t_ms: 200, value: 3, interpolation: "linear" as const, strength: 1 },
    ];
    expect(laneValue(keys, 0, 9)).toBe(1);
    expect(laneValue(keys, 150, 9)).toBe(2);
    expect(laneValue(keys, 500, 9)).toBe(3);
    expect(laneValue([], 150, 9)).toBe(9);
  });

  it("knows which properties are keyed", () => {
    expect(isKeyed(cases[1].clip, "opacity")).toBe(true);
    expect(isKeyed(cases[1].clip, "x")).toBe(false);
  });
});

describe("editing a keyed clip", () => {
  const key = (id: string, prop: ClipKey["prop"], t_ms: number, value: number): ClipKey => ({
    id,
    prop,
    t_ms,
    value,
    interpolation: "linear",
    ease_strength: 1,
  });
  const clip = { id: "c", timeline_ms: 1000, end_ms: 6000, keys: [key("a", "x", 0, 0.2), key("b", "x", 6000, 0.9)] };

  it("keys keyed properties at the playhead and sets the rest on the clip", () => {
    expect(clipEditOps(clip, { x: 0.4, y: 0.6, scale: 0.5 }, 2000.4)).toEqual({
      ops: [
        { op: "set_lane_clip", clip_id: "c", y: 0.6, scale: 0.5 },
        { op: "key_lane_clip", clip_id: "c", prop: "x", timeline_ms: 2000, value: 0.4 },
      ],
      skipped: [],
    });
    expect(clipEditOps(clip, { x: 0.4 }, 9000)).toEqual({ ops: [], skipped: ["x"] });
  });

  it("finds the key at the playhead and hides keys outside the clip", () => {
    expect(clipKeyNear(clip, "x", 1030)?.id).toBe("a");
    expect(clipKeyNear(clip, "x", 1040)).toBeNull();
    expect(clipKeyNear(clip, "y", 1000)).toBeNull();
    expect(visibleClipKeys(clip).map((k) => k.id)).toEqual(["a"]);
    expect(hiddenClipKeys(clip)).toEqual({ before: 0, after: 1 });
    expect(hiddenClipKeys({ ...clip, keys: [key("z", "y", -5, 0.1)] })).toEqual({ before: 1, after: 0 });
  });
});

describe("key curves for the timeline", () => {
  it("follows each segment's easing, and holds then jumps", () => {
    const pts = keyCurve(
      [
        { t_ms: 0, value: 0, interpolation: "ease_in", strength: 1 },
        { t_ms: 100, value: 1, interpolation: "hold", strength: 1 },
        { t_ms: 200, value: 0.5, interpolation: "linear", strength: 1 },
      ],
      4,
    );
    expect(pts).toEqual([
      { t: 0, v: 0 },
      { t: 25, v: 0.0625 },
      { t: 50, v: 0.25 },
      { t: 75, v: 0.5625 },
      { t: 100, v: 1 },
      { t: 200, v: 1 },
      { t: 200, v: 0.5 },
    ]);
    expect(keyCurve([])).toEqual([]);
  });
});
