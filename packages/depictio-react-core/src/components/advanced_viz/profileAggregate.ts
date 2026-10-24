/** Aggregation of long rows into one profile point per x, for `ProfileConfig.aggregate`.
 *
 * A profile is usually drawn from rows a recipe already summarised (one row per
 * series and x). A summary computed upstream cannot follow the dashboard's
 * filters, though: narrowing the features changes which rows exist, not the
 * medians someone wrote down. With `aggregate: median_iqr` the tile reads one
 * row per feature, series and x, and the median and interquartile band are
 * computed here, over whatever rows the filters left.
 */

export type ProfileAggregate = 'none' | 'median_iqr';

export interface ProfilePoint {
  x: number;
  y: number;
  lo: number | null;
  hi: number | null;
}

/** Linear-interpolation quantile of an ascending array (numpy's and polars' default). */
export function quantileSorted(sorted: number[], q: number): number {
  if (sorted.length === 0) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** One point per distinct x: the median of its y values, banded by the quartiles. */
export function medianIqrByX(points: { x: number; y: number }[]): ProfilePoint[] {
  const byX = new Map<number, number[]>();
  for (const p of points) {
    const ys = byX.get(p.x);
    if (ys) ys.push(p.y);
    else byX.set(p.x, [p.y]);
  }
  return Array.from(byX.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([x, ys]) => {
      ys.sort((a, b) => a - b);
      return {
        x,
        y: quantileSorted(ys, 0.5),
        lo: quantileSorted(ys, 0.25),
        hi: quantileSorted(ys, 0.75),
      };
    });
}
