/**
 * Data plumbing shared by the `msa` and `sequence_track` renderers: which
 * dashboard filters reach their fetches, the one-entity filter they add, and
 * column-oriented row helpers. Pure, unit-tested in `rendererData.test.ts`.
 */

import type { InteractiveFilter } from '../../../api';
import {
  chainSelectionFilterIndex,
  filterColumn,
  isResidueFilter,
  residueRangeFilterIndex,
} from '../../../selection';

/**
 * Drop every SELECTION filter on a residue-position column.
 *
 * A picked residue range is a place to look, not a subset: the protein tiles
 * keep drawing the whole sequence and shade the range instead (read back with
 * `residueRangeFromFilters` from the unfiltered list). A sidebar slider on the
 * same column has no `source` and still narrows, as any dashboard filter does.
 */
export function withoutPositionSelections(
  filters: readonly InteractiveFilter[],
  positionColumns: ReadonlyArray<string | null | undefined>,
): InteractiveFilter[] {
  const cols = new Set(positionColumns.filter((c): c is string => Boolean(c)));
  return filters.filter((f) => !(f.source && cols.has(filterColumn(f) ?? '')));
}

/**
 * Distinct entities of a column, the one with the most rows first (ties keep
 * their first-appearance order). The order every protein tile opens on, so a
 * structure, a sequence track and an alignment of the same table start on the
 * same protein (`distinctEntities` on molecule_3d, `useEntityPicker` here).
 */
export function entitiesByRowCount(values: readonly unknown[]): string[] {
  const count = new Map<string, number>();
  for (const v of values) {
    if (v === null || v === undefined || v === '') continue;
    const key = String(v);
    count.set(key, (count.get(key) ?? 0) + 1);
  }
  return Array.from(count.keys()).sort((a, b) => (count.get(b) ?? 0) - (count.get(a) ?? 0));
}

/**
 * A plain `MultiSelect` filter narrowing a fetch to one entity (or alignment),
 * so a proteome-sized table is never pulled whole for the one protein on
 * screen. Keyed off the tile's own index; it is never emitted to the
 * dashboard, only sent with the tile's own fetch.
 */
export function entityScopeFilter(
  componentIndex: string,
  dcId: string | undefined,
  column: string,
  value: string,
): InteractiveFilter {
  return {
    index: `${componentIndex}::scope`,
    value: [value],
    column_name: column,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: dcId,
      column_name: column,
      interactive_component_type: 'MultiSelect',
    },
  };
}

/**
 * `filters` narrowed to one entity: the tile's scope filter replaces any other
 * filter on the entity column, so a pick that differs from the dashboard's
 * never intersects to nothing. Unchanged when there is no column or entity.
 */
export function scopeToEntity(
  filters: InteractiveFilter[],
  componentIndex: string,
  dcId: string | undefined,
  column: string | null | undefined,
  entity: string | null,
): InteractiveFilter[] {
  if (!column || !entity) return filters;
  return [
    ...filters.filter((f) => filterColumn(f) !== column),
    entityScopeFilter(componentIndex, dcId, column, entity),
  ];
}

/** Whether the tile's own residue pick (either half) currently holds a value. */
export function hasOwnResiduePick(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
): boolean {
  const rangeIndex = residueRangeFilterIndex(componentIndex);
  return filters.some(
    (f) =>
      isResidueFilter(f) &&
      (f.index === componentIndex || f.index === rangeIndex) &&
      Array.isArray(f.value) &&
      f.value.length > 0,
  );
}

/** Index of the chain half of a tile's residue pick on a complex (lives in
 *  selection.ts, beside the other halves' indices, so `ownSelection` sees it). */
export { chainSelectionFilterIndex };

/**
 * The chain half of a complex's residue pick, beside the entity / range pair
 * `residueRangeFilters` emits: a `MultiSelect` on the residue tables' chain
 * column, same `residue_selection` source, so resetting the selection clears
 * it with the rest. `null` returns the cleared form.
 */
export function chainSelectionFilter(
  componentIndex: string,
  dcId: string | undefined,
  column: string,
  chain: string | null,
): InteractiveFilter {
  return {
    index: chainSelectionFilterIndex(componentIndex),
    value: chain ? [chain] : [],
    source: 'residue_selection',
    column_name: column,
    interactive_component_type: 'MultiSelect',
    metadata: {
      dc_id: dcId,
      column_name: column,
      interactive_component_type: 'MultiSelect',
      selection_column: column,
    },
  };
}

/** Drop a tile's own chain pick (it draws the chain the reader picked, not
 *  only the rows of it). */
export function withoutOwnChainPick(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
): InteractiveFilter[] {
  const own = chainSelectionFilterIndex(componentIndex);
  return filters.filter((f) => !(f.source === 'residue_selection' && f.index === own));
}

/** The selected values a component's own `scatter_selection` holds. */
export function ownSelectionValues(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
): string[] {
  for (const f of filters) {
    if (f.index === componentIndex && f.source === 'scatter_selection' && Array.isArray(f.value)) {
      return f.value.map((v) => String(v));
    }
  }
  return [];
}

/** Values another component (or the sidebar) selected on `column`. */
export function foreignValuesOn(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
  column: string,
): string[] {
  const out: string[] = [];
  for (const f of filters) {
    if (f.index === componentIndex || filterColumn(f) !== column) continue;
    if (Array.isArray(f.value)) for (const v of f.value) out.push(String(v));
  }
  return out;
}

/** The named columns, deduplicated, in order (unset roles dropped). */
export function distinctColumns(columns: ReadonlyArray<string | null | undefined>): string[] {
  return Array.from(new Set(columns.filter((c): c is string => Boolean(c))));
}

/** The first value of `column` as a string, or null when the frame lacks it. */
export function firstValueOf(
  rows: Record<string, unknown[]> | null | undefined,
  column: string | null | undefined,
): string | null {
  const col = column ? rows?.[column] : undefined;
  return col && col.length ? String(col[0]) : null;
}

/** Row count of a column-oriented frame. */
export function frameLength(rows: Record<string, unknown[]> | null | undefined): number {
  if (!rows) return 0;
  for (const col of Object.values(rows)) return col?.length ?? 0;
  return 0;
}

/** Indices of the rows whose `column` equals `value` (all rows when the frame
 *  lacks the column: the server already scoped it, or the table has one entity). */
export function rowIndicesWhere(
  rows: Record<string, unknown[]>,
  column: string | null | undefined,
  value: string | null,
): number[] {
  const n = frameLength(rows);
  const col = column ? rows[column] : undefined;
  const out: number[] = [];
  for (let i = 0; i < n; i++) {
    if (!col || value == null || String(col[i]) === value) out.push(i);
  }
  return out;
}

/** A finite number, or null. */
export function numberOrNull(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** A non-empty string, or null. */
export function stringOrNull(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  const s = String(v);
  return s === '' ? null : s;
}
