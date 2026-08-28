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
 * output with no header needs a recipe, which this app does not author.
 *
 * The tell is numeric column names. Real headers essentially never have them,
 * and a data row usually has several, so a third of the columns is a safe line.
 */
export function headerLooksLikeData(names: string[]): boolean {
  if (names.length < 2) return false;
  const numeric = names.filter((n) => n.trim() !== '' && FLOAT_RE.test(n.trim())).length;
  return numeric >= Math.ceil(names.length / 3);
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

  // Sample up to 500 rows for dtype inference (fixtures are small anyway).
  const sample = rows.slice(0, 500);
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

  return {
    fileName: committedName,
    ...(needsTsvName ? { renamedFrom: fileName } : {}),
    delimiter,
    columns,
    rows,
    raw,
  };
}
