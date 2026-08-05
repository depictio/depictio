/**
 * The icons and colours a section can be given.
 *
 * The icon list is a curated array of string literals rather than a free-text
 * field, and that is a hard requirement rather than a UX preference:
 * `scripts/generate-icon-subset.mjs` bundles only the Iconify ids it finds
 * written as literals in scanned source, and the app's CSP blocks Iconify's
 * network fallback. An id typed by hand into a text box therefore renders as an
 * empty box everywhere except `vite dev`.
 *
 * Every id used by a section in the reference dashboards is listed here, which
 * is what makes those icons resolve in a built bundle.
 */
export interface IconOption {
  value: string;
  label: string;
}

export const SECTION_ICON_OPTIONS: IconOption[] = [
  // Overview / summary
  { value: 'mdi:counter', label: 'Counter' },
  { value: 'mdi:view-dashboard-outline', label: 'Overview' },
  { value: 'mdi:information-outline', label: 'Info' },
  { value: 'mdi:star-outline', label: 'Highlights' },
  // Charts
  { value: 'mdi:chart-bell-curve', label: 'Distribution' },
  { value: 'mdi:chart-bar', label: 'Bar chart' },
  { value: 'mdi:chart-line', label: 'Trend' },
  { value: 'mdi:chart-scatter-plot', label: 'Scatter' },
  { value: 'mdi:chart-donut', label: 'Composition' },
  { value: 'mdi:chart-box-outline', label: 'Charts' },
  { value: 'mdi:chart-timeline-variant', label: 'Timeline' },
  // Data
  { value: 'mdi:table', label: 'Table' },
  { value: 'mdi:database-outline', label: 'Data' },
  { value: 'mdi:file-document-outline', label: 'Reports' },
  { value: 'mdi:folder-outline', label: 'Files' },
  // Quality / status
  { value: 'mdi:check-decagram', label: 'Quality' },
  { value: 'mdi:shield-check-outline', label: 'Validation' },
  { value: 'mdi:alert-outline', label: 'Warnings' },
  { value: 'mdi:filter-variant', label: 'Filters' },
  { value: 'mdi:tune', label: 'Settings' },
  // Science / domain
  { value: 'mdi:test-tube', label: 'Sample' },
  { value: 'mdi:dna', label: 'Genomics' },
  { value: 'mdi:bacteria-outline', label: 'Microbiology' },
  { value: 'mdi:microscope', label: 'Imaging' },
  { value: 'mdi:ruler', label: 'Measurements' },
  { value: 'mdi:shape-outline', label: 'Categories' },
  { value: 'mdi:map-marker-outline', label: 'Location' },
  { value: 'mdi:calendar-outline', label: 'Time' },
  { value: 'mdi:account-group-outline', label: 'Cohort' },
];

/**
 * Mantine palette names. Same list the dashboard-icon picker offers, because a
 * section's colour and a dashboard's colour are drawn from the same theme.
 * `''` means "no override" — the header renders neutral.
 */
export const SECTION_COLOR_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'None' },
  { value: 'gray', label: 'Gray' },
  { value: 'red', label: 'Red' },
  { value: 'pink', label: 'Pink' },
  { value: 'grape', label: 'Grape' },
  { value: 'violet', label: 'Violet' },
  { value: 'indigo', label: 'Indigo' },
  { value: 'blue', label: 'Blue' },
  { value: 'cyan', label: 'Cyan' },
  { value: 'teal', label: 'Teal' },
  { value: 'green', label: 'Green' },
  { value: 'lime', label: 'Lime' },
  { value: 'yellow', label: 'Yellow' },
  { value: 'orange', label: 'Orange' },
];

/**
 * Icon options with `current` guaranteed present.
 *
 * A dashboard authored in YAML may name an icon outside the curated list. The
 * Select must still show it, or opening the form and saving an unrelated field
 * would silently blank it.
 */
export function iconOptionsWith(current?: string | null): IconOption[] {
  const id = (current ?? '').trim();
  if (!id || SECTION_ICON_OPTIONS.some((o) => o.value === id)) {
    return SECTION_ICON_OPTIONS;
  }
  return [{ value: id, label: `${id} (custom)` }, ...SECTION_ICON_OPTIONS];
}
