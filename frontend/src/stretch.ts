/** Tighten limits; keep in step with `STRETCH_*` in backend/project/schema.py and backend/voice/stretch.py. */
export const STRETCH_MIN = 1;
export const STRETCH_MAX = 1.25;
/** The one-click Tighten never goes past this (about 8 percent). */
export const STRETCH_AUTO_MAX = 1.08;
/** Above this the voice may sound unnatural. */
export const STRETCH_WARN = 1.15;

/** "+8.3%" for a stretch of 1.083. */
export function stretchText(stretch: number): string {
  return `+${((stretch - 1) * 100).toFixed(1)}%`;
}

/**
 * The stretch the Tighten button applies: the one that clears the overflow, capped at the
 * one-click limit. Null when there is nothing to fix, or the cap would not go further than
 * the line already is.
 */
export function tightenTarget(fit: number | null, current: number): number | null {
  if (fit === null) {
    return null;
  }
  const target = Math.min(fit, STRETCH_AUTO_MAX);
  return target > current + 0.0005 ? target : null;
}
