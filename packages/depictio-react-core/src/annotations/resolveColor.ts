import type { MantineTheme } from '@mantine/core';

import type { AnnotationColor } from './types';

export type ColorResolver = (name: AnnotationColor, shade?: number) => string;

/**
 * Resolve an annotation's palette name to a concrete colour from the Mantine
 * theme, so annotations follow light/dark mode like the rest of the viewer.
 * Default shade: 6 in light mode, 4 in dark mode.
 */
export function makeColorResolver(
  theme: MantineTheme,
  colorScheme: 'light' | 'dark',
): ColorResolver {
  const fallbackShade = colorScheme === 'dark' ? 4 : 6;
  return (name, shade) => {
    const tuple = theme.colors[name] ?? theme.colors.gray;
    const idx = Math.min(9, Math.max(0, Math.round(shade ?? fallbackShade)));
    return tuple[idx];
  };
}
