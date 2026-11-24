/**
 * Apply light/dark theming to a Plotly layout so previews match the browser /
 * app color scheme. plotly.js doesn't ship named templates (that's plotly.py),
 * so we set transparent backgrounds (inherit the card), a theme-appropriate
 * font color, and subtle grid/zeroline colors — deep-merging xaxis/yaxis so we
 * don't clobber their titles/ranges. Works for both the client-built UI-mode
 * preview and the Pyodide code-mode figure.
 */
import { PLOT_FONT_FAMILY } from 'depictio-react-core/palettes.generated';
import { categoricalPalette, plotChrome } from 'depictio-react-core/palettes';

type Layout = Record<string, unknown>;

// Tokens, font and default colorway come from depictio's shared plot palette
// (`palettes.ts`, one source with the Python side). Imported from its module
// directly, not the barrel, so react-core's renderer tree stays out of this
// backend-less bundle. `guide` is depictio's zero-line colour
// (`services/advanced_viz/theme.py`), which its figure builder draws reference
// lines in.

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
  const chrome = plotChrome(scheme);
  const { text: font, grid, zero: guide } = chrome;
  const axis = (a: unknown): Record<string, unknown> => ({
    ...(a && typeof a === 'object' ? (a as Record<string, unknown>) : {}),
    gridcolor: grid,
    zerolinecolor: chrome.zero,
    linecolor: chrome.axis_line,
  });
  return {
    ...layout,
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: {
      family: PLOT_FONT_FAMILY,
      ...(layout.font as Record<string, unknown> | undefined),
      color: font,
    },
    // A figure's own colorway wins; traces that name no colour take the palette.
    colorway: layout.colorway ?? [...categoricalPalette(null, scheme)],
    hoverlabel: {
      bgcolor: chrome.hover_bg,
      bordercolor: chrome.hover_border,
      ...(layout.hoverlabel as Record<string, unknown> | undefined),
      font: {
        color: chrome.hover_text,
        ...((layout.hoverlabel as Record<string, unknown> | undefined)?.font as
          | Record<string, unknown>
          | undefined),
      },
    },
    xaxis: axis(layout.xaxis),
    yaxis: axis(layout.yaxis),
    ...(layout.shapes ? { shapes: guided(layout.shapes, guide, 'line') } : {}),
    ...(layout.annotations ? { annotations: guided(layout.annotations, guide, 'font') } : {}),
  };
}
