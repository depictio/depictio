/**
 * Shared scalar-aggregation kernel — mirrors the server's `_agg_value`
 * (dashboards routes.py:1290). Extracted from HyparquetEngine.aggregate so the
 * prologue interpreter's `group_by` produces IDENTICAL per-group results (RFC
 * phase 6): one implementation, two callers.
 *
 * All pinned traps live here, verified on Polars 1.42.1 (the repo pin):
 *   - count = NON-null count; nunique COUNTS null as a distinct value
 *   - std/var: ddof=1, n < 2 → null
 *   - median: linear interpolation between the two middle values
 *   - first/last: positional, nulls INCLUDED (first([None,1]) is None)
 *   - sum: 0 for an empty/all-null NUMERIC selection; null on non-numeric
 *   - mode: null is a candidate value; the server str()'s a None winner
 *   - box_plot_stats: the one COMPOUND member — resolves to a BoxPlotStats
 *     object rather than a scalar (see boxPlotStats below)
 *
 * `numericColumn` is the caller's dtype knowledge: the engine derives it from
 * DataRef dtypes (NUMERIC_DTYPE), the prologue infers it from decoded values.
 */

import type { AggFn, Bitmask } from './QueryEngine';

/** Polars numeric dtype detector (Int / UInt / Float families at export time). */
export const NUMERIC_DTYPE = /^(U?Int|Float)/;

type ColumnValues = ArrayLike<unknown>;

/**
 * Compute one aggregation over the mask-selected values (mask null = all
 * rows). Return values mirror `_agg_value`: numbers (or strings for
 * non-numeric min/max/mode/first/last), `null` when the aggregation has no
 * answer; empty-selection pins: sum → 0 on numeric columns, count/nunique → 0,
 * everything else → null.
 */
export function aggregateValues(
  values: ColumnValues,
  mask: Bitmask | null,
  fn: AggFn,
  numericColumn: boolean,
): unknown {
  switch (fn) {
    case 'count': {
      // Server: col.drop_nulls().len() — NON-null count (routes.py:1299-1300).
      let n = 0;
      forEachMasked(values, mask, (v) => {
        if (v != null) n++;
      });
      return n;
    }
    case 'sum': {
      // Polars sum skips nulls and returns 0 for an empty/all-null NUMERIC
      // series (verified, Polars 1.42.1); on a non-numeric column col.sum()
      // raises and _agg_value's catch returns None (routes.py:1384-1386).
      if (!numericColumn) return null;
      let sum = 0;
      let big = 0n;
      forEachMasked(values, mask, (v) => {
        if (typeof v === 'number') sum += v;
        else if (typeof v === 'bigint') big += v;
      });
      return sum + (big === 0n ? 0 : Number(big));
    }
    case 'mean': {
      if (!numericColumn) return null;
      let sum = 0;
      let big = 0n;
      let n = 0;
      forEachMasked(values, mask, (v) => {
        if (typeof v === 'number') {
          sum += v;
          n++;
        } else if (typeof v === 'bigint') {
          big += v;
          n++;
        }
      });
      return n === 0 ? null : (sum + (big === 0n ? 0 : Number(big))) / n;
    }
    case 'median': {
      // Polars default: linear interpolation between the two middle values on
      // even counts (verified: median([1,2,3,10]) == 2.5) — i.e. exactly
      // quantile(0.5, interpolation="linear").
      const nums = collectNumbers(values, mask);
      if (nums.length === 0) return null;
      nums.sort((a, b) => a - b);
      return quantileLinear(nums, 0.5);
    }
    case 'min':
    case 'max': {
      // Numeric -> float; non-numeric -> str (routes.py:1310-1319).
      const wantMin = fn === 'min';
      let bestNum: number | null = null;
      let bestStr: string | null = null;
      forEachMasked(values, mask, (v) => {
        if (v == null) return;
        if (typeof v === 'number' || typeof v === 'bigint') {
          const cur = typeof v === 'bigint' ? Number(v) : v;
          if (Number.isNaN(cur)) return;
          if (bestNum === null || (wantMin ? cur < bestNum : cur > bestNum)) bestNum = cur;
        } else {
          const cur = stringifyValue(v);
          if (bestStr === null || (wantMin ? cur < bestStr : cur > bestStr)) bestStr = cur;
        }
      });
      return bestNum !== null ? bestNum : bestStr;
    }
    case 'std':
    case 'var': {
      // ddof=1 (sample), Polars default; n < 2 -> null (verified: std of a
      // single value is None, not NaN).
      const nums = collectNumbers(values, mask);
      const n = nums.length;
      if (n < 2) return null;
      let sum = 0;
      for (const v of nums) sum += v;
      const mean = sum / n;
      let ssd = 0;
      for (const v of nums) ssd += (v - mean) * (v - mean);
      const variance = ssd / (n - 1);
      return fn === 'var' ? variance : Math.sqrt(variance);
    }
    case 'nunique': {
      // Polars n_unique counts null as a distinct value (verified:
      // n_unique([1,2,None,2]) == 3, n_unique([None,None]) == 1).
      const seen = new Set<string>();
      let sawNull = false;
      forEachMasked(values, mask, (v) => {
        if (v == null) sawNull = true;
        else seen.add(typeof v + ':' + stringifyValue(v));
      });
      return seen.size + (sawNull ? 1 : 0);
    }
    case 'mode': {
      // Server (_agg_value routes.py:1377-1383): m[0] of col.mode(). Two
      // measured traps, both matched here:
      // - Polars mode() counts NULL as a candidate value (verified on 1.42.1:
      //   mode of a null-heavy Int64 column is [None]) — and str(None) makes
      //   the server literally return the string "None" for it.
      // - Polars' order among TIED modes is nondeterministic (neither sorted
      //   nor first-encountered), so the server is arbitrary there. We pin
      //   the deterministic first-encountered winner; identical whenever the
      //   mode is unique.
      // Empty selection -> null (routes.py:1379-1381).
      const NULL_KEY = ' null';
      const counts = new Map<string, { value: unknown; count: number; firstIdx: number }>();
      let idx = 0;
      forEachMasked(values, mask, (v) => {
        const i = idx++;
        const key = v == null ? NULL_KEY : typeof v + ':' + stringifyValue(v);
        const entry = counts.get(key);
        if (entry) entry.count++;
        else counts.set(key, { value: v ?? null, count: 1, firstIdx: i });
      });
      let best: { value: unknown; count: number; firstIdx: number } | null = null;
      for (const entry of counts.values()) {
        if (
          best === null ||
          entry.count > best.count ||
          (entry.count === best.count && entry.firstIdx < best.firstIdx)
        ) {
          best = entry;
        }
      }
      if (best === null) return null;
      const v = best.value;
      if (v === null) return 'None'; // str(None) — the server's exact artifact
      return typeof v === 'number' ? v : typeof v === 'bigint' ? Number(v) : stringifyValue(v);
    }
    case 'first':
    case 'last': {
      // Polars Series.first()/last(): the positional first/last element,
      // nulls INCLUDED (first([None,1]) is None — verified).
      let result: unknown = null;
      let found = false;
      forEachMasked(values, mask, (v) => {
        if (fn === 'first') {
          if (!found) {
            result = v ?? null;
            found = true;
          }
        } else {
          result = v ?? null;
          found = true;
        }
      });
      if (!found || result == null) return null;
      return typeof result === 'number'
        ? result
        : typeof result === 'bigint'
          ? Number(result)
          : stringifyValue(result);
    }
    case 'box_plot_stats':
      return boxPlotStats(values, mask);
  }
}

/** The compound `box_plot_stats` payload — field-for-field the dict the server
 *  builds (routes.py:1508), which is what `BoxPlot.tsx` type-guards on. */
export interface BoxPlotStats {
  min: number;
  max: number;
  q1: number;
  q3: number;
  median: number;
  mean: number;
  lower_whisker: number;
  upper_whisker: number;
  outliers: number[];
  outlier_count: number;
}

/** Cap on the returned outlier list, mirroring the server's `head(100)`: past
 *  that the dots overlap into a solid bar at card scale, and `outlier_count`
 *  carries the real total. */
const MAX_OUTLIERS = 100;

/**
 * Tukey box-and-whisker payload — port of the server's `box_plot_stats` branch
 * of `_agg_value` (dashboards routes.py:1508). Pinned behaviours, each mirrored
 * from a specific line there:
 *   - selection = `col.cast(Float64, strict=False).drop_nulls()`; no numeric
 *     values (all-null, or a non-numeric column) → null, NOT a zeroed payload
 *   - q1/q3/median: `quantile(interpolation="linear")`, so median is the same
 *     reduction as the `median` agg above
 *   - mean: plain arithmetic mean over that same selection (the payload
 *     carries no std/var — the card draws a box, not an error bar)
 *   - whiskers: the most extreme datum still inside the 1.5×IQR fence, with a
 *     min/max fallback when the fence admits nothing. IQR=0 does NOT by itself
 *     trigger the fallback — a constant column puts both fences on q1=q3, and
 *     every value compares equal, so the whiskers land on the constant
 *   - outliers keep ORIGINAL ROW ORDER, not sorted order: the server filters
 *     the unsorted `numeric` series and takes `head(100)` off that
 */
function boxPlotStats(values: ColumnValues, mask: Bitmask | null): BoxPlotStats | null {
  const nums = collectNumbers(values, mask);
  if (nums.length === 0) return null;
  const sorted = [...nums].sort((a, b) => a - b);
  const q1 = quantileLinear(sorted, 0.25);
  const q3 = quantileLinear(sorted, 0.75);
  const iqr = q3 - q1;
  const fenceLo = q1 - 1.5 * iqr;
  const fenceHi = q3 + 1.5 * iqr;

  let lowerWhisker: number | null = null;
  let upperWhisker: number | null = null;
  const outliers: number[] = [];
  let outlierCount = 0;
  for (const v of nums) {
    if (v < fenceLo || v > fenceHi) {
      outlierCount++;
      if (outliers.length < MAX_OUTLIERS) outliers.push(v);
    } else {
      if (lowerWhisker === null || v < lowerWhisker) lowerWhisker = v;
      if (upperWhisker === null || v > upperWhisker) upperWhisker = v;
    }
  }

  let sum = 0;
  for (const v of nums) sum += v;
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  return {
    min,
    max,
    q1,
    q3,
    median: quantileLinear(sorted, 0.5),
    mean: sum / nums.length,
    lower_whisker: lowerWhisker ?? min,
    upper_whisker: upperWhisker ?? max,
    outliers,
    outlier_count: outlierCount,
  };
}

/**
 * Polars `quantile(q, interpolation="linear")` over an ASCENDING-sorted array:
 * position `q*(n-1)`, linearly interpolated between its neighbours (the numpy
 * convention — verified on Polars 1.42.1: quantile([1,2,3,10], 0.25) == 1.75,
 * 0.75 == 4.75). Callers must sort first; `sorted` must be non-empty.
 */
function quantileLinear(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const frac = pos - lo;
  return frac === 0 ? sorted[lo] : sorted[lo] + frac * (sorted[lo + 1] - sorted[lo]);
}

function forEachMasked(
  values: ColumnValues,
  mask: Bitmask | null,
  fn: (v: unknown) => void,
): void {
  for (let i = 0; i < values.length; i++) {
    if (mask !== null && mask[i] === 0) continue;
    fn(values[i]);
  }
}

function collectNumbers(values: ColumnValues, mask: Bitmask | null): number[] {
  const out: number[] = [];
  forEachMasked(values, mask, (v) => {
    if (typeof v === 'number') {
      if (!Number.isNaN(v)) out.push(v);
    } else if (typeof v === 'bigint') {
      out.push(Number(v));
    }
  });
  return out;
}

/** String form for unique()/string aggregates; ISO for Dates. */
export function stringifyValue(v: unknown): string {
  if (v instanceof Date) return v.toISOString();
  return String(v);
}
