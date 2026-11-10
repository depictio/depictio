/**
 * "Export as metadata sheet": a metadata table with label columns added, as a
 * TSV built in the browser.
 *
 * A pipeline's metadata sheet cannot be written from a dashboard (the next
 * ingest would rewrite it), and the statistics a pipeline computes from its
 * metadata never see a column added in Depictio anyway. The way to make
 * labels real there is to add them to the sheet the pipeline reads, run it
 * again and ingest: this builds that sheet from the rows on screen.
 */

import { asKey } from './annotationInput';
import type { AnnotationColumn } from './sessionAnnotations';

function tsvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  const s = typeof value === 'object' ? JSON.stringify(value) : String(value);
  return /[\t\r\n"]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** The header a label column takes: its name, or "<name> (label)" when the
 *  table, or another label column, already holds that name. */
function headersFor(tableColumns: string[], labels: AnnotationColumn[]): string[] {
  const taken = new Set(tableColumns);
  return labels.map((label) => {
    let header = taken.has(label.name) ? `${label.name} (label)` : label.name;
    for (let n = 2; taken.has(header); n += 1) header = `${label.name} (label ${n})`;
    taken.add(header);
    return header;
  });
}

/**
 * Every row of the table, in its order, with one column per label column.
 * A row whose key has no label gets an empty cell, and so does every row of a
 * key repeated on several rows gets the key's label.
 */
/** A column Depictio adds at ingest (`depictio_run_id`, `aggregation_time`):
 *  not the source sheet's, so it stays out of a sheet meant to go back there. */
function addedAtIngest(name: string): boolean {
  return name.startsWith('depictio_') || name === 'aggregation_time';
}

export function buildMetadataSheet(
  allColumns: string[],
  rows: Record<string, unknown>[],
  keyColumn: string,
  labels: AnnotationColumn[],
): string {
  const tableColumns = allColumns.filter((c) => c === keyColumn || !addedAtIngest(c));
  const headers = headersFor(tableColumns, labels);
  const lines = [[...tableColumns, ...headers].map(tsvCell).join('\t')];
  for (const row of rows) {
    const key = asKey(row[keyColumn]);
    const cells = tableColumns.map((c) => tsvCell(row[c]));
    for (const label of labels) cells.push(tsvCell(key === null ? '' : (label.values[key] ?? '')));
    lines.push(cells.join('\t'));
  }
  return lines.join('\n') + '\n';
}

/** The file name of an export: the table's tag, then `_with_labels.tsv`. */
export function metadataSheetName(tag: string): string {
  const base = tag.trim().replace(/[^\w.-]+/g, '_') || 'metadata';
  return `${base}_with_labels.tsv`;
}
