import { createTheme, MantineColorsTuple } from '@mantine/core';

/**
 * Depictio Mantine theme. Mirrors the Dash `MantineProvider` config in
 * depictio/dash/layouts/shared_app_shell.py:create_app_shell so the viewer
 * renders with identical tokens to the Dash app.
 *
 * TODO: if Depictio's Dash app customizes colors via an env-driven config,
 * read the same source here.
 */
export const depictioTheme = createTheme({
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif',
  fontFamilyMonospace: 'Menlo, Monaco, Consolas, "Courier New", monospace',
  defaultRadius: 'md',
  primaryColor: 'blue',
  // Headings use the normal sans stack — the Virgil hand-drawn font is opt-in
  // per-place (e.g. AuthCard's "Welcome to Depictio") via inline style, not the
  // global default.
});
