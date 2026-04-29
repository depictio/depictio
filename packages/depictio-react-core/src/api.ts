/**
 * Thin fetch wrapper for Depictio's FastAPI backend. Preserves the same auth
 * contract as the Dash app: JWT bearer token from localStorage, with a public
 * fallback that relies on get_user_or_anonymous middleware for anonymous mode.
 */

const API_BASE = '/depictio/api/v1';

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  try {
    const stored = localStorage.getItem('local-store');
    if (stored) {
      const parsed = JSON.parse(stored);
      if (parsed?.access_token) {
        headers.Authorization = `Bearer ${parsed.access_token}`;
      }
    }
  } catch {
    // ignore malformed localStorage
  }
  return headers;
}

export interface StoredMetadata {
  index: string;
  component_type: string;
  wf_id?: string;
  dc_id?: string;
  project_id?: string;
  // Card
  title?: string;
  value?: unknown;
  column_name?: string;
  column_type?: string;
  aggregation?: string;
  aggregations?: string[];
  filter_expr?: string;
  title_color?: string;
  background_color?: string;
  title_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  value_font_size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl';
  icon_name?: string;
  icon_color?: string;
  metric_theme?: string;
  parent_index?: string;
  // Interactive
  interactive_component_type?: string;
  default_state?: { default_value?: unknown; default_range?: unknown; options?: unknown[] };
  [key: string]: unknown;
}

export interface DashboardData {
  _id?: string;
  dashboard_id?: string;
  title?: string;
  project_id?: string;
  stored_metadata?: StoredMetadata[];
  stored_layout_data?: unknown;
  left_panel_layout_data?: unknown;
  right_panel_layout_data?: unknown;
  [key: string]: unknown;
}

/** Fetch dashboard including stored_metadata. Mirrors what the Dash viewer reads. */
export async function fetchDashboard(dashboardId: string): Promise<DashboardData> {
  const res = await fetch(`${API_BASE}/dashboards/get/${dashboardId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch dashboard: ${res.status}`);
  return res.json();
}

/**
 * Fetch all dashboards including child tabs. Used to build the tab nav in
 * the sidebar — parent dashboard + its child tabs grouped together.
 */
export interface DashboardSummary {
  dashboard_id: string;
  title?: string;
  parent_dashboard_id?: string | null;
  project_id?: string;
  /** Order within parent (0 = main tab). Mirrors the Dash sort key. */
  tab_order?: number;
  /** Custom name shown for the parent (main) tab. Defaults to dashboard title. */
  main_tab_name?: string;
  /** Tab-specific fields. Dash precedence: `tab_icon || icon`, `tab_icon_color || icon_color`. */
  tab_icon?: string;
  tab_icon_color?: string;
  icon?: string;
  icon_color?: string;
}

export async function fetchAllDashboards(): Promise<DashboardSummary[]> {
  const res = await fetch(`${API_BASE}/dashboards/list?include_child_tabs=true`, {
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : data.dashboards || [];
}

/** Fetch precomputed column specs for a data collection (includes aggregations). */
export async function fetchSpecs(dcId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/deltatables/specs/${dcId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch specs: ${res.status}`);
  return res.json();
}

/** Fetch unique values for a column (backing MultiSelect options).
 *
 *  This hits /deltatables/unique_values/{dc_id}?column=... which the viewer
 *  branch adds as a thin wrapper around
 *  `load_deltatable_lite(..., load_for_options=True)`.
 */
export async function fetchUniqueValues(
  dcId: string,
  columnName: string,
): Promise<string[]> {
  const res = await fetch(
    `${API_BASE}/deltatables/unique_values/${dcId}?column=${encodeURIComponent(columnName)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to fetch unique values: ${res.status}`);
  const body = (await res.json()) as { values?: string[] };
  return body.values || [];
}

/** Numeric range bounds for a column — backs RangeSlider min/max.
 *  Reads precomputed min/max from /deltatables/specs/{dcId}.
 */
export async function fetchColumnRange(
  dcId: string,
  columnName: string,
): Promise<{ min: number | null; max: number | null }> {
  const specs = await fetchSpecs(dcId);
  if (Array.isArray(specs)) {
    // List shape: [{name, type, specs}]
    const entry = (specs as Array<Record<string, unknown>>).find(
      (e) => (e?.name as string) === columnName,
    );
    const s = (entry?.specs || {}) as Record<string, unknown>;
    return {
      min: typeof s.min === 'number' ? s.min : null,
      max: typeof s.max === 'number' ? s.max : null,
    };
  }
  // Dict shape (legacy)
  const dict = specs as Record<string, Record<string, unknown>>;
  const s = (dict[columnName] || {}) as Record<string, unknown>;
  return {
    min: typeof s.min === 'number' ? s.min : null,
    max: typeof s.max === 'number' ? s.max : null,
  };
}

/** Per-component computed data (current value under the given filter state). */
export interface InteractiveFilter {
  index: string;
  value: unknown;
  column_name?: string;
  interactive_component_type?: string;
}

export async function fetchComponentData(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
): Promise<{ value?: unknown; secondary_metrics?: unknown; comparison?: unknown }> {
  const res = await fetch(
    `${API_BASE}/dashboards/get_component_data/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters }),
    },
  );
  if (!res.ok) throw new Error(`Failed to fetch component data: ${res.status}`);
  return res.json();
}

/**
 * Bulk-compute card values with filters applied. One request covers all cards
 * in the dashboard — the backend dedupes Delta loads per unique (wf_id, dc_id)
 * so cost scales with distinct data collections, not with card count.
 *
 * Returns { values: { componentIndex: value, ... }, filter_applied, filter_count }.
 */
export interface BulkComputeResponse {
  values: Record<string, unknown>;
  filter_applied: boolean;
  filter_count: number;
}

export async function bulkComputeCards(
  dashboardId: string,
  filters: InteractiveFilter[],
  componentIds?: string[],
): Promise<BulkComputeResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/bulk_compute_cards/${dashboardId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, component_ids: componentIds }),
    },
  );
  if (!res.ok) throw new Error(`Failed to bulk-compute cards: ${res.status}`);
  return res.json();
}

/** Server-rendered Plotly figure for one component. */
export interface FigureResponse {
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  metadata: { visu_type?: string; filter_applied?: boolean };
}

export async function renderFigure(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_figure/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, theme }),
    },
  );
  if (!res.ok) throw new Error(`Failed to render figure: ${res.status}`);
  return res.json();
}

/** Paginated table rows + AG Grid column definitions. */
export interface TableResponse {
  columns: Array<{ field: string; headerName: string; type: string }>;
  rows: Record<string, unknown>[];
  total: number;
}

export async function renderTable(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  start = 0,
  limit = 100,
): Promise<TableResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_table/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, start, limit }),
    },
  );
  if (!res.ok) throw new Error(`Failed to render table: ${res.status}`);
  return res.json();
}

/** Fetch up to `max` non-null values of an image component's image_column.
 *  `dcId`, `imageColumn`, `s3BaseFolder` accepted for call-site symmetry but
 *  resolved server-side from the component's `stored_metadata`.
 */
export async function fetchImagePaths(
  dashboardId: string,
  componentId: string,
  _dcId: string,
  _imageColumn: string,
  _s3BaseFolder: string,
  max = 50,
): Promise<string[]> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_image_paths/${dashboardId}/${componentId}?max=${max}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to fetch image paths: ${res.status}`);
  const body = (await res.json()) as { paths?: string[] };
  return body.paths || [];
}

/** Server-rendered Plotly map (px.scatter_map / density_map / choropleth_map). */
export async function renderMap(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_map/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, theme }),
    },
  );
  if (!res.ok) throw new Error(`Failed to render map: ${res.status}`);
  return res.json();
}

/** JBrowse 2 iframe session payload. The standalone JBrowse server runs at
 *  localhost:3000 with sessions hosted at localhost:9010. Filter state may
 *  narrow the visible tracks via existing /jbrowse/* internal endpoints. If
 *  any of those services are unreachable, the backend returns 503.
 */
export interface JBrowseSessionResponse {
  iframe_url: string;
  assembly: string;
  location: string;
  tracks?: string[];
  metadata?: { filter_applied?: boolean };
}

export async function fetchJBrowseSession(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  theme: 'light' | 'dark' = 'light',
): Promise<JBrowseSessionResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_jbrowse/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, theme }),
    },
  );
  if (!res.ok) {
    let detail = `Failed to render JBrowse: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON error
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Server-rendered MultiQC Plotly figure (wraps create_multiqc_plot). */
export async function renderMultiQC(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  theme: 'light' | 'dark' = 'light',
): Promise<FigureResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_multiqc/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, theme }),
    },
  );
  if (!res.ok) throw new Error(`Failed to render MultiQC: ${res.status}`);
  return res.json();
}

// ---- MultiQC General Statistics ------------------------------------------

export interface GeneralStatsColumnFormat {
  precision: number;
  suffix: string;
  group: boolean;
}

export interface GeneralStatsColumn {
  id: string;
  name: string;
  type: 'numeric' | 'text';
  format: GeneralStatsColumnFormat | null;
}

export interface GeneralStatsStyle {
  if: { filter_query?: string; column_id?: string; state?: string };
  backgroundImage?: string;
  backgroundColor?: string;
  paddingTop?: number;
  paddingBottom?: number;
  fontWeight?: string;
  border?: string;
  [key: string]: unknown;
}

export interface GeneralStatsModeData {
  table_data: Array<Record<string, unknown>>;
  table_columns: GeneralStatsColumn[];
  table_styles: GeneralStatsStyle[];
  violin_figure: { data?: unknown[]; layout?: Record<string, unknown> };
}

export interface GeneralStatsPayload {
  is_paired_end: boolean;
  all_samples: string[];
  modes: {
    mean: GeneralStatsModeData;
    r1?: GeneralStatsModeData;
    r2?: GeneralStatsModeData;
    all?: GeneralStatsModeData;
  };
}

/** JSON-safe MultiQC General Statistics payload (table + violin, all read modes). */
export async function renderMultiQCGeneralStats(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[] = [],
): Promise<GeneralStatsPayload> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_multiqc_general_stats/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters }),
    },
  );
  if (!res.ok) {
    let detail = `Failed to render MultiQC General Stats: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON error bodies
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Server status — backs the sidebar status badge. Polled every 30s. */
export interface ServerStatusResponse {
  status: 'online' | 'offline' | string;
  version?: string;
}

export async function fetchServerStatus(): Promise<ServerStatusResponse> {
  const res = await fetch(`${API_BASE}/utils/status`, { cache: 'no-cache' });
  if (!res.ok) return { status: 'offline' };
  return res.json();
}

/** Current user — anonymous-tolerant. Returns null for missing/invalid token. */
export interface CurrentUser {
  id?: string;
  email: string;
  is_admin: boolean;
}

/**
 * Tab CRUD wrappers — mirror the Dash editor's tab-management endpoints.
 * The React editor uses these from EditorApp to back the per-tab "..." menu
 * (Edit / Move up / Move down / Delete) and the trailing "+ Add tab" pill.
 */

export interface UpdateTabPayload {
  title?: string;
  tab_icon?: string;
  tab_icon_color?: string;
  /** Only allowed on main tabs — backend rejects with 400 for child tabs. */
  main_tab_name?: string;
}

export async function updateTab(
  dashboardId: string,
  payload: UpdateTabPayload,
): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/tab/${dashboardId}`, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to update tab: ${res.status} ${text}`);
  }
}

export async function deleteTab(dashboardId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/tab/${dashboardId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to delete tab: ${res.status} ${text}`);
  }
}

export interface TabOrderEntry {
  dashboard_id: string;
  tab_order: number;
}

export async function reorderTabs(
  parentDashboardId: string,
  tabOrders: TabOrderEntry[],
): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/tabs/reorder`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      parent_dashboard_id: parentDashboardId,
      tab_orders: tabOrders,
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to reorder tabs: ${res.status} ${text}`);
  }
}

/**
 * Create a new child tab under `parentDashboardId`.
 *
 * Mirrors Dash's `_create_new_tab` (`tab_callbacks.py:1150-1281`):
 *   1. Fetch parent to inherit `permissions` + `project_id`.
 *   2. Count siblings to compute the next `tab_order`.
 *   3. POST a fresh `DashboardData` to `/save/{newDashboardId}` with
 *      `is_main_tab=false` and the modal-supplied icon/color/title.
 *
 * Returns the new dashboard id so the caller can navigate to it.
 */
export async function createTab(
  parentDashboardId: string,
  fields: { title: string; tab_icon?: string; tab_icon_color?: string },
): Promise<string> {
  const parent = await fetchDashboard(parentDashboardId);
  const siblings = await fetchAllDashboards();
  const childCount = siblings.filter(
    (d) => String(d.parent_dashboard_id ?? '') === String(parentDashboardId),
  ).length;
  const nextOrder = childCount + 1;

  const newId =
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID().replace(/-/g, '').slice(0, 24)
      : Math.random().toString(16).slice(2).padEnd(24, '0').slice(0, 24);

  const payload: Record<string, unknown> = {
    dashboard_id: newId,
    version: 1,
    title: fields.title,
    subtitle: '',
    icon: fields.tab_icon ?? 'mdi:tab',
    icon_color: fields.tab_icon_color ?? 'blue',
    icon_variant: 'filled',
    workflow_system: 'none',
    notes_content: '',
    permissions: (parent as Record<string, unknown>).permissions ?? {},
    is_public: false,
    last_saved_ts: '',
    project_id: parent.project_id,
    is_main_tab: false,
    parent_dashboard_id: parentDashboardId,
    tab_order: nextOrder,
    tab_icon: fields.tab_icon ?? null,
    tab_icon_color: fields.tab_icon_color ?? null,
  };

  const res = await fetch(`${API_BASE}/dashboards/save/${newId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to create tab: ${res.status} ${text}`);
  }
  return newId;
}

// ---- Builder helpers (component create/edit) ----------------------------
//
// These back the React component-creation stepper and edit page. They wrap
// existing FastAPI endpoints used by the Dash editor; no schema changes.

export interface WorkflowEntry {
  _id: string;
  name?: string;
  workflow_tag?: string;
  engine?: { name?: string } | string;
  data_collections?: Array<{
    _id: string;
    data_collection_tag?: string;
    config?: { type?: string; [k: string]: unknown };
    [k: string]: unknown;
  }>;
  project_id?: string;
  [k: string]: unknown;
}

/** All workflows accessible to the current user (each carries its DCs).
 *  Mirrors GET /workflows/get_all_workflows. Note: requires a logged-in user;
 *  anonymous sessions get an empty list. */
export async function fetchWorkflowsForUser(): Promise<WorkflowEntry[]> {
  const res = await fetch(`${API_BASE}/workflows/get_all_workflows`, {
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/**
 * Fetch the project tied to a dashboard (with embedded workflows + DCs).
 *
 * This is what the Dash stepper uses (`stepper.py:set_workflow_options` →
 * `GET /projects/get/from_dashboard_id/{id}`). Workflows aren't fetched
 * globally — they are project-scoped, so a dashboard's create/edit page must
 * use this endpoint instead of `/workflows/get_all_workflows`.
 *
 * Backend uses `get_user_or_anonymous`, so this works for anonymous sessions
 * on public dashboards too.
 *
 * Normalizes workflow + DC IDs: backends sometimes return `_id`, sometimes
 * `id` after a `from_mongo` round-trip. We coalesce both into `_id` so the
 * React side has one shape.
 */
export async function fetchProjectFromDashboard(
  dashboardId: string,
): Promise<{
  project: { _id: string; workflows: WorkflowEntry[]; [k: string]: unknown };
  delta_locations: Record<string, string>;
}> {
  const res = await fetch(
    `${API_BASE}/projects/get/from_dashboard_id/${dashboardId}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    throw new Error(
      `Failed to fetch project for dashboard ${dashboardId}: ${res.status}`,
    );
  }
  const data = await res.json();
  // Some response paths return `{project, delta_locations}`, some return the
  // project object directly — handle both.
  const projectRaw = (data?.project ?? data) as Record<string, unknown>;
  const deltaLocations = (data?.delta_locations ?? {}) as Record<string, string>;

  const wfsRaw = (projectRaw?.workflows as Array<Record<string, unknown>>) || [];
  const workflows: WorkflowEntry[] = wfsRaw.map((wf) => {
    const wfId = (wf._id ?? wf.id) as string;
    const dcsRaw = (wf.data_collections as Array<Record<string, unknown>>) || [];
    const dcs = dcsRaw.map((dc) => ({
      _id: (dc._id ?? dc.id) as string,
      data_collection_tag: dc.data_collection_tag as string | undefined,
      config: dc.config as Record<string, unknown> | undefined,
      ...dc,
    }));
    return {
      _id: wfId,
      name: wf.name as string | undefined,
      workflow_tag: wf.workflow_tag as string | undefined,
      engine: wf.engine as { name?: string } | string | undefined,
      data_collections: dcs,
      project_id: (projectRaw._id ?? projectRaw.id) as string | undefined,
      ...wf,
    };
  });

  return {
    project: {
      _id: (projectRaw._id ?? projectRaw.id) as string,
      workflows,
      ...projectRaw,
    },
    delta_locations: deltaLocations,
  };
}

export interface DcShapeResponse {
  num_rows?: number;
  num_columns?: number;
  [k: string]: unknown;
}

/** Row/column counts for a delta table — for the step-one preview pane. */
export async function fetchDeltaShape(dcId: string): Promise<DcShapeResponse> {
  const res = await fetch(`${API_BASE}/deltatables/shape/${dcId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) return {};
  return res.json();
}

/** First N rows of a delta table for the data-source preview pane.
 *  Backed by GET /deltatables/preview/{dc_id}?limit=N — capped server-side. */
export interface PreviewResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  total_rows: number;
  total_columns: number;
}

export async function fetchDataCollectionPreview(
  dcId: string,
  limit = 100,
): Promise<PreviewResult> {
  const res = await fetch(
    `${API_BASE}/deltatables/preview/${dcId}?limit=${limit}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch preview: ${res.status}`);
  }
  return res.json();
}

/** Fetch DC config from the data collection registry (not delta specs).
 *  Returns at minimum `config.type` (used to detect MultiQC). */
export async function fetchDataCollectionConfig(
  dcId: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/datacollections/specs/${dcId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) return {};
  return res.json();
}

/** Server-rendered figure preview without persisting metadata.
 *  Used by the live preview pane during edit. */
export interface FigurePreviewRequest {
  metadata: Record<string, unknown>;
  filters?: InteractiveFilter[];
  theme?: 'light' | 'dark';
}

export async function previewFigure(
  body: FigurePreviewRequest,
): Promise<FigureResponse> {
  const res = await fetch(`${API_BASE}/figure/preview`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      filters: [],
      theme: 'light',
      ...body,
    }),
  });
  if (!res.ok) {
    let detail = `Preview failed: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Render a MultiQC plot from in-flight builder metadata (no save needed).
 *  Mirrors POST /api/v1/multiqc/preview — same Plotly figure shape that
 *  /dashboards/render_multiqc/{id}/{cid} returns. */
export interface MultiQCPreviewRequest {
  dc_id: string;
  module: string;
  plot: string;
  dataset?: string | null;
  theme?: 'light' | 'dark';
}

export async function previewMultiQC(
  body: MultiQCPreviewRequest,
): Promise<FigureResponse> {
  const res = await fetch(`${API_BASE}/multiqc/preview`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ theme: 'light', ...body }),
  });
  if (!res.ok) {
    let detail = `MultiQC preview failed: ${res.status}`;
    try {
      const b = await res.json();
      if (b?.detail) detail = String(b.detail);
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Wraps figure_component/code_mode.py:analyze_constrained_code so the React
 *  builder can validate code mode and round-trip params↔code on mode switch. */
export interface CodeAnalysis {
  is_valid: boolean;
  error?: string | null;
  visu_type?: string | null;
  dict_kwargs?: Record<string, unknown>;
  warnings?: string[];
}

export async function analyzeFigureCode(
  code: string,
  visuTypeHint?: string,
): Promise<CodeAnalysis> {
  const res = await fetch(`${API_BASE}/figure/analyze_code`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ code, visu_type: visuTypeHint }),
  });
  if (!res.ok) {
    return { is_valid: false, error: `Analyze failed: ${res.status}` };
  }
  return res.json();
}

export type FigureParameterType =
  | 'string'
  | 'integer'
  | 'float'
  | 'boolean'
  | 'column'
  | 'select'
  | 'multi_select'
  | 'color'
  | 'range';

export type FigureParameterCategory = 'core' | 'common' | 'specific' | 'advanced';

export type FigureVisualizationGroup =
  | 'core'
  | 'advanced'
  | '3d'
  | 'geographic'
  | 'clustering'
  | 'specialized';

export interface FigureParameterSpec {
  name: string;
  type: FigureParameterType;
  category: FigureParameterCategory;
  label: string;
  description: string;
  default: unknown;
  required: boolean;
  options: Array<string | number> | null;
  min_value: number | null;
  max_value: number | null;
  depends_on: string[] | null;
}

export interface FigureVisualizationDefinition {
  name: string;
  function_name: string;
  label: string;
  description: string;
  parameters: FigureParameterSpec[];
  icon: string;
  group: FigureVisualizationGroup;
}

/** Lightweight summary returned by `GET /figure/visualizations`. The figure
 *  builder dropdown uses this to populate the list at runtime so the React
 *  side stays in sync with the Python registry without a hardcoded mirror. */
export interface FigureVisualizationSummary {
  name: string;
  label: string;
  description: string;
  icon: string;
  group: FigureVisualizationGroup;
}

/** Mirror of figure_component.definitions.get_visualization_definition.
 *  Lets the React builder render the parameter accordion (Core / Common /
 *  Specific / Advanced) without duplicating the spec on the client. */
export async function fetchFigureParameterDiscovery(
  vizType: string,
): Promise<FigureVisualizationDefinition> {
  const res = await fetch(
    `${API_BASE}/figure/parameter-discovery/${encodeURIComponent(vizType)}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(`Parameter discovery failed: ${detail}`);
  }
  return res.json();
}

/** Fetch the full curated list of visualization types with display metadata.
 *  Matches `GET /figure/visualizations`. */
export async function fetchFigureVisualizationList(): Promise<
  FigureVisualizationSummary[]
> {
  const res = await fetch(`${API_BASE}/figure/visualizations`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(`Visualization list failed: ${detail}`);
  }
  return res.json();
}

/**
 * Save (create or update) a single component's metadata into a dashboard.
 * Mirrors save_card_to_dashboard / save_figure_to_dashboard pattern from
 * depictio/dash/modules/*\/callbacks/save_utils.py: GET dashboard → replace
 * (or append) entry by `index` → POST full DashboardData back.
 *
 * Also auto-appends a layout entry for new components when `appendLayout` is
 * truthy: interactive → left panel, otherwise → right panel. The new entry
 * stacks under the existing layout (y = max bottom). The caller can override
 * by passing an explicit { x, y, w, h } object.
 */
export interface SaveComponentOptions {
  appendLayout?:
    | boolean
    | { panel: 'left' | 'right'; x?: number; y?: number; w?: number; h?: number };
}

// Default grid box for a freshly-created component. Sizes track the seeded
// dashboards under depictio/projects/<project>/.db_seeds/dashboard*.json —
// small KPI tiles for cards, full-width tables, medium plots elsewhere.
function defaultLayoutForType(
  componentType: string,
  panel: 'left' | 'right',
  y: number,
): { x: number; y: number; w: number; h: number } {
  if (panel === 'left') {
    // left panel cols=1; interactives are stacked vertically.
    return { x: 0, y, w: 1, h: 2 };
  }
  // right panel cols=8.
  switch (componentType) {
    case 'card':
      return { x: 0, y, w: 2, h: 2 };
    case 'figure':
      return { x: 0, y, w: 4, h: 5 };
    case 'multiqc':
      return { x: 0, y, w: 4, h: 5 };
    case 'table':
      return { x: 0, y, w: 8, h: 5 };
    case 'image':
      return { x: 0, y, w: 4, h: 4 };
    case 'map':
      return { x: 0, y, w: 4, h: 4 };
    default:
      return { x: 0, y, w: 4, h: 4 };
  }
}

export async function upsertComponent(
  dashboardId: string,
  metadata: StoredMetadata,
  opts: SaveComponentOptions = {},
): Promise<void> {
  const dashboard = await fetchDashboard(dashboardId);
  const existing = (dashboard.stored_metadata || []) as StoredMetadata[];
  const idx = existing.findIndex((m) => String(m.index) === String(metadata.index));
  const isNew = idx === -1;
  const next: StoredMetadata[] = isNew
    ? [...existing, metadata]
    : existing.map((m, i) => (i === idx ? metadata : m));

  const payload: DashboardData = { ...dashboard, stored_metadata: next };

  if (isNew && opts.appendLayout) {
    const panel: 'left' | 'right' =
      typeof opts.appendLayout === 'object'
        ? opts.appendLayout.panel
        : metadata.component_type === 'interactive'
        ? 'left'
        : 'right';
    const layoutKey =
      panel === 'left' ? 'left_panel_layout_data' : 'right_panel_layout_data';
    const current = (payload[layoutKey] as Array<Record<string, unknown>>) || [];
    const nextY = current.reduce((acc, it) => {
      const y = Number((it as { y?: number }).y ?? 0);
      const h = Number((it as { h?: number }).h ?? 0);
      return Math.max(acc, y + h);
    }, 0);
    // Per-type sizes match the seeded dashboards (right panel cols=8, left
    // panel cols=1). Cards are small KPIs; figures/tables/maps need room.
    const defaultBox = defaultLayoutForType(
      String(metadata.component_type || ''),
      panel,
      nextY,
    );
    const explicit: { x?: number; y?: number; w?: number; h?: number } =
      typeof opts.appendLayout === 'object' ? opts.appendLayout : {};
    payload[layoutKey] = [
      ...current,
      {
        i: `box-${metadata.index}`,
        x: explicit.x ?? defaultBox.x,
        y: explicit.y ?? defaultBox.y,
        w: explicit.w ?? defaultBox.w,
        h: explicit.h ?? defaultBox.h,
      },
    ];
  }

  const res = await fetch(`${API_BASE}/dashboards/save/${dashboardId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to save component: ${res.status} ${text}`);
  }
}

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch(`${API_BASE}/auth/me/optional`, { headers: authHeaders() });
  if (!res.ok) return null;
  // Endpoint returns `{auth_mode, user: {id, email, is_admin}, ...}`. Older
  // shape (flat user object) is tolerated for forward/backward compat.
  const data = (await res.json()) as
    | {
        auth_mode?: string;
        user?: { id?: string; email?: string; is_admin?: boolean } | null;
        id?: string;
        email?: string;
        is_admin?: boolean;
      }
    | null;
  if (!data) return null;
  const u = data.user ?? (data.email ? { id: data.id, email: data.email, is_admin: data.is_admin } : null);
  if (!u || !u.email) return null;
  return { id: u.id, email: u.email, is_admin: Boolean(u.is_admin) };
}

// ---- Auth helpers (React /auth page) ------------------------------------
//
// Thin wrappers around the FastAPI auth endpoints. These back the React
// /auth route — login form, register form, public-mode modal, and Google
// OAuth callback. The returned session payloads share the same JSON shape
// the Dash app writes into localStorage[`local-store`], so the still-Dash
// /dashboards page picks up the React-issued session without changes.

/** Auth mode + flags returned by /auth/me/optional. */
export type AuthMode = 'standard' | 'single_user' | 'unauthenticated';

export interface AuthStatusResponse {
  auth_mode: AuthMode;
  user: { id: string; email: string; is_admin: boolean } | null;
  is_public_mode: boolean;
  is_single_user_mode: boolean;
  /** Demo mode (public mode + onboarding tooltips). Older backends omit this
   *  field — treat absent as `false`. */
  is_demo_mode?: boolean;
  /** Unauthenticated mode — anonymous users get a session, can upgrade to
   *  temporary. Older backends omit this — treat absent as `false`. */
  unauthenticated_mode?: boolean;
  google_oauth_enabled: boolean;
}

/** Session payload persisted to localStorage['local-store'] on successful auth.
 *  Mirrors the dict shape returned by the backend's session endpoints
 *  (_create_temporary_user_session, _get_anonymous_user_session) and the
 *  shape the Dash app writes itself.
 */
export interface SessionPayload {
  logged_in: true;
  email: string;
  user_id: string;
  access_token: string;
  refresh_token: string;
  expire_datetime: string;
  refresh_expire_datetime: string;
  name?: string | null;
  token_lifetime?: string;
  token_type?: string;
  is_temporary?: boolean;
  is_anonymous?: boolean;
  expiration_time?: string | null;
}

/** Fetch the auth state + mode flags. Drives which UI the /auth page renders. */
export async function fetchAuthStatus(): Promise<AuthStatusResponse> {
  const res = await fetch(`${API_BASE}/auth/me/optional`, { headers: authHeaders() });
  if (!res.ok) {
    return {
      auth_mode: 'standard',
      user: null,
      is_public_mode: false,
      is_single_user_mode: false,
      google_oauth_enabled: false,
    };
  }
  return (await res.json()) as AuthStatusResponse;
}

/** Login a user. Returns a session payload ready to persist to local-store.
 *  Throws Error("invalid_credentials") on 401 so callers can show a generic
 *  message without leaking which field was wrong.
 */
export async function loginUser(email: string, password: string): Promise<SessionPayload> {
  const body = new URLSearchParams();
  body.set('username', email);
  body.set('password', password);

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });
  if (res.status === 401) throw new Error('invalid_credentials');
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Login failed: ${res.status} ${detail}`);
  }
  const token = (await res.json()) as {
    access_token: string;
    refresh_token: string;
    expire_datetime: string;
    refresh_expire_datetime: string;
    user_id: string;
    name?: string;
    token_lifetime?: string;
    token_type?: string;
  };
  return {
    logged_in: true,
    email,
    user_id: String(token.user_id),
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    expire_datetime: token.expire_datetime,
    refresh_expire_datetime: token.refresh_expire_datetime,
    name: token.name ?? null,
    token_lifetime: token.token_lifetime,
    token_type: token.token_type ?? 'bearer',
  };
}

/** Register a new user. The backend returns success/message/user; this helper
 *  surfaces the message verbatim (e.g. "Email already registered") so the
 *  form can render it directly.
 */
export interface RegisterResult {
  success: boolean;
  message?: string;
}

export async function registerUser(email: string, password: string): Promise<RegisterResult> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, is_admin: false }),
  });
  if (!res.ok) {
    let detail = `Registration failed: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON
    }
    return { success: false, message: detail };
  }
  const body = (await res.json()) as { success?: boolean; message?: string };
  return { success: Boolean(body.success), message: body.message };
}

/** Public-mode "Continue as temporary user" — the React modal calls this. */
export async function createTemporaryUser(): Promise<SessionPayload> {
  const res = await fetch(`${API_BASE}/auth/public/create_temporary_user`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Failed to create temporary user: ${res.status} ${detail}`);
  }
  return (await res.json()) as SessionPayload;
}

/** Single-user / public-mode anonymous session for auto-redirects. */
export async function getAnonymousSession(): Promise<SessionPayload> {
  const res = await fetch(`${API_BASE}/auth/public/get_anonymous_user_session`);
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Failed to fetch anonymous session: ${res.status} ${detail}`);
  }
  return (await res.json()) as SessionPayload;
}

/** Initiate Google OAuth — caller redirects to the returned authorization_url. */
export async function startGoogleOAuth(): Promise<{ authorization_url: string; state: string }> {
  const res = await fetch(`${API_BASE}/auth/google/login`);
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Failed to start Google OAuth: ${res.status} ${detail}`);
  }
  return (await res.json()) as { authorization_url: string; state: string };
}

/** Complete the Google OAuth flow with the code/state from the redirect URL. */
export interface GoogleCallbackResult {
  success: boolean;
  message?: string;
  session: SessionPayload | null;
  redirect_url?: string;
}

export async function handleGoogleCallback(code: string, state: string): Promise<GoogleCallbackResult> {
  const params = new URLSearchParams({ code, state });
  const res = await fetch(`${API_BASE}/auth/google/callback?${params.toString()}`);
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    return { success: false, message: detail || `OAuth failed: ${res.status}`, session: null };
  }
  const body = (await res.json()) as {
    success?: boolean;
    message?: string;
    user?: { id: string; email: string };
    token?: {
      access_token: string;
      refresh_token: string;
      token_type?: string;
      expire_datetime: string;
      refresh_expire_datetime: string;
      user_id: string;
    };
    redirect_url?: string;
  };
  if (!body.success || !body.token || !body.user) {
    return { success: false, message: body.message, session: null };
  }
  return {
    success: true,
    message: body.message,
    redirect_url: body.redirect_url,
    session: {
      logged_in: true,
      email: body.user.email,
      user_id: String(body.token.user_id),
      access_token: body.token.access_token,
      refresh_token: body.token.refresh_token,
      expire_datetime: body.token.expire_datetime,
      refresh_expire_datetime: body.token.refresh_expire_datetime,
      token_type: body.token.token_type ?? 'bearer',
    },
  };
}

/** Persist a session payload to localStorage under the same key Dash uses. */
export function persistSession(session: SessionPayload): void {
  try {
    localStorage.setItem('local-store', JSON.stringify(session));
  } catch (err) {
    console.error('Failed to persist auth session:', err);
  }
}

/** Clear the persisted session — used for logout. */
export function clearSession(): void {
  try {
    localStorage.removeItem('local-store');
  } catch {
    // ignore — quota / private mode
  }
}

// ---- Dashboard management (list / create / edit / delete / import / export)
//
// These back the React /dashboards-beta page. Mirrors the endpoints today's
// Dash management page consumes (see depictio/dash/layouts/dashboards_management.py).

/** Permissions block embedded in each dashboard list entry. Shapes match
 *  what the FastAPI `/dashboards/list` endpoint returns after Pydantic
 *  serialization — `_id` is a string here, not an ObjectId. */
export interface DashboardPermissionsUser {
  _id?: string;
  id?: string;
  email: string;
}
export interface DashboardPermissions {
  owners?: DashboardPermissionsUser[];
  viewers?: DashboardPermissionsUser[];
  editors?: DashboardPermissionsUser[];
}

/** Full dashboard list entry. Superset of `DashboardSummary` — the same
 *  list endpoint backs both the in-dashboard tab nav (which only needs the
 *  Summary fields) and the management page (which needs metadata + perms). */
export interface DashboardListEntry extends DashboardSummary {
  subtitle?: string;
  icon_variant?: string;
  is_public?: boolean;
  is_main_tab?: boolean;
  workflow_system?: string;
  last_saved_ts?: string;
  permissions?: DashboardPermissions;
  /** Some endpoints stamp this; matches the YAML/seed origin. */
  template_origin?: string;
  /** Shape can drift slightly per backend version — keep it permissive. */
  [key: string]: unknown;
}

export async function listDashboards(
  includeChildTabs = true,
): Promise<DashboardListEntry[]> {
  const res = await fetch(
    `${API_BASE}/dashboards/list?include_child_tabs=${includeChildTabs}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to list dashboards: ${res.status} ${text}`);
  }
  const data = await res.json();
  return Array.isArray(data) ? data : (data?.dashboards ?? []);
}

/** Full project entry — covers list + detail responses. The /projects/get/all
 *  and /projects/get/from_id endpoints both return this shape after Pydantic
 *  serialization (Project / ProjectResponse). Keep permissive — backend
 *  versions vary on which optional fields are stamped. */
export interface ProjectListEntry {
  _id?: string;
  id?: string;
  name: string;
  project_type?: 'basic' | 'advanced';
  is_public?: boolean;
  registration_time?: string;
  yaml_config_path?: string | null;
  data_management_platform_project_url?: string | null;
  permissions?: DashboardPermissions;
  workflows?: WorkflowEntry[];
  [key: string]: unknown;
}

export async function listProjects(): Promise<ProjectListEntry[]> {
  const res = await fetch(`${API_BASE}/projects/get/all`, {
    headers: authHeaders(),
  });
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/** Fetch one project by ID. The response includes embedded workflows + DCs
 *  and (when skip_enrichment=false, the default) a `delta_locations` map per
 *  data-collection. Mirrors the Dash `api_call_fetch_project_by_id` helper. */
export async function fetchProject(
  projectId: string,
  options: { skipEnrichment?: boolean } = {},
): Promise<{ project: ProjectListEntry; delta_locations: Record<string, string> }> {
  const params = new URLSearchParams({ project_id: projectId });
  if (options.skipEnrichment) params.set('skip_enrichment', 'true');
  const res = await fetch(`${API_BASE}/projects/get/from_id?${params}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to fetch project ${projectId}: ${res.status} ${text}`);
  }
  const data = await res.json();
  // skip_enrichment=true returns the project dict directly; the default
  // returns {project, delta_locations}. Normalize to the wrapped shape.
  if (data && typeof data === 'object' && 'project' in data) {
    return {
      project: data.project as ProjectListEntry,
      delta_locations: (data.delta_locations ?? {}) as Record<string, string>,
    };
  }
  return { project: data as ProjectListEntry, delta_locations: {} };
}

/** Fields the projects management Create-modal collects. The backend's
 *  POST /projects/create expects a full Project payload — `createProject`
 *  builds the rest from these inputs (current user as sole owner, empty
 *  workflows, etc.). */
export interface CreateProjectInput {
  name: string;
  project_type: 'basic' | 'advanced';
  is_public: boolean;
  data_collections?: string[];
  yaml_config_path?: string | null;
  data_management_platform_project_url?: string | null;
}

export interface CreateProjectResult {
  success: boolean;
  message: string;
  project_id?: string;
}

function generateProjectId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 24)
    : Math.random().toString(16).slice(2).padEnd(24, '0').slice(0, 24);
}

/** Create a project. Stamps `permissions.owners` with the current user;
 *  mirrors `api_call_create_project` in
 *  depictio/dash/layouts/api_calls.py:1185. */
export async function createProject(
  input: CreateProjectInput,
): Promise<CreateProjectResult> {
  const me = await fetchCurrentUser();
  if (!me?.id) {
    throw new Error('You must be signed in to create a project.');
  }
  const newId = generateProjectId();
  const ownerEntry = { _id: me.id, email: me.email, is_admin: me.is_admin };
  const payload: Record<string, unknown> = {
    _id: newId,
    name: input.name,
    project_type: input.project_type,
    is_public: input.is_public,
    yaml_config_path: input.yaml_config_path ?? null,
    data_management_platform_project_url:
      input.data_management_platform_project_url ?? null,
    permissions: { owners: [ownerEntry], editors: [], viewers: [] },
    workflows: [],
  };
  const res = await fetch(`${API_BASE}/projects/create`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to create project: ${res.status} ${text}`);
  }
  const result = (await res.json()) as CreateProjectResult;
  if (!result.success) throw new Error(result.message || 'Project creation failed');
  return { ...result, project_id: result.project_id ?? newId };
}

/** Fields editable via the Edit modal. Update-project endpoint accepts a
 *  full Project, so the caller fetches the existing project, merges these
 *  fields, and PUTs the merged document. */
export interface EditProjectInput {
  name?: string;
  is_public?: boolean;
  data_management_platform_project_url?: string | null;
}

/** Update a project. Fetches current project, merges editable fields, PUTs
 *  the full payload (the backend endpoint requires a complete Project body). */
export async function updateProject(
  projectId: string,
  input: EditProjectInput,
): Promise<void> {
  const { project } = await fetchProject(projectId, { skipEnrichment: true });
  const merged: Record<string, unknown> = { ...project, ...input };
  const res = await fetch(`${API_BASE}/projects/update`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify(merged),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to update project: ${res.status} ${text}`);
  }
}

/** Cascading delete: the backend removes S3 objects, delta tables, files,
 *  data collections, runs, MultiQC, JBrowse refs, AND child dashboards. */
export async function deleteProject(projectId: string): Promise<void> {
  const params = new URLSearchParams({ project_id: projectId });
  const res = await fetch(`${API_BASE}/projects/delete?${params}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to delete project: ${res.status} ${text}`);
  }
}

export async function toggleProjectVisibility(
  projectId: string,
  isPublic: boolean,
): Promise<void> {
  const params = new URLSearchParams({ is_public: isPublic ? 'true' : 'false' });
  const res = await fetch(
    `${API_BASE}/projects/toggle_public_private/${projectId}?${params}`,
    { method: 'POST', headers: authHeaders() },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to toggle project visibility: ${res.status} ${text}`);
  }
}

export interface ProjectPermissionsInput {
  project_id: string;
  permissions: {
    owners?: DashboardPermissionsUser[];
    editors?: DashboardPermissionsUser[];
    viewers?: DashboardPermissionsUser[];
  };
}

export async function updateProjectPermissions(
  input: ProjectPermissionsInput,
): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/update_project_permissions`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to update permissions: ${res.status} ${text}`);
  }
}

/** Upload a project .zip and create the project from its contents.
 *  ⚠️ Backend endpoint POST /projects/import does NOT exist yet — this client
 *  function is staged for when it lands. Until then, calls will 404. */
export async function importProjectZip(
  file: File,
  overwrite: boolean,
): Promise<{ success: boolean; project_id?: string; message: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const params = new URLSearchParams({ overwrite: overwrite ? 'true' : 'false' });
  // Build headers WITHOUT Content-Type — the browser stamps the multipart
  // boundary automatically when given a FormData body. Strip it from the
  // shared authHeaders() to avoid corrupting the multipart frame.
  const headers = { ...authHeaders() } as Record<string, string>;
  delete headers['Content-Type'];
  const res = await fetch(`${API_BASE}/projects/import?${params}`, {
    method: 'POST',
    headers,
    body: formData,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to import project: ${res.status} ${text}`);
  }
  return res.json();
}

/** Look up a user by email. Used by the permissions editor to convert an
 *  email entry into a `{_id, email, is_admin}` row before persisting. */
export async function fetchUserByEmail(email: string): Promise<{
  _id: string;
  id?: string;
  email: string;
  is_admin?: boolean;
} | null> {
  const params = new URLSearchParams({ email });
  const res = await fetch(`${API_BASE}/auth/fetch_user/from_email?${params}`, {
    headers: authHeaders(),
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`User lookup failed: ${res.status} ${text}`);
  }
  const data = await res.json();
  if (!data) return null;
  return {
    _id: (data._id ?? data.id) as string,
    id: data.id,
    email: data.email,
    is_admin: Boolean(data.is_admin),
  };
}

/** Export a project bundle as a ZIP. Backend returns binary content; we
 *  wrap it in a Blob and trigger a browser download. Mirrors the Dash
 *  flow at projects.py:2360 (`/migrate/export-project`). */
export async function exportProjectZip(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/migrate/export-project`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ project_id: projectId, mode: 'all' }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to export project: ${res.status} ${text}`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `depictio_export_${projectId}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** MultiQC report list response shape — used to render the DC viewer panel
 *  for multiqc-typed data collections. The backend stamps everything inside
 *  `report` (the embedded MultiQCReport doc) so callers should always read
 *  through that wrapper. */
export interface MultiQCReportSummary {
  report?: {
    id?: string;
    report_id?: string;
    report_name?: string;
    title?: string;
    creation_date?: string;
    processed_at?: string;
    multiqc_version?: string;
    s3_location?: string;
    original_file_path?: string;
    file_size_bytes?: number;
    /** Canonical metadata shape (after backend list response). Counts are
     *  not pre-computed — derive from the array/object lengths. */
    metadata?: {
      /** Raw sample tag list — can run into tens of thousands of entries
       *  for runs with adapter sub-samples. */
      samples?: string[];
      /** Deduplicated sample list — preferred for the "Samples" count. */
      canonical_samples?: string[];
      /** Module list — typically an object keyed by module index ("0", "1"
       *  …); occasionally an array. Use length-of-keys to count. */
      modules?: Record<string, unknown> | unknown[];
      /** Plot list — same shape variations as modules. */
      plots?: Record<string, unknown> | unknown[];
      sample_mappings?: Record<string, unknown>;
      [k: string]: unknown;
    };
    [k: string]: unknown;
  };
  data_collection_tag?: string;
  workflow_name?: string;
}

export interface MultiQCReportsList {
  reports: MultiQCReportSummary[];
  total_count: number;
}

export async function fetchMultiQCByDataCollection(
  dcId: string,
  limit = 50,
): Promise<MultiQCReportsList> {
  const res = await fetch(
    `${API_BASE}/multiqc/reports/data-collection/${dcId}?limit=${limit}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to fetch MultiQC reports: ${res.status} ${text}`);
  }
  return res.json();
}

/** Rename a data collection (changes data_collection_tag). */
export async function renameDataCollection(
  dcId: string,
  newTag: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/datacollections/${dcId}/name`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ new_name: newTag }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to rename data collection: ${res.status} ${text}`);
  }
}

/** Delete a data collection by ID. Cascades to files, delta tables, runs. */
export async function deleteDataCollection(dcId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/datacollections/${dcId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to delete data collection: ${res.status} ${text}`);
  }
}

/** Fields the management Create-modal collects. Matches the allowlist on
 *  POST /dashboards/save/{id} — we hand the rest of the payload defaults
 *  client-side so the user only fills what's interesting. */
export interface CreateDashboardInput {
  title: string;
  subtitle?: string;
  project_id: string;
  icon?: string;
  icon_color?: string;
}

/** Generate the same kind of 24-char hex string that `createTab` uses, so the
 *  shape stays identical regardless of which client path created the doc. */
function generateDashboardId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 24)
    : Math.random().toString(16).slice(2).padEnd(24, '0').slice(0, 24);
}

export async function createDashboard(input: CreateDashboardInput): Promise<string> {
  // The save endpoint requires `permissions.owners` to be set — stamp the
  // current user as the sole owner. Mirrors handle_dashboard_creation() in
  // depictio/dash/layouts/dashboards_management.py:2137-2150.
  const me = await fetchCurrentUser();
  if (!me?.id) {
    throw new Error('You must be signed in to create a dashboard.');
  }
  const newId = generateDashboardId();
  const ownerEntry = { _id: me.id, email: me.email, is_admin: me.is_admin };
  const payload: Record<string, unknown> = {
    dashboard_id: newId,
    version: 1,
    title: input.title,
    subtitle: input.subtitle ?? '',
    icon: input.icon || 'mdi:view-dashboard',
    icon_color: input.icon_color || 'orange',
    icon_variant: 'filled',
    workflow_system: 'none',
    notes_content: '',
    permissions: { owners: [ownerEntry], editors: [], viewers: [] },
    is_public: false,
    last_saved_ts: '',
    project_id: input.project_id,
    is_main_tab: true,
    tab_order: 0,
  };
  const res = await fetch(`${API_BASE}/dashboards/save/${newId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to create dashboard: ${res.status} ${text}`);
  }
  return newId;
}

/** Fields editable via POST /dashboards/edit/{id} — backend's `allowed_fields`
 *  is the source of truth (`routes.py:509`). */
export interface EditDashboardInput {
  title?: string;
  subtitle?: string;
  icon?: string;
  icon_color?: string;
  workflow_system?: string;
}

export async function editDashboard(
  dashboardId: string,
  input: EditDashboardInput,
): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/edit/${dashboardId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to edit dashboard: ${res.status} ${text}`);
  }
}

export async function deleteDashboard(dashboardId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/delete/${dashboardId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to delete dashboard: ${res.status} ${text}`);
  }
}

/** Duplicate a dashboard. Mirrors handle_dashboard_duplication() in
 *  depictio/dash/layouts/dashboards_management.py:2240-2289: fetch the source,
 *  rewrite id/title/permissions, save under a fresh id. Screenshot files are
 *  not copied — they'll regenerate the next time the new dashboard is viewed.
 */
export async function duplicateDashboard(sourceDashboardId: string): Promise<string> {
  const me = await fetchCurrentUser();
  if (!me?.id) {
    throw new Error('You must be signed in to duplicate a dashboard.');
  }
  const source = (await fetchDashboard(sourceDashboardId)) as Record<string, unknown>;
  const newId = generateDashboardId();
  const ownerEntry = { _id: me.id, email: me.email, is_admin: me.is_admin };

  const payload: Record<string, unknown> = {
    ...source,
    dashboard_id: newId,
    _id: newId,
    title: `${(source.title as string) || 'Untitled'} (copy)`,
    permissions: { owners: [ownerEntry], editors: [], viewers: [] },
    is_public: false,
    is_main_tab: true,
    parent_dashboard_id: null,
    tab_order: 0,
    last_saved_ts: '',
  };

  const res = await fetch(`${API_BASE}/dashboards/save/${newId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to duplicate dashboard: ${res.status} ${text}`);
  }
  return newId;
}

export interface ImportDashboardOptions {
  projectId?: string;
  validateIntegrity?: boolean;
}

export interface ImportDashboardResult {
  success?: boolean;
  dashboard_id?: string;
  message?: string;
  warnings?: unknown[];
  [key: string]: unknown;
}

/** Import a JSON export file. The backend resolves the project via the
 *  embedded `_export_source.project_tag` if `projectId` is omitted. */
export async function importDashboardJson(
  jsonContent: Record<string, unknown>,
  opts: ImportDashboardOptions = {},
): Promise<ImportDashboardResult> {
  const params = new URLSearchParams();
  if (opts.projectId) params.set('project_id', opts.projectId);
  if (opts.validateIntegrity !== undefined) {
    params.set('validate_integrity', String(opts.validateIntegrity));
  }
  const qs = params.toString();
  const res = await fetch(
    `${API_BASE}/dashboards/import/json${qs ? `?${qs}` : ''}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(jsonContent),
    },
  );
  if (!res.ok) {
    let detail = `Failed to import dashboard: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // ignore non-JSON
    }
    throw new Error(detail);
  }
  return res.json();
}

/** YAML import accepts a text body (media type `text/plain`). */
export async function importDashboardYaml(
  yamlContent: string,
  opts: { projectId?: string; overwrite?: boolean } = {},
): Promise<ImportDashboardResult> {
  const params = new URLSearchParams();
  if (opts.projectId) params.set('project_id', opts.projectId);
  if (opts.overwrite !== undefined) params.set('overwrite', String(opts.overwrite));
  const qs = params.toString();
  const headers: Record<string, string> = { ...authHeaders(), 'Content-Type': 'text/plain' };
  const res = await fetch(
    `${API_BASE}/dashboards/import/yaml${qs ? `?${qs}` : ''}`,
    { method: 'POST', headers, body: yamlContent },
  );
  if (!res.ok) {
    let detail = `Failed to import YAML dashboard: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // ignore non-JSON
    }
    throw new Error(detail);
  }
  return res.json();
}

/** Validate a JSON export before importing — surfaces structural problems
 *  to the user without committing the import. */
export async function validateDashboardJson(
  jsonContent: Record<string, unknown>,
): Promise<{ valid: boolean; errors?: unknown[] }> {
  const res = await fetch(`${API_BASE}/dashboards/json/validate`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(jsonContent),
  });
  if (!res.ok) return { valid: false, errors: [`HTTP ${res.status}`] };
  return res.json();
}

/** Trigger a JSON export. Caller is responsible for saving the response to disk. */
export async function exportDashboardJson(
  dashboardId: string,
): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/dashboards/${dashboardId}/json`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to export dashboard: ${res.status} ${text}`);
  }
  return res.json();
}

// ---- Admin (system-wide) helpers ----------------------------------------
//
// These back the React /admin-beta page. Backend already enforces `is_admin`
// on every endpoint; the SPA just renders them when the current user passes
// the same check. Mirrors the calls in `depictio/dash/layouts/admin_management.py`.

/** Subset of `UserBaseUI` we care about in the admin Users tab. Keep it
 *  permissive — extra fields from the backend pass through. */
export interface AdminUser {
  id?: string;
  _id?: string;
  email: string;
  is_admin: boolean;
  is_active?: boolean;
  is_verified?: boolean;
  registration_date?: string | null;
  last_login?: string | null;
  [key: string]: unknown;
}

export async function listAllUsers(): Promise<AdminUser[]> {
  const res = await fetch(`${API_BASE}/auth/list`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to list users: ${res.status} ${text}`);
  }
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function deleteUser(userId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/delete/${userId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to delete user: ${res.status} ${text}`);
  }
}

/** Toggle the `is_admin` flag on a user. The backend's path takes the new
 *  value as a literal segment ("True"/"False" — `eval()` over the string in
 *  the Dash callback). We send the Python-style capitalized form for parity. */
export async function setUserAdmin(userId: string, isAdmin: boolean): Promise<void> {
  const flag = isAdmin ? 'True' : 'False';
  const res = await fetch(
    `${API_BASE}/auth/turn_sysadmin/${userId}/${flag}`,
    { method: 'POST', headers: authHeaders() },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to update admin status: ${res.status} ${text}`);
  }
}

/** Admin variant of project listing — same endpoint as `listProjects()` but
 *  semantically distinct (admins see *all* projects, not just their own).
 *  Kept as a separate function to keep call sites readable. */
export interface AdminProject {
  _id?: string;
  id?: string;
  name: string;
  description?: string;
  is_public?: boolean;
  workflow_system?: string;
  permissions?: DashboardPermissions;
  [key: string]: unknown;
}

export async function listAllProjects(): Promise<AdminProject[]> {
  const res = await fetch(`${API_BASE}/projects/get/all`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to list all projects: ${res.status} ${text}`);
  }
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/** Subset of `DashboardData` we care about in the admin Dashboards tab. */
export interface AdminDashboard {
  _id?: string;
  dashboard_id: string;
  title?: string;
  is_public?: boolean;
  last_saved_ts?: string;
  permissions?: DashboardPermissions;
  stored_metadata?: unknown[];
  [key: string]: unknown;
}

export async function listAllDashboards(): Promise<AdminDashboard[]> {
  const res = await fetch(`${API_BASE}/dashboards/list_all`, { headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to list all dashboards: ${res.status} ${text}`);
  }
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

// ---- Profile + CLI token management (/profile-beta, /cli-agents-beta) -----
//
// These wrap the FastAPI endpoints used by the React profile and CLI agents
// pages. Token create/delete go through bearer-authed `/auth/me/tokens`
// rather than the api-key-gated `/auth/create_token` and `/auth/delete_token`,
// since the browser cannot safely hold the internal API key.

/** Full user record returned by the strict `/auth/me` endpoint. Has the
 *  metadata fields (registration_date, last_login, is_anonymous, is_temporary)
 *  that the profile page renders — `useCurrentUser` only carries a slim
 *  subset for the chrome badge. */
export interface ProfileUser {
  id: string;
  email: string;
  is_admin: boolean;
  is_anonymous: boolean;
  is_temporary: boolean;
  registration_date?: string | null;
  last_login?: string | null;
}

export async function fetchCurrentUserFull(): Promise<ProfileUser | null> {
  const res = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() });
  if (!res.ok) return null;
  const data = (await res.json()) as Record<string, unknown>;
  if (!data || typeof data.email !== 'string') return null;
  return {
    id: String(data.id ?? data._id ?? ''),
    email: data.email,
    is_admin: Boolean(data.is_admin),
    is_anonymous: Boolean(data.is_anonymous),
    is_temporary: Boolean(data.is_temporary),
    registration_date: (data.registration_date as string | null | undefined) ?? null,
    last_login: (data.last_login as string | null | undefined) ?? null,
  };
}

/** Change the current user's password. The backend validates the old password
 *  server-side and rejects equal old/new. Throws Error(<detail>) on non-200
 *  so the caller can surface the message verbatim. */
export async function editPassword(oldPassword: string, newPassword: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/edit_password`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    let detail = `Password update failed: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON
    }
    throw new Error(detail);
  }
}

/** A long-lived CLI token entry — the management page only renders these
 *  metadata fields (the access_token plaintext is shown only once at
 *  creation in DisplayTokenModal). */
export interface CliToken {
  _id: string;
  name: string | null;
  expire_datetime: string;
  token_lifetime: string;
  user_id: string;
}

export async function listLongLivedTokens(): Promise<CliToken[]> {
  const params = new URLSearchParams({ token_lifetime: 'long-lived' });
  const res = await fetch(`${API_BASE}/auth/list_tokens?${params.toString()}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to list tokens: ${res.status} ${text}`);
  }
  const data = await res.json();
  if (!Array.isArray(data)) return [];
  return data.map((t: Record<string, unknown>) => ({
    _id: String(t._id ?? t.id ?? ''),
    name: (t.name as string | null | undefined) ?? null,
    expire_datetime: String(t.expire_datetime ?? ''),
    token_lifetime: String(t.token_lifetime ?? ''),
    user_id: String(t.user_id ?? ''),
  }));
}

/** Created-token payload: includes the plaintext access_token + refresh_token
 *  (only ever returned at creation time). The CLI agents page feeds this
 *  straight into `generateAgentConfig` to render the YAML config. */
export interface CreatedToken {
  _id: string;
  user_id: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  token_lifetime: string;
  expire_datetime: string;
  refresh_expire_datetime: string;
  name: string | null;
}

export async function createLongLivedToken(name: string): Promise<CreatedToken> {
  const res = await fetch(`${API_BASE}/auth/me/tokens`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    let detail = `Failed to create token: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON
    }
    throw new Error(detail);
  }
  const t = (await res.json()) as Record<string, unknown>;
  return {
    _id: String(t._id ?? t.id ?? ''),
    user_id: String(t.user_id ?? ''),
    access_token: String(t.access_token ?? ''),
    refresh_token: String(t.refresh_token ?? ''),
    token_type: String(t.token_type ?? 'bearer'),
    token_lifetime: String(t.token_lifetime ?? 'long-lived'),
    expire_datetime: String(t.expire_datetime ?? ''),
    refresh_expire_datetime: String(t.refresh_expire_datetime ?? ''),
    name: (t.name as string | null | undefined) ?? null,
  };
}

export async function deleteLongLivedToken(tokenId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/me/tokens/${encodeURIComponent(tokenId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) {
    let detail = `Failed to delete token: ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      // ignore non-JSON
    }
    throw new Error(detail);
  }
}

/** CLI YAML config returned by `/auth/generate_agent_config`. Shape mirrors
 *  the Pydantic `CLIConfig` model — opaque to this layer; the modal just
 *  yaml-dumps it for display. */
export type CliAgentConfig = Record<string, unknown>;

export async function generateAgentConfig(token: CreatedToken): Promise<CliAgentConfig> {
  const res = await fetch(`${API_BASE}/auth/generate_agent_config`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      user_id: token.user_id,
      access_token: token.access_token,
      refresh_token: token.refresh_token,
      token_type: token.token_type,
      token_lifetime: token.token_lifetime,
      expire_datetime: token.expire_datetime,
      refresh_expire_datetime: token.refresh_expire_datetime,
      name: token.name,
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Failed to generate CLI config: ${res.status} ${text}`);
  }
  return (await res.json()) as CliAgentConfig;
}

/** Upgrade an anonymous user (in unauthenticated mode) to a temporary user.
 *  Returns a fresh session payload that the caller persists to localStorage
 *  and then reloads the page so the rest of the SPA picks up the new token.
 *  Returns `null` when already temporary or when the mode disallows upgrade. */
export async function upgradeToTemporaryUser(expiryHours = 24): Promise<SessionPayload | null> {
  const params = new URLSearchParams({ expiry_hours: String(expiryHours) });
  const res = await fetch(`${API_BASE}/auth/upgrade_to_temporary_user?${params.toString()}`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (res.status === 400) return null; // already temporary
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Upgrade failed: ${res.status} ${text}`);
  }
  return (await res.json()) as SessionPayload;
}
