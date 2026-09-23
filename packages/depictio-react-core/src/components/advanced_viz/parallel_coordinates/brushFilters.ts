/**
 * Turning an axis brush into dashboard filters, and back.
 *
 * Plotly reports a `parcoords` brush as `dimensions[i].constraintrange` on a
 * restyle event, in the axis's *plotted* units. Everything interesting
 * happens between that and a filter the rest of the dashboard understands:
 * the index has to become a column, the range has to come back out of
 * whatever normalisation the axis applied, and several brushed axes have to
 * coexist as separate entries.
 *
 * Shape of the emitted entry: a `RangeSlider` filter on the brushed column,
 * exactly what the sidebar's own range control emits, because that is exactly
 * what the reader did, carried under `source: 'axis_selection'` so the rest
 * of the dashboard can tell a gesture made on a tile from a value typed into
 * a control. That is what lets a clear-selections pass reach a brush: without
 * a source it reads as an ordinary control value and survives one.
 *
 * It is still not a group candidate. `SELECTION_SOURCES` in
 * `selectionGroups.ts` lists the sources the Analysis panel offers to save as
 * a group, and those carry a list of picked values; a numeric range saved
 * that way would become a group of two values (the two endpoints) matching
 * almost nothing. `axis_selection` is deliberately absent from it, as
 * `genome_selection` is, and for the same reason.
 *
 * The index carries the column, the way the genome brush's position half does
 * (`genomePosFilterIndex` in selection.ts): `mergeFiltersBySource` keeps one
 * entry per `(index, source)` pair, and a tile with four brushed axes needs
 * four.
 */

import type { InteractiveFilter } from '../../../api';

/** Separator between the emitting tile's index and the axis it brushed. */
export const AXIS_INDEX_SEPARATOR = '::';

export function axisFilterIndex(componentIndex: string, column: string): string {
  return `${componentIndex}${AXIS_INDEX_SEPARATOR}${column}`;
}

/** Brushed axes, keyed by column, in the column's own units. */
export type AxisBrushes = Record<string, [number, number]>;

const CONSTRAINT_KEY = /^dimensions\[(\d+)\]\.constraintrange$/;

/**
 * The envelope of a `constraintrange` value, whatever plotly nested it in.
 *
 * The same brush arrives as `[lo, hi]`, as `[[lo, hi]]` (wrapped per trace),
 * or as `[[lo, hi], [lo2, hi2]]` when the reader drew two windows on one
 * axis. A filter is one range, so every number in there is flattened and the
 * outer bounds win: two windows narrow to the span that covers both, which
 * shows the reader more rows than they asked for rather than fewer.
 */
function constraintEnvelope(value: unknown): [number, number] | null {
  const numbers: number[] = [];
  const walk = (v: unknown): void => {
    if (Array.isArray(v)) {
      v.forEach(walk);
      return;
    }
    if (v === null || v === undefined || v === '') return;
    const n = Number(v);
    if (Number.isFinite(n)) numbers.push(n);
  };
  walk(value);
  if (numbers.length < 2) return null;
  const lo = Math.min(...numbers);
  const hi = Math.max(...numbers);
  // A brush with no width selects nothing; plotly emits one while the pointer
  // is still on its first pixel.
  return hi > lo ? [lo, hi] : null;
}

/** Brushed dimensions in a `plotly_restyle` payload, in plotted units. */
export function parseConstraintUpdate(update: unknown): Map<number, [number, number] | null> {
  const out = new Map<number, [number, number] | null>();
  if (!update || typeof update !== 'object') return out;
  for (const [key, value] of Object.entries(update as Record<string, unknown>)) {
    const match = CONSTRAINT_KEY.exec(key);
    if (!match) continue;
    out.set(Number(match[1]), constraintEnvelope(value));
  }
  return out;
}

/**
 * The brush state after a restyle, in the columns' own units.
 *
 * `toOriginal` is the per-axis inversion from `axisScaling`, so a brush drawn
 * on a z-scored axis leaves here as the read counts it stands for. Brushes on
 * columns that are no longer axes are dropped: an axis the reader removed is
 * not a filter they are still asking for.
 */
export function applyConstraintUpdate(
  current: AxisBrushes,
  parsed: ReadonlyMap<number, [number, number] | null>,
  columns: readonly string[],
  toOriginal: (column: string, value: number) => number,
): AxisBrushes {
  const next: AxisBrushes = { ...current };
  for (const [dimension, range] of parsed) {
    const column = columns[dimension];
    if (!column) continue;
    if (!range) {
      delete next[column];
      continue;
    }
    const lo = toOriginal(column, range[0]);
    const hi = toOriginal(column, range[1]);
    next[column] = lo <= hi ? [lo, hi] : [hi, lo];
  }
  for (const column of Object.keys(next)) {
    if (!columns.includes(column)) delete next[column];
  }
  return next;
}

export interface AxisFilterBase {
  /** The emitting tile's index. */
  index: string;
  /** Its collection, so the server can resolve the filter across links. The
   *  viewer's own enrichment looks the index up among the dashboard's
   *  components and cannot find a suffixed one, so the tile carries it. */
  dcId?: string;
}

/** The filter entry one brushed axis emits. `null` is the cleared form. */
export function axisRangeFilter(
  base: AxisFilterBase,
  column: string,
  range: [number, number] | null,
): InteractiveFilter {
  return {
    index: axisFilterIndex(base.index, column),
    // `[]` rather than null, which is the cleared shape every other emitter
    // uses and the one `mergeFiltersBySource` drops.
    value: range ?? [],
    column_name: column,
    interactive_component_type: 'RangeSlider',
    source: 'axis_selection',
    metadata: {
      dc_id: base.dcId,
      column_name: column,
      interactive_component_type: 'RangeSlider',
    },
  };
}

/** Whether two brush states say the same thing, so a restyle that changed
 *  nothing this tile cares about costs no render and no emit. */
export function sameBrushes(a: AxisBrushes, b: AxisBrushes): boolean {
  const columns = Object.keys(a);
  if (columns.length !== Object.keys(b).length) return false;
  return columns.every((column) => {
    const other = b[column];
    return Boolean(other) && a[column][0] === other[0] && a[column][1] === other[1];
  });
}

/**
 * Only the axes whose brush actually moved, so dragging one axis does not
 * republish the other three and retrigger every tile that follows them.
 */
export function brushFilterUpdates(
  previous: AxisBrushes,
  next: AxisBrushes,
  base: AxisFilterBase,
): InteractiveFilter[] {
  const columns = new Set([...Object.keys(previous), ...Object.keys(next)]);
  const out: InteractiveFilter[] = [];
  for (const column of columns) {
    const before = previous[column];
    const after = next[column];
    if (before && after && before[0] === after[0] && before[1] === after[1]) continue;
    if (!before && !after) continue;
    out.push(axisRangeFilter(base, column, after ?? null));
  }
  return out;
}

/**
 * The filters this tile should render against: every dashboard filter except
 * the ones its own brushes emitted.
 *
 * A tile that narrowed itself by its own brush would redraw as only the
 * polylines it caught, and the brush could never be widened again.
 */
export function filtersExcludingOwnBrushes(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
): InteractiveFilter[] {
  const prefix = `${componentIndex}${AXIS_INDEX_SEPARATOR}`;
  return filters.filter(
    (filter) => filter.index !== componentIndex && !String(filter.index).startsWith(prefix),
  );
}
