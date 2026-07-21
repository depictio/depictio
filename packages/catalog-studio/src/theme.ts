import { createTheme } from '@mantine/core';

/**
 * Depictio Mantine theme — copied verbatim from depictio/viewer/src/theme.ts
 * so Catalog Studio renders with identical tokens to the viewer / Dash app.
 * The viewer's theme is not exported from a shared package; if it ever is,
 * import it here instead of duplicating these five lines.
 */
export const depictioTheme = createTheme({
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif',
  fontFamilyMonospace: 'Menlo, Monaco, Consolas, "Courier New", monospace',
  defaultRadius: 'md',
  primaryColor: 'blue',
});
