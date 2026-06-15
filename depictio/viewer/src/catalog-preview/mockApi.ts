/**
 * Offline API shim for the standalone catalog-preview bundle.
 *
 * The catalog-preview Vite build aliases every `depictio-react-core` import of
 * `./api` to this module (see vite.catalog-preview.config.ts). It re-exports the
 * real api unchanged, then overrides ONLY the data-fetching functions so the
 * viewer's real `ComponentRenderer` (and every per-type renderer) renders from
 * the payloads embedded in `window.__CATALOG_PREVIEW__` — no network, fully
 * offline. Everything else (types, auth helpers, formatting) comes from the real
 * api via `export *`.
 *
 * Keying: figure/table/map/image/multiqc requests carry a component id, so those
 * payloads are keyed by component index. interactive/advanced_viz requests carry
 * a `dc_id` instead, so the Python side gives every render a UNIQUE synthetic
 * `dc_id` ("catalog::<index>") and those payloads are keyed by dc_id.
 */

// Real api (importer === this file, so the shim plugin lets it through).
export * from '../../../../packages/depictio-react-core/src/api';

import type {
  InteractiveFilter,
} from '../../../../packages/depictio-react-core/src/api';

export interface CatalogPreviewData {
  figures: Record<string, { figure: unknown; metadata?: unknown }>;
  tables: Record<string, { columns: unknown[]; rows: Record<string, unknown>[]; total: number }>;
  maps: Record<string, { figure: unknown; metadata?: unknown }>;
  images: Record<string, unknown>;
  multiqc: Record<string, unknown>;
  multiqcGeneralStats: Record<string, unknown>;
  cards: {
    values: Record<string, unknown>;
    secondary: Record<string, Record<string, unknown>>;
    aggregations: Record<string, string[]>;
  };
  unique: Record<string, string[]>;
  ranges: Record<string, { min: number | null; max: number | null }>;
  specs: Record<string, Record<string, unknown>>;
  advancedVizData: Record<string, unknown>;
  compute: Record<string, unknown>;
}

interface CatalogPreviewGlobal {
  theme: 'light' | 'dark';
  initialOutputId: string | null;
  // tools[].outputs[] carry per-output metadata (output/renders/fixturePreview);
  // all outputs' component data is merged into the single top-level `data` map
  // (keys are globally unique), which is the only field this offline shim reads.
  tools: unknown[];
  data: CatalogPreviewData;
  // Single-output preview mode (built by `catalog preview`): these live at the
  // top level alongside `data`. Gallery mode omits them (they're nested inside
  // tools[].outputs[] instead).
  output?: unknown;
  renders?: unknown[];
  fixturePreview?: unknown;
}

declare global {
  interface Window {
    __CATALOG_PREVIEW__: CatalogPreviewGlobal;
  }
}

const DATA = (): CatalogPreviewData => window.__CATALOG_PREVIEW__.data;

function need<T>(map: Record<string, T>, key: string, kind: string): T {
  if (!(key in map)) {
    throw new Error(`catalog preview: no ${kind} payload for "${key}"`);
  }
  return map[key];
}

// ---- figure / map (keyed by component id) ---------------------------------

export async function renderFigure(_dashboardId: string, componentId: string) {
  return need(DATA().figures, componentId, 'figure') as {
    figure: { data?: unknown[]; layout?: Record<string, unknown> };
    metadata: { visu_type?: string; filter_applied?: boolean };
  };
}

export async function renderMap(_dashboardId: string, componentId: string) {
  return need(DATA().maps, componentId, 'map') as {
    figure: { data?: unknown[]; layout?: Record<string, unknown> };
    metadata: { visu_type?: string; filter_applied?: boolean };
  };
}

// ---- table (keyed by component id; full rows returned in one block) --------

export async function renderTable(
  _dashboardId: string,
  componentId: string,
  _filters: InteractiveFilter[],
  start = 0,
  limit = 100,
) {
  const t = need(DATA().tables, componentId, 'table') as {
    columns: { field: string; headerName: string; type: string }[];
    rows: Record<string, unknown>[];
    total: number;
  };
  return {
    columns: t.columns,
    rows: t.rows.slice(start, start + limit),
    total: t.total,
    sort_by: null,
    sort_dir: 'desc' as const,
  };
}

// ---- cards (parent calls bulkComputeCards once) ---------------------------

export async function bulkComputeCards(
  _dashboardId: string,
  _filters: InteractiveFilter[],
  componentIds?: string[],
) {
  const c = DATA().cards;
  const ids = componentIds ?? Object.keys(c.values);
  const values: Record<string, unknown> = {};
  const secondary_values: Record<string, Record<string, unknown>> = {};
  const aggregations: Record<string, string[]> = {};
  for (const id of ids) {
    if (id in c.values) values[id] = c.values[id];
    if (c.secondary[id]) secondary_values[id] = c.secondary[id];
    if (c.aggregations[id]) aggregations[id] = c.aggregations[id];
  }
  return { values, secondary_values, aggregations, filter_applied: false, filter_count: 0 };
}

// ---- interactive (keyed by dc_id) -----------------------------------------

export async function fetchUniqueValues(dcId: string, columnName: string): Promise<string[]> {
  return need(DATA().unique, `${dcId}::${columnName}`, 'unique-values');
}

export async function fetchColumnRange(dcId: string, columnName: string) {
  return need(DATA().ranges, `${dcId}::${columnName}`, 'column-range');
}

export async function fetchSpecs(dcId: string): Promise<Record<string, unknown>> {
  return need(DATA().specs, dcId, 'specs');
}

// ---- image / multiqc (keyed by component id) ------------------------------

export async function fetchImagePaths(_dashboardId: string, componentId: string) {
  return need(DATA().images, componentId, 'images') as never;
}

export async function renderMultiQC(_dashboardId: string, componentId: string) {
  return need(DATA().multiqc, componentId, 'multiqc') as never;
}

export async function renderMultiQCGeneralStats(_dashboardId: string, componentId: string) {
  return need(DATA().multiqcGeneralStats, componentId, 'multiqc-general-stats') as never;
}

// ---- advanced viz (keyed by dc_id) ----------------------------------------

export async function fetchAdvancedVizData(_wfId: string, dcId: string) {
  return need(DATA().advancedVizData, dcId, 'advanced-viz-data') as never;
}

export async function fetchPhylogenyNewick(dcId: string): Promise<string> {
  return need(DATA().advancedVizData, `${dcId}::newick`, 'newick') as unknown as string;
}

// dispatch/poll kinds: results are precomputed, so dispatch returns a finished
// job immediately and poll echoes it. Keyed by the payload's dc_id.
function finishedJob(dcId: string) {
  return { job_id: dcId, status: 'done' as const, result: need(DATA().compute, dcId, 'compute'), from_cache: true };
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
