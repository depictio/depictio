/**
 * CSV export for the genome browser's own tables (the region picker and the
 * tile's data table). The tables of other tiles export through AG Grid's
 * `exportDataAsCsv`; these two cannot: the picker pages its rows from the
 * server, so the grid holds only the blocks scrolled to, and the track table
 * is built from column-oriented rows. Pure apart from `downloadText`.
 */

/** One CSV field: quoted when it holds a comma, a quote or a line break. */
export function csvField(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = typeof value === 'string' ? value : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** A CSV document: a header line and one line per row, CRLF-terminated. */
export function csvText(headers: readonly string[], rows: readonly (readonly unknown[])[]): string {
  const lines = [headers, ...rows].map((row) => row.map(csvField).join(','));
  return lines.join('\r\n') + '\r\n';
}

/** The CSV of column-oriented rows (`{column: values[]}`), for `columns` that exist. */
export function columnsCsv(
  dataRows: Record<string, readonly unknown[]>,
  columns?: readonly string[],
): string {
  const cols = (columns ?? Object.keys(dataRows)).filter((c) => c in dataRows);
  const total = cols.length ? dataRows[cols[0]].length : 0;
  const rows = Array.from({ length: total }, (_, i) => cols.map((c) => dataRows[c][i]));
  return csvText(cols, rows);
}

/** Rows of a server-paged table, fetched page by page until `total` or `max`. */
export async function collectAllPages<T>(
  fetchPage: (start: number, end: number) => Promise<{ rows: T[]; total: number }>,
  { pageSize = 200, max = 20_000 }: { pageSize?: number; max?: number } = {},
): Promise<{ rows: T[]; total: number; truncated: boolean }> {
  const rows: T[] = [];
  let total = 0;
  while (rows.length < max) {
    const page = await fetchPage(rows.length, rows.length + pageSize);
    total = page.total;
    rows.push(...page.rows);
    if (page.rows.length === 0 || rows.length >= total) break;
  }
  const kept = rows.slice(0, max);
  return { rows: kept, total, truncated: kept.length < total };
}

/** A file name safe on every system, from a tile or a table title. */
export function exportFileName(base: string, ext = 'csv'): string {
  const stem = base.trim().replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '') || 'table';
  return `${stem}.${ext}`;
}

/** Hand `text` to the browser as a download (a Blob behind a temporary link). */
export function downloadText(filename: string, text: string, type = 'text/csv;charset=utf-8'): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
