/**
 * What a lollipop draws over its finished figure for the protein cross-talk:
 * the picked residue range (a shaded band, its stems ringed) and the residue
 * another tile is hovering (a dotted line). Pure, so the geometry is tested
 * without Plotly; the renderer turns it into shapes and a ring trace.
 */
import type { HighlightEvent } from '../../highlight/bus';

export interface LollipopLane {
  gene: string;
  /** Plotly y axis of the lane (`y`, `y2`, ...). */
  yref: string;
  /** The lane's vertical extent in paper coordinates, `[bottom, top]`. */
  domain: [number, number];
}

export interface LollipopStem {
  gene: string;
  position: number;
  /** Head height (the effect, or 1). */
  height: number;
  /** Row of the fetched frame the stem was drawn from. */
  row: number;
}

export interface OverlayShape {
  kind: 'band' | 'line';
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export interface OverlayRing {
  yref: string;
  x: number[];
  y: number[];
  size: number;
}

/** Half a residue either side, so a single picked residue is a visible band. */
const HALF_RESIDUE = 0.5;

/** One overlay shape as a Plotly layout shape on the x axis: the picked range
 *  as a faint band behind the marks, a hovered residue as a dotted line. Shared
 *  with the profile's residue axis so both draw the pick the same way. */
export function overlayShapeToPlotly(shape: OverlayShape, accent: string): Record<string, unknown> {
  const { x0, x1, y0, y1 } = shape;
  const placement = { xref: 'x', yref: 'paper', x0, x1, y0, y1 };
  if (shape.kind === 'band') {
    return {
      type: 'rect',
      ...placement,
      fillcolor: accent,
      opacity: 0.14,
      line: { width: 0 },
      layer: 'below',
    };
  }
  return { type: 'line', ...placement, line: { color: accent, width: 1.5, dash: 'dot' } };
}

export function residueOverlay(args: {
  lanes: readonly LollipopLane[];
  stems: readonly LollipopStem[];
  picked: { entity: string | null; start: number; end: number } | null;
  highlight: HighlightEvent | null;
  /** The tile's position column: a highlight naming another axis is not ours. */
  positionColumn: string;
  pointSize: number;
}): { shapes: OverlayShape[]; rings: OverlayRing[] } {
  const { lanes, stems, picked, highlight, positionColumn, pointSize } = args;
  const shapes: OverlayShape[] = [];
  const rings: OverlayRing[] = [];

  if (picked) {
    for (const lane of lanes) {
      if (picked.entity != null && picked.entity !== lane.gene) continue;
      shapes.push({
        kind: 'band',
        x0: picked.start - HALF_RESIDUE,
        x1: picked.end + HALF_RESIDUE,
        y0: lane.domain[0],
        y1: lane.domain[1],
      });
      const inRange = stems.filter(
        (st) => st.gene === lane.gene && st.position >= picked.start && st.position <= picked.end,
      );
      if (inRange.length) {
        rings.push({
          yref: lane.yref,
          x: inRange.map((st) => st.position),
          y: inRange.map((st) => st.height),
          size: pointSize + 8,
        });
      }
    }
  }

  const onOurAxis =
    highlight != null &&
    (highlight.positionColumn == null || highlight.positionColumn === positionColumn);
  if (highlight && onOurAxis) {
    const end = highlight.end ?? highlight.start;
    const xs = end === highlight.start ? [highlight.start] : [highlight.start, end];
    for (const lane of lanes) {
      if (highlight.entity != null && highlight.entity !== lane.gene) continue;
      for (const x of xs) {
        shapes.push({ kind: 'line', x0: x, x1: x, y0: lane.domain[0], y1: lane.domain[1] });
      }
    }
  }
  return { shapes, rings };
}
