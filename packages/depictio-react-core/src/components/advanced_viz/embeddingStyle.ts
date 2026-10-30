/**
 * Marker and axis sizing of the embedding scatter, as pure functions so they
 * can be tested without Plotly.
 */

/** Point size when the config names none: 6, or 4 past DENSE_POINTS points. */
export const DEFAULT_POINT_SIZE = 6;
export const DENSE_POINTS = 1000;
const DENSE_POINT_SIZE = 4;

/**
 * The marker size drawn. An explicit `point_size` (the config's, or the
 * viewer's from the Point size control) is drawn as asked, at any point count.
 * Unset, the size shrinks to 4 px past 1,000 points so a dense cloud does not
 * turn into a solid blot.
 */
export function effectivePointSize(explicit: number | null | undefined, nPoints: number): number {
  if (explicit != null && Number.isFinite(explicit)) return explicit;
  return nPoints > DENSE_POINTS ? DENSE_POINT_SIZE : DEFAULT_POINT_SIZE;
}

export type OutlineColourMode = 'contrast' | 'background';

/**
 * Colour of the point outline. "contrast" is the text colour (dark on light,
 * light on dark), which rings each point; "background" is the page colour
 * (white on light, near-black on dark), which separates overlapping points
 * the way a halo does.
 */
export function outlineColour(mode: OutlineColourMode | null | undefined, isDark: boolean, textColor: string): string {
  if (mode === 'background') return isDark ? '#1a1b1e' : '#ffffff';
  return textColor;
}

/** Axis line width, clamped to the 1-6 px the control offers. */
export function clampAxisLineWidth(width: number | null | undefined): number {
  const w = Number(width);
  if (!Number.isFinite(w)) return 1;
  return Math.max(1, Math.min(6, w));
}
