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

/**
 * Rows per stored row on a read-only grid.
 *
 * Text tiles and cards size themselves to their content, and rounding that up
 * to whole 100px rows left up to a row of blank under a tile — a framed card
 * a few pixels over two rows came out three rows tall, and prose reflowed on
 * a phone came out a row long. A read-only grid lays out in rows half as tall
 * with the same gap, so two of them span exactly one stored row: figures keep
 * their height to the pixel and fitted tiles stop within half a row of their
 * content. The editor keeps whole rows, the unit layouts are stored in.
 */
export const ROW_SPLIT = 2;

/** A stored layout in read-only rows (see `ROW_SPLIT`). */
export function toSplitRows<T extends { y: number; h: number }>(layout: readonly T[]): T[] {
  return layout.map((l) => ({ ...l, y: l.y * ROW_SPLIT, h: l.h * ROW_SPLIT }));
}

/** The geometry a layout item carries (react-grid-layout's `Layout`). */
export interface GridTile {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * The `lg` layout rescaled to `cols` columns.
 *
 * Scale the column EDGES, never `x` and `w` separately: rounding each of those
 * on its own lets a row that tiled exactly at `lg` stop tiling. Four `w: 2`
 * cards at x 0/2/4/6 would scale to widths 2/2/2/2 at 6 columns but to x
 * 0/2/3/4, so the last three overlap, and react-grid-layout then breaks the
 * row apart to resolve the collision. Rounding the shared edge once gives both
 * neighbours the same answer, so a boundary that coincided still coincides.
 *
 * Edges still land between columns when a full row of equal tiles does not
 * divide the new count: those four cards come out 2/1/2/1 wide in six
 * columns. Such a row wraps instead, into lines of equal tiles — as many per
 * line as divide both the row and the columns (two lines of two, there). The
 * rows below move down by the lines it gained.
 */
export function scaleLayout<T extends GridTile>(lg: T[], cols: number): T[] {
  const edge = (v: number) => Math.round((v * cols) / GRID_MAX_COLS);
  const out = lg.map((item) => {
    // Every tile keeps at least one column, so a row with more tiles than the
    // breakpoint has columns still collides — there is no honest way to fit
    // five cards into two columns, and the grid stacks them instead.
    const x = Math.min(cols - 1, Math.max(0, edge(item.x)));
    const right = Math.min(cols, Math.max(x + 1, edge(item.x + item.w)));
    return { ...item, x, w: right - x };
  });

  const rowYs = [...new Set(lg.map((t) => t.y))].sort((a, b) => a - b);
  let shift = 0;
  const shiftFrom: Array<[number, number]> = [];
  for (const y of rowYs) {
    const row = lg.filter((t) => t.y === y).sort((a, b) => a.x - b.x);
    const n = row.length;
    const w0 = row[0].w;
    const even =
      n > 1 &&
      row.every((t, k) => t.w === w0 && t.x === k * w0) &&
      n * w0 === GRID_MAX_COLS &&
      (w0 * cols) % GRID_MAX_COLS !== 0;
    if (!even) continue;
    let perLine = 1;
    for (let k = n; k >= 1; k--) {
      if (cols % k === 0 && n % k === 0) {
        perLine = k;
        break;
      }
    }
    const lineH = Math.max(...row.map((t) => t.h));
    const width = cols / perLine;
    row.forEach((t, k) => {
      const at = lg.indexOf(t);
      out[at] = {
        ...out[at],
        x: (k % perLine) * width,
        w: width,
        y: y + Math.floor(k / perLine) * lineH,
      };
    });
    const gained = (n / perLine - 1) * lineH;
    if (gained > 0) {
      shift += gained;
      shiftFrom.push([y, shift]);
    }
  }
  if (shiftFrom.length === 0) return out;
  // Tiles below a wrapped row move down by every line gained above them.
  return out.map((t, k) => {
    const y0 = lg[k].y;
    let by = 0;
    for (const [rowY, total] of shiftFrom) if (y0 > rowY) by = total;
    return by ? { ...t, y: t.y + by } : t;
  });
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
