import { DEFAULT_THEME } from '@mantine/core';

import { annotationInk } from '../palettes';
import { withAlpha } from './toPlotly';
import { ANNOTATION_COLORS, ANNOTATION_INK } from './types';
import type { AnnotationColorName } from './types';

export type ColorResolver = (name: AnnotationColorName, shade?: number) => string;

export type AnnotationColorScheme = 'light' | 'dark';

/**
 * Concrete colour of an annotation palette name. Always taken from Mantine's
 * default palette, never from the active theme: a dashboard brand theme can
 * remap palettes (e.g. teal to a data series colour), and annotations must
 * stay distinguishable from the data they mark.
 * Default shade: 6 in light mode, 4 in dark mode.
 *
 * The neutral `ink` (what an annotation with no chosen colour wears) is the
 * shared palette's annotation ink for the scheme, whatever the shade.
 */
export function annotationColorValue(
  name: AnnotationColorName,
  colorScheme: AnnotationColorScheme,
  shade?: number,
): string {
  if (name === ANNOTATION_INK) return annotationInk(colorScheme);
  const tuple = DEFAULT_THEME.colors[name] ?? DEFAULT_THEME.colors.gray;
  const fallbackShade = colorScheme === 'dark' ? 4 : 6;
  const idx = Math.min(9, Math.max(0, Math.round(shade ?? fallbackShade)));
  return tuple[idx];
}

/**
 * Translucent tint of an annotation colour, for backgrounds (table rows).
 * Alpha mirrors Mantine's `light` variant: 0.1 in light mode, 0.15 in dark;
 * `strong` mirrors its hover tone (0.12 / 0.2).
 */
export function annotationColorTint(
  name: AnnotationColorName,
  colorScheme: AnnotationColorScheme,
  strong = false,
): string {
  const dark = colorScheme === 'dark';
  const a = strong ? (dark ? 0.2 : 0.12) : dark ? 0.15 : 0.1;
  return withAlpha(annotationColorValue(name, colorScheme), a);
}

/**
 * CSS custom properties for every annotation colour
 * (`--depictio-annot-<name>-bg|-bg-strong|-stripe`), set inline on a container
 * so the per-colour classes of styles/table-annotations.css read the default
 * palette instead of the (possibly brand-remapped) Mantine CSS variables.
 */
export function annotationPaletteVars(colorScheme: AnnotationColorScheme): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const c of [...ANNOTATION_COLORS, ANNOTATION_INK] as const) {
    vars[`--depictio-annot-${c}-bg`] = annotationColorTint(c, colorScheme);
    vars[`--depictio-annot-${c}-bg-strong`] = annotationColorTint(c, colorScheme, true);
    vars[`--depictio-annot-${c}-stripe`] = annotationColorValue(c, colorScheme);
  }
  return vars;
}

/** Resolver bound to a colour scheme (see `annotationColorValue`). */
export function makeColorResolver(colorScheme: AnnotationColorScheme): ColorResolver {
  return (name, shade) => annotationColorValue(name, colorScheme, shade);
}
