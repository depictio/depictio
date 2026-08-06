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
 *
 * SHIM SURFACE. The rule is: every api.ts export that touches the network AND
 * sits in the static entry's module graph must be overridden here. That graph
 * was walked from `static-runtime/main.tsx` (which mounts App directly — no
 * router, so builder/, dashboards/, projects/, admin/, profile/, cli-agents/
 * and auth/ are absent from the bundle entirely, and their api calls are
 * unreachable by construction, not by luck). Two traps that walk found:
 *   - reachability is not "fires on page load". `fetchMapData` and
 *     `fetchProject` are one user click deep (a map's data popover; the
 *     header's Settings gear, which unlike Edit carries no `isStaticBundle`
 *     guard) — a clean load trace proves nothing about them.
 *   - a shimmed function does not make its module safe: `availableValues`
 *     dispatches to `fetchUniqueValues` (shimmed) OR
 *     `fetchMultiQCSampleMappings` (was not).
 * Still unshimmed and deliberately so: `preflightStaticExport` /
 * `dispatchStaticExport` / `pollStaticExport` / `downloadStaticExport`.
 * `ExportStaticModal` IS in the graph (App renders it unconditionally) and
 * only the `!isStaticBundle` guard on its opener keeps it shut — that opener
 * now lives in `SettingsDrawer`'s Actions section (it used to be a header
 * button), i.e. inside a surface that IS reachable in a bundle, so the guard
 * has to stay there. Any future second opener turns those four into live
 * calls.
 *
 * NOT an api.ts concern, but the last thing standing between a bundle and a
 * zero-network load: Iconify. `../icons` registers only the source-SCANNED
 * icon subset, so an icon named solely in dashboard YAML/Mongo (mdi:penguin,
 * mdi:island, …) misses and @iconify/react falls back to its three public API
 * hosts — measured as 6 aborted requests on the penguins bundle, present both
 * before and after this file's overrides. STILL OPEN; the fix belongs at the
 * static entry beside `import '../icons'`, not here
 * (`addAPIProvider('', { resources: [] })` refuses the fallback outright).
 */

// Real api (importer === this file, so the shim plugin lets it through).
export * from '../../../../packages/depictio-react-core/src/api';

import type {
  AdvancedVizDataRequest,
  AdvancedVizDataResponse,
  DashboardData,
  DashboardSummary,
  FigureResponse,
  FloatingComponentsResponse,
  InteractiveFilter,
  StoredMetadata,
} from '../../../../packages/depictio-react-core/src/api';

import { bundle, bundledTabs, frozenPayload, interactiveIndexFor, rawBundle } from './bundle';
import {
  columnRangeLive,
  computeCardsLive,
  coverageTrackLive,
  dataRefFor,
  fetchAdvancedVizDataLive,
  renderFigureLive,
  renderPrologueFigureLive,
  renderTableLive,
  specsLive,
  uniqueValuesLive,
  userColumns,
  type CoverageTrackLiveRequest,
} from './liveData';
import { themedFrozenFigure } from './mantinePlotlyTemplate';
import { renderMultiQCGeneralStatsStatic, renderMultiQCStatic } from './multiqcShim';

// ---- dashboard shell -------------------------------------------------------

/** Stand-in workflow id for a bundle whose document has none. Every
 *  advanced_viz renderer gates its data fetch on a truthy `metadata.wf_id` and
 *  otherwise renders "missing data binding"; the id itself is inert offline
 *  (the shim's `fetchAdvancedVizData` keys on `dcId` alone).
 *
 *  Both producers now write a real workflow id — producer A the Mongo one,
 *  producer B its synthetic `synthetic_wf_id(workflow_tag)` — so this fill
 *  only ever fires for bundles built before that, which must keep rendering. */
const BUNDLE_WF_ID = 'static-bundle';

/** Cached so the document keeps one identity across App's re-fetches. */
let dashboardDoc: DashboardData | null = null;

interface DocComponent {
  component_type?: string;
  dc_id?: string | null;
  wf_id?: string | null;
}

/** True for an advanced_viz component that would render live but is missing
 *  the workflow id its renderer insists on. */
function needsWorkflowId(m: DocComponent): boolean {
  return (
    m.component_type === 'advanced_viz' &&
    !m.wf_id &&
    Boolean(m.dc_id) &&
    Boolean(dataRefFor(String(m.dc_id)))
  );
}

export async function fetchDashboard(_dashboardId: string): Promise<DashboardData> {
  if (dashboardDoc) return dashboardDoc;
  const doc = bundle().dashboard.doc as { stored_metadata?: DocComponent[] };
  const meta = doc.stored_metadata;
  dashboardDoc = (
    Array.isArray(meta) && meta.some(needsWorkflowId)
      ? {
          ...doc,
          stored_metadata: meta.map((m) => (needsWorkflowId(m) ? { ...m, wf_id: BUNDLE_WF_ID } : m)),
        }
      : doc
  ) as unknown as DashboardData;
  return dashboardDoc;
}

export async function fetchAllDashboards(): Promise<DashboardSummary[]> {
  // No sibling tabs in a bundle — the sidebar renders the single dashboard.
  return [];
}

/** Floating-map panel surface (`useMapPanel`), one request per page load.
 *
 *  Mirrors `/dashboards/floating_components/{id}`, including the part that
 *  makes the endpoint exist at all: it walks the whole TAB FAMILY, because a
 *  floating map is authored on one tab and rendered on every one. So this
 *  reads `bundledTabs()` — NOT `bundle().dashboard.doc`, which is only the tab
 *  on screen and would drop a map authored on a sibling. A single-tab bundle
 *  has no `tabs` array and is its own family.
 *
 *  Worth shimming even though the real function already resolves empty on a
 *  network failure instead of throwing: unshimmed it still ATTEMPTED the
 *  fetch, and a bundle's contract is zero requests, not zero fatal ones.
 *
 *  Component ids are uuids and the frozen section spans the family, so a
 *  sibling tab's map resolves its payload through `renderMap` unchanged —
 *  and producer A freezes every `map` component regardless of placement, so
 *  the payload is there. Never throws: the caller uses this result to prune
 *  filters hydrated from storage, and a rejection would leave a stale
 *  cross-tab selection applied with nothing left to prune it. */
export async function fetchFloatingComponents(
  dashboardId: string,
): Promise<FloatingComponentsResponse> {
  const raw = rawBundle();
  const tabs = bundledTabs();
  const family = tabs.length
    ? tabs.map((t) => ({ id: t.id, title: t.title, doc: t.doc }))
    : [{ id: raw.dashboard.id || dashboardId, title: raw.dashboard.title, doc: raw.dashboard.doc }];

  const components = [];
  for (const tab of family) {
    const meta =
      (tab.doc as { stored_metadata?: (DocComponent & { placement?: string })[] })
        .stored_metadata ?? [];
    for (const m of meta) {
      if (m.component_type === 'map' && m.placement === 'floating') {
        // `dashboard_id` is the OWNING tab, which is what MapRenderer fetches
        // against — not necessarily the tab being viewed.
        components.push({
          dashboard_id: tab.id,
          tab_title: tab.title,
          metadata: m as unknown as StoredMetadata,
        });
      }
    }
  }

  // Endpoint: `parent_dashboard_id or dashboard_id` — a main tab is its own
  // parent. The viewer keys panel state and cross-tab filter persistence on
  // this, so it must be the family id, not a placeholder. `bundledTabs()`
  // already sorts the main tab first.
  const entryDoc = raw.dashboard.doc as { parent_dashboard_id?: string | null };
  const parentId = tabs.length
    ? (tabs.find((t) => t.is_main_tab)?.id ?? tabs[0].id)
    : String(entryDoc.parent_dashboard_id || raw.dashboard.id || dashboardId);
  return { parent_dashboard_id: parentId, components };
}

export async function fetchProjectFromDashboard(_dashboardId: string) {
  // App's ingestion-banner effect is best-effort and swallows failures.
  throw new Error('static bundle: no project backend');
}

/** Reached one click deep: the header's Settings gear is NOT `isStaticBundle`-
 *  gated (unlike Edit beside it), and `DashboardInfoBody` enriches
 *  `doc.project_id` — which producer A keeps — into a project name. Rejecting
 *  matches the sibling `fetchProjectFromDashboard` above, and that effect
 *  already catches and falls back to "no name"; the drawer's other fields all
 *  come from the bundled document and still render. */
export async function fetchProject(
  _projectId: string,
  _options: { skipEnrichment?: boolean } = {},
) {
  throw new Error('static bundle: no project backend');
}

export async function fetchIngestionHealth(_projectId: string) {
  throw new Error('static bundle: no ingestion backend');
}

export async function saveDashboardNotes(_dashboardId: string, _notes: unknown) {
  throw new Error('static bundle: read-only — notes cannot be saved');
}

// ---- frozen render-path lookups (keyed by component index) -----------------

/** dc_id of a figure component, from the dashboard document. */
function figureDcIdFor(componentId: string): string {
  const doc = bundle().dashboard.doc as {
    stored_metadata?: { index?: string; component_type?: string; dc_id?: string | null }[];
  };
  const meta = (doc.stored_metadata ?? []).find(
    (c) => c.component_type === 'figure' && String(c.index ?? '') === componentId,
  );
  return String(meta?.dc_id ?? '');
}

export async function renderFigure(
  _dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[] = [],
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  // Live path (phase 5b): a figure with a binding table refills from the
  // bundled Parquet under the current filter state — the RFC §4
  // bind-and-refill runtime. Gating is by BINDING PRESENCE, never by the
  // component's mode field: the producer only emits bindings[cid] for
  // figures it could bind (ui-mode, or — phase 6 — code-mode with a
  // transpiled prologue), so a code-mode figure with both bindings[cid] and
  // a non-empty prologues[cid] takes the live path below, while a figure
  // with a prologue but NO binding falls through to frozen and never
  // renders live. Figures without a prologue keep the ui-mode refill
  // unchanged. The theme template swap is shared with the frozen path
  // (themedFrozenFigure only replaces layout.template, exactly like the
  // live server re-templating on a color-scheme flip).
  const binding = bundle().bindings?.[componentId];
  if (binding) {
    const dcId = figureDcIdFor(componentId);
    if (dcId && dataRefFor(dcId)) {
      const prologue = bundle().prologues?.[componentId];
      try {
        const live =
          prologue && prologue.length > 0
            ? // Phase 6: replay the transpiled prologue over the mask-selected
              // base rows, then refill from the derived frame. displayed/total
              // count DERIVED rows (post-reshape) — what the figure plots.
              await renderPrologueFigureLive(binding, prologue, dcId, filters)
            : await renderFigureLive(binding, dcId, filters);
        return themedFrozenFigure(
          {
            figure: live.figure,
            metadata: {
              filter_applied: live.filterApplied,
              was_sampled: binding.sampled,
              displayed_data_count: live.displayed,
              total_data_count: live.total,
              full_data_loaded: !binding.sampled,
            },
          },
          theme,
        );
      } catch (e) {
        // Structural degradation (RFC §4): a refill (or prologue replay)
        // that cannot complete falls back to the frozen snapshot rather than
        // rendering wrong data. Prologue figures ship WITHOUT a frozen
        // payload — for those, frozenPayload() below throws its readable
        // "no frozen figure payload" error, which the FigureRenderer
        // surfaces as the component's error state (same behavior as any
        // frozen-payload miss today).
        console.error(
          `static bundle: live figure refill failed for "${componentId}" — serving frozen payload`,
          e,
        );
      }
    }
  }
  // FigureRenderer re-requests on every color-scheme flip (the live path
  // sends `theme` to the server, which re-templates the figure). Offline
  // equivalent: swap the frozen figure's layout.template with the matching
  // client-side mantine template so frozen figures follow the theme too.
  return themedFrozenFigure(frozenPayload<FigureResponse>(componentId, 'figure'), theme);
}

export async function renderMap(_dashboardId: string, componentId: string) {
  return frozenPayload(componentId, 'map') as never;
}

/** The "show data" popover behind every map (`MapDataButton`, rendered by both
 *  ComponentRenderer and the floating panel). Fires on user click, so it never
 *  showed up in a page-load network trace — but it is a live POST all the same.
 *
 *  Rejects rather than serving an approximation: a map is a FROZEN-tier
 *  component, so its DC is only in the bundle when some *other* live component
 *  happens to share it, and the endpoint's own column order + truncation rules
 *  are not reproduced here. `MapDataButton` catches and renders `err.message`
 *  inside the popover, so this text is what the user reads. */
export async function fetchMapData(
  _dashboardId: string,
  _componentId: string,
  _filters: InteractiveFilter[],
  _signal?: AbortSignal,
) {
  throw new Error('static bundle: the map data table is not exported');
}

/** dc_id of a table component, from the dashboard document. */
function tableDcIdFor(componentId: string): string {
  const doc = bundle().dashboard.doc as {
    stored_metadata?: { index?: string; component_type?: string; dc_id?: string | null }[];
  };
  const meta = (doc.stored_metadata ?? []).find(
    (c) => c.component_type === 'table' && String(c.index ?? '') === componentId,
  );
  return String(meta?.dc_id ?? '');
}

export async function renderTable(
  _dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[] = [],
  start = 0,
  limit = 100,
  sortBy?: string | null,
  sortDir: 'asc' | 'desc' = 'desc',
) {
  // Live path (phase 3): a table whose data collection ships in the bundle
  // recomputes every page offline — filter, then sort, then slice — through
  // the shared sortSlice kernel, mirroring the server's
  // render_table_endpoint contract exactly (single sort key, sort_dir
  // default desc, limit clamped 1..500, total = filtered count).
  const dcId = tableDcIdFor(componentId);
  if (dcId && dataRefFor(dcId)) {
    try {
      return await renderTableLive(dcId, filters, start, limit, sortBy, sortDir);
    } catch (e) {
      // Structural degradation (RFC §4): a live page that cannot be computed
      // falls back to the frozen snapshot rather than rendering wrong data.
      console.error(
        `static bundle: live table failed for "${componentId}" — serving frozen payload`,
        e,
      );
    }
  }
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

/** Live path: `render_multiqc` never recomputed anything at request time — it
 *  fetched a figure keyed on inputs frozen into `stored_metadata` (s3 locations,
 *  module, plot, dataset, theme), then ran the pure `patch_multiqc_figures` over
 *  it (patching.py:59). Both halves are in the bundle, so the shipped payload is
 *  re-sliced under the current filters instead of being served verbatim.
 *  Degrades to the unpatched figure on any resolution failure — never an error
 *  tile. */
export async function renderMultiQC(
  _dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[] = [],
  theme: 'light' | 'dark' = 'light',
) {
  return (await renderMultiQCStatic(componentId, filters, theme)) as never;
}

export async function renderMultiQCGeneralStats(
  _dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[] = [],
) {
  return (await renderMultiQCGeneralStatsStatic(componentId, filters)) as never;
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

/** `availableValues`' multiqc branch — the asymmetric sibling of
 *  `fetchUniqueValues` above. Same provider, same effect, but a multiqc DC
 *  exposes its sample list only through this per-project endpoint, and the
 *  bundle carries no sample-mapping table. Fires when a bundle pairs a multiqc
 *  DC with an interactive filter over a sample-like column; `availableValues`
 *  runs both branches under `Promise.allSettled` and drops the rejection, so
 *  the filter falls back to the values it can resolve. */
export async function fetchMultiQCSampleMappings(
  _projectId: string,
  _dcId: string,
): Promise<Record<string, string[]>> {
  throw new Error('static bundle: multiqc sample mappings are not exported');
}

// ---- advanced viz (requests carry dc_id) -----------------------------------

interface AdvancedVizMeta {
  index?: string;
  component_type?: string;
  viz_kind?: string;
  dc_id?: string | null;
  config?: {
    viz_kind?: string;
    tree_dc_id?: string | null;
    metadata_dc_id?: string | null;
  } | null;
}

/**
 * Component index whose frozen payload answers a request for `dcId`.
 *
 * TWO id namespaces reach this lookup. Most advanced_viz tiles are found by
 * their own `dc_id`, but a phylogenetic tile reads two collections —
 * `PhylogeneticRenderer` pulls the tree from `config.tree_dc_id` and the tip
 * metadata from `config.metadata_dc_id` — and both of those lookups must land
 * on the one component whose frozen payload carries the merged answer.
 *
 * The two namespaces can collide: nothing stops another advanced_viz from
 * owning the very DC a phylogenetic tile names as its metadata source, and a
 * single first-match over the array then hands whichever component happens to
 * come first the other's payload — silently, because no caller checks. So the
 * search is ordered instead. `vizKind` is the caller's own kind (every caller
 * knows it: the request carries it, and the newick fetch is phylogenetic by
 * construction) and settles the collision; within one kind, owning the DC
 * outranks merely referencing it in config. The last two passes ignore the kind
 * so a manifest whose components predate `viz_kind` still resolves.
 */
function advancedVizIndexFor(dcId: string, vizKind?: string): string {
  const doc = bundle().dashboard.doc as { stored_metadata?: AdvancedVizMeta[] };
  const components = (doc.stored_metadata ?? []).filter(
    (c) => c.component_type === 'advanced_viz',
  );
  const owns = (c: AdvancedVizMeta) => String(c.dc_id ?? '') === dcId;
  const refers = (c: AdvancedVizMeta) => {
    const cfg = c.config ?? {};
    return String(cfg.tree_dc_id ?? '') === dcId || String(cfg.metadata_dc_id ?? '') === dcId;
  };
  // Kind lives top-level or inside the config blob, depending on how the
  // component was authored (mirrors `advanced_viz_kind` in serverless/pruning.py).
  const sameKind = (c: AdvancedVizMeta) =>
    Boolean(vizKind) && (c.viz_kind ?? c.config?.viz_kind) === vizKind;

  const meta =
    components.find((c) => sameKind(c) && owns(c)) ??
    components.find((c) => sameKind(c) && refers(c)) ??
    components.find(owns) ??
    components.find(refers);
  if (!meta?.index) {
    throw new Error(`static bundle: no advanced_viz component for dc "${dcId}"`);
  }
  return meta.index;
}

export async function fetchAdvancedVizData(
  req: AdvancedVizDataRequest,
  _signal?: AbortSignal,
): Promise<AdvancedVizDataResponse> {
  // Live path (phase 4): a data-path advanced_viz kind whose DC ships in the
  // bundle recomputes `/advanced_viz/data` offline — mask, project, reduce by
  // the kind's sampling policy — so intra-viz controls and the global filters
  // both move real data instead of a snapshot. Routing is by DATA_REF
  // presence, matching the producers' own live gate: they bundle the DC (and
  // emit no frozen payload) exactly for these components. Everything else —
  // phylogenetic, whose source is a tree rather than a frame, and every
  // pre-phase-4 bundle — keeps the frozen payload.
  if (dataRefFor(req.dcId)) {
    // Deliberately NOT wrapped in a try/catch: a live component has no frozen
    // payload to fall back to, so swallowing the error would only turn a
    // readable message into an empty chart. Every advanced_viz renderer has
    // its own error state and shows what the throw said.
    //
    // `signal` is ignored: the work is local and synchronous once the table is
    // open, so there is no in-flight request to abort — the renderers' own
    // `cancelled` flags already discard a superseded result.
    return fetchAdvancedVizDataLive(req);
  }
  return frozenPayload<AdvancedVizDataResponse>(
    advancedVizIndexFor(req.dcId, req.vizKind),
    'advanced-viz-data',
  );
}

/** The DC's polars schema, straight off the DataRef the producer wrote —
 *  dtype strings pass through unchanged (they were serialised from the same
 *  `pl.DataFrame.schema` this endpoint reads server-side), companions
 *  excluded. Renderers treat this as best-effort decoration (annotation
 *  pickers, hover extras) and catch failures, but a bundled DC can answer it
 *  exactly, and the real implementation would network-fail offline. */
export async function fetchPolarsSchema(dcId: string): Promise<Record<string, string>> {
  const ref = dataRefFor(dcId);
  if (!ref) throw new Error(`static bundle: no data_ref for dc "${dcId}"`);
  return Object.fromEntries(userColumns(ref).map((c) => [c.name, c.dtype]));
}

export async function fetchPhylogenyNewick(dcId: string): Promise<string> {
  const p = frozenPayload<{ newick?: string }>(
    advancedVizIndexFor(dcId, 'phylogenetic'),
    'newick',
  );
  return p.newick ?? '';
}

// Celery dispatch/poll kinds: the compute has no in-browser equivalent, so the
// result is frozen at export time — dispatch returns a finished job
// immediately and poll echoes it (catalog-preview precedent). `coverage_track`
// left this family in phase 8; see its override below.
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
/** Live path (phase 8): `coverage_track` dispatches to Celery on a server, but
 *  its task is a projection + two whitelist masks + a sort + a
 *  per-(chromosome, sample) rolling mean, all of which commute with the
 *  dashboard filters — so the browser recomputes it from the bundled Parquet
 *  and the tile responds to filters instead of freezing. Gated on DATA_REF
 *  presence like every other live path; a bundle built before phase 8 still
 *  carries the frozen `compute` payload and takes the echo below.
 *
 *  The compute resolves inside the dispatch, so the renderer's `status ===
 *  'done'` branch accepts it and `pollCoverageTrack` is never reached for a
 *  live component. Not wrapped in a try/catch, for the same reason
 *  `fetchAdvancedVizData` is not: there is no frozen payload behind it, so
 *  swallowing the throw would trade a readable message for an empty chart. */
export async function dispatchCoverageTrack(p: CoverageTrackLiveRequest) {
  if (dataRefFor(p.dc_id)) {
    return {
      job_id: p.dc_id,
      status: 'done' as const,
      result: await coverageTrackLive(p),
      from_cache: false,
    } as never;
  }
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
