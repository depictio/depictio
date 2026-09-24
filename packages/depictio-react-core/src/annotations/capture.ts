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
  XRange,
  YRange,
} from './types';
import { MAX_POINT_IDS } from './types';

export interface ClickedPoint {
  x?: unknown;
  y?: unknown;
}

export interface SelectedPoint {
  x?: unknown;
  y?: unknown;
  curveNumber?: number;
  customdata?: unknown;
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

/**
 * Range from a `plotly_relayout` event on the given axis. Reads
 * `xaxis.range[0]` / `xaxis.range[1]` or an `xaxis.range` array. Returns
 * null for autorange resets, other axes or unusable values.
 */
export function rangeFromRelayout(ev: Record<string, unknown> | null | undefined, axis: 'x'): XRange | null;
export function rangeFromRelayout(ev: Record<string, unknown> | null | undefined, axis: 'y'): YRange | null;
export function rangeFromRelayout(
  ev: Record<string, unknown> | null | undefined,
  axis: 'x' | 'y',
): XRange | YRange | null;
export function rangeFromRelayout(
  ev: Record<string, unknown> | null | undefined,
  axis: 'x' | 'y',
): XRange | YRange | null {
  if (!ev) return null;
  const key = `${axis}axis.range`;
  let r0: unknown = ev[`${key}[0]`];
  let r1: unknown = ev[`${key}[1]`];
  const arr = ev[key];
  if ((r0 === undefined || r1 === undefined) && Array.isArray(arr) && arr.length >= 2) {
    [r0, r1] = arr;
  }
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

/**
 * Marked points from a `plotly_selected` event. Uses selection ids when the
 * component has a selection column (`selectionColumnIndex` + `column`), plain
 * coordinates otherwise (or when no selected point carries an id). Deduped,
 * capped at MAX_POINT_IDS. Null for an empty selection.
 */
export function markedPointsFromSelection(
  ev: { points?: SelectedPoint[] } | null | undefined,
  selectionColumnIndex?: number,
  column?: string,
): MarkedPoints | null {
  const points = ev?.points ?? [];
  if (!points.length) return null;

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
    if (ids.length) return { kind: 'points', column, ids };
  }

  const coords: PointCoord[] = [];
  const seen = new Set<string>();
  for (const p of points) {
    const x = asAxisValue(p.x);
    const y = asAxisValue(p.y);
    if (x == null || y == null) continue;
    const trace = typeof p.curveNumber === 'number' ? p.curveNumber : null;
    const key = `${trace}|${typeof x}:${x}|${typeof y}:${y}`;
    if (seen.has(key)) continue;
    seen.add(key);
    coords.push(trace == null ? { x, y } : { x, y, trace });
    if (coords.length >= MAX_POINT_IDS) break;
  }
  return coords.length ? { kind: 'points', coords } : null;
}
