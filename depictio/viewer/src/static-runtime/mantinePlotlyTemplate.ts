/**
 * Client-side `mantine_light` / `mantine_dark` Plotly templates for the
 * static-bundle runtime.
 *
 * The LIVE render path re-requests `renderFigure(..., theme)` whenever the
 * Mantine color scheme flips, and the server re-templates the figure with
 * `depictio/cli/cli/utils/mantine_templates.py`. A bundle has no server, so
 * the api shim swaps the frozen figure's `layout.template` with this
 * JS mirror of those templates instead. Colorway, text, grid, zero-line and
 * hover tokens and the font all come from depictio's shared plot palette
 * (`palettes.ts`, one source with the Python side), so a frozen figure and a
 * live one wear the same colours.
 */
import { PLOT_FONT_FAMILY } from '../../../../packages/depictio-react-core/src/palettes.generated';
import {
  categoricalPalette,
  plotChrome,
} from '../../../../packages/depictio-react-core/src/palettes';

/** Sequential colorscale — verbatim mirror of `_SEQUENTIAL_COLORS` in
 *  `mantine_templates.py` (dmc's gradient; interpolated stops, so most of
 *  these are not palette entries and must stay literal to match the server). */
const SEQUENTIAL_COLORS = [
  '#1864ab',
  '#7065b9',
  '#af61b7',
  '#e35ea5',
  '#ff6587',
  '#ff7c63',
  '#ff9e3d',
  '#fcc419',
];
const SEQUENTIAL: [number, string][] = SEQUENTIAL_COLORS.map((c, i) => [
  i / (SEQUENTIAL_COLORS.length - 1),
  c,
]);

export type ThemeName = 'light' | 'dark';

/** Build the template object Plotly should merge under `layout.template`. */
export function mantinePlotlyTemplate(theme: ThemeName): Record<string, unknown> {
  const chrome = plotChrome(theme);
  const colorway = [...categoricalPalette(null, theme)];
  const bg = chrome.surface;
  const axis = {
    gridcolor: chrome.grid,
    gridwidth: 0.5,
    zerolinecolor: chrome.zero,
    linecolor: chrome.axis_line,
    color: chrome.text,
  };
  return {
    layout: {
      colorway,
      paper_bgcolor: bg,
      plot_bgcolor: bg,
      font: { family: PLOT_FONT_FAMILY, color: chrome.text },
      xaxis: axis,
      yaxis: axis,
      geo: { bgcolor: bg },
      hoverlabel: {
        bgcolor: chrome.hover_bg,
        bordercolor: chrome.hover_border,
        font: { color: chrome.hover_text },
      },
      colorscale: { sequential: SEQUENTIAL },
    },
  };
}

/**
 * Re-theme a frozen figure payload for the requested UI theme. Non-mutating:
 * the manifest object stays pristine so a later toggle re-themes from the
 * original again. Only `layout.template` is replaced — per-trace colors the
 * producer baked in stay untouched, exactly like the live server path, where
 * only the template changes between light and dark renders.
 */
export function themedFrozenFigure<
  T extends { figure?: { data?: unknown[]; layout?: Record<string, unknown> } },
>(payload: T, theme: ThemeName): T {
  const figure = payload.figure ?? {};
  return {
    ...payload,
    figure: {
      ...figure,
      layout: {
        ...(figure.layout ?? {}),
        template: mantinePlotlyTemplate(theme),
      },
    },
  };
}
