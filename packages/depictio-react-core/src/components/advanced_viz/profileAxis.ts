/** Marker and tick rules of the `profile` kind, kept pure so they are tested
 *  without Plotly.
 *
 * A profile is a line per series, but a series of one point draws no line at
 * all, and a refinement run (x = step index 0..N) reads as dots on a ladder.
 * So every point carries a marker, and a step-like x axis prints whole numbers
 * only (a tick at 0.5 or 1.5 names a step that does not exist).
 */

import { LINE_STYLE } from '../../palettes.generated';

/** Past this many points a series is a curve, and a marker per point would
 *  paint over it. Every series of one or a few points stays under it. */
export const MARKER_MAX_POINTS = LINE_STYLE.marker_max_points;

/** Marker diameter for a line of `lineWidth` px: about twice the width plus
 *  three, never under 6, so the dot always clears the stroke it sits on. */
export function markerSizeFor(lineWidth: number): number {
  const w = Number.isFinite(lineWidth) && lineWidth > 0 ? lineWidth : 2;
  return Math.max(6, Math.round(2 * w + 3));
}

/** Whether a series of `pointCount` points gets a marker on each point. */
export function showsMarkers(pointCount: number): boolean {
  return pointCount <= MARKER_MAX_POINTS;
}

/** At most this many distinct whole x values are labelled one by one. */
export const MAX_INTEGER_TICKS = 16;

/**
 * The x values to label when the axis is integer-valued, else null.
 *
 * `xs` are every plotted x. When all are whole numbers and few are distinct
 * (a step index, a number of copies), the distinct values are the ticks, so
 * no fractional tick appears. A continuous or a long integer axis (positions)
 * keeps Plotly's own ticks.
 */
export function integerTickValues(xs: readonly number[]): number[] | null {
  if (xs.length === 0) return null;
  const distinct = new Set<number>();
  for (const x of xs) {
    if (!Number.isFinite(x) || !Number.isInteger(x)) return null;
    distinct.add(x);
    if (distinct.size > MAX_INTEGER_TICKS) return null;
  }
  return Array.from(distinct).sort((a, b) => a - b);
}

/** An x value named by the data (deepTools' `bin_label`: TSS, TES, -3.0Kb). */
export interface AxisAnchor {
  x: number;
  label: string;
}

/**
 * The anchors a label column names: the first non-empty label met at each x,
 * sorted along x. Rows of every series repeat the same anchors, so each x is
 * kept once; a blank or null label names nothing.
 */
export function axisAnchors(xs: readonly unknown[], labels: readonly unknown[]): AxisAnchor[] {
  const byX = new Map<number, string>();
  const n = Math.min(xs.length, labels.length);
  for (let i = 0; i < n; i++) {
    const raw = labels[i];
    if (raw === null || raw === undefined) continue;
    const label = String(raw).trim();
    const x = Number(xs[i]);
    if (!label || xs[i] === null || !Number.isFinite(x) || byX.has(x)) continue;
    byX.set(x, label);
  }
  return Array.from(byX, ([x, label]) => ({ x, label })).sort((a, b) => a.x - b.x);
}
