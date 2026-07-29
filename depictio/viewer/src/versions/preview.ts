/**
 * Rendering a stored version through the live viewer.
 *
 * A `DashboardVersion` holds the whole tab family; the viewer renders one tab
 * at a time. This module is the seam between the two.
 *
 * The snapshot is **merged onto the live dashboard document**, not used in its
 * place. That is not a convenience — a `TabSnapshot` structurally omits
 * `project_id`, `permissions` and `is_public` so a snapshot can never re-grant
 * revoked access, which means rendering one directly leaves the viewer with no
 * project to resolve data collections against and no permissions to gate the
 * notes footer. The result looks like the right dashboard with the wrong (or
 * missing) contents. Identity and access always come from the live document;
 * only layout and components come from the version. Same split as the restore
 * endpoint, for the same reason.
 */

import type { DashboardData, DashboardVersionDetail } from 'depictio-react-core';

/** Content fields a version owns. Everything else stays as the live document
 *  has it: mirrors `_RESTORABLE_FIELDS` in `versions_routes.py`, so preview
 *  shows exactly what restoring would produce. */
const SNAPSHOT_CONTENT_FIELDS = [
  'title',
  'subtitle',
  'main_tab_name',
  'tab_icon',
  'tab_icon_color',
  'icon',
  'icon_color',
  'icon_variant',
  'workflow_system',
  'notes_content',
  'stored_metadata',
  'left_panel_layout_data',
  'right_panel_layout_data',
  'tab_order',
  'is_main_tab',
] as const;

/** The version id in `?version=`, or null. Read once per load; the viewer has
 *  no router, so this mirrors how `extractDashboardId` reads the path. */
export function extractPreviewVersionId(): string | null {
  try {
    const raw = new URLSearchParams(window.location.search).get('version');
    return raw && raw.trim() ? raw.trim() : null;
  } catch {
    return null;
  }
}

/**
 * Overlay a version's snapshot of one tab onto the live dashboard document.
 *
 * Falls back to the family's main tab when the addressed tab is absent from
 * the snapshot — the normal case for a version taken before that tab existed.
 * Showing the main tab beats an empty screen, and the banner already says a
 * past version is on display.
 */
export function dashboardFromVersion(
  version: DashboardVersionDetail,
  dashboardId: string,
  live: DashboardData,
): DashboardData {
  const tabs = version.tabs || [];
  const tab =
    tabs.find((t) => String(t.dashboard_id) === String(dashboardId)) ??
    tabs.find((t) => t.is_main_tab) ??
    tabs[0];

  if (!tab) {
    throw new Error('This version holds no snapshot for this dashboard.');
  }

  const content: Record<string, unknown> = {};
  for (const field of SNAPSHOT_CONTENT_FIELDS) {
    if (field in tab) content[field] = (tab as Record<string, unknown>)[field];
  }

  return {
    ...live,
    ...content,
    // Keep the live identity: the snapshot's `dashboard_id` may be the main
    // tab's when we fell back above, and the viewer keys fetches off this.
    dashboard_id: live.dashboard_id ?? dashboardId,
    stored_metadata: tab.stored_metadata || [],
    left_panel_layout_data: tab.left_panel_layout_data || [],
    right_panel_layout_data: tab.right_panel_layout_data || [],
  } as DashboardData;
}

/**
 * The snapshot's component definitions, keyed by component index, in the shape
 * the render endpoints accept as `component_overrides`.
 *
 * Needed because overlaying the snapshot is only half the job. The overlay is
 * client-side: it decides what the viewer *labels* each component and where it
 * sits. Every value and every trace comes from a render endpoint, and those
 * read the component from the **live** dashboard document — so without this a
 * preview drew a past version's data through today's definition and presented
 * the result under the past version's title.
 *
 * On this repo's own demo that produced a card headed "Mean Petal Length
 * (Average)" showing 1.9, which is the *max* — the aggregation the same
 * component id was later changed to. A wrong number under a confident label is
 * worse than a blank, because nothing on screen contradicts it.
 *
 * Sends the whole stored component rather than a hand-picked subset: the server
 * narrows it to a per-type allow-list of presentation fields (`_DEFINITION_FIELDS`
 * in `routes.py`), and duplicating that list here would be a second copy to
 * keep in sync. `wf_id` / `dc_id` / `dc_config` are rejected there, so this
 * cannot redirect a read at another collection.
 */
export function overridesFromVersion(
  // Deliberately the snapshot's own looser shape rather than `StoredMetadata`.
  // A `TabSnapshot` stores components as plain records — an older version can
  // hold a component whose fields no longer satisfy today's stricter type, and
  // refusing to read it would break history for exactly the versions history
  // exists to reach.
  metadata: Record<string, unknown>[] | undefined,
): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const meta of metadata || []) {
    const index = String(meta.index ?? '');
    if (!index) continue;
    out[index] = meta;
  }
  return out;
}
