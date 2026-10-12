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
