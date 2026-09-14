/**
 * Hover emphasis for a plotly-upset figure, as in the UpSet Shiny app: hovering
 * an intersection keeps its bar, its matrix column, its annotation marks and
 * the size bars of the sets it joins at full strength, and dims the rest.
 *
 * Read off the figure's structure rather than trace names, so it holds in every
 * colouring mode: each trace places intersections at x = 0..n-1 except the
 * horizontal set-size bars, whose y is the set index, and the dot matrix is
 * whatever sits on a y axis labelled with the set names.
 */

type Trace = Record<string, unknown>;
type Layout = Record<string, unknown>;

export const UPSET_DIMMED_OPACITY = 0.2;

function isSetSizeBars(t: Trace): boolean {
  return t.type === 'bar' && t.orientation === 'h';
}

function hasMarkers(t: Trace): boolean {
  return t.type === 'scatter' && String(t.mode ?? '').includes('markers');
}

function values(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

/** Trace references (`y`, `y2`, …) of the y axes labelled with set names. */
function setNameAxes(layout: Layout): Set<string> {
  const refs = new Set<string>();
  for (const [key, axis] of Object.entries(layout)) {
    const match = /^yaxis(\d*)$/.exec(key);
    if (match && Array.isArray((axis as { ticktext?: unknown } | null)?.ticktext)) {
      refs.add(`y${match[1]}`);
    }
  }
  return refs;
}

function isMatrixDots(t: Trace, axes: Set<string>): boolean {
  return hasMarkers(t) && axes.has(String(t.yaxis ?? 'y'));
}

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

/** `data` with every mark outside intersection `column` dimmed. */
export function emphasizeUpsetColumn(data: Trace[], layout: Layout, column: number): Trace[] {
  const axes = setNameAxes(layout);
  // The sets the intersection joins: the rows of its filled dots, the only
  // matrix dots that carry a label.
  const joined = new Set<number>();
  for (const t of data) {
    if (!isMatrixDots(t, axes) || t.hovertext == null) continue;
    const ys = values(t.y);
    values(t.x).forEach((x, i) => {
      if (Number(x) === column) joined.add(Number(ys[i]));
    });
  }

  const opacity = (kept: boolean) => (kept ? 1 : UPSET_DIMMED_OPACITY);
  return data.map((t) => {
    if (isSetSizeBars(t)) {
      return withMarkerOpacity(t, values(t.y).map((y) => opacity(joined.has(Number(y)))));
    }
    const xs = values(t.x);
    // No positions to read: legend-only entries.
    if (xs.length === 0 || xs.some((x) => x == null)) return t;
    if (t.type === 'bar' || hasMarkers(t)) {
      return withMarkerOpacity(t, xs.map((x) => opacity(Number(x) === column)));
    }
    // Matrix edges and box or violin tracks draw one intersection per trace.
    if (xs.every((x) => x === xs[0])) return { ...t, opacity: opacity(Number(xs[0]) === column) };
    return t;
  });
}
