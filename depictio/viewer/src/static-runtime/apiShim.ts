/**
 * Offline API shim for the serverless static-bundle runtime.
 *
 * vite.static.config.ts redirects every import of the real
 * `depictio-react-core` api.ts to this module (see vite-plugins/module-shim).
 * It re-exports the real api unchanged, then overrides only the render-path
 * data functions so the real App + ComponentRenderer render from the bundle
 * manifest. Phase 0: every override serves the component's *frozen* payload —
 * later phases route live tiers through depictio-static-core's query kernels.
 *
 * Keying (mirrors catalog-preview's mockApi): figure/table/map/image/multiqc/
 * jbrowse payloads by component index; interactive + advanced_viz requests
 * carry a dc_id, resolved to a component index via the dashboard document.
 * `fetchComponentData` is intentionally NOT shimmed — it has no callers
 * (RFC errata #5).
 */

// Real api (importer === this file, so the shim plugin lets it through).
export * from '../../../../packages/depictio-react-core/src/api';

import type {
  DashboardData,
  DashboardSummary,
  FigureResponse,
  InteractiveFilter,
} from '../../../../packages/depictio-react-core/src/api';

import { bundle, frozenPayload, interactiveIndexFor } from './bundle';
import {
  columnRangeLive,
  computeCardsLive,
  dataRefFor,
  specsLive,
  uniqueValuesLive,
} from './liveData';
import { themedFrozenFigure } from './mantinePlotlyTemplate';

// ---- dashboard shell -------------------------------------------------------

export async function fetchDashboard(_dashboardId: string): Promise<DashboardData> {
  return bundle().dashboard.doc as unknown as DashboardData;
}

export async function fetchAllDashboards(): Promise<DashboardSummary[]> {
  // No sibling tabs in a bundle — the sidebar renders the single dashboard.
  return [];
}

export async function fetchProjectFromDashboard(_dashboardId: string) {
  // App's ingestion-banner effect is best-effort and swallows failures.
  throw new Error('static bundle: no project backend');
}

export async function fetchIngestionHealth(_projectId: string) {
  throw new Error('static bundle: no ingestion backend');
}

export async function saveDashboardNotes(_dashboardId: string, _notes: unknown) {
  throw new Error('static bundle: read-only — notes cannot be saved');
}

// ---- frozen render-path lookups (keyed by component index) -----------------

export async function renderFigure(
  _dashboardId: string,
  componentId: string,
  _filters: InteractiveFilter[] = [],
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  // FigureRenderer re-requests on every color-scheme flip (the live path
  // sends `theme` to the server, which re-templates the figure). Offline
  // equivalent: swap the frozen figure's layout.template with the matching
  // client-side mantine template so frozen figures follow the theme too.
  return themedFrozenFigure(frozenPayload<FigureResponse>(componentId, 'figure'), theme);
}

export async function renderMap(_dashboardId: string, componentId: string) {
  return frozenPayload(componentId, 'map') as never;
}

export async function renderTable(
  _dashboardId: string,
  componentId: string,
  _filters: InteractiveFilter[],
  start = 0,
  limit = 100,
) {
  const t = frozenPayload<{
    columns: { field: string; headerName: string; type: string }[];
    rows: Record<string, unknown>[];
    total: number;
  }>(componentId, 'table');
  return {
    columns: t.columns,
    rows: t.rows.slice(start, start + limit),
    total: t.total,
    sort_by: null,
    sort_dir: 'desc' as const,
  };
}

export async function fetchImagePaths(_dashboardId: string, componentId: string) {
  return frozenPayload(componentId, 'image') as never;
}

export async function fetchJBrowseSession(_dashboardId: string, componentId: string) {
  return frozenPayload(componentId, 'jbrowse') as never;
}

export async function renderMultiQC(_dashboardId: string, componentId: string) {
  return frozenPayload(componentId, 'multiqc') as never;
}

export async function renderMultiQCGeneralStats(_dashboardId: string, componentId: string) {
  return frozenPayload(componentId, 'multiqc-general-stats') as never;
}

// ---- cards (App calls bulkComputeCards once, data flows down as props) -----

export async function bulkComputeCards(
  _dashboardId: string,
  filters: InteractiveFilter[],
  componentIds?: string[],
) {
  // Live-tier cards (phase 1: bundles with data_refs) compute through the
  // query engine with the current filter state; frozen card payloads (phase-0
  // bundles, or frozen-tier cards in mixed bundles) merge in unchanged.
  const live = await computeCardsLive(filters, componentIds).catch((e) => {
    console.error('static bundle: live card computation failed', e);
    return {
      values: {} as Record<string, unknown>,
      secondary_values: {} as Record<string, Record<string, unknown>>,
      aggregations: {} as Record<string, string[]>,
      filter_applied: false,
      filter_count: 0,
    };
  });
  const values: Record<string, unknown> = {};
  const secondary_values: Record<string, Record<string, unknown>> = {};
  const aggregations: Record<string, string[]> = {};
  for (const [, entry] of Object.entries(bundle().frozen)) {
    if (entry.kind !== 'card') continue;
    const p = entry.payload as {
      values?: Record<string, unknown>;
      secondary_values?: Record<string, Record<string, unknown>>;
      aggregations?: Record<string, string[]>;
    };
    Object.assign(values, p.values ?? {});
    Object.assign(secondary_values, p.secondary_values ?? {});
    Object.assign(aggregations, p.aggregations ?? {});
  }
  if (componentIds) {
    for (const key of Object.keys(values)) {
      if (!componentIds.includes(key)) delete values[key];
    }
  }
  // Live results win over any frozen snapshot of the same component.
  Object.assign(values, live.values);
  Object.assign(secondary_values, live.secondary_values);
  Object.assign(aggregations, live.aggregations);
  return {
    values,
    secondary_values,
    aggregations,
    filter_applied: live.filter_applied,
    filter_count: live.filter_count,
  };
}

// ---- interactive (requests carry dc_id + column, not a component id) -------

interface InteractiveFrozen {
  unique?: string[];
  range?: { min: number | null; max: number | null };
  specs?: Record<string, unknown>;
}

function interactiveFrozen(dcId: string, columnName?: string, kind = 'interactive'): InteractiveFrozen {
  const index = interactiveIndexFor(dcId, columnName);
  if (!index) {
    throw new Error(
      `static bundle: no interactive component for dc "${dcId}"${columnName ? ` column "${columnName}"` : ''}`,
    );
  }
  return frozenPayload<InteractiveFrozen>(index, kind);
}

export async function fetchUniqueValues(dcId: string, columnName: string): Promise<string[]> {
  if (dataRefFor(dcId)) return uniqueValuesLive(dcId, columnName);
  return interactiveFrozen(dcId, columnName, 'unique-values').unique ?? [];
}

export async function fetchColumnRange(dcId: string, columnName: string) {
  if (dataRefFor(dcId)) return columnRangeLive(dcId, columnName);
  return interactiveFrozen(dcId, columnName, 'column-range').range ?? { min: null, max: null };
}

export async function fetchSpecs(dcId: string): Promise<Record<string, unknown>> {
  if (dataRefFor(dcId)) return specsLive(dcId);
  return interactiveFrozen(dcId, undefined, 'specs').specs ?? {};
}

// ---- advanced viz (requests carry dc_id) -----------------------------------

function advancedVizIndexFor(dcId: string): string {
  const doc = bundle().dashboard.doc as {
    stored_metadata?: { index?: string; component_type?: string; dc_id?: string | null }[];
  };
  const meta = (doc.stored_metadata ?? []).find(
    (c) => c.component_type === 'advanced_viz' && String(c.dc_id ?? '') === dcId,
  );
  if (!meta?.index) {
    throw new Error(`static bundle: no advanced_viz component for dc "${dcId}"`);
  }
  return meta.index;
}

export async function fetchAdvancedVizData(req: { dcId: string }) {
  return frozenPayload(advancedVizIndexFor(req.dcId), 'advanced-viz-data') as never;
}

export async function fetchPhylogenyNewick(dcId: string): Promise<string> {
  const p = frozenPayload<{ newick?: string }>(advancedVizIndexFor(dcId), 'newick');
  return p.newick ?? '';
}

// Celery dispatch/poll kinds: results are frozen, so dispatch returns a
// finished job immediately and poll echoes it (catalog-preview precedent).
function finishedJob(dcId: string) {
  const p = frozenPayload<{ result?: unknown }>(advancedVizIndexFor(dcId), 'compute');
  return { job_id: dcId, status: 'done' as const, result: p.result, from_cache: true };
}
export async function dispatchComputeEmbedding(p: { dc_id: string }) {
  return finishedJob(p.dc_id) as never;
}
export async function pollComputeEmbedding(jobId: string) {
  return finishedJob(jobId) as never;
}
export async function dispatchComplexHeatmap(p: { dc_id: string }) {
  return finishedJob(p.dc_id) as never;
}
export async function pollComplexHeatmap(jobId: string) {
  return finishedJob(jobId) as never;
}
export async function dispatchUpset(p: { dc_id: string }) {
  return finishedJob(p.dc_id) as never;
}
export async function pollUpset(jobId: string) {
  return finishedJob(jobId) as never;
}
export async function dispatchCoverageTrack(p: { dc_id: string }) {
  return finishedJob(p.dc_id) as never;
}
export async function pollCoverageTrack(jobId: string) {
  return finishedJob(jobId) as never;
}
export async function dispatchSankey(p: { dc_id: string }) {
  return finishedJob(p.dc_id) as never;
}
export async function pollSankey(jobId: string) {
  return finishedJob(jobId) as never;
}
