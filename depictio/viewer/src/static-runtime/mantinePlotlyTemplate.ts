/**
 * Client-side `mantine_light` / `mantine_dark` Plotly templates for the
 * static-bundle runtime.
 *
 * The LIVE render path re-requests `renderFigure(..., theme)` whenever the
 * Mantine color scheme flips, and the server re-templates the figure with
 * `depictio/cli/cli/utils/mantine_templates.py`. A bundle has no server, so
 * the api shim swaps the frozen figure's `layout.template` with this
 * JS mirror of those exact templates instead — same colorway, backgrounds and
 * grid colors, all derived from the Mantine default palette (the server's
 * hexes ARE Mantine default shades: light grid = gray[3], dark grid =
 * gray[8], dark paper = dark[7], colorway = accent shade 6 / 8).
 *
 * One readability addition over the server templates: an explicit font/axis
 * text color (gray[8] light / gray[2] dark — the same pair the shared
 * advanced-viz helper `plotlyTheme.ts` uses), since Plotly's built-in #444
 * default is unreadable on the dark paper.
 */
import { DEFAULT_THEME } from '@mantine/core';

/** Mantine accent order used by the server templates. */
const ACCENTS = ['blue', 'red', 'green', 'violet', 'orange', 'cyan', 'pink', 'yellow'] as const;

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
  const isDark = theme === 'dark';
  const colors = DEFAULT_THEME.colors;
  const colorway = ACCENTS.map((name) => colors[name][isDark ? 8 : 6]);
  const bg = isDark ? colors.dark[7] : DEFAULT_THEME.white;
  const grid = isDark ? colors.gray[8] : colors.gray[3];
  const text = isDark ? colors.gray[2] : colors.gray[8];
  const axis = {
    gridcolor: grid,
    gridwidth: 0.5,
    zerolinecolor: grid,
    color: text,
  };
  return {
    layout: {
      colorway,
      paper_bgcolor: bg,
      plot_bgcolor: bg,
      font: { family: DEFAULT_THEME.fontFamily, color: text },
      xaxis: axis,
      yaxis: axis,
      geo: { bgcolor: bg },
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
