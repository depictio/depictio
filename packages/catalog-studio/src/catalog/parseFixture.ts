/**
 * Parse a dropped CSV/TSV into a ParsedFixture: columns with inferred polars-
 * style dtypes, row objects for preview/compute, and the raw text (exported
 * verbatim as the fixture). Delimiter is picked by extension then sniffed.
 */
import Papa from 'papaparse';
import type { Dtype, FixtureColumn, ParsedFixture } from '../types';

const INT_RE = /^-?\d+$/;
const FLOAT_RE = /^-?(\d+\.\d*|\.\d+|\d+)(e[-+]?\d+)?$/i;
const BOOL_RE = /^(true|false)$/i;
// ISO-ish date / datetime — cheap heuristic, CI re-derives the real dtype.
const DATE_RE = /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?/;

function inferDtype(values: string[]): Dtype {
  let sawFloat = false;
  let sawAny = false;
  for (const raw of values) {
    const v = raw?.trim();
    if (v === '' || v == null) continue;
    sawAny = true;
    if (BOOL_RE.test(v)) return 'Boolean';
    if (DATE_RE.test(v)) return 'Datetime';
    if (INT_RE.test(v)) continue;
    if (FLOAT_RE.test(v)) {
      sawFloat = true;
      continue;
    }
    return 'String';
  }
  if (!sawAny) return 'String';
  return sawFloat ? 'Float64' : 'Int64';
}

export function parseFixture(fileName: string, raw: string): ParsedFixture {
  const delimiter: ',' | '\t' = fileName.toLowerCase().endsWith('.tsv') ? '\t' : ',';
  const parsed = Papa.parse<Record<string, string>>(raw, {
    delimiter,
    header: true,
    skipEmptyLines: true,
  });
  const fields = parsed.meta.fields ?? [];
  const rows = (parsed.data as Record<string, string>[]).filter((r) => r && Object.keys(r).length);

  // Sample up to 500 rows for dtype inference (fixtures are small anyway).
  const sample = rows.slice(0, 500);
  const columns: FixtureColumn[] = fields.map((name) => ({
    name,
    dtype: inferDtype(sample.map((r) => r[name])),
  }));

  return { fileName, delimiter, columns, rows, raw };
}
