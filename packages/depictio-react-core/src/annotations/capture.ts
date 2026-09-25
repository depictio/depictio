/**
 * Pure helpers turning Plotly events into annotation geometry, for the
 * "Annotate" mode: drag a range, click for a line or a note, lasso points.
 */
import type {
  ArrowNote,
  AxisValue,
  MarkedPoints,
  PointCoord,
  RefLine,
  SelectionRegion,
  XRange,
  YRange,
} from './types';
import { MAX_POINT_IDS, MAX_REGION_VERTICES } from './types';
import { POSITIONED_TRACE_TYPES } from './renderedPoints';

export interface ClickedPoint {
  x?: unknown;
  y?: unknown;
}

export interface SelectedPoint {
  x?: unknown;
  y?: unknown;
  curveNumber?: number;
  pointNumber?: unknown;
  pointIndex?: unknown;
  customdata?: unknown;
  data?: { type?: unknown } | null;
  fullData?: { type?: unknown } | null;
}

/**
 * Index of a selected point in its trace's data, for the trace types drawn
 * away from their data x/y (see POSITIONED_TRACE_TYPES); null otherwise.
 */
function positionedIndex(p: SelectedPoint): number | null {
  const type = p.fullData?.type ?? p.data?.type;
  if (typeof type !== 'string' || !POSITIONED_TRACE_TYPES.has(type)) return null;
  const i = typeof p.pointNumber === 'number' ? p.pointNumber : p.pointIndex;
  return typeof i === 'number' && Number.isInteger(i) && i >= 0 ? i : null;
}

function asAxisValue(v: unknown): AxisValue | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v !== '') return v;
  return null;
}

function orderPair(a: AxisValue, b: AxisValue): [AxisValue, AxisValue] {
  if (typeof a === 'number' && typeof b === 'number' && a > b) return [b, a];
  if (typeof a === 'string' && typeof b === 'string' && a > b) return [b, a];
  return [a, b];
}

/** Two bounds as a range on `axis`, ordered; null when unusable or empty. */
function rangeFromBounds(r0: unknown, r1: unknown, axis: 'x' | 'y'): XRange | YRange | null {
  if (axis === 'y') {
    const y0 = typeof r0 === 'string' ? Number(r0) : r0;
    const y1 = typeof r1 === 'string' ? Number(r1) : r1;
    if (typeof y0 !== 'number' || typeof y1 !== 'number') return null;
    if (!Number.isFinite(y0) || !Number.isFinite(y1) || y0 === y1) return null;
    return { kind: 'y_range', y0: Math.min(y0, y1), y1: Math.max(y0, y1) };
  }
  const a = asAxisValue(r0);
  const b = asAxisValue(r1);
  if (a == null || b == null || a === b) return null;
  const [x0, x1] = orderPair(a, b);
  return { kind: 'x_range', x0, x1 };
}

/**
 * Range from a box `plotly_selected` event, on the given axis of the main
 * subplot: `range.x` / `range.y`, else the newest rectangle of `selections`.
 * The other axis of the box is ignored. Null for a lasso, another subplot's
 * box or unusable values.
 */
export function rangeFromSelection(ev: SelectionEvent | null | undefined, axis: 'x'): XRange | null;
export function rangeFromSelection(ev: SelectionEvent | null | undefined, axis: 'y'): YRange | null;
export function rangeFromSelection(
  ev: SelectionEvent | null | undefined,
  axis: 'x' | 'y',
): XRange | YRange | null;
export function rangeFromSelection(
  ev: SelectionEvent | null | undefined,
  axis: 'x' | 'y',
): XRange | YRange | null {
  if (!ev) return null;
  const bounds = ev.range?.[axis];
  if (Array.isArray(bounds) && bounds.length >= 2) return rangeFromBounds(bounds[0], bounds[1], axis);
  const last = Array.isArray(ev.selections) ? ev.selections[ev.selections.length - 1] : null;
  if (!last || last.type !== 'rect') return null;
  const ref = last[`${axis}ref`];
  if (ref != null && ref !== axis) return null;
  return rangeFromBounds(last[`${axis}0`], last[`${axis}1`], axis);
}

/** Reference line through a clicked point, across the given axis. */
export function refLineFromClick(
  point: ClickedPoint | null | undefined,
  axis: 'x' | 'y',
): RefLine | null {
  const value = asAxisValue(axis === 'x' ? point?.x : point?.y);
  return value == null ? null : { kind: 'ref_line', axis, value };
}

/** Arrow note pointing at a clicked point, label offset up-left. */
export function arrowNoteFromClick(point: ClickedPoint | null | undefined): ArrowNote | null {
  const x = asAxisValue(point?.x);
  const y = asAxisValue(point?.y);
  if (x == null || y == null) return null;
  return { kind: 'arrow_note', x, y, ax: -40, ay: -40 };
}

function idFromCustomdata(cd: unknown, col: number): string | number | null {
  const v = Array.isArray(cd) ? cd[col] : col === 0 ? cd : undefined;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v !== '') return v;
  return null;
}

/** The parts of a `plotly_selected` event that describe the selected area. */
export interface SelectionEvent {
  points?: SelectedPoint[];
  /** Box selection: `{x: [a, b], y: [c, d]}`. */
  range?: { x?: unknown[]; y?: unknown[] } | null;
  /** Lasso selection: the traced vertices. */
  lassoPoints?: { x?: unknown[]; y?: unknown[] } | null;
  /** Plotly >= 2.13: the drawn selection shapes, the last one being the newest. */
  selections?: Array<Record<string, unknown>> | null;
}

/** At most `max` items, picked evenly so a long lasso keeps its outline. */
function thin<T>(values: T[], max: number): T[] {
  if (values.length <= max) return values;
  const step = values.length / max;
  return Array.from({ length: max }, (_, i) => values[Math.floor(i * step)]);
}

function boxRegion(x: unknown[] | undefined, y: unknown[] | undefined): SelectionRegion | null {
  if (!Array.isArray(x) || !Array.isArray(y) || x.length < 2 || y.length < 2) return null;
  const [x0, x1] = [asAxisValue(x[0]), asAxisValue(x[1])];
  const [y0, y1] = [asAxisValue(y[0]), asAxisValue(y[1])];
  if (x0 == null || x1 == null || y0 == null || y1 == null) return null;
  const [ox0, ox1] = orderPair(x0, x1);
  const [oy0, oy1] = orderPair(y0, y1);
  return { shape: 'box', x0: ox0, x1: ox1, y0: oy0, y1: oy1 };
}

function lassoRegion(x: unknown[] | undefined, y: unknown[] | undefined): SelectionRegion | null {
  if (!Array.isArray(x) || !Array.isArray(y) || x.length !== y.length) return null;
  const xs: AxisValue[] = [];
  const ys: AxisValue[] = [];
  for (let i = 0; i < x.length; i++) {
    const a = asAxisValue(x[i]);
    const b = asAxisValue(y[i]);
    if (a == null || b == null) continue;
    xs.push(a);
    ys.push(b);
  }
  if (xs.length < 3) return null;
  return { shape: 'lasso', x: thin(xs, MAX_REGION_VERTICES), y: thin(ys, MAX_REGION_VERTICES) };
}

/** Vertices of an SVG path made of M/L commands (what Plotly stores for a lasso). */
function parsePath(path: unknown): { x: number[]; y: number[] } | null {
  if (typeof path !== 'string') return null;
  const x: number[] = [];
  const y: number[] = [];
  for (const m of path.matchAll(/[ML]\s*(-?[\d.eE+-]+)\s*,\s*(-?[\d.eE+-]+)/g)) {
    const a = Number(m[1]);
    const b = Number(m[2]);
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    x.push(a);
    y.push(b);
  }
  return x.length ? { x, y } : null;
}

/**
 * The area a `plotly_selected` event covered, in data coordinates: `range`
 * for a box, `lassoPoints` for a lasso, else the newest entry of
 * `selections`. On a category axis Plotly reports positions as category
 * serial numbers (e.g. -0.3..1.4), which shapes take as is: they are kept.
 * Null when the event carries none of them.
 */
export function regionFromSelection(ev: SelectionEvent | null | undefined): SelectionRegion | null {
  if (!ev) return null;
  if (ev.range) {
    const box = boxRegion(ev.range.x, ev.range.y);
    if (box) return box;
  }
  if (ev.lassoPoints) {
    const lasso = lassoRegion(ev.lassoPoints.x, ev.lassoPoints.y);
    if (lasso) return lasso;
  }
  const last = Array.isArray(ev.selections) ? ev.selections[ev.selections.length - 1] : null;
  if (!last) return null;
  if (last.type === 'rect') return boxRegion([last.x0, last.x1], [last.y0, last.y1]);
  if (last.type === 'path') {
    const v = parsePath(last.path);
    return v ? lassoRegion(v.x, v.y) : null;
  }
  return null;
}

/**
 * Marked points from a `plotly_selected` event. Uses selection ids when the
 * component has a selection column (`selectionColumnIndex` + `column`), plain
 * coordinates otherwise (or when no selected point carries an id). Deduped,
 * capped at MAX_POINT_IDS. The selected area is kept as `region` when the
 * event describes it. Null for an empty selection.
 */
export function markedPointsFromSelection(
  ev: SelectionEvent | null | undefined,
  selectionColumnIndex?: number,
  column?: string,
): MarkedPoints | null {
  const points = ev?.points ?? [];
  if (!points.length) return null;
  const region = regionFromSelection(ev);
  const withRegion = (g: MarkedPoints): MarkedPoints => (region ? { ...g, region } : g);

  if (selectionColumnIndex != null && selectionColumnIndex >= 0 && column) {
    const ids: Array<string | number> = [];
    const seen = new Set<string>();
    for (const p of points) {
      const id = idFromCustomdata(p.customdata, selectionColumnIndex);
      if (id == null) continue;
      const key = `${typeof id}:${id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      ids.push(id);
      if (ids.length >= MAX_POINT_IDS) break;
    }
    if (ids.length) return withRegion({ kind: 'points', column, ids });
  }

  const coords: PointCoord[] = [];
  const seen = new Set<string>();
  for (const p of points) {
    const x = asAxisValue(p.x);
    const y = asAxisValue(p.y);
    if (x == null || y == null) continue;
    const trace = typeof p.curveNumber === 'number' ? p.curveNumber : null;
    const index = trace == null ? null : positionedIndex(p);
    // Box points sharing a category and a value are distinct marks.
    const key = `${trace}|${typeof x}:${x}|${typeof y}:${y}|${index}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const coord: PointCoord = trace == null ? { x, y } : { x, y, trace };
    if (index != null) coord.index = index;
    coords.push(coord);
    if (coords.length >= MAX_POINT_IDS) break;
  }
  return coords.length ? withRegion({ kind: 'points', coords }) : null;
}
