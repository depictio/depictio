/**
 * Parse a tabular fixture into a ParsedFixture: columns with inferred polars-
 * style dtypes, row objects for preview/compute, and the raw text (exported
 * verbatim as the fixture).
 *
 * The delimiter comes from the extension when it states one (.csv, .tsv) and is
 * sniffed from the header line otherwise. Sniffing matters because real tool
 * outputs are so often `.txt` or `.tab`: most tabular files in MultiQC's and
 * Galaxy's test corpora would otherwise parse as one wide column. An explicit
 * extension still wins, so a comma-delimited `.tsv` keeps mis-parsing loudly
 * (and the Fixture step says so) rather than being silently repaired.
 */
import Papa from 'papaparse';
import type { Dtype, FixtureColumn, ParsedFixture } from '../types';

// Mirrors `pl.read_csv(..., infer_schema_length=10_000)`, which is what
// `catalog validate` grounds against (read_fixture_schema). Probed against
// polars rather than guessed: no trimming (" 1" is a String), a bare "+1" is a
// String while "+1.5" is a Float, booleans match in any case, NaN/inf (exact
// spellings) are floats while "nan"/"Infinity" are Strings, and dates are NOT
// parsed (try_parse_dates is off), so an ISO date column is a String.
const INT_RE = /^-?\d+$/;
const FLOAT_RE = /^[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?$/;
const FLOAT_SPECIAL = new Set(['NaN', '-NaN', '+NaN', 'inf', '-inf', '+inf']);
const BOOL_RE = /^(true|false)$/i;
/** Rows polars samples for inference in `read_fixture_schema`. */
export const INFER_SCHEMA_LENGTH = 10_000;

/** Polars dtype of one CSV column. Empty cells are nulls and do not vote. */
export function inferDtype(values: Array<string | null | undefined>): Dtype {
  let sawInt = false;
  let sawFloat = false;
  let sawBool = false;
  for (const v of values) {
    if (v == null || v === '') continue;
    if (BOOL_RE.test(v)) sawBool = true;
    else if (INT_RE.test(v)) sawInt = true;
    else if (FLOAT_SPECIAL.has(v) || (FLOAT_RE.test(v) && !/^\+\d+$/.test(v))) sawFloat = true;
    else return 'String';
    if (sawBool && (sawInt || sawFloat)) return 'String';
  }
  if (sawBool) return 'Boolean';
  if (sawFloat) return 'Float64';
  if (sawInt) return 'Int64';
  return 'String'; // all-null column
}

/** Kept for the header heuristic below (numeric-looking column names). */
const NUMERIC_NAME_RE = /^-?(\d+\.\d*|\.\d+|\d+)(e[-+]?\d+)?$/i;

/** Delimiter of the first non-comment, non-empty line, by count. A tie, or a
 *  line with neither, falls back to comma, which is what a genuinely
 *  single-column file wants anyway. Leading `#` lines are skipped: plenty of
 *  tool outputs open with a banner before the header. */
function sniffDelimiter(raw: string): ',' | '\t' {
  const header = raw.split('\n').find((l) => l.trim() !== '' && !l.startsWith('#'));
  if (!header) return ',';
  const tabs = (header.match(/\t/g) ?? []).length;
  const commas = (header.match(/,/g) ?? []).length;
  return tabs > commas ? '\t' : ',';
}

/**
 * Whether the first row was data rather than a header.
 *
 * Plenty of tool outputs ship no header at all: a kraken2 report opens straight
 * on ` 25.41\t147167\t147167\tU\t0\tunclassified`, so the parse turns numbers
 * into column names and every binding made against them is nonsense. Nothing
 * downstream can catch that, and the file cannot be fixed by renaming it: an
 * output with no header needs a recipe, which the Fixture step offers to start.
 *
 * The tell is numeric column names. Real headers essentially never have them,
 * and a data row usually has several, so a third of the columns is a safe line.
 */
export function headerLooksLikeData(names: string[]): boolean {
  if (names.length < 2) return false;
  const numeric = names.filter((n) => n.trim() !== '' && NUMERIC_NAME_RE.test(n.trim())).length;
  return numeric >= Math.ceil(names.length / 3);
}

/** Collapse papaparse's per-row errors into a few readable lines (row numbers
 *  are 1-based and count the header, like an editor would). */
function describeParseErrors(errors: Papa.ParseError[]): string[] {
  const byKind = new Map<string, number[]>();
  for (const e of errors) {
    if (e.code === 'UndetectableDelimiter') continue; // delimiter is always given
    const label =
      e.code === 'TooFewFields'
        ? 'fewer fields than the header'
        : e.code === 'TooManyFields'
          ? 'more fields than the header'
          : e.type === 'Quotes'
            ? 'an unterminated or misplaced quote'
            : e.message;
    const rows = byKind.get(label) ?? [];
    if (typeof e.row === 'number') rows.push(e.row + 2);
    byKind.set(label, rows);
  }
  return [...byKind].map(([label, rows]) => {
    const where = rows.length ? ` (line ${rows.slice(0, 5).join(', ')}${rows.length > 5 ? ', …' : ''})` : '';
    return `${rows.length || 1} row${rows.length > 1 ? 's' : ''} with ${label}${where}.`;
  });
}

export function parseFixture(fileName: string, raw: string): ParsedFixture {
  const lower = fileName.toLowerCase();
  const delimiter: ',' | '\t' = lower.endsWith('.tsv')
    ? '\t'
    : lower.endsWith('.csv')
      ? ','
      : sniffDelimiter(raw);
  const parsed = Papa.parse<Record<string, string>>(raw, {
    delimiter,
    header: true,
    skipEmptyLines: true,
  });
  const fields = parsed.meta.fields ?? [];
  const rows = (parsed.data as Record<string, string>[]).filter((r) => r && Object.keys(r).length);

  // Same sample size polars uses in `read_fixture_schema`.
  const sample = rows.slice(0, INFER_SCHEMA_LENGTH);
  const columns: FixtureColumn[] = fields.map((name) => ({
    name,
    dtype: inferDtype(sample.map((r) => r[name])),
  }));

  // depictio reads a fixture with a tab separator ONLY when the file is named
  // `.tsv` (`read_fixture_schema` in models/components/advanced_viz/catalog.py
  // and `payload.py` both do `sep = "\t" if suffix == ".tsv" else ","`). A
  // tab-delimited `.txt` would therefore ground as one wide column in CI while
  // looking perfectly parsed here. Normalise the committed name once, so every
  // consumer downstream (zip, PR, preview) inherits it. Comma needs no such
  // care: it is the `else` branch, so any extension already reads correctly.
  const needsTsvName = delimiter === '\t' && !lower.endsWith('.tsv');
  const committedName = needsTsvName ? `${fileName.replace(/\.[^./]*$/, '')}.tsv` : fileName;

  const parseWarnings = describeParseErrors(parsed.errors);
  if (fields.length > 0 && rows.length === 0) {
    // `catalog validate` needs a header plus at least one data line.
    parseWarnings.push('The file has a header but no data rows; CI rejects a fixture without data.');
  }

  return {
    fileName: committedName,
    ...(parseWarnings.length ? { parseWarnings } : {}),
    ...(needsTsvName ? { renamedFrom: fileName } : {}),
    delimiter,
    columns,
    rows,
    raw,
  };
}
