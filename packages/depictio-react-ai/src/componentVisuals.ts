/**
 * Icons and colours for the surfaces that name components and sections.
 *
 * A component type looks the same wherever it appears: the plan, the progress
 * list and the draft review all read `componentTypeVisual` from
 * depictio-react-core, the palette the builder's type grid and the catalog
 * picker already use. This module adds only what that palette does not cover,
 * the section icon, and it is deliberately thin: a copy of a colour is a copy
 * that drifts.
 *
 * Section icons arrive as data (the planner picks one, an author can change
 * it), and only Iconify ids written as literals in a scanned source are
 * bundled: `scripts/generate-icon-subset.mjs` scans package sources and the
 * app's CSP blocks Iconify's network fallback. An id outside the allowlist
 * below therefore falls back to a generic one rather than rendering as a
 * blank box.
 *
 * The list mirrors SECTION_ICONS in
 * depictio/api/v1/endpoints/ai_endpoints/dashboard_plan.py, itself a copy of
 * the viewer's sectionIcons.ts.
 */

export const PLAN_SECTION_ICONS = new Set<string>([
  'mdi:counter',
  'mdi:view-dashboard-outline',
  'mdi:information-outline',
  'mdi:star-outline',
  'mdi:chart-bell-curve',
  'mdi:chart-bar',
  'mdi:chart-line',
  'mdi:chart-scatter-plot',
  'mdi:chart-donut',
  'mdi:chart-box-outline',
  'mdi:chart-timeline-variant',
  'mdi:table',
  'mdi:table-account',
  'mdi:database-outline',
  'mdi:set-merge',
  'mdi:relation-many-to-many',
  'mdi:file-document-outline',
  'mdi:folder-outline',
  'mdi:check-decagram',
  'mdi:shield-check-outline',
  'mdi:alert-outline',
  'mdi:filter-variant',
  'mdi:tune',
  'mdi:test-tube',
  'mdi:dna',
  'mdi:bacteria-outline',
  'mdi:virus',
  'mdi:family-tree',
  'mdi:stethoscope',
  'mdi:scale-balance',
  'mdi:waves',
  'mdi:microscope',
  'mdi:ruler',
  'mdi:shape-outline',
  'mdi:map-marker-outline',
  'mdi:calendar-outline',
  'mdi:account-group-outline',
]);

/** What a section falls back to per kind: the filter panel is a panel of
 *  filters whatever it holds, a grid section is a piece of the dashboard. */
const FALLBACK_FILTER_ICON = 'mdi:filter-variant';
const FALLBACK_GRID_ICON = 'mdi:view-dashboard-outline';

/** The icon to draw for a section: its own when it has one that is bundled,
 *  otherwise the generic one for its kind. */
export function sectionIconId(
  icon: string | null | undefined,
  kind?: 'filter' | 'grid' | string | null,
): string {
  if (icon && PLAN_SECTION_ICONS.has(icon)) return icon;
  return kind === 'filter' ? FALLBACK_FILTER_ICON : FALLBACK_GRID_ICON;
}
