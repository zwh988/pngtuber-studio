/**
 * Timeline canvas colours (UI-2 S6). The canvas cannot use CSS variables directly, so the
 * colours are read once from the theme tokens in theme.css. FALLBACK is used only when a
 * token is missing (for example in a unit test without the stylesheet).
 */

export type TimelineColors = {
  background: string;
  ruler: string;
  rulerMajor: string;
  rulerMinor: string;
  rulerText: string;
  row: string;
  rowLine: string;
  hint: string;
  clip: string;
  clipAlt: string;
  clipText: string;
  clipTextMuted: string;
  speedBadge: string;
  speedText: string;
  cut: string;
  voice: string;
  voiceEmpty: string;
  audio: string;
  wave: string;
  expression: string;
  reaction: string;
  motion: string;
  motionHold: string;
  keyText: string;
  selected: string;
  selectedRing: string;
  missing: string;
  orphan: string;
  overflow: string;
  playhead: string;
  ghost: string;
  font: string;
};

/** CSS token for each colour (fonts are handled apart). */
const TOKENS: Record<Exclude<keyof TimelineColors, "font">, string> = {
  background: "--bg",
  ruler: "--surface-1",
  rulerMajor: "--text-3",
  rulerMinor: "--border-strong",
  rulerText: "--text-2",
  row: "--surface-1",
  rowLine: "--border",
  hint: "--text-3",
  clip: "--lane-clip",
  clipAlt: "--lane-clip-alt",
  clipText: "--text-1",
  clipTextMuted: "--text-2",
  speedBadge: "--warning",
  speedText: "--bg",
  cut: "--text-1",
  voice: "--lane-voice",
  voiceEmpty: "--surface-3",
  audio: "--lane-audio",
  wave: "--text-1",
  expression: "--lane-expression",
  reaction: "--lane-reaction",
  motion: "--lane-motion",
  motionHold: "--lane-motion-hold",
  keyText: "--text-1",
  selected: "--selected",
  selectedRing: "--accent",
  missing: "--danger",
  orphan: "--warning",
  overflow: "--overflow",
  playhead: "--playhead",
  ghost: "--accent",
};

export const FALLBACK: TimelineColors = {
  background: "#0e1014",
  ruler: "#15181e",
  rulerMajor: "#6d7482",
  rulerMinor: "#363d4a",
  rulerText: "#a6adba",
  row: "#15181e",
  rowLine: "#272c36",
  hint: "#6d7482",
  clip: "#3a67a8",
  clipAlt: "#2f5285",
  clipText: "#e7e9ee",
  clipTextMuted: "#a6adba",
  speedBadge: "#e8a93a",
  speedText: "#0e1014",
  cut: "#e7e9ee",
  voice: "#2c8f72",
  voiceEmpty: "#232833",
  audio: "#b8683a",
  wave: "#e7e9ee",
  expression: "#d9ad3c",
  reaction: "#9b72de",
  motion: "#4ea3c9",
  motionHold: "#9fcbe0",
  keyText: "#e7e9ee",
  selected: "#ffffff",
  selectedRing: "#4f8cff",
  missing: "#f0615f",
  orphan: "#e8a93a",
  overflow: "#f0615f",
  playhead: "#f4f6fa",
  ghost: "#4f8cff",
  font: '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif',
};

/** Read every colour from computed styles; a missing or empty token keeps its fallback. */
export function readTimelineColors(styles: Pick<CSSStyleDeclaration, "getPropertyValue">): TimelineColors {
  const out: TimelineColors = { ...FALLBACK };
  for (const [name, token] of Object.entries(TOKENS) as [keyof typeof TOKENS, string][]) {
    const value = styles.getPropertyValue(token).trim();
    if (value !== "") {
      out[name] = value;
    }
  }
  const font = styles.getPropertyValue("--font").trim();
  if (font !== "") {
    out.font = font;
  }
  return out;
}
