/**
 * Grid sections that keep linked tiles together: `display: 'workbench'`. Pure
 * geometry, so the grid, the viewer's `?layout=` switch and the tests all apply
 * one rule.
 *
 * - `workbench`: the section's tiles share one screen height. Row height is
 *   fitted so the stored layout, whatever its row count, fills the visible part
 *   of the scrolling container (`fitRowPx`).
 *
 * A workbench is a view of the stored layout: nothing here is ever persisted.
 */
import type { FilterSectionSpec } from '../api';

/** The reader's `?layout=` override: `classic` draws workbench sections as
 *  ordinary ones, null keeps what the dashboard declares. */
export type LayoutOverride = 'classic' | null;

/** A section's `display` once the override is applied. Anything that is not a
 *  workbench (`grid`, `strip`, unset) passes through untouched. */
export function effectiveDisplay(
  spec: Pick<FilterSectionSpec, 'display'> | null | undefined,
  override: LayoutOverride,
): FilterSectionSpec['display'] {
  const declared = spec?.display;
  if (declared !== 'workbench') return declared;
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
 * stacks share `availPx`: each has its own gaps, so `totalRows` is their sum
 * and the gaps are `totalRows - blocks`. An unusable input (no rows, no room)
 * leaves the normal height.
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
