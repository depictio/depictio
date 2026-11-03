/**
 * Where a scatter_xy point label sits relative to its point.
 *
 * A label centred above its point runs off the plot where the point is near an
 * edge: onto the y tick labels for the left-most point, past the right margin
 * for the right-most, into the top margin for the highest. Autorange pads the
 * markers, not their text, and few points make every point an extreme, so the
 * placement leans inward by where the point sits in the data's extent.
 */

export interface LabelPlacement {
  xanchor: 'left' | 'center' | 'right';
  xshift: number;
  /** Plotly's `yshift`: positive is above the point. */
  yshift: number;
}

/** A point this close to an edge of the extent (0..1) leans its label inward. */
const EDGE_FRACTION = 0.15;
/** Vertical offset from the point to the label, px. */
const LABEL_LIFT_PX = 10;
/** Horizontal nudge of an inward-leaning label, px. */
const LABEL_NUDGE_PX = 4;

/** Where `value` sits in `[lo, hi]`, 0..1; 0.5 when the range is empty. */
export function extentFraction(value: number, lo: number, hi: number): number {
  if (!(hi > lo) || !Number.isFinite(value)) return 0.5;
  return Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
}

/**
 * Placement of a label for a point at fractions `fx`, `fy` of the x and y
 * extents (axis coordinates, so log axes work too). Left edge: the text starts
 * at the point; right edge: it ends there; top edge: it goes under the point.
 */
export function labelPlacement(fx: number, fy: number): LabelPlacement {
  const xanchor = fx <= EDGE_FRACTION ? 'left' : fx >= 1 - EDGE_FRACTION ? 'right' : 'center';
  const xshift = xanchor === 'left' ? LABEL_NUDGE_PX : xanchor === 'right' ? -LABEL_NUDGE_PX : 0;
  const yshift = fy >= 1 - EDGE_FRACTION ? -LABEL_LIFT_PX : LABEL_LIFT_PX;
  return { xanchor, xshift, yshift };
}
