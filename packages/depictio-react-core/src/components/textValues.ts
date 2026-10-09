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
import { formatNumber } from './card/metrics/format';

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
  // `search` leaves the shared global regex's `lastIndex` alone, which `test`
  // would advance and `splitPlaceholders` would then start from.
  return text.search(PLACEHOLDER) !== -1;
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

/**
 * A computed value as the tile shows it. `format` is the value's own
 * (`percent` for a 0-1 share, `integer`, `si`, `decimals:N`), printed by the
 * same `formatNumber` a card's `format` goes through; without one, a number
 * reads as a card's would and a string as is. Null, or a number that is not
 * finite, shows a dash.
 */
export function formatTextValue(value: unknown, format?: string | null): string {
  if (value === null || value === undefined) return MISSING_VALUE;
  if (typeof value !== 'number') return String(value);
  if (!Number.isFinite(value)) return MISSING_VALUE;
  return formatNumber(value, format);
}
