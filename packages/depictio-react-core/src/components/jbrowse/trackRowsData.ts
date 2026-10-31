import type { JBrowseTrackRow } from '../../api';

/** The columns of the "Show data" grid, in order, with their header. */
const COLUMNS: Array<[keyof JBrowseTrackRow, string]> = [
  ['name', 'Track'],
  ['format', 'Format'],
  ['sample', 'Sample'],
  ['category', 'Category'],
  ['selection_value', 'Selection'],
  ['source', 'Source'],
  ['storage', 'Storage'],
  ['uri', 'File'],
  ['index_uri', 'Index'],
  ['track_id', 'Track id'],
];

/**
 * The tracks of a payload as columns (the shape the data grid takes): one array
 * per column, one entry per track. A column no track fills is left out, so the
 * grid does not open on a wall of empty cells (a project with no categories, a
 * payload from an older backend with no `source`).
 */
export function trackRowsToColumns(rows: readonly JBrowseTrackRow[]): {
  rows: Record<string, unknown[]>;
  columns: string[];
} {
  const out: Record<string, unknown[]> = {};
  const columns: string[] = [];
  for (const [key, header] of COLUMNS) {
    const values = rows.map((r) => r[key] ?? null);
    if (values.every((v) => v === null || v === '')) continue;
    out[header] = values;
    columns.push(header);
  }
  return { rows: out, columns };
}
