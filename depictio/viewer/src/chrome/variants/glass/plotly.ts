import type { ChromePlotlyLayout } from 'depictio-react-core';

/** Plotly cannot read CSS variables: resolve Mantine's to concrete colours. */
function cssVar(name: string): string {
  if (typeof document === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
const pick = (name: string) => cssVar(`--mantine-color-${name}`);

/** `#rrggbb` (Mantine's palette format) at an alpha, as Plotly's rgba(). */
function alpha(color: string, a: number): string {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(color);
  if (!m) return color;
  const [r, g, b] = [m[1], m[2], m[3]].map((h) => parseInt(h, 16));
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/** Glass's hues, after the instance's primary: distinct in hue and close in
 *  weight, so no series shouts. Shade 6 on light, 4 on dark. */
const GLASS_HUES = ['teal', 'orange', 'grape', 'cyan', 'pink', 'lime', 'indigo', 'yellow', 'red'];

/**
 * Glass: charts that sit in the tile rather than on a card of their own.
 *
 * - One family, the app's Inter, in three steps: titles in the text colour,
 *   axis titles dimmed, tick labels faint. Sizes stay the figure's own.
 * - Transparent paper and plot: the tile's frosted surface shows through.
 * - A whisper of horizontal grid only; zero lines as light as a rule, no
 *   axis lines boxing the plot, no ticks.
 * - The hover label is a small card of the tile's surface with a hairline rim.
 * - Legends lose their box and keep small, even swatches.
 *
 * What a figure may set for itself (margins, legend placement, colorway) is
 * in `glassPlotlyDefaults`, merged under the figure's layout.
 */
export const glassPlotly: ChromePlotlyLayout = (scheme) => {
  const dark = scheme === 'dark';
  const base = cssVar('--mantine-font-family') || 'sans-serif';
  const sans = `'Inter Variable', Inter, ${base}`;
  const ink = dark ? pick('dark-0') : pick('gray-9');
  const dimmed = dark ? pick('dark-1') : pick('gray-7');
  const faint = dark ? pick('dark-2') : pick('gray-6');
  const line = dark ? pick('dark-0') : pick('gray-9');
  const surface = dark ? pick('dark-6') : pick('white');
  const axisPatch = {
    showline: false,
    zerolinecolor: alpha(line, dark ? 0.2 : 0.16),
    zerolinewidth: 1,
    gridcolor: alpha(line, dark ? 0.08 : 0.07),
    gridwidth: 1,
    ticks: '',
    tickfont: { family: sans, color: faint },
    title: { font: { family: sans, color: dimmed }, standoff: 8 },
    automargin: true,
  };
  return {
    font: { family: sans, color: ink },
    title: { font: { family: sans, color: ink }, x: 0, xanchor: 'left', xref: 'paper' },
    paper_bgcolor: 'rgba(0, 0, 0, 0)',
    plot_bgcolor: 'rgba(0, 0, 0, 0)',
    xaxis: { ...axisPatch, showgrid: false },
    yaxis: { ...axisPatch, showgrid: true },
    hoverlabel: {
      bgcolor: surface,
      bordercolor: alpha(line, dark ? 0.18 : 0.12),
      font: { family: sans, color: ink },
      align: 'left',
    },
    legend: {
      bgcolor: 'rgba(0, 0, 0, 0)',
      borderwidth: 0,
      font: { family: sans, color: dimmed },
      title: { font: { family: sans, color: ink } },
      itemsizing: 'constant',
      itemwidth: 30,
    },
    coloraxis: {
      colorbar: { outlinewidth: 0, thickness: 12, ticks: '', tickfont: { family: sans, color: faint } },
    },
    modebar: { bgcolor: 'rgba(0, 0, 0, 0)', color: faint, activecolor: ink },
    bargap: 0.3,
  };
};

/** The keys that place a legend. A figure that sets any of them has placed
 *  its own (an advanced figure's Legend control, a server layout), and a
 *  default filling in the others would only move it somewhere half-chosen. */
const LEGEND_PLACEMENT = ['orientation', 'x', 'y', 'xanchor', 'yanchor', 'xref', 'yref'];

/**
 * Glass defaults: merged under the figure's layout, so every value here
 * only fills what the figure leaves unset.
 *
 * - Tight margins: the axes' automargin makes room for their labels, so the
 *   plot starts on the tile's inner edge, under the header.
 * - The legend, when the figure has not placed it, runs in one row at the
 *   top left of the figure, level with the tile title's edge; Plotly keeps
 *   the plot clear of it. It needs the figure's layout to know that, so it
 *   is only set when the caller passes the layout.
 * - The colorway, led by the instance's primary: a figure's own colorway
 *   and any trace's own colour win over it.
 */
export const glassPlotlyDefaults = (
  scheme: 'light' | 'dark',
  layout?: Record<string, unknown>,
): Record<string, unknown> => {
  const dark = scheme === 'dark';
  const primary = cssVar('--mantine-primary-color-filled');
  const colorway = GLASS_HUES.map((h) => pick(`${h}-${dark ? 4 : 6}`)).filter(Boolean);
  if (/^#[0-9a-f]{6}$/i.test(primary) && !colorway.includes(primary)) colorway.unshift(primary);
  const own = (layout?.legend ?? {}) as Record<string, unknown>;
  const placeLegend = layout !== undefined && !LEGEND_PLACEMENT.some((k) => own[k] !== undefined);
  return {
    margin: { l: 4, r: 8, t: 8, b: 4, pad: 0 },
    ...(colorway.length ? { colorway } : {}),
    ...(placeLegend
      ? {
          legend: {
            orientation: 'h',
            x: 0,
            xanchor: 'left',
            xref: 'container',
            y: 1,
            yanchor: 'top',
            yref: 'container',
          },
        }
      : {}),
  };
};
