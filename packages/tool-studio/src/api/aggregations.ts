/**
 * Card aggregations, computed by depictio-static-core's `aggregateValues` — the
 * kernel the exported serverless dashboard uses, a port of the server's
 * `_agg_value` (dashboards routes.py) pinned by static-core's golden fixtures.
 *
 * The server has two card paths, and so does this module:
 *   - no active filter → the card reads its column's PRECOMPUTED specs
 *     (`_POLARS_AGG_EXPRS`, deltatables_endpoints/utils.py). There `nunique`
 *     is `drop_nulls().n_unique()` and `mode` is `drop_nulls().mode().min()`
 *     — nulls are not values, and a tie goes to the smallest. Pinned by
 *     `src/test/cardMetrics.test.ts` against `cardMetricsGolden.json`.
 *   - a filter is active → `_agg_value` over the filtered rows, where
 *     `n_unique()` counts null as a value and `mode()` lets null win (returned
 *     as the string "None"). That is `aggregateValues` verbatim.
 * Every other aggregation agrees between the two paths, so only those two
 * differ by `mask`.
 */
import type { AggFn, Bitmask } from 'depictio-static-core';
// The kernel itself is not re-exported by the package index (the bundle reaches
// it through `HyparquetEngine.aggregate`, which is async); the Studio needs it
// synchronously — the builder's column specs are computed inline — so it is
// imported from its module, the same file the engine calls.
import { aggregateValues } from '../../../depictio-static-core/src/engine/aggregate';
import type { StudioFrame } from './frame';
import { isNumericKind } from './frame';
import { frameTable } from './frameEngine';

/** Tukey five-number summary + outliers, the payload the `box_plot` strip reads. */
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

export type AggResult = number | string | BoxPlotStats | null;

/** Card aggregation name (server aliases included) → kernel function. */
const AGG_FNS: Record<string, AggFn> = {
  sum: 'sum',
  mean: 'mean',
  average: 'mean',
  median: 'median',
  min: 'min',
  max: 'max',
  count: 'count',
  nunique: 'nunique',
  unique: 'nunique',
  std: 'std',
  std_dev: 'std',
  var: 'var',
  variance: 'var',
  mode: 'mode',
  first: 'first',
  last: 'last',
  q1: 'q1',
  q3: 'q3',
  percentile: 'percentile',
  skewness: 'skewness',
  kurtosis: 'kurtosis',
  box_plot_stats: 'box_plot_stats',
};

/** Linear-interpolated quantile — polars' `quantile(q, interpolation='linear')`. */
export function quantileLinear(sorted: number[], q: number): number | null {
  const n = sorted.length;
  if (n === 0) return null;
  const pos = q * (n - 1);
  const lo = Math.floor(pos);
  const frac = pos - lo;
  return frac === 0 ? sorted[lo] : sorted[lo] + frac * (sorted[lo + 1] - sorted[lo]);
}

/** Box-plot payload over plain numbers, via the shared kernel. */
export function boxPlotStats(values: number[]): BoxPlotStats | null {
  return aggregateValues(values, null, 'box_plot_stats', true) as BoxPlotStats | null;
}

/** `drop_nulls().mode().min()` — the precomputed spec's mode. */
function specMode(values: ArrayLike<unknown>): number | string | null {
  const freq = new Map<unknown, number>();
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (v !== null && v !== undefined) freq.set(v, (freq.get(v) ?? 0) + 1);
  }
  let best: unknown = null;
  let bestCount = -1;
  for (const [value, count] of freq) {
    const lower =
      typeof value === 'number' && typeof best === 'number'
        ? value < best
        : String(value) < String(best);
    if (count > bestCount || (count === bestCount && lower)) {
      best = value;
      bestCount = count;
    }
  }
  if (best === null) return null;
  return typeof best === 'number' ? best : String(best);
}

/**
 * One aggregation over one column, over the rows `mask` keeps (`null` = no
 * filter active). Returns `null` — never NaN — when the reduction has no answer.
 */
export function aggregate(
  frame: StudioFrame,
  column: string,
  aggregation: string,
  mask: Bitmask | null = null,
): AggResult {
  const col = frame.byName.get(column);
  if (!col) return null;
  const values = frameTable(frame).columns[column];
  const numeric = isNumericKind(col.kind);
  const agg = (aggregation || '').toLowerCase();

  if (mask === null && (agg === 'nunique' || agg === 'unique')) {
    return new Set(col.present).size;
  }
  if (mask === null && agg === 'mode') return specMode(values);
  if (agg === 'range') {
    if (!numeric) return null;
    const lo = aggregateValues(values, mask, 'min', true);
    const hi = aggregateValues(values, mask, 'max', true);
    return typeof lo === 'number' && typeof hi === 'number' ? hi - lo : null;
  }
  const fn = AGG_FNS[agg];
  if (!fn) return null;
  const value = aggregateValues(values, mask, fn, numeric);
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  return value as AggResult;
}
