import { describe, expect, it } from "vitest";
import { HOTKEY_GROUPS, listedKeys } from "./hotkeys";
import editorSource from "./Editor.svelte?raw";

/** The `case "x":` keys of `onKeyDown` in Editor.svelte, lower case. */
function handledKeys(): Set<string> {
  const source = editorSource;
  const start = source.indexOf("function onKeyDown");
  const end = source.indexOf("function onKeyUp", start);
  expect(start).toBeGreaterThan(0);
  expect(end).toBeGreaterThan(start);
  const body = source.slice(start, end);
  const keys = new Set<string>();
  for (const match of body.matchAll(/case "([^"]+)":/g)) {
    keys.add(match[1].toLowerCase());
  }
  // Ctrl shortcuts are compared as `key === "z"` / `"y"`.
  for (const match of body.matchAll(/key === "([a-z])"/g)) {
    keys.add(match[1]);
  }
  return keys;
}

describe("hotkey map", () => {
  it("lists every key the editor handles", () => {
    const listed = listedKeys();
    const missing = [...handledKeys()].filter((key) => !listed.has(key));
    expect(missing).toEqual([]);
  });

  it("has no duplicate shortcut", () => {
    const seen = new Set<string>();
    for (const group of HOTKEY_GROUPS) {
      for (const item of group.items) {
        for (const combo of [item.keys, ...(item.alts ?? [])]) {
          const id = combo.join("+");
          expect(seen.has(id)).toBe(false);
          seen.add(id);
        }
      }
    }
  });

  it("maps named keys to KeyboardEvent values", () => {
    const keys = listedKeys();
    expect(keys.has(" ")).toBe(true);
    expect(keys.has("delete")).toBe(true);
    expect(keys.has("?")).toBe(true);
  });
});
