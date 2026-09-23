/**
 * How one field of a record reads: its value as text, and the links a value
 * can stand behind.
 *
 * Values arrive as parsed JSON, so the type is the collection's own: only a
 * real number is reformatted. A string that happens to parse as one is left
 * exactly as it came, because `00123` is a library id and `1.20` is a version
 * the pipeline printed, and rounding either would be the card inventing data.
 */

/** What a null or an empty value shows as. The caller dims it; the glyph is
 *  there so an empty field still reads as a field rather than as a gap. */
export const NULL_DISPLAY = '–';

const VALUE_PLACEHOLDER = '{value}';

/** One value, as the card prints it. */
export function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return NULL_DISPLAY;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') return formatNumber(value);
  const text = String(value);
  return text.trim() === '' ? NULL_DISPLAY : text;
}

function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return NULL_DISPLAY;
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  const magnitude = Math.abs(value);
  // Outside this band the decimal form is either all zeros or all digits, and
  // a QC table carries both ends (a 3e-8 e-value, a 1.4e9 read count).
  if (magnitude !== 0 && (magnitude < 1e-3 || magnitude >= 1e7)) return value.toExponential(2);
  // Enough decimals to separate two neighbouring values, and no more: the
  // fields that matter here are rates, ratios and percentages.
  const digits = magnitude >= 100 ? 1 : magnitude >= 1 ? 2 : 4;
  return value.toLocaleString('en-US', { maximumFractionDigits: digits });
}

/**
 * A link template resolved against one value, or null when there is nothing
 * to link to.
 *
 * The value is percent-encoded: a run accession goes into a path segment and
 * a sample name may carry a slash or a space, neither of which survives being
 * pasted into a URL raw. A template naming no `{value}` is a constant link
 * (a protocol page, a pipeline's docs) and resolves to itself.
 */
export function renderLinkTemplate(template: string, value: unknown): string | null {
  if (!template) return null;
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  if (!template.includes(VALUE_PLACEHOLDER)) return template;
  return template.split(VALUE_PLACEHOLDER).join(encodeURIComponent(raw));
}

export interface RecordLink {
  /** Column the link was built from; also the chip's label. */
  column: string;
  href: string;
  /** The value behind the link, for the chip's tooltip. */
  value: string;
}

/** Every link chip one record earns, in the order the templates declare. */
export function recordLinks(
  row: Record<string, unknown>,
  templates?: Record<string, string> | null,
): RecordLink[] {
  if (!templates) return [];
  const out: RecordLink[] = [];
  for (const [column, template] of Object.entries(templates)) {
    const href = renderLinkTemplate(template, row[column]);
    if (!href) continue;
    out.push({ column, href, value: String(row[column] ?? '') });
  }
  return out;
}
