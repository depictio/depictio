/**
 * 0-based positions to keep from an `n`-long rank-ordered sequence.
 *
 * Positions are spaced evenly in *log-index* space rather than linear index
 * space, so the kept subset is dense near position 0 (small rank, the
 * cell/background inflection a knee plot exists to show) and sparse near
 * position `n - 1` (the flat empty-droplet tail, which is most of the curve
 * and none of its content). Each returned position names a row to draw
 * unchanged: this thins the curve, it does not bin or recompute it.
 *
 * Mirrors `log_spaced_rank_thin` in
 * depictio/models/components/advanced_viz/sampling.py (the server's
 * `log_rank` sampling policy for `knee_plot`). This client-side copy is
 * `KneePlotRenderer`'s own defensive cap on whatever the `/data` endpoint
 * returns; `log_rank` is declared there but not yet wired into that
 * endpoint's scan-level reduction, so today every row still arrives
 * unsampled and this is what keeps a very large curve's trace bounded.
 *
 * Returns every position when `n <= cap`. Always includes position 0 and
 * `n - 1` so the curve's endpoints are never dropped.
 */
export function logSpacedRankThin(n: number, cap: number): number[] {
  if (n <= 0) return [];
  if (cap <= 0 || n <= cap) return Array.from({ length: n }, (_, i) => i);
  if (cap === 1) return [0];

  const logN = Math.log(n);
  const positions = new Set<number>();
  for (let t = 0; t < cap; t += 1) {
    positions.add(Math.min(n - 1, Math.round(Math.exp((t / (cap - 1)) * logN)) - 1));
  }
  positions.add(0);
  positions.add(n - 1);
  return Array.from(positions).sort((a, b) => a - b);
}
