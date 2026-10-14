/**
 * Single source of truth for the AI affordance icon.
 *
 * Every AI entry point (menu items, panel headers, modal titles, fill/
 * generate buttons, section-summary sparkles) renders this one star so
 * users learn a single visual cue for "this is AI". Keep it a string
 * literal here: the viewer's generate-icon-subset.mjs scans package
 * sources for `prefix:name` literals to build the CSP-safe icon bundle.
 */
export const AI_ICON = 'material-symbols:auto-awesome-outline';

/**
 * The assistant's colour, a Mantine palette name, paired with AI_ICON on
 * every AI affordance. Cyan because the other accents are spoken for: blue
 * is the manual builder, violet the catalog, teal the success states, green
 * the save actions, orange and yellow the warnings and project types.
 * Hosts that cannot import this package (depictio-react-core) repeat the
 * literal and say so.
 */
export const AI_COLOR = 'cyan';

/** CSS variable for one shade of AI_COLOR, for inline styles. */
export const aiColorVar = (shade: number): string => `var(--mantine-color-${AI_COLOR}-${shade})`;
