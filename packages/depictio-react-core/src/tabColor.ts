/**
 * The hue of the tab a component is drawn on.
 *
 * A tab names its colour once (`tab_icon_color`). Its sections, its KPI cards
 * and the marks of figures that colour by no data column all take it, so a tab
 * reads as one thing. The viewer and the editor provide it next to the
 * dashboard's category colours; the builder preview and the catalog gallery
 * provide nothing, and a figure there keeps the theme's own colours.
 *
 * Data colours (`category_colors`, `color_scale`, verdicts) are never replaced
 * by it: it only reaches marks that had no colour of their own.
 */
import { createContext, useContext } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';

import { paletteHex, parsePaletteColor } from './paletteColor';

/** The tab's `tab_icon_color` as authored (`teal`, `teal.5`, `brandPrimary`),
 *  or null outside a tab. */
export const TabColorContext = createContext<string | null>(null);

/** Colours that are ink or paper, not a hue: a tab forced to `dark` (the
 *  MultiQC tabs) must not paint its figures black. */
const NOT_A_HUE: ReadonlySet<string> = new Set(['dark', 'black', 'white']);

/**
 * The tab hue as a concrete colour Plotly (or a canvas) can paint, or
 * undefined without one: shade 6 on the light theme, 4 on the dark, unless the
 * tab named a shade itself.
 */
export function tabHueHex(
  theme: Parameters<typeof paletteHex>[0],
  tabColor: string | null | undefined,
  isDark: boolean,
): string | undefined {
  const parsed = parsePaletteColor(tabColor);
  if (!parsed) return undefined;
  if (parsed.kind === 'palette' && NOT_A_HUE.has(parsed.name)) return undefined;
  const hex = paletteHex(theme, tabColor, isDark ? 4 : 6);
  // An unknown palette name comes back as itself: not a colour Plotly knows.
  return hex && (parsed.kind === 'literal' || hex !== parsed.name) ? hex : undefined;
}

/** The tab hue for the current theme and colour scheme (see `tabHueHex`). */
export function useTabHue(): string | undefined {
  const tabColor = useContext(TabColorContext);
  const theme = useMantineTheme();
  const { colorScheme } = useMantineColorScheme();
  return tabHueHex(theme, tabColor, colorScheme === 'dark');
}
