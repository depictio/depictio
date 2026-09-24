/**
 * Facts about an annotation as drawn on the current data (how many points it
 * marks or covers), and the one-line summaries built from them. Pure: the
 * counts are computed in `annotationsToPlotly`, next to the drawing.
 */
import type { Annotation, AxisValue, Geometry } from './types';

/**
 * Counts measured against the figure's current data. Marked points: how many
 * were asked for (`expected`) and are drawn (`found`). Ranges: how many data
 * points fall inside (`inRange`), when the axis is numeric or dates.
 */
export interface AnnotationStats {
  expected?: number;
  found?: number;
  inRange?: number;
}

/** A value for a summary: integers as is, other numbers to 4 significant digits. */
export function formatAxisValue(v: AxisValue): string {
  if (typeof v !== 'number') return v;
  if (!Number.isFinite(v) || Number.isInteger(v)) return String(v);
  const magnitude = Math.floor(Math.log10(Math.abs(v)));
  const decimals = Math.min(20, Math.max(0, 3 - magnitude));
  return String(Number(v.toFixed(decimals)));
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

function markedCount(geometry: Geometry & { kind: 'points' }): number {
  return geometry.ids?.length ?? geometry.coords?.length ?? 0;
}

/**
 * One line describing the annotation, e.g. "42 points (40 found)",
 * "x from 2.1 to 3.5 · 18 points", "y = 5", "Note at (3, 4)". `stats` adds
 * the counts measured on the current data when known.
 */
export function annotationSummary(annotation: Annotation, stats?: AnnotationStats): string {
  const g = annotation.geometry;
  const inRange = stats?.inRange != null ? ` · ${plural(stats.inRange, 'point')}` : '';
  switch (g.kind) {
    case 'x_range':
      return `x from ${formatAxisValue(g.x0)} to ${formatAxisValue(g.x1)}${inRange}`;
    case 'y_range':
      return `y from ${formatAxisValue(g.y0)} to ${formatAxisValue(g.y1)}${inRange}`;
    case 'ref_line':
      return `${g.axis} = ${formatAxisValue(g.value)}`;
    case 'points': {
      const n = stats?.expected ?? markedCount(g);
      const found = stats?.found;
      return found != null && found < n ? `${plural(n, 'point')} (${found} found)` : plural(n, 'point');
    }
    case 'arrow_note':
      return `Note at (${formatAxisValue(g.x)}, ${formatAxisValue(g.y)})`;
  }
}

/**
 * Hover text of an annotation's label on the chart (Plotly `hovertext`,
 * lines joined with `<br>`).
 */
export function annotationHoverText(annotation: Annotation, stats?: AnnotationStats): string {
  const g = annotation.geometry;
  switch (g.kind) {
    case 'x_range':
    case 'y_range': {
      const head =
        g.kind === 'x_range'
          ? `x from ${formatAxisValue(g.x0)} to ${formatAxisValue(g.x1)}`
          : `y from ${formatAxisValue(g.y0)} to ${formatAxisValue(g.y1)}`;
      return stats?.inRange != null ? `${head}<br>${plural(stats.inRange, 'point')} in range` : head;
    }
    case 'points': {
      const n = stats?.expected ?? markedCount(g);
      const found = stats?.found;
      const head = `${plural(n, 'point')} marked`;
      return found != null && found < n ? `${head}<br>${found} of ${n} found` : head;
    }
    case 'ref_line':
    case 'arrow_note':
      return annotationSummary(annotation, stats);
  }
}

/** Whether two stats maps hold the same counts (shallow, per annotation). */
export function sameStats(
  a: Record<string, AnnotationStats> | null | undefined,
  b: Record<string, AnnotationStats> | null | undefined,
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  const ka = Object.keys(a);
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => {
    const x = a[k];
    const y = b[k];
    return (
      !!y && x.expected === y.expected && x.found === y.found && x.inRange === y.inRange
    );
  });
}
