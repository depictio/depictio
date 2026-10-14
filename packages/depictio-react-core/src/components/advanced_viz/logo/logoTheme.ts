/**
 * The logo's lane colours, all from the Mantine theme (light and dark), on
 * top of the protein panels' shared `panelColours`. Residue letters keep the
 * scientific palettes of `protein/residueColours.ts`, like the msa tile.
 */

import { alpha, type MantineTheme } from '@mantine/core';

import { cssToRgb, panelColours, type PanelColours } from '../protein/panelTheme';
import type { RGB } from '../protein/residueColours';

export interface LogoColours extends PanelColours {
  /** Insert-probability strip (alpha scaled by the probability). */
  insert: string;
  /** Expected insert-length strip. */
  insertLength: string;
  /** Occupancy (or deletion) bars and the coverage area. */
  bars: string;
  coverageFill: string;
  /** Hit bars, weakest E-value to strongest. */
  evalueRamp: RGB[];
  /** Outline of the bars on the panel background. */
  barEdge: string;
}

export function logoColours(theme: MantineTheme, isDark: boolean): LogoColours {
  const base = panelColours(theme, isDark);
  const primary = theme.colors[theme.primaryColor] ?? theme.colors.blue;
  // Weak hits fade towards the background, strong ones stand out from it.
  const ramp = isDark ? [primary[8], primary[5], primary[2]] : [primary[2], primary[5], primary[8]];
  return {
    ...base,
    insert: theme.colors.orange[isDark ? 5 : 6],
    insertLength: theme.colors.grape[isDark ? 4 : 6],
    bars: base.accent,
    coverageFill: alpha(base.accent, isDark ? 0.35 : 0.25),
    evalueRamp: ramp.map(cssToRgb),
    barEdge: isDark ? alpha(theme.colors.dark[9], 0.6) : alpha(theme.white, 0.8),
  };
}
