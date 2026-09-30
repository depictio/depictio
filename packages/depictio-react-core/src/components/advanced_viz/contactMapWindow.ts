/**
 * Keeping a contact map on the region it was narrowed to.
 *
 * A region reaches a contact map in two ways. Named on the tile's own columns
 * (`chrom1` / `start1`), `useFollowedRegion` sees it and the tile fetches that
 * window. Rewritten by a `region` link (the navigator publishes `chrom` /
 * `start` on another collection), it only narrows the rows server-side, on the
 * first bin of each pair: the tile never learns the window, and the second bin
 * (`start2`) still runs to the end of the chromosome. The triangle then drew
 * 65 to 180 Mb for a 65 to 85 Mb region, with a separation axis to match.
 *
 * So the drawing is clipped by role: both bins of a pair must fall inside the
 * window, and when the window is not known it is read back off the first-bin
 * coordinates of the narrowed rows.
 */

export interface ContactWindow {
  start: number;
  end: number;
}

export interface ContactCell {
  a: number;
  b: number;
  count: number;
}

/**
 * The first-bin extent of the cells, as the window a region link narrowed
 * them to. `binSize` closes the last bin (a start alone has no width).
 */
export function inferContactWindow(
  cells: readonly ContactCell[],
  binSize?: number | null,
): ContactWindow | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const { a } of cells) {
    if (a < lo) lo = a;
    if (a > hi) hi = a;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null;
  const width = binSize && binSize > 0 ? binSize : 0;
  return { start: lo, end: hi + width };
}

/**
 * The cells whose two bins both overlap `window`. A bin is `[start,
 * start + binSize)`; without a bin size it is its start alone.
 */
export function clipContactCells<T extends ContactCell>(
  cells: readonly T[],
  window: ContactWindow | null,
  binSize?: number | null,
): T[] {
  if (!window) return cells.slice();
  const width = binSize && binSize > 0 ? binSize : 0;
  const inside = (p: number) =>
    width > 0 ? p + width > window.start && p < window.end : p >= window.start && p <= window.end;
  return cells.filter((c) => inside(c.a) && inside(c.b));
}
