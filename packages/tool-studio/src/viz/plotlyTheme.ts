/**
 * Apply light/dark theming to a Plotly layout so previews match the browser /
 * app color scheme. plotly.js doesn't ship named templates (that's plotly.py),
 * so we set transparent backgrounds (inherit the card), a theme-appropriate
 * font color, and subtle grid/zeroline colors — deep-merging xaxis/yaxis so we
 * don't clobber their titles/ranges. Works for both the client-built UI-mode
 * preview and the Pyodide code-mode figure.
 */
type Layout = Record<string, unknown>;

// `guide` is depictio's zero-line colour (`services/advanced_viz/theme.py`),
// which its figure builder draws reference lines in.
const PALETTE = {
  light: { font: '#1a1b1e', grid: '#e9ecef', guide: 'rgba(0,0,0,0.35)' },
  dark: { font: '#c1c2c5', grid: '#373a40', guide: 'rgba(255,255,255,0.35)' },
};

/** Shapes and annotations named `reference_line` (see figureBuilder.ts). */
function guided(items: unknown, guide: string, key: 'line' | 'font'): unknown {
  if (!Array.isArray(items)) return items;
  return items.map((item) => {
    if (!item || typeof item !== 'object') return item;
    const it = item as Record<string, unknown>;
    if (it.name !== 'reference_line') return item;
    return { ...it, [key]: { ...(it[key] as Record<string, unknown> | undefined), color: guide } };
  });
}

export function applyPlotlyTheme(layout: Layout, scheme: 'light' | 'dark'): Layout {
  const { font, grid, guide } = PALETTE[scheme];
  const axis = (a: unknown): Record<string, unknown> => ({
    ...(a && typeof a === 'object' ? (a as Record<string, unknown>) : {}),
    gridcolor: grid,
    zerolinecolor: grid,
    linecolor: grid,
  });
  return {
    ...layout,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { ...(layout.font as Record<string, unknown> | undefined), color: font },
    xaxis: axis(layout.xaxis),
    yaxis: axis(layout.yaxis),
    ...(layout.shapes ? { shapes: guided(layout.shapes, guide, 'line') } : {}),
    ...(layout.annotations ? { annotations: guided(layout.annotations, guide, 'font') } : {}),
  };
}
