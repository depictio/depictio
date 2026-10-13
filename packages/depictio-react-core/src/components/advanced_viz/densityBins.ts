/**
 * Bin geometry for a Plotly `histogram2d` density view.
 *
 * Two things a trace builder gets wrong on its own, both worth a unit test:
 *
 * - `nbinsx` / `nbinsy` are a hint. Plotly rounds the bin width to a "nice"
 *   number and delivers whatever count that implies, so a declared
 *   `density_bins` becomes a suggestion. An explicit `{start, end, size}`
 *   block pins the grid, and two tiles configured the same way then bin the
 *   same way.
 * - `xbins` on a log axis is in log10 units, while the trace's own `x` stays
 *   in data units. Computing the edges from the raw values puts the whole
 *   grid at 10^value, which is the same trap the reference lines in
 *   `ScatterXyRenderer` already carry a comment about.
 *
 * A pair is dropped when either coordinate cannot be drawn: non-finite, or
 * non-positive on a log axis.
 */

export interface BinEdges {
  start: number;
  end: number;
  size: number;
}

export interface DensityGrid {
  /** Drawable x values, in data units, as the trace carries them. */
  x: number[];
  /** Drawable y values, paired with `x`. */
  y: number[];
  /** Bin block in axis units, or null when there is nothing to bin. */
  xbins: BinEdges | null;
  ybins: BinEdges | null;
}

/** A value in its axis' own coordinates: log10 on a log axis, else itself. */
function axisCoord(value: number, log: boolean): number | null {
  if (!Number.isFinite(value)) return null;
  if (!log) return value;
  return value > 0 ? Math.log10(value) : null;
}

/**
 * Edges covering `coords` (already in axis units) in `bins` equal-width
 * buckets.
 *
 * A constant column is widened by half a unit on each side so its single bin
 * has a non-zero width, which Plotly needs to draw anything at all. `end` sits
 * one bin width past the largest value because the bins are half-open and the
 * maximum would otherwise fall outside the grid.
 */
export function binEdges(coords: readonly number[], bins: number): BinEdges | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of coords) {
    if (!Number.isFinite(v)) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;

  const count = Math.max(1, Math.floor(bins));
  if (lo === hi) return { start: lo - 0.5, end: hi + 0.5, size: 1 / count };
  const size = (hi - lo) / count;
  return { start: lo, end: hi + size, size };
}

/** Drawable pairs plus the bin block for each axis. */
export function densityGrid(
  xs: readonly number[],
  ys: readonly number[],
  options: { logX: boolean; logY: boolean; bins: number },
): DensityGrid {
  const x: number[] = [];
  const y: number[] = [];
  const xCoords: number[] = [];
  const yCoords: number[] = [];
  const n = Math.min(xs.length, ys.length);
  for (let i = 0; i < n; i++) {
    const cx = axisCoord(xs[i], options.logX);
    const cy = axisCoord(ys[i], options.logY);
    if (cx === null || cy === null) continue;
    x.push(xs[i]);
    y.push(ys[i]);
    xCoords.push(cx);
    yCoords.push(cy);
  }
  return {
    x,
    y,
    xbins: binEdges(xCoords, options.bins),
    ybins: binEdges(yCoords, options.bins),
  };
}

export interface DensityHeatmap {
  /** Bin edges in data units (10^edge on a log axis), one more than the columns of `z`. */
  xEdges: number[];
  /** Bin edges in data units, one more than the rows of `z`. */
  yEdges: number[];
  /** Counts, `z[row][column]`, rows along y. */
  z: number[][];
  /** Drawable pairs that were counted. */
  count: number;
}

/**
 * The density grid counted here rather than by Plotly's `histogram2d`.
 *
 * `histogram2d` with an explicit bin block on a log axis took Chromium down
 * on any scatter past the density threshold (mag Contigs tab, 2026-09-23:
 * 8 crashes in 9 loads with log axes, none on linear axes, none in points
 * mode). Whether the trace read the log10 block in data units and allocated
 * tens of millions of bins, or something else, the outcome was a dead tab
 * with nothing in the console. A `heatmap` trace fed pre-counted cells and
 * explicit edges leaves Plotly nothing to bin: edges in data units draw the
 * same on a linear and a log axis, since the axis maps them itself.
 *
 * Returns `null` when nothing is drawable.
 */
export function densityHeatmap(
  xs: readonly number[],
  ys: readonly number[],
  options: { logX: boolean; logY: boolean; bins: number },
): DensityHeatmap | null {
  const grid = densityGrid(xs, ys, options);
  if (grid.x.length === 0) return null;
  const n = Math.max(1, Math.floor(options.bins));
  const xc = grid.x.map((v) => axisCoord(v, options.logX) as number);
  const yc = grid.y.map((v) => axisCoord(v, options.logY) as number);
  // Exactly `bins` cells per axis, the maximum clamped into the last one: a
  // heatmap draws its own edges, so it needs no spare bin past the maximum
  // the way a `histogram2d` block does.
  const span = (coords: number[]): { lo: number; size: number } => {
    let lo = Infinity;
    let hi = -Infinity;
    for (const v of coords) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (lo === hi) return { lo: lo - 0.5, size: 1 / n };
    return { lo, size: (hi - lo) / n };
  };
  const sx = span(xc);
  const sy = span(yc);
  const z: number[][] = Array.from({ length: n }, () => new Array<number>(n).fill(0));
  for (let i = 0; i < xc.length; i++) {
    const ix = Math.min(n - 1, Math.max(0, Math.floor((xc[i] - sx.lo) / sx.size)));
    const iy = Math.min(n - 1, Math.max(0, Math.floor((yc[i] - sy.lo) / sy.size)));
    z[iy][ix] += 1;
  }
  const edges = (s: { lo: number; size: number }, log: boolean): number[] =>
    Array.from({ length: n + 1 }, (_, k) => {
      const e = s.lo + k * s.size;
      return log ? Math.pow(10, e) : e;
    });
  return { xEdges: edges(sx, options.logX), yEdges: edges(sy, options.logY), z, count: xc.length };
}
