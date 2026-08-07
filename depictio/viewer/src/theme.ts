import { createTheme, MantineColorsTuple } from '@mantine/core';

/**
 * Depictio Mantine theme. Mirrors the Dash `MantineProvider` config in
 * depictio/dash/layouts/shared_app_shell.py:create_app_shell so the viewer
 * renders with identical tokens to the Dash app.
 */

export interface DepictioThemeOptions {
  /** Global size multiplier (`theme.scale` → `--mantine-scale`). */
  scale?: number;
  /** Mantine palette name to use as the primary color. */
  primaryColor?: string;
  /** Extra palettes to register (e.g. a generated brand palette). */
  colors?: Record<string, MantineColorsTuple>;
}

export function buildDepictioTheme(options: DepictioThemeOptions = {}) {
  return createTheme({
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif',
    fontFamilyMonospace: 'Menlo, Monaco, Consolas, "Courier New", monospace',
    defaultRadius: 'md',
    primaryColor: options.primaryColor ?? 'blue',
    ...(options.colors ? { colors: options.colors } : {}),
    ...(options.scale && options.scale !== 1 ? { scale: options.scale } : {}),
    // Headings use the normal sans stack — the Virgil hand-drawn font is opt-in
    // per-place (e.g. AuthCard's "Welcome to Depictio") via inline style, not the
    // global default.
  });
}

export const depictioTheme = buildDepictioTheme();
