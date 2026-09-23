/**
 * How many grid rows an advanced-viz tile's content actually needs.
 *
 * A Plotly figure fills whatever box it is given, so a tile cannot be measured
 * off the DOM the way a text block or a table can: the node reports the tile
 * back rather than the content. What these renderers *do* know is a count  - 
 * six contrasts, forty genes, twelve sets, three cards, and roughly how much
 * vertical room one of them needs to stay readable. That is the whole of the
 * calculation here: a count, a per-item height, and the fixed chrome (axis
 * labels, colourbar, legend, dendrogram band) that sits around them.
 *
 * Every renderer that publishes a demand goes through this module, for two
 * reasons. The conversion from pixels to rows belongs to the grid geometry in
 * `autofit.ts` and must not be re-derived per renderer (a hardcoded 104 in
 * twenty files is twenty places to forget when the row height moves), and the
 * clamp has to be the same everywhere or one kind quietly asks for forty rows
 * while its neighbours ask for eight.
 *
 * The numbers are honest, not flattering: a tile with two bars asks for the
 * minimum. `advanced_viz` may only grow (see `FIT_POLICIES` in `autofit.ts`),
 * so a small demand changes nothing on a tile the author sized generously  - 
 * the policy decides what to do with the answer, this module only answers.
 */

import { heightForRows, rowsForHeight, type ContentDemand } from '../autofit';

export type { ContentDemand };

/**
 * The `advanced_viz` bounds, mirrored from `FIT_POLICIES` in `autofit.ts`.
 *
 * Clamped here as well as there so a demand is already in range by the time it
 * is published: an unclamped 60-row demand and a clamped 16-row one produce
 * the same layout, but only the second one reads correctly in the autofit
 * event log when a tile looks wrong.
 */
export const ADVANCED_VIZ_MIN_ROWS = 3;
export const ADVANCED_VIZ_MAX_ROWS = 16;

/** Narrower bounds than the kind's policy, for a tile that knows better. */
export interface RowBounds {
  min?: number;
  max?: number;
}

/** The px a span of `rows` offers, re-exported so a caller sizing against the
 *  grid does not have to reach past this module into `autofit.ts`. */
export { heightForRows };

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function boundsOf(bounds: RowBounds): { min: number; max: number } {
  const min = Math.max(1, Math.round(bounds.min ?? ADVANCED_VIZ_MIN_ROWS));
  const max = Math.max(min, Math.round(bounds.max ?? ADVANCED_VIZ_MAX_ROWS));
  return { min, max };
}

/** A finite, non-negative number, or `fallback` for anything else. */
function finite(value: number, fallback = 0): number {
  return Number.isFinite(value) ? Math.max(0, value) : fallback;
}

/**
 * The grid rows `px` of content needs, clamped to the advanced-viz policy.
 *
 * Always an integer in `[min, max]`: the grid counts rows, and a fractional
 * one would round somewhere else, differently, later.
 */
export function rowsForPx(px: number, bounds: RowBounds = {}): number {
  const { min, max } = boundsOf(bounds);
  return clamp(rowsForHeight(Math.round(finite(px))), min, max);
}

/**
 * The grid rows `count` items need at `pxPerItem` each, inside `chromePx` of
 * fixed furniture.
 *
 * The shape nearly every producer wants: rows of a heatmap, bars of a forest
 * plot, facets of a faceted panel, cards of a record list. A count of zero is
 * not a small tile but an unknown one (nothing fetched yet), so it comes back
 * at the minimum rather than at the chrome height.
 */
export function rowsForItems(
  count: number,
  pxPerItem: number,
  chromePx = 0,
  bounds: RowBounds = {},
): number {
  const items = Math.floor(finite(count));
  const { min } = boundsOf(bounds);
  if (items <= 0) return min;
  return rowsForPx(items * finite(pxPerItem) + finite(chromePx), bounds);
}

/**
 * `rowsForItems` as the prop `AdvancedVizFrame` takes, or `undefined` when
 * there is nothing on screen to make a claim about.
 *
 * `undefined` rather than a minimum demand is deliberate: the frame publishes
 * nothing for it, so a tile that has not fetched yet keeps the height its
 * author stored instead of collapsing to three rows and jumping back out when
 * the data lands.
 */
export function demandForItems(
  count: number,
  pxPerItem: number,
  chromePx = 0,
  bounds: RowBounds = {},
): ContentDemand | undefined {
  const items = Math.floor(finite(count));
  if (items <= 0) return undefined;
  return { rows: rowsForItems(items, pxPerItem, chromePx, bounds) };
}

/**
 * A demand straight from a pixel height, for content whose size is furniture
 * rather than a count (a parcoords axis strip, a stacked bar panel).
 */
export function demandForPx(px: number, bounds: RowBounds = {}): ContentDemand | undefined {
  const height = finite(px);
  if (height <= 0) return undefined;
  return { rows: rowsForPx(height, bounds) };
}
