/**
 * Port of depictio/models/components/value_order.py — the order a filter
 * offers its values in (`/deltatables/unique_values` → `order_values`).
 *
 *   - `keys` (an `order_by` companion column) gives each value a key: values
 *     follow their keys, numerically when every present key is a number, else
 *     naturally; a value with no key goes last; ties fall back on the value's
 *     natural key.
 *   - no keys: values that ALL end in a duration (`30min`, `2h`, `GM_1d`)
 *     follow the duration, then the natural key; anything else keeps the plain
 *     (code-point) string sort.
 */

const DURATION_RE =
  /(?:^|[_\-.\s])(\d+(?:\.\d+)?)\s*(s|sec|secs|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)$/i;
const UNIT_HOURS: Record<string, number> = { s: 1 / 3600, m: 1 / 60, h: 1, d: 24 };

/** `parse_duration_hours`. */
export function parseDurationHours(label: string | null | undefined): number | null {
  if (label === null || label === undefined) return null;
  const m = String(label).trim().match(DURATION_RE);
  if (!m) return null;
  const unit = m[2].toLowerCase();
  const key = unit.startsWith('m') ? 'm' : unit[0];
  return Number(m[1]) * UNIT_HOURS[key];
}

type NaturalPart = string | number;

/** `natural_key`: digit runs as numbers, the rest lower-cased. */
export function naturalKey(text: string): NaturalPart[] {
  return text.split(/(\d+)/).map((p) => (/^\d+$/.test(p) ? Number(p) : p.toLowerCase()));
}

function cmpScalar(a: NaturalPart, b: NaturalPart): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b;
  const sa = String(a);
  const sb = String(b);
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

function cmpList(a: NaturalPart[], b: NaturalPart[]): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const c = cmpScalar(a[i], b[i]);
    if (c !== 0) return c;
  }
  return a.length - b.length;
}

function isNumber(v: unknown): boolean {
  if (typeof v === 'boolean') return false;
  if (typeof v === 'number') return true;
  if (typeof v === 'bigint') return true;
  if (typeof v === 'string') {
    const s = v.trim();
    return s !== '' && !Number.isNaN(Number(s));
  }
  return false;
}

/** `order_values(values, keys)`. */
export function orderValues(
  values: Iterable<unknown>,
  keys?: ReadonlyMap<string, unknown> | null,
): string[] {
  const distinct = [...new Set([...values].filter((v) => v !== null && v !== undefined).map(String))].sort();
  if (keys && keys.size > 0) {
    const present = new Map<string, unknown>();
    for (const v of distinct) {
      const k = keys.get(v);
      if (k !== null && k !== undefined && k !== '') present.set(v, k);
    }
    const numeric = present.size > 0 && [...present.values()].every(isNumber);
    const keyed = (v: string): [number, number | NaturalPart[], NaturalPart[]] => {
      if (!present.has(v)) return [1, 0, naturalKey(v)];
      const k = present.get(v);
      return [0, numeric ? Number(k) : naturalKey(String(k)), naturalKey(v)];
    };
    return distinct.sort((a, b) => {
      const ka = keyed(a);
      const kb = keyed(b);
      if (ka[0] !== kb[0]) return ka[0] - kb[0];
      const c =
        typeof ka[1] === 'number' && typeof kb[1] === 'number'
          ? ka[1] - kb[1]
          : cmpList(ka[1] as NaturalPart[], kb[1] as NaturalPart[]);
      if (c !== 0) return c;
      return cmpList(ka[2], kb[2]);
    });
  }
  const hours = new Map(distinct.map((v) => [v, parseDurationHours(v)]));
  if (distinct.length > 0 && [...hours.values()].every((h) => h !== null)) {
    return distinct.sort((a, b) => {
      const c = (hours.get(a) as number) - (hours.get(b) as number);
      return c !== 0 ? c : cmpList(naturalKey(a), naturalKey(b));
    });
  }
  return distinct;
}
