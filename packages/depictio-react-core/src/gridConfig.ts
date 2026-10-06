/**
 * Shared canvas grid geometry.
 *
 * Two grids render dashboard components — `DashboardGrid` (the tab's own
 * canvas) and `PersistentSectionsHost` (cross-tab pinned sections) — and their
 * breakpoint/column maps must never drift apart, or the same component row
 * wraps in one surface and not the other.
 *
 * Breakpoints apply to the CONTENT width, not the window: the tabs sidebar
 * (250px), the filter panel (~300px + 6px resizer) and paddings eat ~570px, so
 * a 1512px laptop with both panels open leaves ~940px for the grid. The `lg`
 * threshold is therefore deliberately low (880): authors lay dashboards out on
 * the 8-column grid, and components should SHRINK when panels open — wrapping
 * to fewer columns is a last resort for genuinely narrow contexts. Below 768px
 * window width the filter panel already moves into a drawer, so `sm`/`xs`
 * effectively serve phones only.
 */
export const GRID_BREAKPOINTS = { lg: 880, md: 700, sm: 560, xs: 0 } as const;

export const GRID_COL_COUNTS = { lg: 8, md: 6, sm: 4, xs: 2 } as const;

/** Column count of the authoring grid — mirrors the server's `_GRID_COLS`. */
export const GRID_MAX_COLS = GRID_COL_COUNTS.lg;

/** The only breakpoint whose layout is ever persisted. */
export const GRID_WIDEST_BREAKPOINT = 'lg';

/** The geometry a layout item carries (react-grid-layout's `Layout`). */
export interface GridTile {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * A phone's layout: the tiles in reading order, a quarter-width tile half a
 * row (so a row of four cards becomes two rows of two) and anything wider the
 * full row.
 *
 * Scaling the edges, as the wider breakpoints do, has nothing to round to at
 * two columns: four quarter-width cards put three of their edges on the same
 * column, compaction then stacks those three down the right-hand side, and two
 * half-width figures stay side by side at a phone's half width.
 */
export function phoneLayout<T extends GridTile>(lg: T[], cols: number): T[] {
  const half = Math.max(1, Math.floor(cols / 2));
  const ordered = [...lg].sort((a, b) => a.y - b.y || a.x - b.x);
  const out: T[] = [];
  let x = 0;
  let y = 0;
  let rowH = 0;
  for (const item of ordered) {
    const w = item.w * 4 <= GRID_MAX_COLS ? half : cols;
    if (x + w > cols) {
      y += rowH;
      x = 0;
      rowH = 0;
    }
    out.push({ ...item, x, y, w });
    x += w;
    rowH = Math.max(rowH, item.h);
  }
  return out;
}
