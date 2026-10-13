/**
 * Pure helpers for the funnel overview (issue #939): which data collection and
 * column the "values of a column" mode charts by default, the hover text of
 * its points, the values by stages matrix listed under that chart, and the
 * color a stage badge takes when the stage comes from a saved selection group.
 * Kept free of React so they run under the node vitest setup.
 */
import type { FunnelColumnValues, InteractiveFilter } from '../../api';
import { GROUP_FILTER_INDEX_PREFIX, type SelectionGroup } from '../../selectionGroups';

/** Values listed in one hover label before it collapses into "and N more". */
export const HOVER_VALUE_LIMIT = 15;

function filterDcId(filter: InteractiveFilter | undefined): string | null {
  const dc = filter?.metadata?.dc_id;
  return dc ? String(dc) : null;
}

/**
 * The data collection that column mode charts: the user's pick while it is still a
 * candidate, else the first active filter's DC when the overview charts it,
 * else the first candidate. An empty `dcIds` means the candidate list is not
 * known yet: the pick (or the filter's DC) is taken on trust, and the server
 * refuses it if it does not qualify.
 */
export function resolveStageDc(
  userDc: string | null,
  firstFilter: InteractiveFilter | undefined,
  dcIds: readonly string[],
): string | null {
  const filterDc = filterDcId(firstFilter);
  if (dcIds.length === 0) return userDc ?? filterDc;
  if (userDc && dcIds.includes(userDc)) return userDc;
  if (filterDc && dcIds.includes(filterDc)) return filterDc;
  return dcIds[0];
}

/**
 * The column that column mode charts on `dcId`: the user's pick, else the first
 * active filter's column when that filter reads `dcId`, else the first column.
 * `columns` is null while the schema is loading; the filter's own column is
 * then safe to request straight away, anything else waits for the schema.
 */
export function resolveStageColumn(
  userColumn: string | null,
  firstFilter: InteractiveFilter | undefined,
  dcId: string,
  columns: readonly string[] | null,
): string | null {
  const filterColumn =
    filterDcId(firstFilter) === dcId
      ? (firstFilter?.column_name ?? firstFilter?.metadata?.column_name ?? null)
      : null;
  if (columns === null) return userColumn ?? filterColumn;
  if (userColumn && columns.includes(userColumn)) return userColumn;
  if (filterColumn && columns.includes(filterColumn)) return filterColumn;
  return columns[0] ?? null;
}

/** The first `limit` values plus how many were left out. Counted against the
 *  full distinct count, so values the server's cap dropped are included. */
export function splitValues(
  values: FunnelColumnValues,
  limit: number,
): { shown: string[]; more: number } {
  const shown = values.values.slice(0, limit);
  return { shown, more: Math.max(0, values.count - shown.length) };
}

const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Hover text for one column-mode funnel point: the distinct count, then up to
 *  `limit` values, then how many more there are. Plotly renders hover labels
 *  as a subset of HTML, so the values are escaped. */
export function valuesHoverText(
  values: FunnelColumnValues | null | undefined,
  limit = HOVER_VALUE_LIMIT,
): string {
  if (!values) return 'No data';
  const { shown, more } = splitValues(values, limit);
  const lines = [
    `${values.count} distinct ${values.count === 1 ? 'value' : 'values'}`,
    ...shown.map(escapeHtml),
  ];
  if (more > 0) lines.push(`… and ${more} more`);
  return lines.join('<br>');
}

/** Rows the values matrix renders before it asks the reader to search. */
export const MATRIX_ROW_LIMIT = 200;

/** One cell of the values matrix: the value is still present after that
 *  column's stage, was removed at or before it, or cannot be told (the stage
 *  failed to load, or its capped list stops before the value). */
export type MatrixCell = 'kept' | 'removed' | 'unknown';

export interface ValuesMatrixRow {
  value: string;
  /** `cells[0]` is the unfiltered data, `cells[k]` the state after stage k. */
  cells: MatrixCell[];
  /** The last column the value is known to be in: 0 when stage 1 removes it,
   *  the stage count when it survives every stage. */
  survives: number;
  /** The 1-based stage that removed the value; null when it survives or when
   *  the removing stage cannot be told. */
  removedAt: number | null;
}

export interface ValuesMatrix {
  /** Longest survivors first, then in natural order. */
  rows: ValuesMatrixRow[];
  /** The server's full distinct counts, `[unfiltered, after stage 1, ...]`,
   *  null where a load failed. They cover values the list cap dropped. */
  counts: (number | null)[];
  /** Per stage, how many values it removed; null when either count is unknown. */
  removed: (number | null)[];
  /** Values the server counted but no list named, so they have no row. */
  unlisted: number;
  hasUnknown: boolean;
}

const naturalOrder = new Intl.Collator(undefined, { numeric: true });

/** The server's list order: Python sorts `str` by code point. JS `<` compares
 *  UTF-16 units instead, which disagrees for characters past U+FFFF. */
export function compareCodePoints(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const ca = a.codePointAt(i) ?? 0;
    const cb = b.codePointAt(i) ?? 0;
    if (ca !== cb) return ca - cb;
    if (ca > 0xffff) i++;
  }
  return a.length - b.length;
}

/**
 * The values by stages matrix: one row per distinct value any list names, one
 * cell per stage.
 *
 * Rows come from the unfiltered list AND every stage's list. Each list is
 * capped at its first values in sorted order, so a column with more distinct
 * values than the cap would otherwise lose exactly the values a narrow stage
 * keeps: they sort past the unfiltered cap but head their own short list.
 *
 * Stages are cumulative, so a value present after stage k was present at every
 * stage before it, and a row is always a run of kept cells, then removed ones
 * (with unknown cells where a failed stage leaves a gap).
 *
 * A value absent from a complete list was removed. A capped list is the sorted
 * prefix of its stage's values, so a value absent from it was removed only if
 * it sorts at or before the list's last value; past that it may simply be
 * beyond the cap, and the cell is unknown.
 */
export function buildValuesMatrix(
  initial: FunnelColumnValues | null | undefined,
  stages: readonly (FunnelColumnValues | null | undefined)[],
): ValuesMatrix {
  const listed = new Set([...(initial?.values ?? []), ...stages.flatMap((s) => s?.values ?? [])]);
  const sets = stages.map((s) => (s ? new Set(s.values) : null));
  let hasUnknown = false;

  const rows = [...listed].map((value): ValuesMatrixRow => {
    const present = stages.map((s, k): boolean | null => {
      const set = sets[k];
      if (!s || !set) return null;
      if (set.has(value)) return true;
      if (!s.truncated) return false;
      const last = s.values[s.values.length - 1];
      return last !== undefined && compareCodePoints(value, last) <= 0 ? false : null;
    });
    const survives = present.lastIndexOf(true) + 1;
    const gone = present.indexOf(false, survives);
    const removedAt = gone === -1 ? null : gone + 1;
    const cells: MatrixCell[] = [
      'kept',
      ...present.map((_, k): MatrixCell => {
        if (k + 1 <= survives) return 'kept';
        if (removedAt !== null && k + 1 >= removedAt) return 'removed';
        return 'unknown';
      }),
    ];
    if (cells.includes('unknown')) hasUnknown = true;
    return { value, cells, survives, removedAt };
  });
  rows.sort((a, b) => b.survives - a.survives || naturalOrder.compare(a.value, b.value));

  const counts = [initial?.count ?? null, ...stages.map((s) => s?.count ?? null)];
  const removed = stages.map((_, k) => {
    const before = counts[k];
    const after = counts[k + 1];
    return before === null || after === null ? null : Math.max(0, before - after);
  });
  // Every listed value is in the unfiltered data, so what the unfiltered count
  // has beyond the rows is the values no list named.
  const unlisted = initial ? Math.max(0, initial.count - rows.length) : 0;
  return { rows, counts, removed, unlisted, hasUnknown };
}

/** Rows whose value contains `query`, case-insensitively. */
export function filterMatrixRows(
  rows: readonly ValuesMatrixRow[],
  query: string,
): readonly ValuesMatrixRow[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((r) => r.value.toLowerCase().includes(needle));
}

/** Accessible name for one matrix cell. `columns[0]` names the unfiltered
 *  data and `columns[k]` stage k. A removed cell names the stage that removed
 *  the value, which is the same for every removed cell of the row. */
export function matrixCellLabel(
  row: ValuesMatrixRow,
  column: number,
  columns: readonly string[],
): string {
  const name = columns[column] ?? `stage ${column}`;
  if (column === 0) return `${row.value} in ${name}`;
  switch (row.cells[column]) {
    case 'kept':
      return `${row.value} kept after ${name}`;
    case 'removed':
      return `${row.value} removed by ${row.removedAt === null ? name : (columns[row.removedAt] ?? name)}`;
    default:
      return `${row.value} unknown after ${name}`;
  }
}

/** A distinct count for display, "?" standing in for one that failed to load. */
export function formatCount(n: number | null): string {
  return n === null ? '?' : n.toLocaleString();
}

/** "4 values → 1 remains": the unfiltered distinct count, then what the last
 *  stage leaves. "?" stands in for a count that failed to load. */
export function matrixSummary(counts: readonly (number | null)[]): string {
  const start = counts[0] ?? null;
  const end = counts[counts.length - 1] ?? null;
  return `${formatCount(start)} ${start === 1 ? 'value' : 'values'} → ${formatCount(end)} ${end === 1 ? 'remains' : 'remain'}`;
}

/**
 * The color of the saved group a stage comes from, or null when the stage is
 * not a group filter. `groupsToFilters` merges every active group on one
 * `(dcId, columnName)` into a single filter; a merged stage has no one group's
 * color, so it is null too. The key format mirrors `groupsToFilters`.
 */
export function groupStageColor(
  filter: InteractiveFilter,
  groups: readonly SelectionGroup[],
): string | null {
  const index = String(filter.index);
  if (!index.startsWith(GROUP_FILTER_INDEX_PREFIX)) return null;
  const key = index.slice(GROUP_FILTER_INDEX_PREFIX.length);
  const matching = groups.filter(
    (g) => g.filterActive && `${g.dcId ?? ''}:${g.columnName}` === key,
  );
  return matching.length === 1 ? matching[0].color : null;
}
