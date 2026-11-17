/**
 * When a Plotly `resize` has nothing to do.
 *
 * `Plots.resize` always ends in `relayout({autosize: true})`, a full redraw,
 * even when the graph div already has the size the figure was drawn at.
 * react-plotly.js calls it right after every mount, and a page-level `resize`
 * event reaches each figure too, so a figure got a second full draw (and
 * re-measured every label again) for no change: 1.98 s on a heatmap.
 *
 * This is the pure test, with no DOM access so it runs in the node test
 * environment; `plotlySkipIdleResize.ts` measures the div and applies it.
 */

/** The slice of a Plotly graph div the test reads. */
export interface ResizableGraphDiv {
  layout?: { width?: unknown; height?: unknown };
  _fullLayout?: { width?: number; height?: number };
  _context?: { fillFrame?: unknown; frameMargins?: unknown };
}

export interface BoxSize {
  width: number;
  height: number;
}

/** Plotly's own floor for an autosized figure (`layout.width.min`). */
const MIN_SIZE = 10;

/**
 * True when a resize would redraw the figure at the size it already has: the
 * figure autosizes (no fixed `layout.width` or `layout.height`, which `resize`
 * would drop), it is not framed to the window, and the box measures what the
 * last draw used, within the pixel Plotly itself tolerates (`plotAutoSize`).
 * Anything unknown (no draw yet, a box that does not measure) is not idle.
 */
export function resizeIsIdle(gd: ResizableGraphDiv, box: BoxSize | null): boolean {
  const drawn = gd._fullLayout;
  const layout = gd.layout;
  if (!drawn || !layout || !box) return false;
  if (layout.width || layout.height) return false;
  if (gd._context?.fillFrame || gd._context?.frameMargins) return false;
  if (!(box.width >= MIN_SIZE) || !(box.height >= MIN_SIZE)) return false;
  if (typeof drawn.width !== 'number' || typeof drawn.height !== 'number') return false;
  return Math.abs(drawn.width - box.width) <= 1 && Math.abs(drawn.height - box.height) <= 1;
}
