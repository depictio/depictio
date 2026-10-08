/**
 * Rendering a stored version through the live viewer.
 *
 * The *content* half of a preview is the server's job:
 * `fetchDashboard(id, versionId)` returns the version's snapshot of that tab
 * overlaid onto the live document, plus a `preview` block for the banner.
 * Identity and access (`project_id`, `permissions`, `is_public`) always come
 * from the live document, so a snapshot can never re-grant revoked access and
 * the viewer still has a project to resolve data collections against.
 *
 * What the overlay cannot fix is the *render* half. Every value and every
 * trace comes from a render endpoint, and those read the component from the
 * live document and the collection at its current commit. Without more, a
 * preview draws a past layout through today's chart definitions over today's
 * data, and labels the result as the past. `previewDataRequest` supplies the
 * two fields that close that gap, for `DataVersionProvider`:
 *
 *   `asOfVersionId`      the version whose data stamps the server expands into
 *                        per-collection Delta pins (`as_of_version`);
 *   `componentOverrides` the overlaid component definitions, keyed by index
 *                        (`component_overrides`).
 */

import type { DashboardData, DataVersionState } from 'depictio-react-core';

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

/** Back to the live dashboard: drop the `version` param, keeping everything
 *  else about the URL intact. A full navigation, as entering the preview was. */
export function exitPreview(): void {
  const url = new URL(window.location.href);
  url.searchParams.delete('version');
  window.location.assign(url.toString());
}

/**
 * The snapshot's component definitions, keyed by component index, in the shape
 * the render endpoints accept as `component_overrides`.
 *
 * On this repo's own demo, a preview without them showed a card headed "Mean
 * Petal Length (Average)" holding 1.9, which is the *max*: the aggregation the
 * same component id was later changed to. A wrong number under a confident
 * label is worse than a blank, because nothing on screen contradicts it.
 *
 * Sends the whole stored component rather than a hand-picked subset: the server
 * narrows it to a per-type allow-list of presentation fields (`_DEFINITION_FIELDS`
 * in `routes.py`), and duplicating that list here would be a second copy to
 * keep in sync. `wf_id` / `dc_id` / `dc_config` are rejected there, so this
 * cannot redirect a read at another collection.
 */
export function overridesFromVersion(
  // Deliberately a looser shape than `StoredMetadata`. A snapshot stores
  // components as plain records, and an older version can hold a component
  // whose fields no longer satisfy today's stricter type; refusing to read it
  // would break history for exactly the versions history exists to reach.
  metadata: ReadonlyArray<Record<string, unknown>> | undefined,
): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const meta of metadata || []) {
    const index = String(meta.index ?? '');
    if (!index) continue;
    out[index] = meta;
  }
  return out;
}

/**
 * What a previewed dashboard adds to every render request, or null when the
 * dashboard is the live one.
 *
 * Keyed off the server's `preview` block rather than the URL: the block is
 * only present when the overlay was actually applied, so the data pins can
 * never be sent against content that is not the version's.
 */
export function previewDataRequest(
  dashboard: Pick<DashboardData, 'preview' | 'stored_metadata'> | null | undefined,
): DataVersionState | null {
  const versionId = dashboard?.preview?.version_id;
  if (!dashboard || !versionId) return null;
  const overrides = overridesFromVersion(
    dashboard.stored_metadata as unknown as ReadonlyArray<Record<string, unknown>> | undefined,
  );
  return {
    asOfVersionId: versionId,
    componentOverrides: Object.keys(overrides).length ? overrides : undefined,
  };
}
