/**
 * Hover emphasis for a plotly-upset figure, as in the UpSet Shiny app: hovering
 * an intersection keeps its bar, its matrix column, its annotation marks and
 * the size bars of the sets it joins at full strength, and dims the rest. A
 * selected intersection is emphasised the same way, and stays so while another
 * one is hovered.
 *
 * The figure's structure is read through upsetFigure.ts.
 */

import {
  hasMarkers,
  isFilledMatrixDots,
  isMatrixDots,
  isSetSizeBars,
  setNameAxes,
  values,
  type Layout,
  type Trace,
} from './upsetFigure';

export const UPSET_DIMMED_OPACITY = 0.2;

function withMarkerOpacity(t: Trace, opacity: number[]): Trace {
  return { ...t, marker: { ...(t.marker as Record<string, unknown> | undefined), opacity } };
}

/** The intersection a hovered point belongs to; null for a set-size bar. */
export function upsetHoverColumn(point: { data?: Trace; x?: unknown } | undefined): number | null {
  if (!point?.data || point.x == null || isSetSizeBars(point.data)) return null;
  const x = Number(point.x);
  return Number.isFinite(x) ? Math.round(x) : null;
}

/** Lets the empty matrix dots report hovers too, so a whole column is a
 *  target. They still show no label. */
export function withUpsetHoverTargets(data: Trace[], layout: Layout): Trace[] {
  const axes = setNameAxes(layout);
  return data.map((t) =>
    isMatrixDots(t, axes) && t.hoverinfo === 'skip' ? { ...t, hoverinfo: 'none' } : t,
  );
}

/** `data` with every mark outside the intersections in `columns` dimmed. */
export function emphasizeUpsetColumns(data: Trace[], layout: Layout, columns: readonly number[]): Trace[] {
  const kept = new Set(columns);
  if (kept.size === 0) return data;
  const axes = setNameAxes(layout);
  // The sets the intersections join: the rows of their filled dots, the only
  // matrix dots that carry a label.
  const joined = new Set<number>();
  for (const t of data) {
    if (!isFilledMatrixDots(t, axes)) continue;
    const ys = values(t.y);
    values(t.x).forEach((x, i) => {
      if (kept.has(Number(x))) joined.add(Number(ys[i]));
    });
  }

  const opacity = (keep: boolean) => (keep ? 1 : UPSET_DIMMED_OPACITY);
  return data.map((t) => {
    if (isSetSizeBars(t)) {
      return withMarkerOpacity(t, values(t.y).map((y) => opacity(joined.has(Number(y)))));
    }
    const xs = values(t.x);
    // No positions to read: legend-only entries.
    if (xs.length === 0 || xs.some((x) => x == null)) return t;
    if (t.type === 'bar' || hasMarkers(t)) {
      return withMarkerOpacity(t, xs.map((x) => opacity(kept.has(Number(x)))));
    }
    // Matrix edges and box or violin tracks draw one intersection per trace.
    if (xs.every((x) => x === xs[0])) return { ...t, opacity: opacity(kept.has(Number(xs[0]))) };
    return t;
  });
}

/** `data` with every mark outside intersection `column` dimmed. */
export function emphasizeUpsetColumn(data: Trace[], layout: Layout, column: number): Trace[] {
  return emphasizeUpsetColumns(data, layout, [column]);
}
