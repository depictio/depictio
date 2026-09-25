/**
 * Curve maths for the benchmark tile's sweep views.
 *
 * Kept out of `PrBenchmarkRenderer` because both rules below stay plausible
 * while being wrong: a trapezoid summed over points in table order reports an
 * area that is quietly too small, and a curve drawn in table order zig-zags
 * back on itself. Neither shows up as an error, so they need a test that
 * states the numbers.
 */

/**
 * Row indices bucketed by group value, in first-seen order.
 *
 * `values` is null when no group column is bound, which is one curve over
 * every row rather than none: the empty-string key stands for "all rows".
 */
export function groupIndices(
  values: readonly unknown[] | null,
  count: number,
): Map<string, number[]> {
  const groups = new Map<string, number[]>();
  for (let i = 0; i < count; i += 1) {
    const key = values ? String(values[i] ?? '') : '';
    const bucket = groups.get(key);
    if (bucket) bucket.push(i);
    else groups.set(key, [i]);
  }
  return groups;
}

/** Size of the largest bucket, which is how many points the longest curve has. */
export function largestGroup(groups: Map<string, number[]>): number {
  let largest = 0;
  groups.forEach((idx) => {
    if (idx.length > largest) largest = idx.length;
  });
  return largest;
}

/**
 * Trapezoidal area under y(x).
 *
 * Sorts by x first, because the points arrive in whatever order the sweep was
 * tabulated in and a trapezoid over an unsorted x cancels itself out. Pairs
 * with a non-finite coordinate are dropped rather than poisoning the sum.
 */
export function trapezoidArea(xs: readonly number[], ys: readonly number[]): number {
  const pts = xs
    .map((x, i) => [Number(x), Number(ys[i])] as [number, number])
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
    .sort((a, b) => a[0] - b[0]);
  let area = 0;
  for (let i = 1; i < pts.length; i += 1) {
    area += ((pts[i][0] - pts[i - 1][0]) * (pts[i][1] + pts[i - 1][1])) / 2;
  }
  return area;
}

/**
 * `idx` ordered along the curve: by the swept threshold when one is bound,
 * otherwise by the x coordinate the curve is drawn against.
 *
 * The threshold is preferred because it is the sweep's own parameter, so a
 * curve that doubles back in x (precision is not monotone in recall) still
 * joins its points in the order they were produced.
 */
export function sortCurveIndices(
  idx: readonly number[],
  x: readonly number[],
  threshold: readonly number[] | null,
): number[] {
  const key = threshold ?? x;
  return [...idx].sort((a, b) => (Number(key[a]) || 0) - (Number(key[b]) || 0));
}
