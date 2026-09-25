/**
 * Where Plotly actually drew the points of traces whose marks sit away from
 * their data coordinates: box and violin points (group offset, `pointpos`,
 * jitter), bars (group offset, stacking) and scatter traces grouped by
 * `scattermode: 'group'`. Read from the graph div's
 * `calcdata` once Plotly has plotted, so marked-point rings can be drawn on
 * the mark rather than at the category centre. Pure: the graph div is only
 * read through the loose shapes below, and everything is unit tested.
 */
import type { AxisValue, PointCoord } from './types';

/** Trace types whose points are drawn away from their data x/y (scatter only when grouped). */
export const POSITIONED_TRACE_TYPES: ReadonlySet<string> = new Set(['box', 'violin', 'bar']);

/** A drawn point: `x`/`y` in axis range coords (what shapes take), plus the data it shows. */
export interface RenderedPoint {
  x: AxisValue;
  y: AxisValue;
  /**
   * Drawn position as Plotly reports it in selection events (`c2d`): the
   * category name on category axes, the offset position on numeric ones.
   */
  pos: unknown;
  /** Value as Plotly reports it in selection events. */
  value: unknown;
}

export interface RenderedTrace {
  /** Position axis letter: 'x' for vertical boxes and bars. */
  posLetter: 'x' | 'y';
  /** By point index in the trace's data. */
  byIndex: Map<number, RenderedPoint>;
  /** Every drawn point, in calcdata order (for matching by position and value). */
  points: RenderedPoint[];
}

/** Rendered points per trace index of the figure. */
export type RenderedPoints = Map<number, RenderedTrace>;

interface AxisLike {
  type?: string;
  c2d?: (v: number) => unknown;
  c2r?: (v: number) => unknown;
}

interface FullTraceLike {
  type?: string;
  visible?: unknown;
  orientation?: string;
  xaxis?: string;
  yaxis?: string;
}

/** The parts of a Plotly graph div read here. */
export interface GraphLike {
  calcdata?: unknown;
  _fullData?: unknown;
  _fullLayout?: { xaxis?: AxisLike; yaxis?: AxisLike; scattermode?: string } | null;
}

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

function converter(ax: AxisLike | undefined, fn: 'c2d' | 'c2r'): (v: number) => unknown {
  const f = ax?.[fn];
  return typeof f === 'function' ? (v: number) => f.call(ax, v) : (v: number) => v;
}

function asAxisValue(v: unknown): AxisValue | null {
  if (isNum(v)) return v;
  if (typeof v === 'string' && v !== '') return v;
  return null;
}

/**
 * The drawn points of every visible box, violin, bar (and grouped scatter)
 * trace on the main x/y subplot, or null when the graph has none (or has not
 * plotted yet). Box and violin points exist only when the trace shows them
 * (`boxpoints` / `points`); Plotly fills in their position once plotted.
 * Bars and grouped scatter points carry their offset position in calcdata.
 */
export function renderedPointsFromGraph(gd: GraphLike | null | undefined): RenderedPoints | null {
  const calcdata = gd?.calcdata;
  const fullData = gd?._fullData;
  const layout = gd?._fullLayout;
  if (!Array.isArray(calcdata) || !Array.isArray(fullData) || !layout) return null;
  const xa = layout.xaxis;
  const ya = layout.yaxis;
  const out: RenderedPoints = new Map();

  fullData.forEach((raw, t) => {
    const trace = raw as FullTraceLike | null;
    const type = trace?.type;
    const grouped = type === 'scatter' && layout.scattermode === 'group';
    if (!type || !(POSITIONED_TRACE_TYPES.has(type) || grouped) || trace.visible !== true) return;
    if ((trace.xaxis ?? 'x') !== 'x' || (trace.yaxis ?? 'y') !== 'y') return;
    const cd = calcdata[t];
    if (!Array.isArray(cd)) return;
    const horizontal = trace.orientation === 'h';
    const posLetter = horizontal ? 'y' : 'x';
    const valLetter = horizontal ? 'x' : 'y';
    const posAx = horizontal ? ya : xa;
    const valAx = horizontal ? xa : ya;
    const posD = converter(posAx, 'c2d');
    const valD = converter(valAx, 'c2d');
    const toX = converter(xa, 'c2r');
    const toY = converter(ya, 'c2r');
    const byIndex = new Map<number, RenderedPoint>();
    const points: RenderedPoint[] = [];
    const add = (index: unknown, posC: number, valC: number) => {
      const x = asAxisValue(toX(horizontal ? valC : posC));
      const y = asAxisValue(toY(horizontal ? posC : valC));
      if (x == null || y == null) return;
      const point: RenderedPoint = { x, y, pos: posD(posC), value: valD(valC) };
      points.push(point);
      if (Number.isInteger(index) && (index as number) >= 0) byIndex.set(index as number, point);
    };

    if (type === 'box' || type === 'violin') {
      for (const d of cd as Array<Record<string, unknown> | null>) {
        if (!d || !Array.isArray(d.pts)) continue;
        for (const pt of d.pts as Array<Record<string, unknown> | null>) {
          // Points of a trace that hides them never get a position.
          if (!pt || !isNum(pt[posLetter]) || !isNum(pt.v)) continue;
          add(pt.i, pt[posLetter] as number, pt.v);
        }
      }
    } else {
      // One calcdata item per data point: the offset centre of the bar (or
      // grouped marker) on the position axis, its top on the value axis.
      cd.forEach((di: Record<string, unknown> | null, j) => {
        if (di && isNum(di[posLetter]) && isNum(di[valLetter])) {
          add(j, di[posLetter] as number, di[valLetter] as number);
        }
      });
    }
    if (points.length) out.set(t, { posLetter, byIndex, points });
  });
  return out.size ? out : null;
}

/**
 * A cheap fingerprint of the rendered positions, to skip state updates (and
 * redraws) when a re-plot put every point back where it was.
 */
export function renderedPointsSignature(rendered: RenderedPoints | null): string {
  if (!rendered) return '';
  const parts: string[] = [];
  for (const [t, trace] of rendered) {
    let sx = 0;
    let sy = 0;
    for (const p of trace.points) {
      sx += isNum(p.x) ? p.x : 0;
      sy += isNum(p.y) ? p.y : 0;
    }
    parts.push(`${t}:${trace.points.length}:${sx.toFixed(6)}:${sy.toFixed(6)}`);
  }
  return parts.join('|');
}

/** Same number (up to float noise) or same text. */
export function sameAxisValue(a: unknown, b: unknown): boolean {
  if (isNum(a) && isNum(b)) return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
  return a != null && b != null && String(a) === String(b);
}

/** Whether a drawn point shows the data point `(x, y)` of a trace oriented by `posLetter`. */
export function renderedPointShows(point: RenderedPoint, posLetter: 'x' | 'y', x: unknown, y: unknown): boolean {
  const [pos, value] = posLetter === 'x' ? [x, y] : [y, x];
  return sameAxisValue(point.pos, pos) && sameAxisValue(point.value, value);
}

/**
 * Where the marked point `coord` is drawn, when its trace is one of the
 * positioned ones: by its stored `index` when that point still shows the
 * stored values (filters or a re-ingest shift indexes), else the first drawn
 * point with the same position and value not in `used` yet; null when none
 * matches (the point is missing). Undefined when the trace is not positioned
 * (or not plotted yet): the point is drawn at its data coordinates.
 */
export function findRenderedPoint(
  rendered: RenderedPoints | null | undefined,
  coord: PointCoord,
  used?: Set<RenderedPoint>,
): RenderedPoint | null | undefined {
  if (!rendered || coord.trace == null) return undefined;
  const trace = rendered.get(coord.trace);
  if (!trace) return undefined;
  const fits = (p: RenderedPoint | undefined): p is RenderedPoint =>
    !!p && !used?.has(p) && renderedPointShows(p, trace.posLetter, coord.x, coord.y);
  if (coord.index != null) {
    const p = trace.byIndex.get(coord.index);
    if (fits(p)) return p;
  }
  return trace.points.find(fits) ?? null;
}
