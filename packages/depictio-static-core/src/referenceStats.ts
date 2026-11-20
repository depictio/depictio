/**
 * Statistics a reference line or a tail cut is drawn at — the twin of
 * `depictio/api/v1/services/advanced_viz/reference_stats.py`.
 *
 * `stat_expr` casts the column to Float64 (strings that parse become numbers,
 * anything else null), drops nulls and non-finite values, then takes the
 * median, the mean or a linearly interpolated quantile. `compute_requests`
 * answers None for a column the frame does not hold and for a column with no
 * finite value left; `parse_requests` drops malformed entries instead of
 * failing the request.
 */

export const REFERENCE_STATS = ['median', 'mean', 'p75', 'p90', 'p95', 'p99'] as const;
export type ReferenceStatName = (typeof REFERENCE_STATS)[number];

const QUANTILES: Record<string, number> = { p75: 0.75, p90: 0.9, p95: 0.95, p99: 0.99 };

export function isReferenceStat(value: unknown): value is ReferenceStatName {
  return typeof value === 'string' && (REFERENCE_STATS as readonly string[]).includes(value);
}

/** Polars' `cast(pl.Float64, strict=False)`: numbers and numeric strings. */
function toFloat(raw: unknown): number | null {
  if (typeof raw === 'number') return raw;
  if (typeof raw === 'bigint') return Number(raw);
  if (typeof raw === 'boolean') return raw ? 1 : 0;
  if (typeof raw === 'string') {
    const s = raw.trim();
    if (s === '') return null;
    // Number() reads hex/octal/binary literals polars would refuse.
    return /^[+-]?0[xob]/i.test(s) ? null : Number(s);
  }
  return null;
}

/** `quantile(q, interpolation="linear")` over sorted finite values. */
function quantileLinear(sorted: number[], q: number): number {
  const pos = q * (sorted.length - 1);
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** `stat` over `values`, or null when no finite value is left. */
export function computeStat(values: readonly unknown[], stat: string): number | null {
  if (!isReferenceStat(stat)) {
    throw new Error(`unknown reference stat ${JSON.stringify(stat)}`);
  }
  const nums: number[] = [];
  for (const raw of values) {
    const v = toFloat(raw);
    if (v !== null && Number.isFinite(v)) nums.push(v);
  }
  if (nums.length === 0) return null;
  let out: number;
  if (stat === 'mean') {
    out = nums.reduce((a, b) => a + b, 0) / nums.length;
  } else {
    nums.sort((a, b) => a - b);
    out = quantileLinear(nums, stat === 'median' ? 0.5 : QUANTILES[stat]);
  }
  return Number.isFinite(out) ? out : null;
}

/** `{field: [column, stat]}` from a request's `reference_stats`. */
export function parseReferenceRequests(raw: unknown): Record<string, [string, ReferenceStatName]> {
  const out: Record<string, [string, ReferenceStatName]> = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const [field, spec] of Object.entries(raw as Record<string, unknown>)) {
    if (!spec || typeof spec !== 'object') continue;
    const { column, stat } = spec as { column?: unknown; stat?: unknown };
    if (typeof column === 'string' && column && isReferenceStat(stat)) {
      out[field] = [column, stat];
    }
  }
  return out;
}

/** Every requested statistic over `data` (column name -> values). */
export function computeReferenceRequests(
  data: Record<string, readonly unknown[]>,
  requests: Record<string, [string, ReferenceStatName]>,
): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  for (const [field, [column, stat]] of Object.entries(requests)) {
    out[field] = column in data ? computeStat(data[column], stat) : null;
  }
  return out;
}

/** The response's rounding: `float(f"{value:.6g}")`. */
export function roundReference(value: number | null): number | null {
  return value === null ? null : Number(value.toPrecision(6));
}
