/**
 * Which file names can become a table collection, decided from the extension
 * alone: the same rule for files dropped in the dialog and for the listing of
 * a folder read before a project exists.
 */

const FORMATS: Record<string, string> = {
  csv: 'CSV',
  tsv: 'TSV',
  tab: 'TSV',
  parquet: 'Parquet',
  pq: 'Parquet',
  feather: 'Feather',
  arrow: 'Feather',
  xls: 'Excel',
  xlsx: 'Excel',
};

/** Extensions that may carry a `.gz` suffix. */
const COMPRESSIBLE = new Set(['csv', 'tsv', 'tab']);

export interface TableGuess {
  table: boolean;
  /** "CSV", "Parquet"...; null for a file that is not a table. */
  format: string | null;
  /** Why a file is not a table; null for a table. */
  reason: string | null;
}

export function baseName(name: string): string {
  const segments = name.replace(/\\/g, '/').split('/');
  return segments[segments.length - 1] || name;
}

/** The name without its table extension (and `.gz`). */
export function stemOf(name: string): string {
  return baseName(name).replace(/\.(csv|tsv|tab)\.gz$/i, '').replace(/\.[^.]+$/, '');
}

export function classifyTableName(name: string): TableGuess {
  const lower = baseName(name).toLowerCase();
  const gz = lower.endsWith('.gz');
  const bare = gz ? lower.slice(0, -3) : lower;
  const dot = bare.lastIndexOf('.');
  const ext = dot >= 0 ? bare.slice(dot + 1) : '';
  const format = FORMATS[ext];
  if (!format || (gz && !COMPRESSIBLE.has(ext))) {
    return { table: false, format: null, reason: 'not a table' };
  }
  return { table: true, format: gz ? `${format}, gzip` : format, reason: null };
}

/** Column names from the first line of a CSV or TSV file; null when the
 *  format has no header to read here (Parquet...) or the read failed. */
export async function readColumns(file: File): Promise<string[] | null> {
  const lower = file.name.toLowerCase();
  let sep: string;
  if (lower.endsWith('.csv')) sep = ',';
  else if (lower.endsWith('.tsv') || lower.endsWith('.tab')) sep = '\t';
  else return null;
  try {
    const text = await file.slice(0, 65536).text();
    const first = text.split(/\r?\n/).find((l) => l.length > 0) ?? '';
    return first
      .split(sep)
      .map((c) => c.trim().replace(/^"|"$/g, ''))
      .filter(Boolean);
  } catch {
    return null;
  }
}

/** "1 column", "8 columns". */
export function columnsText(n: number): string {
  return `${n} ${n === 1 ? 'column' : 'columns'}`;
}
