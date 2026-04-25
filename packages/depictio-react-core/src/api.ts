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

export async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const res = await fetch(`${API_BASE}/auth/me/optional`, { headers: authHeaders() });
  if (!res.ok) return null;
  const data = (await res.json()) as { id?: string; email?: string; is_admin?: boolean } | null;
  if (!data || !data.email) return null;
  return { id: data.id, email: data.email, is_admin: Boolean(data.is_admin) };
}
