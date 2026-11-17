/** Axis furniture for the embedding scatter (2D).
 *
 * Why this exists: `applyLayoutTheme` retints every axis after the renderer
 * built it, and sets `linecolor` to the grid colour (8 % alpha). The axis
 * lines the renderer asked for were therefore drawn at the same near-invisible
 * tint as a gridline, so a PCA read as "no axes" and axis, grid and zero line
 * could not be told apart. This module builds the axes (and their arrow tips)
 * and re-asserts the line colour after the theme pass.
 *
 * Styles (`plot_style`):
 *  - `default`: two bold axis lines with an arrowhead at the end of each, no
 *    grid. A linear projection (PCA / PCoA) keeps its tick labels, since the
 *    PC values can matter; a neighbour embedding (UMAP / t-SNE) hides them and
 *    puts the short axis names in the corner, the usual "clean embedding" look.
 *  - `lines`: the bold axis lines alone (no arrowheads, no tick labels).
 *  - `grid`: ticks and a faint grid, with the same bold axis lines.
 *  - `clean`: no axes at all.
 */
import type { EmbeddingMethod } from './embeddingAxes';

export type PlotStyle = 'default' | 'lines' | 'grid' | 'clean';

/** `linear`: coordinates are a projection whose values mean something (PC
 *  scores). `neighbour`: UMAP / t-SNE, where only the layout is meaningful. */
export type EmbeddingFamily = 'linear' | 'neighbour';

export interface EmbeddingAxisColors {
  /** Bold axis line, arrowheads and tick marks. */
  axis: string;
  /** Faint gridlines, only drawn by the `grid` style. */
  grid: string;
  /** Titles and tick labels. */
  text: string;
}

const NEIGHBOUR_NAME = /umap|t-?sne|tsne|neighbo/i;

/** Which family an embedding belongs to: the live method when computing, else
 *  the axis prefix or the coordinate column names. Anything unrecognised is
 *  `linear` so its tick values are kept rather than hidden. */
export function embeddingFamily(
  config: {
    dim_1_col?: string | null;
    dim_2_col?: string | null;
    axis_prefix?: string | null;
  },
  liveMethod?: EmbeddingMethod | null,
): EmbeddingFamily {
  if (liveMethod) return liveMethod === 'umap' || liveMethod === 'tsne' ? 'neighbour' : 'linear';
  const hint = [config.axis_prefix, config.dim_1_col, config.dim_2_col].filter(Boolean).join(' ');
  return NEIGHBOUR_NAME.test(hint) ? 'neighbour' : 'linear';
}

/** Axis stroke width in px: clearly heavier than the 1 px grid. */
export const AXIS_LINE_WIDTH = 1.8;
/** Length in px of the stub the arrowhead is drawn on. */
const ARROW_STUB = 22;

type Obj = Record<string, unknown>;

function arrow(ax: number, ay: number, x: number, y: number, color: string): Obj {
  // Paper-referenced: the tip stays on the corner of the plot area whatever
  // the zoom. The pixel-offset tail is just long enough to carry the head.
  return {
    xref: 'paper',
    yref: 'paper',
    x,
    y,
    axref: 'pixel',
    ayref: 'pixel',
    ax,
    ay,
    text: '',
    showarrow: true,
    arrowhead: 2,
    arrowsize: 1.1,
    arrowwidth: AXIS_LINE_WIDTH,
    arrowcolor: color,
    standoff: 0,
    startstandoff: 0,
    captureevents: false,
  };
}

function cornerLabel(text: string, vertical: boolean, color: string): Obj {
  const base = {
    xref: 'paper',
    yref: 'paper',
    text,
    showarrow: false,
    font: { size: 12, color },
    captureevents: false,
  };
  return vertical
    ? { ...base, x: 0, y: 0, xanchor: 'right', yanchor: 'bottom', xshift: -8, textangle: -90 }
    : { ...base, x: 0, y: 0, xanchor: 'left', yanchor: 'top', yshift: -8 };
}

export interface EmbeddingAxisLayout {
  xaxis: Obj;
  yaxis: Obj;
  annotations: Obj[];
}

/** The two 2D axes and their annotations for a plot style. `titles` are the
 *  dimension names (`PC1`, `UMAP 1`, ...). */
export function embeddingAxisLayout(opts: {
  style: PlotStyle;
  family: EmbeddingFamily;
  titles: [string, string];
  colors: EmbeddingAxisColors;
}): EmbeddingAxisLayout {
  const { style, family, titles, colors } = opts;
  const clean = style === 'clean';
  const grid = style === 'grid';
  const arrows = style === 'default';
  const ticks = grid || (arrows && family === 'linear');
  const cornerTitles = arrows && family === 'neighbour';

  const axis = (title: string): Obj => ({
    zeroline: false,
    showgrid: grid,
    gridcolor: colors.grid,
    gridwidth: 1,
    showline: !clean,
    linecolor: colors.axis,
    linewidth: AXIS_LINE_WIDTH,
    mirror: false,
    showticklabels: ticks,
    ticks: ticks ? 'outside' : '',
    ticklen: 4,
    tickwidth: 1,
    tickcolor: colors.axis,
    color: colors.text,
    tickfont: { color: colors.text },
    title: cornerTitles ? { text: '' } : { text: title, standoff: 6, font: { size: 12, color: colors.text } },
  });

  const annotations: Obj[] = [];
  if (arrows) {
    annotations.push(arrow(-ARROW_STUB, 0, 1, 0, colors.axis));
    annotations.push(arrow(0, ARROW_STUB, 0, 1, colors.axis));
  }
  if (cornerTitles) {
    annotations.push(cornerLabel(titles[0], false, colors.text));
    annotations.push(cornerLabel(titles[1], true, colors.text));
  }
  return {
    xaxis: axis(titles[0]),
    yaxis: { ...axis(titles[1]), scaleanchor: 'x', scaleratio: 1 },
    annotations,
  };
}

/** Axis keys the embedding owns outright: the strokes, ticks and grid of the
 *  chosen style. */
const OWNED_AXIS_KEYS = [
  'showline',
  'linecolor',
  'linewidth',
  'mirror',
  'ticks',
  'ticklen',
  'tickwidth',
  'tickcolor',
  'showgrid',
  'gridcolor',
  'gridwidth',
  'zeroline',
] as const;

/** Put the stroke settings of `source` back on `themed`. Two passes run after
 *  the renderer builds its axes and both flatten them: the theme pass tints
 *  `linecolor` to the grid colour (8 % alpha), and the Glass ("Paper") chrome
 *  patch forces `showline: false`, `ticks: ''` and its own grid onto every
 *  axis. Left alone, the axes the plot style asked for never show. */
export function reassertAxisLines(themed: Obj, source: Obj): Obj {
  const out: Obj = { ...themed };
  for (const key of ['xaxis', 'yaxis']) {
    const from = source[key] as Obj | undefined;
    const to = out[key] as Obj | undefined;
    if (!from || !to) continue;
    const owned: Obj = {};
    for (const k of OWNED_AXIS_KEYS) if (k in from) owned[k] = from[k];
    out[key] = { ...to, ...owned };
  }
  return out;
}

/** Marker size and outline when the author set none, from the point count.
 *  A sample PCA of a dozen libraries reads best as big outlined dots; a cell
 *  UMAP of thousands needs small bare ones, or the cloud turns into a blot. */
export interface AutoMarker {
  size: number;
  outlineWidth: number;
}

export const FEW_POINTS = 50;
export const MANY_POINTS = 1000;

export function autoMarker(nPoints: number): AutoMarker {
  if (nPoints <= FEW_POINTS) return { size: 20, outlineWidth: 2.5 };
  if (nPoints <= MANY_POINTS) return { size: 8, outlineWidth: 0.5 };
  return { size: 4, outlineWidth: 0 };
}
