/**
 * Reading annotations typed, pasted or dropped in the browser.
 *
 * A dropped file is parsed here and never sent anywhere. It is matched to the
 * table by the rule the server's file merge uses (`_as_key` in
 * `table_merge.py`): text comparison, integer-valued numbers written as
 * integers, blanks never match, and the file's keys must be unique.
 */

import Papa from 'papaparse';

import { MAX_ANNOTATION_COLUMNS, MAX_LABEL_LENGTH, normaliseLabel } from './annotations';

export const MAX_DROP_BYTES = 5 * 1024 * 1024;

const NUMBER_RE = /^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i;

/**
 * A value as the server compares keys: null for blank or NaN, "true"/"false"
 * for booleans, an integer-valued number without its decimals, else trimmed text.
 */
export function asKey(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (Number.isNaN(value)) return null;
    return Number.isInteger(value) ? String(Math.trunc(value)) : String(value);
  }
  const s = String(value).trim();
  return s ? s : null;
}

/**
 * Keys of one file column. The server reads a file with dtype inference, so a
 * column that is numbers throughout is compared as numbers ("1.0" matches 1),
 * while a text column keeps its text ("1.0" stays "1.0").
 */
export function fileColumnKeys(values: string[]): (string | null)[] {
  const filled = values.map((v) => v?.trim() ?? '').filter((v) => v !== '');
  const numeric = filled.length > 0 && filled.every((v) => NUMBER_RE.test(v));
  return values.map((v) => {
    const t = v?.trim() ?? '';
    if (!t) return null;
    return numeric ? asKey(Number(t)) : t;
  });
}

export interface ParsedTable {
  columns: string[];
  rows: Record<string, string>[];
}

/** Delimiter of the first non-comment, non-empty line, by count (as tool-studio's). */
function sniffDelimiter(raw: string): ',' | '\t' {
  const header = raw.split('\n').find((l) => l.trim() !== '' && !l.startsWith('#'));
  if (!header) return ',';
  const tabs = (header.match(/\t/g) ?? []).length;
  const commas = (header.match(/,/g) ?? []).length;
  return tabs > commas ? '\t' : ',';
}

/** Parse a dropped CSV or TSV. The extension wins; otherwise the header line decides. */
export function parseDroppedTable(fileName: string, text: string): ParsedTable | { error: string } {
  const lower = fileName.toLowerCase();
  const raw = text.replace(/^﻿/, '');
  const delimiter = lower.endsWith('.tsv')
    ? '\t'
    : lower.endsWith('.csv')
      ? ','
      : sniffDelimiter(raw);
  const parsed = Papa.parse<Record<string, string>>(raw, {
    delimiter,
    header: true,
    skipEmptyLines: 'greedy',
    transformHeader: (h) => h.trim(),
  });
  const columns = (parsed.meta.fields ?? []).filter((c) => c !== '');
  if (columns.length === 0) return { error: 'The file has no header row.' };
  // papaparse renames a repeated header ("a" -> "a_1") and says so here.
  const renamed = (parsed.meta as { renamedHeaders?: Record<string, string> | null })
    .renamedHeaders;
  if ((renamed && Object.keys(renamed).length > 0) || new Set(columns).size !== columns.length) {
    return { error: 'Two columns of the file have the same name.' };
  }
  return { columns, rows: parsed.data };
}

export interface DropMatch {
  /** The file column matched to the table's key. */
  fileKeyColumn: string;
  /** One annotation per other file column, labels only for matched keys. */
  annotations: { name: string; values: Record<string, string> }[];
  matchedRows: number;
  unmatchedRows: number;
  /** Up to 5 file keys that are not in the table. */
  unmatchedSample: string[];
}

/**
 * Match a parsed file to the table's keys.
 *
 * The file column named like the table's key column is used when it exists;
 * otherwise the file column with unique values that matches most table keys.
 */
export function matchDroppedTable(
  file: ParsedTable,
  tableKeyColumn: string,
  tableKeys: Set<string>,
): DropMatch | { error: string } {
  const keysOf = (col: string) => fileColumnKeys(file.rows.map((r) => r[col] ?? ''));
  const unique = (keys: (string | null)[]) => {
    const filled = keys.filter((k): k is string => k !== null);
    return new Set(filled).size === filled.length;
  };
  const matches = (keys: (string | null)[]) =>
    keys.filter((k) => k !== null && tableKeys.has(k)).length;

  let keyColumn: string | null = null;
  if (file.columns.includes(tableKeyColumn)) {
    if (!unique(keysOf(tableKeyColumn))) {
      return { error: `"${tableKeyColumn}" repeats a value in the file; each row needs its own key.` };
    }
    keyColumn = tableKeyColumn;
  } else {
    let best = 0;
    for (const col of file.columns) {
      const keys = keysOf(col);
      const n = matches(keys);
      if (n > best && unique(keys)) {
        best = n;
        keyColumn = col;
      }
    }
  }
  if (!keyColumn) {
    return { error: `No column of the file matches the table's "${tableKeyColumn}" values.` };
  }
  const labelColumns = file.columns.filter((c) => c !== keyColumn);
  if (labelColumns.length === 0) {
    return { error: 'The file has a key column but nothing to annotate with.' };
  }
  if (labelColumns.length > MAX_ANNOTATION_COLUMNS) {
    return { error: `The file has more than ${MAX_ANNOTATION_COLUMNS} columns to annotate with.` };
  }

  const keys = keysOf(keyColumn);
  const annotations = labelColumns.map((name) => ({ name, values: {} as Record<string, string> }));
  let matchedRows = 0;
  const unmatched: string[] = [];
  for (let i = 0; i < file.rows.length; i += 1) {
    const key = keys[i];
    if (key === null) continue;
    if (!tableKeys.has(key)) {
      unmatched.push(key);
      continue;
    }
    matchedRows += 1;
    for (const a of annotations) {
      const label = normaliseLabel(file.rows[i][a.name]);
      if (label === null) continue;
      if (label.length > MAX_LABEL_LENGTH) {
        return {
          error: `A value of "${a.name}" is longer than ${MAX_LABEL_LENGTH} characters.`,
        };
      }
      a.values[key] = label;
    }
  }
  if (matchedRows === 0) {
    return { error: `No key of the file is in the table's "${tableKeyColumn}".` };
  }
  return {
    fileKeyColumn: keyColumn,
    annotations,
    matchedRows,
    unmatchedRows: unmatched.length,
    unmatchedSample: unmatched.slice(0, 5),
  };
}

/**
 * Cells of a block pasted from a spreadsheet: tab-separated, one row per line,
 * quoted cells may hold tabs or newlines. The trailing newline spreadsheets
 * add is dropped.
 */
export function parsePastedBlock(text: string): string[][] {
  const raw = text.replace(/\r\n?/g, '\n').replace(/\n$/, '');
  if (raw === '') return [];
  const parsed = Papa.parse<string[]>(raw, { delimiter: '\t', header: false });
  return parsed.data;
}
