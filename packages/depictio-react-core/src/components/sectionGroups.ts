/**
 * Grid sections that keep linked tiles together: `display: 'linked'`. Pure
 * geometry, so the grid, the viewer's `?layout=` switch and the tests all apply
 * one rule.
 *
 * - `linked`: the section's tiles share one screen height. Row height is
 *   fitted so the stored layout, whatever its row count, fills the visible part
 *   of the scrolling container (`fitRowPx`), but never so low that a tile drops
 *   under `LINKED_VIEW_MIN_PANE_PX`: a stack of three is taller than a laptop's
 *   screen, and the reader scrolls a little instead of reading three slivers.
 *
 * A linked view is a view of the stored layout: nothing here is ever persisted.
 */
import type { FilterSectionSpec } from '../api';

/** The reader's `?layout=` override: `classic` draws linked view sections as
 *  ordinary ones, null keeps what the dashboard declares. */
export type LayoutOverride = 'classic' | null;

/** A section's `display` once the override is applied. Anything that is not a
 *  linked view (`grid`, `strip`, unset) passes through untouched. */
export function effectiveDisplay(
  spec: Pick<FilterSectionSpec, 'display'> | null | undefined,
  override: LayoutOverride,
): FilterSectionSpec['display'] {
  const declared = spec?.display;
  if (declared !== 'linked') return declared;
  return override === 'classic' ? 'grid' : declared;
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
 *  reading, and the section overflows its screen instead. The tiles' own floor
 *  (`LINKED_VIEW_MIN_PANE_PX`) is what usually holds a row up; this is the least
 *  a row keeps when nothing else does. */
export const MIN_FIT_ROW_PX = 28;

/** How much taller than its normal height a row may stretch to fill a tall
 *  screen. Past this a short section would just look inflated. A linked view
 *  exists to fill its screen, so this is generous. */
export const MAX_FIT_ROW_RATIO = 2;

/** Least height, in px, that a linked view gives each of its tiles by default.
 *  Below it a figure's header, its axes and its lanes crowd each other, and a
 *  track or an alignment spills past its box. A reader may still drag a gutter
 *  below it, and the linked view is made as tall as its stacks need, not as tall
 *  as the screen. */
export const LINKED_VIEW_MIN_PANE_PX = 280;

/**
 * The row height at which `totalRows` rows, and the `gapPx` between them, fill
 * `availPx`, clamped to [`MIN_FIT_ROW_PX`, 2 * `normalRowPx`], and never below
 * `floorPx`.
 *
 * `normalRowPx` is the unit the layout is counted in: `GRID_ROW_PX` in the
 * editor, `SPLIT_ROW_PX` on a read-only grid that counts in half rows, and
 * `totalRows` must be counted the same way. `blocks` is how many separate
 * stacks share `availPx`: each has its own gaps, so `totalRows` is their sum
 * and the gaps are `totalRows - blocks`. An unusable input (no rows, no room)
 * leaves the normal height.
 *
 * `floorPx` is the row height the tiles need to keep their own minimum
 * (`rowFloorPx`, `minRowPxForTiles`). It wins over the screen and over the
 * stretch cap: a linked view whose stacks need more than the screen has is
 * taller than the screen, and the reader scrolls.
 */
export function fitRowPx(
  totalRows: number,
  availPx: number,
  gapPx: number,
  normalRowPx: number,
  blocks = 1,
  floorPx = 0,
): number {
  const floor = Number.isFinite(floorPx) && floorPx > 0 ? floorPx : 0;
  if (!(totalRows > 0) || !Number.isFinite(availPx) || availPx <= 0) {
    return Math.max(normalRowPx, floor);
  }
  const gaps = Math.max(0, totalRows - Math.max(1, blocks));
  const fitted = Math.floor((availPx - gaps * gapPx) / totalRows);
  const min = Math.min(MIN_FIT_ROW_PX, normalRowPx);
  const max = normalRowPx * MAX_FIT_ROW_RATIO;
  return Math.max(floor, Math.min(max, Math.max(min, fitted)));
}

/**
 * The row height at which `totalRows` rows and the `gapPx` between them are at
 * least `heightPx` tall: what a split tree needs (`treeMinHeightPx`) turned
 * into the row height `fitRowPx` takes as its floor. Rounded up, so the rows
 * never fall a pixel short.
 */
export function rowFloorPx(heightPx: number, totalRows: number, gapPx: number): number {
  if (!(totalRows > 0) || !Number.isFinite(heightPx) || heightPx <= 0) return 0;
  return Math.max(0, Math.ceil((heightPx - (totalRows - 1) * gapPx) / totalRows));
}

/**
 * The row height at which every tile of a grid layout is at least its own
 * floor tall: a tile `h` rows high spans `h * row + (h - 1) * gap`, so its row
 * must be `(floor - (h - 1) * gap) / h`. The tightest tile sets it. This is the
 * minimum row height of a linked view that react-grid-layout draws (a layout
 * that cannot be cut into panes), where there is no split to sum over.
 * `floorOf` answers per tile key; 0 leaves a tile as short as it is.
 */
export function minRowPxForTiles(
  tiles: readonly Pick<GroupTile, 'i' | 'h'>[],
  floorOf: (key: string) => number,
  gapPx: number,
): number {
  let row = 0;
  for (const t of tiles) {
    if (!(t.h > 0)) continue;
    const floor = floorOf(t.i);
    if (!Number.isFinite(floor) || floor <= 0) continue;
    row = Math.max(row, Math.ceil((floor - (t.h - 1) * gapPx) / t.h));
  }
  return row;
}

/** Rows a layout spans: the bottom edge of its lowest tile. */
export function layoutRows(layout: readonly Pick<GroupTile, 'y' | 'h'>[]): number {
  return layout.reduce((bottom, t) => Math.max(bottom, t.y + t.h), 0);
}
