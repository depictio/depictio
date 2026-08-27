import { createTheme, type MantineColorsTuple } from '@mantine/core';

/**
 * Depictio Mantine theme for Tool Studio.
 *
 * Two brand colours:
 *
 *   brand  = #7651e7, the purple of the hammer in the Catalog mark
 *            (public/logos/tools_catalog_logo.png). The primary: buttons, the
 *            active step, selected cards, focus rings. Sampled from the logo
 *            itself so the chrome and the mark are literally the same purple.
 *   accent = #45b8ac, depictio's teal from the shared palette
 *            (`depictio/viewer/src/profile/colors.ts`). The secondary, for
 *            surfaces that must read as "a different thing" beside a primary
 *            action (success, the append-mode banners). Use `color="accent"`.
 *
 * Each ramp keeps the source hex at shade 6, which is what Mantine fills with
 * and what borders, `variant="light"` text and outline variants resolve to, so
 * the exact colour is what shows up everywhere.
 *
 * White on brand shade 6 is 5.1:1, past the 4.5:1 AA floor, so the default
 * `primaryShade` needs no override. Filled `accent` is only 2.4:1, so prefer
 * `variant="light"` for it (dark text on a tint) and shade 8 if a filled teal
 * is ever really wanted.
 *
 * The viewer's theme (depictio/viewer/src/theme.ts) is still on Mantine's stock
 * blue; if it ever adopts these tokens, export them from a shared package and
 * import here instead of duplicating.
 */
const brand: MantineColorsTuple = [
  '#f5f3fd',
  '#e8e1fb',
  '#d3c7f7',
  '#bcaaf3',
  '#a38aef',
  '#8c6deb',
  '#7651e7',
  '#6546c7',
  '#543aa4',
  '#432e84',
];

const accent: MantineColorsTuple = [
  '#f0f9f8',
  '#daf1ee',
  '#bee6e2',
  '#9edad4',
  '#7fcec6',
  '#61c3b8',
  '#45b8ac',
  '#3b9e94',
  '#308178',
  '#276760',
];

/** Display face for the wordmark and page headings: Outfit, the open geometric
 *  sans closest to Product Sans (which is proprietary and cannot be shipped).
 *  Bundled in `styles/app.css`; falls back to the theme's own stack. Virgil is
 *  still loaded for anything that wants the hand-drawn brand signature. */
export const HEADING_FONT = '"Outfit", var(--mantine-font-family)';

export const depictioTheme = createTheme({
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif',
  fontFamilyMonospace: 'Menlo, Monaco, Consolas, "Courier New", monospace',
  defaultRadius: 'md',
  colors: { brand, accent },
  primaryColor: 'brand',
});
