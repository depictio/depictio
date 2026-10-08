/**
 * Live values in a text tile's title and body.
 *
 * `{{name}}` stands for a value the tile declares under `values:` (a column
 * aggregated under the dashboard's filters, like a card's), `{{param:KEY}}`
 * for one of the run's pipeline parameters. The server computes both in the
 * card bulk-compute pass and returns them raw, keyed by what the braces hold
 * (`name`, `param:KEY`); this module finds the placeholders and formats what
 * comes back. Pure, so the grammar is tested without a DOM.
 *
 * The block and inline parsers leave placeholders alone (no markdown syntax
 * uses braces), so they reach the renderer's leaves intact and are filled
 * there: in plain text, bold, italics, link labels, a result row's figure.
 */
import type { StoredMetadata } from '../api';
import { formatCardNumber, formatDecimals } from './card/metrics/format';

/** A placeholder: `{{name}}` (the names `values:` allows) or `{{param:KEY}}`. */
const PLACEHOLDER = /\{\{(param:[A-Za-z0-9_.-]+|[a-z][a-z0-9_]{0,11})\}\}/g;

/** What a missing or unresolvable value shows. */
export const MISSING_VALUE = '–';

export type TextSegment =
  | { type: 'text'; value: string }
  /** `key` is what the braces hold, the key of the computed values map. */
  | { type: 'value'; key: string; param: boolean };

/** Whether `text` holds a placeholder at all. */
export function hasPlaceholder(text: string): boolean {
  PLACEHOLDER.lastIndex = 0;
  return PLACEHOLDER.test(text);
}

/** `text` cut into its prose and its placeholders, in order. */
export function splitPlaceholders(text: string): TextSegment[] {
  const out: TextSegment[] = [];
  let last = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ type: 'text', value: text.slice(last, at) });
    out.push({ type: 'value', key: m[1], param: m[1].startsWith('param:') });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ type: 'text', value: text.slice(last) });
  return out;
}

/**
 * `text` with each placeholder replaced by `standIn`: what a shape check (a
 * result row's figure holds a digit and is short) reads, since the value the
 * placeholder will show is not known when the body is parsed.
 */
export function withStandIns(text: string, standIn = '0'): string {
  return text.replace(PLACEHOLDER, standIn);
}

/**
 * Whether a text tile has anything to compute: declared `values`, or a
 * `{{param:…}}` in its title or body. Such a tile joins the cards in the
 * bulk-compute batch.
 */
export function hasLiveValues(m: StoredMetadata): boolean {
  if (m.component_type !== 'text') return false;
  const values = m.values;
  if (values && typeof values === 'object' && Object.keys(values).length > 0) return true;
  return [m.title, m.body].some((t) => typeof t === 'string' && t.includes('{{param:'));
}

const INTEGER = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const ONE_DECIMAL = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 });
const SI_UNITS: [number, string][] = [
  [1e12, 'T'],
  [1e9, 'G'],
  [1e6, 'M'],
  [1e3, 'k'],
];

/** 1.2k, 3.4M, 5.6G; below a thousand, as a card prints it. */
function si(v: number): string {
  const abs = Math.abs(v);
  for (let i = 0; i < SI_UNITS.length; i++) {
    const [unit, suffix] = SI_UNITS[i];
    if (abs < unit) continue;
    const scaled = Math.round((v / unit) * 10) / 10;
    // 999,960 rounds to 1000.0k: the next unit up reads it.
    if (Math.abs(scaled) >= 1000 && i > 0) {
      const [up, upSuffix] = SI_UNITS[i - 1];
      return `${ONE_DECIMAL.format(v / up)}${upSuffix}`;
    }
    return `${ONE_DECIMAL.format(scaled)}${suffix}`;
  }
  return formatCardNumber(v);
}

/**
 * A computed value as the tile shows it. `format` is the value's own
 * (`percent` for a 0-1 share, `integer`, `si`, `decimals:N`); without one, a
 * number reads as a card's would and a string as is. Null, or a number that
 * is not finite, shows a dash.
 */
export function formatTextValue(value: unknown, format?: string | null): string {
  if (value === null || value === undefined) return MISSING_VALUE;
  if (typeof value !== 'number') return String(value);
  if (!Number.isFinite(value)) return MISSING_VALUE;
  const f = typeof format === 'string' ? format.trim() : '';
  if (f === 'percent') {
    const pct = value * 100;
    // 41%, but 4.7%: a small share keeps the digit that tells it from 4%.
    return `${Math.abs(pct) < 10 ? ONE_DECIMAL.format(pct) : INTEGER.format(pct)}%`;
  }
  // `|| 0`: -0.4 rounds to -0, which prints as "-0".
  if (f === 'integer') return INTEGER.format(Math.round(value) || 0);
  if (f === 'si') return si(value);
  const decimals = /^decimals:([0-6])$/.exec(f);
  if (decimals) return formatDecimals(value, Number(decimals[1]));
  return formatCardNumber(value);
}
