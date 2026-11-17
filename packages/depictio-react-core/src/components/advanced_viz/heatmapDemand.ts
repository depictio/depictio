/**
 * How tall a clustered heatmap's tile wants to be, from the matrix it draws.
 *
 * One row of cells needs `minCellPx` to read as a band. That alone is enough
 * for a 90-gene matrix and far too little for a 12-run correlation matrix:
 * twelve rows at 12 px is a 144 px strip under a 1000 px dendrogram, and a
 * tile that follows the demand shrinks to it. So a small matrix with no
 * author-chosen cell size gets a floor on the matrix itself, spread over its
 * rows up to `MAX_AUTO_CELL_PX` each (three rows are three fat bands, not a
 * 320 px column). An author who states `min_cell_px` gets exactly that.
 */

/** The shortest a row may be drawn when the author states nothing. */
export const DEFAULT_MIN_CELL_PX = 12;
/** The least height the matrix itself is given when `min_cell_px` is unset. */
export const MIN_MATRIX_PX = 320;
/** The tallest a row grows to when the floor above is spread over few rows. */
export const MAX_AUTO_CELL_PX = 40;

/** The px the cells of `rows` rows need, bands and chrome excluded. */
export function heatmapMatrixPx(rows: number, minCellPx?: number | null): number {
  const n = Math.max(0, Math.floor(rows));
  if (n === 0) return 0;
  if (typeof minCellPx === 'number' && minCellPx > 0) return n * minCellPx;
  return Math.min(Math.max(n * DEFAULT_MIN_CELL_PX, MIN_MATRIX_PX), n * MAX_AUTO_CELL_PX);
}

/** The px a heatmap tile wants: the matrix plus the chrome and bands around it. */
export function heatmapDemandPx(
  rows: number,
  surroundPx: number,
  minCellPx?: number | null,
): number {
  const matrix = heatmapMatrixPx(rows, minCellPx);
  return matrix > 0 ? matrix + Math.max(0, surroundPx) : 0;
}
