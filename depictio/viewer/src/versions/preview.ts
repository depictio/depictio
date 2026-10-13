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
 *   `asOfVersionId`        the version whose data stamps the server expands
 *                          into per-collection Delta pins (`as_of_version`);
 *   `definitionVersionId`  the version the server reads each component's
 *                          definition from (`definition_version`).
 *
 * Both are the previewed version's id. The client sends no definitions of its
 * own: the server reads them out of the stored version, so nothing in a
 * request body can point a read at another collection.
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
 * The version whose component definitions a preview renders, or null when the
 * dashboard is the live one.
 *
 * On this repo's own demo, a preview without it showed a card headed "Mean
 * Petal Length (Average)" holding 1.9, which is the *max*: the aggregation the
 * same component id was later changed to. A wrong number under a confident
 * label is worse than a blank, because nothing on screen contradicts it.
 *
 * Keyed off the server's `preview` block rather than the URL: the block is
 * only present when the overlay was actually applied, so a definition
 * version is never sent against content that is not the version's.
 */
export function definitionVersionFromPreview(
  dashboard: Pick<DashboardData, 'preview'> | null | undefined,
): string | null {
  return dashboard?.preview?.version_id || null;
}

/**
 * What a previewed dashboard adds to every render request, or null when the
 * dashboard is the live one.
 */
export function previewDataRequest(
  dashboard: Pick<DashboardData, 'preview'> | null | undefined,
): DataVersionState | null {
  const versionId = definitionVersionFromPreview(dashboard);
  if (!versionId) return null;
  return { asOfVersionId: versionId, definitionVersionId: versionId };
}
