/**
 * The UI colours the protein panels paint with, all taken from the Mantine
 * theme so they follow a branded theme and the dark scheme. Residue colours
 * are the separate, scientific palettes of `residueColours.ts`.
 */

import { alpha, type MantineTheme } from '@mantine/core';

import { mantineCategoricalPalette, resolveCategoricalPalette } from '../../../colors';
import type { RGB } from './residueColours';

export interface PanelColours {
  text: string;
  dimmed: string;
  grid: string;
  /** Selection shading and strokes. */
  accent: string;
  accentFill: string;
  /** Hover crosshair / highlight band from elsewhere. */
  hoverFill: string;
  highlight: string;
  highlightFill: string;
  /** Uncoloured residue blocks (colour scheme off, or below threshold). */
  neutral: RGB;
  /** Categorical palette for category lanes and variant heads. */
  categorical: readonly string[];
  monoFont: string;
  font: string;
}

/** `#rrggbb` / `#rgb` / `rgb(r,g,b)` to an RGB tuple; mid grey otherwise. */
export function cssToRgb(color: string): RGB {
  const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const h = hex[1].length === 3 ? hex[1].replace(/./g, (c) => c + c) : hex[1];
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  const rgb = color.match(/rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i);
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  return [128, 128, 128];
}

export function panelColours(theme: MantineTheme, isDark: boolean): PanelColours {
  const primary = theme.colors[theme.primaryColor] ?? theme.colors.blue;
  const accent = primary[isDark ? 4 : 6];
  const highlight = theme.colors.orange[isDark ? 4 : 6];
  return {
    text: isDark ? theme.colors.gray[2] : theme.colors.gray[8],
    dimmed: isDark ? theme.colors.gray[5] : theme.colors.gray[6],
    grid: isDark ? alpha(theme.colors.gray[5], 0.25) : alpha(theme.colors.gray[6], 0.25),
    accent,
    accentFill: alpha(accent, isDark ? 0.22 : 0.16),
    hoverFill: alpha(isDark ? theme.colors.gray[3] : theme.colors.gray[7], 0.12),
    highlight,
    highlightFill: alpha(highlight, 0.22),
    neutral: cssToRgb(isDark ? theme.colors.gray[6] : theme.colors.gray[4]),
    categorical: resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark)),
    monoFont: theme.fontFamilyMonospace || 'monospace',
    font: theme.fontFamily || 'sans-serif',
  };
}
