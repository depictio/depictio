/** Number formatting shared by every secondary-metric layout.
 *
 *  One module so a value cannot be printed three different ways depending on
 *  which strip happens to draw it.
 */

const NUMBER_FORMATS = new Map<number, Intl.NumberFormat>();

function fixed(digits: number): Intl.NumberFormat {
  let f = NUMBER_FORMATS.get(digits);
  if (!f) {
    // en-US, like the builder preview: a card must read the same in both.
    f = new Intl.NumberFormat('en-US', { maximumFractionDigits: digits });
    NUMBER_FORMATS.set(digits, f);
  }
  return f;
}

const SMALL = new Intl.NumberFormat('en-US', { maximumSignificantDigits: 3 });

/**
 * A card number, readable at a glance: thousands separators, and decimals that
 * shrink as the magnitude grows (879,737,777 / 3,641 / 907.1 / 12.35 / 0.0123).
 * Integers are never rounded; values too small for three significant digits
 * switch to scientific notation rather than printing as 0.
 */
export function formatCardNumber(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Number.isInteger(v)) return fixed(0).format(v);
  const abs = Math.abs(v);
  if (abs >= 1000) return fixed(0).format(v);
  if (abs >= 100) return fixed(1).format(v);
  if (abs >= 1) return fixed(2).format(v);
  if (abs >= 0.001) return SMALL.format(v);
  return v.toExponential(2);
}

const DECIMAL_FORMATS = new Map<number, Intl.NumberFormat>();

/**
 * A number at an author's `decimals`, kept as written (7.10, not 7.1) so a row
 * of figures lines up. Integers are left whole; thousands separators as in
 * `formatCardNumber`.
 */
export function formatDecimals(v: number, decimals: number): string {
  if (!Number.isFinite(v)) return '—';
  if (Number.isInteger(v)) return fixed(0).format(v);
  const digits = Math.min(20, Math.max(0, Math.round(decimals)));
  let f = DECIMAL_FORMATS.get(digits);
  if (!f) {
    f = new Intl.NumberFormat('en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    DECIMAL_FORMATS.set(digits, f);
  }
  return f.format(v);
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
 * A number in one of the formats a card's `format` and a text tile's live
 * value share: `percent` (a 0-1 fraction times 100: 41%, but 4.7% under ten,
 * so a small share keeps the digit that tells it from 4%), `integer`, `si`
 * (214k, 3.7M) or `decimals:N`. Anything else, or no format, prints as
 * `formatCardNumber` does.
 */
export function formatNumber(v: number, format?: string | null): string {
  if (!Number.isFinite(v)) return '—';
  const f = typeof format === 'string' ? format.trim() : '';
  if (f === 'percent') {
    const pct = v * 100;
    return `${Math.abs(pct) < 10 ? ONE_DECIMAL.format(pct) : INTEGER.format(pct)}%`;
  }
  // `|| 0`: -0.4 rounds to -0, which prints as "-0".
  if (f === 'integer') return INTEGER.format(Math.round(v) || 0);
  if (f === 'si') return si(v);
  const decimals = /^decimals:([0-6])$/.exec(f);
  if (decimals) return formatDecimals(v, Number(decimals[1]));
  return formatCardNumber(v);
}

/**
 * The format a card's value takes: its `format`, else its `decimals` as
 * `decimals:N`. `format` wins when both are set (validation refuses the pair
 * in YAML, but a stored card is not re-validated on read).
 */
export function cardNumberFormat(m: { format?: unknown; decimals?: unknown }): string | undefined {
  if (typeof m.format === 'string' && m.format.trim()) return m.format.trim();
  if (typeof m.decimals === 'number' && Number.isFinite(m.decimals)) {
    return `decimals:${Math.min(6, Math.max(0, Math.round(m.decimals)))}`;
  }
  return undefined;
}

/**
 * A count (rows passing a threshold, outliers, a `count` or `nunique`) on a
 * card whose `format` is for its column, not for counts: it stays whole, and
 * takes the SI suffix only when that format is `si`.
 */
export function formatCount(n: number, format?: string | null): string {
  if (!Number.isFinite(n)) return '—';
  return typeof format === 'string' && format.trim() === 'si' ? si(n) : n.toLocaleString();
}

/** Aggregations that count rows or values, whatever the column holds. */
const COUNT_AGGREGATIONS = new Set(['count', 'nunique']);

/** Aggregations in the column's own unit, so in the card's `format`. The
 *  rest (variance, skewness, kurtosis) are not, and print as they always did. */
const UNIT_AGGREGATIONS = new Set([
  'sum',
  'average',
  'median',
  'min',
  'max',
  'range',
  'std_dev',
  'percentile',
  'q1',
  'q3',
  'mode',
]);

/**
 * One secondary aggregation of the card's column. Under the card's `format`
 * a median or a max reads like the value above it (41%) and a count stays a
 * count; without a format, as `formatSecondary`.
 */
export function formatAggregate(aggregation: string, v: unknown, format?: string | null): string {
  if (format && typeof v === 'number') {
    if (COUNT_AGGREGATIONS.has(aggregation)) return formatCount(v, format);
    if (UNIT_AGGREGATIONS.has(aggregation)) return formatNumber(v, format);
  }
  return formatSecondary(v);
}

/** Rendering for a stat list or an axis anchor, in `format` when one is given
 *  (the card's own, so the strip agrees with the value above it). */
export function formatSecondary(v: unknown, format?: string | null): string {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'number') return formatNumber(v, format);
  return String(v);
}

/** Compact number for tight captions: 1.2B / 45.3k / 812. */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}k`;
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

/** Axis-friendly rendering of a bin edge or a threshold — enough precision to
 *  distinguish adjacent values without spilling out of a 260px card. */
export function axisNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e4 || (abs > 0 && abs < 0.01)) return value.toExponential(1);
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/** Percent from a 0–1 share, without the false precision of "33.333%". */
export function percent(share: number, digits = 0): string {
  if (!Number.isFinite(share)) return '—';
  return `${(share * 100).toFixed(digits)}%`;
}

/** Convert a hex colour ("#FF7F00" or "FF7F00"), an rgb()/rgba() colour or a
 *  Mantine palette name to a colour with the given alpha. Returns a teal
 *  fallback for anything else, which is the accent cards without an explicit
 *  colour have always used. */
export function hexWithAlpha(hex: string | null | undefined, alpha: number): string {
  const fallback = `rgba(69,184,172,${alpha})`;
  if (!hex || typeof hex !== 'string') return fallback;
  // rgb()/rgba() inputs keep their channels with the requested alpha. Without
  // this, neutral tokens like METRIC.remainder fell through to the teal
  // fallback, so an "All"/"Other" ring rank-tinted teal while its siblings
  // drew the intended gray.
  const rgba = hex.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgba) return `rgba(${rgba[1]},${rgba[2]},${rgba[3]},${alpha})`;
  // A Mantine palette name (`orange`, `grape`, a theme's own `brandPrimary`):
  // the colour a card's icon takes, so its strip takes it too, in either scheme.
  if (/^[a-zA-Z][a-zA-Z0-9]*$/.test(hex.trim())) {
    const pct = Math.round(alpha * 100);
    return `color-mix(in srgb, var(--mantine-color-${hex.trim()}-filled) ${pct}%, transparent)`;
  }
  const cleaned = hex.replace('#', '').trim();
  if (cleaned.length !== 6 || !/^[0-9a-fA-F]{6}$/.test(cleaned)) return fallback;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Opacity ramp for ranked segments of one accent colour. Rank 0 is the most
 *  opaque; nothing falls below 0.3, where a segment stops being distinguishable
 *  from the neutral track behind it. */
export function rankTint(color: string | null | undefined, rank: number): string {
  return hexWithAlpha(color, Math.max(0.3, 0.85 - rank * 0.16));
}
