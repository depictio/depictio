/**
 * Rendering a stored version through the live viewer.
 *
 * A `DashboardVersion` holds the whole tab family; the viewer renders one tab
 * at a time. This module is the seam between the two: it picks the addressed
 * tab out of a snapshot and projects it onto the `DashboardData` shape every
 * component path already consumes, so preview reuses the real renderer rather
 * than a second, drifting one.
 *
 * Deliberately *not* a full `DashboardData`. `permissions`, `is_public` and
 * `project_id` are structurally absent from a `TabSnapshot` — a snapshot must
 * never be able to re-grant access that was since revoked — so they are taken
 * from nowhere and the preview is read-only regardless of who opens it.
 */

import type { DashboardData, DashboardVersionDetail } from 'depictio-react-core';

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
 * Project a version's snapshot of one tab onto the viewer's dashboard shape.
 *
 * Falls back to the main tab when the addressed tab is not in the snapshot,
 * which is the normal case for a version taken before that tab existed —
 * showing the family's main tab is more useful than an empty screen, and the
 * banner already states that a past version is on screen.
 */
export function dashboardFromVersion(
  version: DashboardVersionDetail,
  dashboardId: string,
): DashboardData {
  const tabs = version.tabs || [];
  const tab =
    tabs.find((t) => String(t.dashboard_id) === String(dashboardId)) ??
    tabs.find((t) => t.is_main_tab) ??
    tabs[0];

  if (!tab) {
    throw new Error('This version holds no snapshot for that dashboard.');
  }

  return {
    ...tab,
    dashboard_id: dashboardId,
    stored_metadata: tab.stored_metadata || [],
    left_panel_layout_data: tab.left_panel_layout_data || [],
    right_panel_layout_data: tab.right_panel_layout_data || [],
  } as unknown as DashboardData;
}
