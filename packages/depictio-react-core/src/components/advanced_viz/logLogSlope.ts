/**
 * Local log-log slope of a curve: `d log10(y) / d log10(x)`.
 *
 * The Hi-C contact-probability convention. P(s) itself is close to a straight
 * line on log-log axes over four orders of magnitude, so the thing a reader is
 * actually after (where the slope changes, and to what) is invisible on the
 * curve and obvious in its derivative.
 *
 * A least-squares fit over a window rather than a finite difference between
 * neighbours: the difference of two noisy points is noise, and the window is
 * the only knob that trades resolution for a readable line.
 *
 * Pure so the window clamping at the ends of the curve, and the points a log
 * axis cannot carry, can be unit tested without mounting Plotly.
 */

export interface SlopePoint {
  /** x in data units, so the caller plots it against the same axis as the curve. */
  x: number;
  slope: number;
}

/**
 * Slope at every point of the curve that has a fittable window around it.
 *
 * Non-positive x or y values are dropped: they have no logarithm, and a
 * clamped stand-in would bend the slope it is supposed to measure. Points are
 * sorted by x first, so the caller does not have to.
 *
 * `window` is the number of points taken on *each* side, clamped to the ends
 * of the curve, so the fit is over at most `2 * window + 1` points. A window
 * that collapses to a single distinct x has no slope and its point is skipped
 * rather than reported as zero.
 */
export function logLogSlope(
  xs: readonly number[],
  ys: readonly number[],
  window: number,
): SlopePoint[] {
  const pts: { x: number; lx: number; ly: number }[] = [];
  const n = Math.min(xs.length, ys.length);
  for (let i = 0; i < n; i++) {
    const x = xs[i];
    const y = ys[i];
    if (!(x > 0) || !(y > 0)) continue;
    pts.push({ x, lx: Math.log10(x), ly: Math.log10(y) });
  }
  pts.sort((a, b) => a.lx - b.lx);
  if (pts.length < 2) return [];

  const half = Math.max(1, Math.floor(window));
  const out: SlopePoint[] = [];
  for (let i = 0; i < pts.length; i++) {
    const from = Math.max(0, i - half);
    const to = Math.min(pts.length - 1, i + half);
    const count = to - from + 1;
    if (count < 2) continue;

    let sx = 0;
    let sy = 0;
    for (let j = from; j <= to; j++) {
      sx += pts[j].lx;
      sy += pts[j].ly;
    }
    const mx = sx / count;
    const my = sy / count;

    let num = 0;
    let den = 0;
    for (let j = from; j <= to; j++) {
      const dx = pts[j].lx - mx;
      num += dx * (pts[j].ly - my);
      den += dx * dx;
    }
    if (den <= 0) continue;
    out.push({ x: pts[i].x, slope: num / den });
  }
  return out;
}
