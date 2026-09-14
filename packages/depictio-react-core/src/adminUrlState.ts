/**
 * The address-bar half of the admin page: which tab is open, which Log & Task
 * pane, and the Ingestion pane's filters, so a refresh, Back/Forward or a
 * pasted link lands on the same view. Only the codec lives here, like
 * `listingUrlState.ts`; the viewer's `AdminApp` reads and writes
 * `window.location`.
 *
 * Paths are flat: `/admin/<tab>` for the plain tabs and `/admin/<pane>` for the
 * monitoring panes, so `/admin/ingestion` opens Log & Task on Ingestion. The
 * two name sets are disjoint, which is what lets one segment say both.
 */

import { asEnum, asScalar, decodeListingParams, encodeListingParams } from './listingUrlState';

export const ADMIN_TABS = [
  'users',
  'projects',
  'dashboards',
  'branding',
  'monitoring',
  'backups',
  'maintenance',
] as const;
export type AdminTab = (typeof ADMIN_TABS)[number];

export const MONITORING_PANES = ['tasks', 'ingestion', 'logs', 'health'] as const;
export type MonitoringPane = (typeof MONITORING_PANES)[number];

/** Mirrors `IngestionStatus` in depictio/models/models/monitoring.py. */
export const INGESTION_STATUSES = [
  'running',
  'success',
  'partial',
  'failed',
  'interrupted',
  'abandoned',
] as const;
export type IngestionStatusFilter = (typeof INGESTION_STATUSES)[number];

export interface IngestionFilters {
  status: IngestionStatusFilter | null;
  instance: string | null;
  /** Filters on the project id; the select shows the project name. */
  projectId: string | null;
  /** Free-text search, applied client-side to the fetched runs. */
  q: string;
}

export const EMPTY_INGESTION_FILTERS: Readonly<IngestionFilters> = Object.freeze({
  status: null,
  instance: null,
  projectId: null,
  q: '',
});

export interface AdminRoute {
  tab: AdminTab;
  /** Log & Task pane. Kept while another tab is open, so coming back restores it. */
  pane: MonitoringPane;
  ingestion: IngestionFilters;
}

/** An `AdminRoute` read from a URL. `tab` is null when the path names none. */
export type ParsedAdminUrl = Omit<AdminRoute, 'tab'> & { tab: AdminTab | null };

const ADMIN_PATH_RE = /^\/admin(?:\/([^/]+))?/;

function decodeIngestionFilters(search: string): IngestionFilters {
  const params = decodeListingParams(search);
  return {
    status: asEnum(params.status, INGESTION_STATUSES) ?? null,
    instance: asScalar(params.instance) ?? null,
    projectId: asScalar(params.project) ?? null,
    q: asScalar(params.q) ?? '',
  };
}

/** What a URL describes. `tab` is null for a bare `/admin` or a segment this
 *  build doesn't know, so the caller can fall back to the remembered tab.
 *  Filters are read only on the Ingestion pane's path. */
export function parseAdminUrl(pathname: string, search: string): ParsedAdminUrl {
  const segment = ADMIN_PATH_RE.exec(pathname)?.[1];
  const values = segment ? [segment] : undefined;
  const pane = asEnum(values, MONITORING_PANES);
  if (pane) {
    return {
      tab: 'monitoring',
      pane,
      ingestion:
        pane === 'ingestion' ? decodeIngestionFilters(search) : { ...EMPTY_INGESTION_FILTERS },
    };
  }
  return {
    tab: asEnum(values, ADMIN_TABS) ?? null,
    pane: 'tasks',
    ingestion: { ...EMPTY_INGESTION_FILTERS },
  };
}

/** The canonical URL for `route`. Filters are written only for the Ingestion
 *  pane, and empty ones are left out. */
export function adminUrl(route: AdminRoute): string {
  if (route.tab !== 'monitoring') return `/admin/${route.tab}`;
  const path = `/admin/${route.pane}`;
  if (route.pane !== 'ingestion') return path;
  const { status, instance, projectId, q } = route.ingestion;
  const query = encodeListingParams({ status, instance, project: projectId, q: q.trim() });
  return query ? `${path}?${query}` : path;
}
