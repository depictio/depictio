/**
 * A residue panel's horizontal axis, for zoom sync (highlight/zoomSync.ts):
 * where a residue sits at a given width per column, and which residue sits at
 * a given x. Pure, unit-tested in `zoomAxis.test.ts`.
 *
 * `x` is in grid pixels: right of the panel's sticky gutter, scroll included,
 * so the view's left edge is at `scrollLeft`. Residue coordinates put residue
 * `p` on `[p, p + 1)`.
 */

export interface ZoomAxis {
  /** Residue coordinate at grid `x`, at the width now drawn. */
  posAt(x: number): number;
  /** Grid x of residue coordinate `pos` at `cw` px per column. Affine in `cw`. */
  xOf(pos: number, cw: number): number;
}

/** One column per residue, the first column holding residue `first`. */
export function uniformAxis(first: number, cw: number): ZoomAxis {
  return {
    posAt: (x) => first + (cw > 0 ? x / cw : 0),
    xOf: (pos, w) => (pos - first) * w,
  };
}

/**
 * Columns against residues when they do not line up one to one: an alignment
 * column on a gap of the reference holds no residue, and a residue the
 * reference has outside the model's match states holds no column. Built from
 * the columns that do hold a residue; in between, the two coordinates move
 * together linearly, and past either end one column is one residue.
 */
export interface ColumnResidueMap {
  /** Breakpoints, ascending in both: column coordinate and residue coordinate. */
  cols: Float64Array;
  res: Float64Array;
}

/**
 * The map of `residueOf(column)` for `count` columns (null on a column that
 * holds no residue). Residues must ascend with the columns; a column whose
 * residue does not is skipped.
 */
export function columnResidueMap(
  count: number,
  residueOf: (col: number) => number | null | undefined,
): ColumnResidueMap {
  const cols: number[] = [];
  const res: number[] = [];
  let last = -Infinity;
  for (let c = 0; c < count; c++) {
    const r = residueOf(c);
    if (r == null || !Number.isFinite(r) || r <= last) continue;
    last = r;
    // Both edges of the column: [c, c + 1) holds [r, r + 1).
    if (cols.length && cols[cols.length - 1] === c && res[res.length - 1] === r) {
      cols.push(c + 1);
      res.push(r + 1);
      continue;
    }
    cols.push(c, c + 1);
    res.push(r, r + 1);
  }
  return { cols: Float64Array.from(cols), res: Float64Array.from(res) };
}

/** Piecewise-linear lookup from `xs` to `ys`; slope 1 past either end. */
function interpolate(xs: Float64Array, ys: Float64Array, v: number): number {
  const n = xs.length;
  if (n === 0) return v;
  if (v <= xs[0]) return ys[0] - (xs[0] - v);
  if (v >= xs[n - 1]) return ys[n - 1] + (v - xs[n - 1]);
  let lo = 0;
  let hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] <= v) lo = mid;
    else hi = mid;
  }
  const span = xs[hi] - xs[lo];
  if (!(span > 0)) return ys[hi];
  return ys[lo] + ((v - xs[lo]) / span) * (ys[hi] - ys[lo]);
}

/** Residue coordinate at column coordinate `col`. */
export function residueAtColumn(map: ColumnResidueMap, col: number): number {
  return interpolate(map.cols, map.res, col);
}

/** Column coordinate of residue coordinate `pos`. */
export function columnOfResidue(map: ColumnResidueMap, pos: number): number {
  return interpolate(map.res, map.cols, pos);
}

/** Columns of `cw` px each, mapped to residues through `map` (an alignment). */
export function mappedAxis(map: ColumnResidueMap, cw: number): ZoomAxis {
  return {
    posAt: (x) => residueAtColumn(map, cw > 0 ? x / cw : 0),
    xOf: (pos, w) => columnOfResidue(map, pos) * w,
  };
}

/**
 * The width per column at which `[start, end)` fills `gridW`, or null when
 * the axis cannot say (an empty or reversed window). Solved from the axis
 * itself, so fixed-width pieces between columns (a logo's folded runs) count.
 */
export function widthForWindow(
  axis: ZoomAxis,
  start: number,
  end: number,
  gridW: number,
): number | null {
  if (!(end > start) || !(gridW > 0)) return null;
  const at0 = axis.xOf(end, 0) - axis.xOf(start, 0);
  const at1 = axis.xOf(end, 1) - axis.xOf(start, 1);
  const slope = at1 - at0;
  if (!(slope > 0)) return null;
  const cw = (gridW - at0) / slope;
  return cw > 0 && Number.isFinite(cw) ? cw : null;
}

/**
 * The width a follower asks for to show `[start, end)`: 0 (fit) when that is
 * at or below its fitted width, else the solved width clamped to `max` and
 * rounded to a hundredth of a pixel. Null when nothing should change.
 */
export function followerWidth(
  axis: ZoomAxis,
  start: number,
  end: number,
  gridW: number,
  fit: number,
  max: number,
): number | null {
  const cw = widthForWindow(axis, start, end, gridW);
  if (cw === null) return null;
  if (cw <= fit * 1.005) return 0;
  return Math.round(Math.min(max, cw) * 100) / 100;
}
