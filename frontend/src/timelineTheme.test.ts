import { describe, expect, it } from "vitest";
import { FALLBACK, readTimelineColors } from "./timelineTheme";

function styles(values: Record<string, string>): Pick<CSSStyleDeclaration, "getPropertyValue"> {
  return { getPropertyValue: (name: string) => values[name] ?? "" };
}

describe("readTimelineColors", () => {
  it("uses the fallback table when no token is set", () => {
    expect(readTimelineColors(styles({}))).toEqual(FALLBACK);
  });

  it("takes each colour from its token, trimmed", () => {
    const colors = readTimelineColors(
      styles({ "--lane-voice": "  #123456 ", "--playhead": "#abcdef", "--font": " Arial " }),
    );
    expect(colors.voice).toBe("#123456");
    expect(colors.playhead).toBe("#abcdef");
    expect(colors.font).toBe("Arial");
    expect(colors.clip).toBe(FALLBACK.clip);
  });

  it("keeps the playhead apart from the overflow colour", () => {
    expect(FALLBACK.playhead).not.toBe(FALLBACK.overflow);
  });
});
