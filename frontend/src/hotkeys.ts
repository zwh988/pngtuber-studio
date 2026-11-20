/**
 * The editor's keyboard shortcuts as one table (M7 S5, decision 3: a read-only map).
 * `Editor.svelte` `onKeyDown` handles them; `hotkeys.test.ts` checks that every key
 * the handler reacts to is listed here, so the map cannot fall behind.
 */

export type Hotkey = {
  /** Keys as shown, e.g. ["Ctrl", "Z"]; alternatives are separate entries in `alts`. */
  keys: string[];
  alts?: string[][];
  action: string;
};

export type HotkeyGroup = { title: string; items: Hotkey[] };

export const HOTKEY_GROUPS: HotkeyGroup[] = [
  {
    title: "Playback",
    items: [
      { keys: ["Space"], action: "Play / pause" },
      { keys: [","], alts: [["."]], action: "Step one frame back / forward" },
    ],
  },
  {
    title: "Cutting",
    items: [
      { keys: ["S"], action: "Split at the playhead (the selected audio or lane clip, else the footage)" },
      { keys: ["["], alts: [["]"]], action: "Trim the selected clip's start / end to the playhead" },
      {
        keys: ["Delete"],
        action: "Ripple-delete the selected clip, or remove the selected line, key or reaction",
      },
    ],
  },
  {
    title: "Voice lines",
    items: [
      { keys: ["N"], action: "New line in the Line bank" },
      { keys: ["G"], action: "Generate the selected line" },
      { keys: ["Shift", "G"], action: "Reroll the selected line (new seed, new take)" },
      { keys: ["M"], action: "Place the selected line's take at the playhead" },
    ],
  },
  {
    title: "Avatar",
    items: [
      { keys: ["E"], action: "Expression key at the playhead" },
      { keys: ["R"], action: "Reaction at the playhead" },
    ],
  },
  {
    title: "General",
    items: [
      { keys: ["Ctrl", "Z"], action: "Undo" },
      { keys: ["Ctrl", "Y"], alts: [["Ctrl", "Shift", "Z"]], action: "Redo" },
      { keys: ["?"], action: "Show these shortcuts" },
    ],
  },
];

/** Shortcuts do nothing while typing in a text box (so N, G, Space can be typed). */
export const HOTKEY_NOTE = "Shortcuts work in the editor, except while you type in a text box.";

/**
 * Every `KeyboardEvent.key` value (lower case) the map covers, without modifiers:
 * letters, punctuation and named keys. Used by the test against `onKeyDown`.
 */
export function listedKeys(groups: HotkeyGroup[] = HOTKEY_GROUPS): Set<string> {
  const keys = new Set<string>();
  const named: Record<string, string> = { space: " ", delete: "delete" };
  for (const group of groups) {
    for (const item of group.items) {
      for (const combo of [item.keys, ...(item.alts ?? [])]) {
        const last = combo[combo.length - 1].toLowerCase();
        keys.add(named[last] ?? last);
      }
    }
  }
  return keys;
}
