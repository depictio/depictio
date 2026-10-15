/**
 * Grid sections that keep linked tiles together: `display: 'workbench'` and
 * `display: 'dock'`. Pure geometry, so the grid, the viewer's `?layout=` switch
 * and the tests all apply one rule.
 *
 * - `workbench`: the section's tiles share one screen height. Row height is
 *   fitted so the stored layout, whatever its row count, fills the visible part
 *   of the scrolling container (`fitRowPx`).
 * - `dock`: the section's anchor tile (and whatever sits in its column band)
 *   stays in a sticky column beside the scrolling sections (`dockSplit`); the
 *   section's other tiles stay in the scrolling column, rebased onto the full
 *   8 columns.
 *
 * Both are views of the same stored layout: nothing here is ever persisted.
 */
import type { FilterSectionSpec } from '../api';
import { GRID_MAX_COLS } from '../gridConfig';

/** The reader's `?layout=` override: `classic` draws workbench and dock
 *  sections as ordinary ones, `dock` turns workbenches into docks, null keeps
 *  what the dashboard declares. */
export type LayoutOverride = 'classic' | 'dock' | null;

/** A section's `display` once the override is applied. Anything that is not a
 *  group (`grid`, `strip`, unset) passes through untouched. */
export function effectiveDisplay(
  spec: Pick<FilterSectionSpec, 'display'> | null | undefined,
  override: LayoutOverride,
): FilterSectionSpec['display'] {
  const declared = spec?.display;
  if (declared !== 'workbench' && declared !== 'dock') return declared;
  if (override === 'classic') return 'grid';
  if (override === 'dock') return 'dock';
  return declared;
}

/** The geometry a layout item carries (react-grid-layout's `Layout`, minus
 *  everything the functions below never read). */
export interface GroupTile {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Fewest pixels a row is squeezed to: below this a tile is not worth
 *  reading, and the section overflows its screen instead. Low enough that a
 *  nine-row workbench still fits a laptop's visible height. */
export const MIN_FIT_ROW_PX = 28;

/** How much taller than its normal height a row may stretch to fill a tall
 *  screen. Past this a short section would just look inflated. */
export const MAX_FIT_ROW_RATIO = 1.5;

/**
 * The row height at which `totalRows` rows, and the `gapPx` between them, fill
 * `availPx`, clamped to [`MIN_FIT_ROW_PX`, 1.5 * `normalRowPx`].
 *
 * `normalRowPx` is the unit the layout is counted in: `GRID_ROW_PX` in the
 * editor, `SPLIT_ROW_PX` on a read-only grid that counts in half rows, and
 * `totalRows` must be counted the same way. `blocks` is how many separate
 * stacks share `availPx` (several docked sections one above the other): each
 * has its own gaps, so `totalRows` is their sum and the gaps are `totalRows -
 * blocks`. An unusable input (no rows, no room) leaves the normal height.
 */
export function fitRowPx(
  totalRows: number,
  availPx: number,
  gapPx: number,
  normalRowPx: number,
  blocks = 1,
): number {
  if (!(totalRows > 0) || !Number.isFinite(availPx) || availPx <= 0) return normalRowPx;
  const gaps = Math.max(0, totalRows - Math.max(1, blocks));
  const fitted = Math.floor((availPx - gaps * gapPx) / totalRows);
  const min = Math.min(MIN_FIT_ROW_PX, normalRowPx);
  const max = normalRowPx * MAX_FIT_ROW_RATIO;
  return Math.min(max, Math.max(min, fitted));
}

/** Rows a layout spans: the bottom edge of its lowest tile. */
export function layoutRows(layout: readonly Pick<GroupTile, 'y' | 'h'>[]): number {
  return layout.reduce((bottom, t) => Math.max(bottom, t.y + t.h), 0);
}

/** The columns a docked group takes: `x` and `w` of the anchor tile. */
export interface Band {
  x: number;
  w: number;
}

/**
 * The columns outside `band`, closed up and stretched back over `cols`.
 *
 * Each tile's left and right EDGES are mapped, never `x` and `w` apart: an edge
 * shared by two tiles stays shared (see `scaleLayout`). An edge maps to its
 * position once the band's columns are removed (`squeeze`; an edge inside the
 * band collapses onto the band's left edge), then to `round(squeezed * cols /
 * (cols - band.w))`. So tiles right of the band move left by its width, tiles
 * left of it stay, and both widen to share the room the band leaves. A tile
 * only partly inside the band keeps what lies outside it. Every tile keeps at
 * least one column. A band as wide as the grid leaves nothing to rebase.
 */
export function rebaseOutsideBand<T extends GroupTile>(
  items: readonly T[],
  band: Band,
  cols: number = GRID_MAX_COLS,
): T[] {
  const kept = cols - band.w;
  if (kept <= 0) return [];
  const squeeze = (edge: number) =>
    edge <= band.x ? edge : edge >= band.x + band.w ? edge - band.w : band.x;
  const stretch = (edge: number) => Math.round((squeeze(edge) * cols) / kept);
  return items.map((it) => {
    const x = Math.min(cols - 1, Math.max(0, stretch(it.x)));
    const right = Math.min(cols, Math.max(x + 1, stretch(it.x + it.w)));
    return { ...it, x, w: right - x };
  });
}

/** What a dock keeps and what stays behind. */
export interface DockSplit<T extends GroupTile> {
  /** The anchor's column band, or null for an empty layout. */
  band: Band | null;
  /** Tiles fully inside the band, `x` relative to the band (0 .. band.w - 1),
   *  so they lay out on a grid of `band.w` columns. */
  docked: T[];
  /** Every other tile, rebased onto the full 8 columns (`rebaseOutsideBand`). */
  rest: T[];
}

/**
 * Split one section's layout (8 columns) into the part that docks and the part
 * that keeps scrolling.
 *
 * The anchor is the tallest tile, the one the others are read against (ties go
 * to the one reading first: top, then left). Its column band [x, x + w) is the
 * dock's width; every tile lying entirely inside that band docks with it. A
 * tile that merely overlaps the band, or lies beside it, stays in the
 * scrolling column.
 */
export function dockSplit<T extends GroupTile>(layouts: readonly T[]): DockSplit<T> {
  if (layouts.length === 0) return { band: null, docked: [], rest: [] };
  const anchor = layouts.reduce((best, t) =>
    t.h > best.h || (t.h === best.h && (t.y < best.y || (t.y === best.y && t.x < best.x)))
      ? t
      : best,
  );
  const band: Band = { x: anchor.x, w: anchor.w };
  const inside = (t: T) => t.x >= band.x && t.x + t.w <= band.x + band.w;
  const docked = layouts.filter(inside).map((t) => ({ ...t, x: t.x - band.x }));
  const rest = rebaseOutsideBand(
    layouts.filter((t) => !inside(t)),
    band,
  );
  return { band, docked, rest };
}

/** Smallest and largest share of the container a dock may take. */
export const MIN_DOCK_FRACTION = 0.25;
export const MAX_DOCK_FRACTION = 0.5;

/**
 * How much of the container's width the dock column takes: the widest docked
 * tile's share of the 8 columns, kept between a quarter and a half so the
 * scrolling column stays the main one and the dock stays usable.
 */
export function dockWidthFraction(layouts: readonly Pick<GroupTile, 'w'>[]): number {
  const widest = layouts.reduce((w, t) => Math.max(w, t.w), 0);
  return Math.min(MAX_DOCK_FRACTION, Math.max(MIN_DOCK_FRACTION, widest / GRID_MAX_COLS));
}
