/**
 * One record, several rows.
 *
 * A collection keyed on more than `id_col` (a gene at every clustering
 * resolution, a sample per callset) answers a pick with several rows. The card
 * shows one of them at a time and lets the reader step through the others by
 * the columns that tell the rows apart, rather than stacking one card per row
 * until the tile is a scrolling column of near-identical cards.
 */

import { formatFieldValue } from './recordFields';

export type RecordRow = Record<string, unknown>;

/** How many columns a row label is built from. */
const MAX_LABEL_COLUMNS = 2;

/**
 * The columns whose values differ across `rows`, in `columns` order, capped at
 * `max`. Empty when there is one row or the rows are identical on every
 * listed column.
 */
export function distinguishingColumns(
  rows: readonly RecordRow[],
  columns: readonly string[],
  max: number = MAX_LABEL_COLUMNS,
): string[] {
  if (rows.length < 2) return [];
  const out: string[] = [];
  for (const column of columns) {
    const first = formatFieldValue(rows[0]?.[column]);
    if (rows.some((row) => formatFieldValue(row[column]) !== first)) {
      out.push(column);
      if (out.length >= max) break;
    }
  }
  return out;
}

/** The label a row picker shows for `row`: its distinguishing values, else its position. */
export function rowLabel(row: RecordRow, columns: readonly string[], position: number): string {
  const parts = columns.map((column) => formatFieldValue(row[column]));
  return parts.length ? parts.join(' / ') : `row ${position + 1}`;
}

/**
 * The value the reader picked last. A table reports its selection in row
 * order, not click order, so the newest pick is the value that was not in
 * the previous selection; with none new (a row was deselected) the last value
 * stands in.
 */
export function latestPickedValue(
  previous: readonly string[] | null,
  current: readonly string[],
): string | null {
  if (current.length === 0) return null;
  const before = new Set(previous ?? []);
  return current.find((value) => !before.has(value)) ?? current[current.length - 1];
}

/**
 * The label the record picker shows for `row`: its title, its id when the
 * title is another column, then the values that tell it apart from the other
 * rows. Every part is searchable, so the reader can type any of them.
 */
export function recordOptionLabel(
  row: RecordRow,
  options: {
    idCol: string;
    titleCol?: string | null;
    labelColumns: readonly string[];
    position: number;
  },
): string {
  const { idCol, titleCol, labelColumns, position } = options;
  const heading = formatFieldValue(titleCol ? row[titleCol] : row[idCol]);
  const id = titleCol && titleCol !== idCol ? formatFieldValue(row[idCol]) : null;
  const rest = labelColumns
    .filter((column) => column !== idCol && column !== titleCol)
    .map((column) => formatFieldValue(row[column]));
  const head = id && id !== heading ? `${heading} (${id})` : heading;
  const label = [head, ...rest].filter(Boolean).join(' · ');
  return label || `row ${position + 1}`;
}
