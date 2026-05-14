/**
 * Thin fetch wrapper for Depictio's FastAPI backend. Preserves the same auth
 * contract as the Dash app: JWT bearer token from localStorage, with a public
 * fallback that relies on get_user_or_anonymous middleware for anonymous mode.
 */

const API_BASE = '/depictio/api/v1';

/** localStorage key shared with the Dash app — same payload shape. */
const SESSION_KEY = 'local-store';

/** Refresh proactively when the access token has less than this many ms left.
 *  Chosen to comfortably cover the 60–120 ms latency of the round-trip plus
 *  the 1 h access-token lifetime upstream — i.e. a single page session never
 *  surfaces an unexpected 401 from clock drift. */
const REFRESH_WINDOW_MS = 60_000;

function readStoredSession(): Record<string, unknown> | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const session = readStoredSession();
  const token = session?.access_token;
  if (typeof token === 'string' && token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

/** Send the user back to the login page when their session can no longer be
 *  refreshed. Skipped if we're already on /auth so we don't loop the redirect
 *  while the login page itself is loading. */
function redirectToAuth(): void {
  if (typeof window === 'undefined') return;
  if (window.location.pathname.startsWith('/auth')) return;
  window.location.replace('/auth');
}

/** Trade a refresh token for a new access token via the public `/auth/refresh`
 *  endpoint (no api-key required — the refresh token is itself the credential).
 *  Mirrors the Dash-side ``refresh_access_token`` helper.
 *
 *  Returns the updated access_token + expire_datetime, or null on failure
 *  (expired / invalidated refresh token, server error, etc.). */
async function refreshAccessToken(refreshToken: string): Promise<{
  access_token: string;
  expire_datetime: string;
} | null> {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { access_token: string; expire_datetime: string };
    return body;
  } catch {
    return null;
  }
}

/** In-flight refresh promise — multiple parallel ``authFetch`` callers share
 *  one refresh round-trip so we don't fire N refreshes at once on a stale
 *  cache. Reset to null when the refresh resolves. */
let pendingRefresh: Promise<string | null> | null = null;

async function ensureFreshAccessToken(): Promise<string | null> {
  const session = readStoredSession();
  const access = typeof session?.access_token === 'string' ? session.access_token : null;
  const refresh = typeof session?.refresh_token === 'string' ? session.refresh_token : null;
  const expireIso = typeof session?.expire_datetime === 'string' ? session.expire_datetime : null;

  if (!access || !refresh) return access;

  const expireMs = expireIso ? Date.parse(expireIso) : NaN;
  if (Number.isFinite(expireMs) && expireMs - Date.now() > REFRESH_WINDOW_MS) {
    return access;
  }

  if (!pendingRefresh) {
    pendingRefresh = (async () => {
      try {
        const refreshed = await refreshAccessToken(refresh);
        if (!refreshed) return null;
        const next = { ...session, ...refreshed };
        try {
          localStorage.setItem(SESSION_KEY, JSON.stringify(next));
        } catch {
          // ignore quota / private mode
        }
        return refreshed.access_token;
      } finally {
        pendingRefresh = null;
      }
    })();
  }
  const next = await pendingRefresh;
  return next ?? access;
}

/**
 * Fetch wrapper that injects the Bearer token, proactively refreshes the
 * access token when it's near expiry, and on a 401 retries once with a freshly
 * minted access token. After persistent 401s the session is cleared so the
 * SPA falls back to the unauthenticated path on the next route resolution.
 */
async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  await ensureFreshAccessToken();

  const headers = new Headers(init.headers || {});
  if (!headers.has('Content-Type') && init.body && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }
  const existing = readStoredSession();
  const token = typeof existing?.access_token === 'string' ? existing.access_token : null;
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const first = await fetch(url, { ...init, headers });
  if (first.status !== 401) return first;

  // Single retry: force a refresh, then re-issue.
  const refresh = typeof existing?.refresh_token === 'string' ? existing.refresh_token : null;
  if (!refresh) {
    redirectToAuth();
    return first;
  }
  const refreshed = await refreshAccessToken(refresh);
  if (!refreshed) {
    clearSession();
    redirectToAuth();
    return first;
  }
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({ ...existing, ...refreshed }));
  } catch {
    // ignore
  }
  const retryHeaders = new Headers(init.headers || {});
  retryHeaders.set('Authorization', `Bearer ${refreshed.access_token}`);
  if (!retryHeaders.has('Content-Type') && init.body && typeof init.body === 'string') {
    retryHeaders.set('Content-Type', 'application/json');
  }
  return fetch(url, { ...init, headers: retryHeaders });
}

/** Throw `Error("<prefix>: <status> <body-text>")` after reading the body as
 *  text. Used for the bulk of endpoints whose error envelope is irrelevant. */
async function throwHttpError(res: Response, prefix: string): Promise<never> {
  const text = await res.text().catch(() => '');
  throw new Error(`${prefix}: ${res.status} ${text}`.trimEnd());
}

/** Throw using FastAPI's `{detail}` envelope when present, otherwise fall back
 *  to `<fallback-or-prefix>: <status>`. Both single-string and JSON `detail`
 *  bodies are surfaced (the latter stringified). */
async function throwHttpDetailError(
  res: Response,
  prefix: string,
): Promise<never> {
  let message = `${prefix}: ${res.status}`;
  try {
    const body = await res.json();
    if (body?.detail) {
      message =
        typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    }
  } catch {
    // ignore non-JSON error bodies
  }
  throw new Error(message);
}

/** 24-char hex id matching MongoDB ObjectId shape. Mirrors the format used by
 *  `bson.ObjectId()` server-side so client-generated ids round-trip cleanly. */
function generateObjectId(): string {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 24)
    : Math.random().toString(16).slice(2).padEnd(24, '0').slice(0, 24);
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
  /** Visual grouping — interactive components sharing the same `group` are
   *  rendered together inside one Mantine Paper. Up to 3 per group. */
  group?: string;
  /** Layout placement: 'left' (default — Filters sidebar) or 'top' (top panel
   *  above the dashboard grid). Currently only 'Timeline' may use 'top'. */
  placement?: 'left' | 'top';
  /** Default timescale for the Timeline interactive component. */
  timescale?: 'year' | 'month' | 'day' | 'hour' | 'minute';
  /** When set, controls tick-mark visibility on Slider / RangeSlider / Timeline.
   *  When omitted, the renderer defaults to visible for ungrouped components and
   *  hidden for components inside a group (compact mode). */
  show_marks?: boolean;
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
  /** Project-level realtime config — only when ``enabled === true`` should
   *  the viewer mount the WebSocket subscription / live-updates indicator. */
  project_realtime?: { enabled: boolean; debounce_ms: number };
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
 *
 *  When `filterExpr` is provided, the server pre-filters the underlying data
 *  with the supplied Polars expression so the returned options reflect only
 *  the rows matching that scope.
 */
export async function fetchUniqueValues(
  dcId: string,
  columnName: string,
  filterExpr?: string | null,
): Promise<string[]> {
  const params = new URLSearchParams({ column: columnName });
  if (filterExpr) params.set('filter_expr', filterExpr);
  const res = await fetch(
    `${API_BASE}/deltatables/unique_values/${dcId}?${params.toString()}`,
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

/** Discriminator for filters produced by selection events on a chart/table/map.
 *  Regular interactive components (MultiSelect, Slider, …) leave `source`
 *  unset so the backend treats them like normal filters.
 */
export type InteractiveFilterSource =
  | 'scatter_selection'
  | 'table_selection'
  | 'map_selection'
  | 'image_selection';

/** Per-component computed data (current value under the given filter state).
 *  `metadata.dc_id` is required for cross-DC link resolution server-side; any
 *  filter without it is treated as global. The optional `source` tags filters
 *  emitted by chart/table/map selection so passive components can merge them
 *  separately from regular interactive controls.
 */
export interface InteractiveFilter {
  index: string;
  value: unknown;
  column_name?: string;
  interactive_component_type?: string;
  source?: InteractiveFilterSource;
  /** Optional Polars filter expression carried with the user-supplied value.
   *  When set, the server ANDs it onto the value-based filter so the source's
   *  row scoping (e.g. `col('depth') >= 30`) propagates to downstream cards/
   *  figures/tables. */
  filter_expr?: string;
  metadata?: {
    dc_id?: string;
    column_name?: string;
    interactive_component_type?: string;
    selection_column?: string;
    filter_expr?: string;
  };
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
 * Returns { values, secondary_values, aggregations, filter_applied, filter_count }.
 *  - `values` — hero scalar per component (existing behavior).
 *  - `secondary_values` — populated for cards that declare `aggregations`;
 *     map of componentId → { aggregationName: value }.
 *  - `aggregations` — ordered list of secondary aggregation names per component
 *     so the renderer can preserve the YAML order.
 */
export interface BulkComputeResponse {
  values: Record<string, unknown>;
  secondary_values?: Record<string, Record<string, unknown>>;
  aggregations?: Record<string, string[]>;
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
  /** Column the server actually sorted by (or null if unsorted). */
  sort_by?: string | null;
  /** Effective sort direction. */
  sort_dir?: 'asc' | 'desc';
}

export async function renderTable(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  start = 0,
  limit = 100,
  sortBy?: string | null,
  sortDir: 'asc' | 'desc' = 'desc',
): Promise<TableResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_table/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        filters,
        start,
        limit,
        sort_by: sortBy ?? null,
        sort_dir: sortDir,
      }),
    },
  );
  if (!res.ok) throw new Error(`Failed to render table: ${res.status}`);
  return res.json();
}

/** Fetch up to `max` non-null values of an image component's image_column.
 *  Filters narrow the grid the same way they narrow figures/tables —
 *  including selection-source filters and cross-DC link filters resolved
 *  server-side. ``sortBy``/``sortDir`` map onto the body of the same name —
 *  when ``sortBy`` is omitted the server picks an ``acquisition*`` column
 *  if one exists.
 */
export interface ImageGridResponse {
  /** One row per image; keys are the underlying DC's column names. */
  rows: Record<string, unknown>[];
  /** The component's image_column (so renderers can read the right field). */
  image_column: string;
  /** The column the server actually sorted by (or null). */
  sort_by: string | null;
  /** Effective sort direction. */
  sort_dir: 'asc' | 'desc';
  /** Every column on the underlying DC — for client-side sort dropdown options. */
  sortable_columns: string[];
  /** Bare path list — preserved for older callers. */
  paths: string[];
  filter_applied: boolean;
  filter_count: number;
}

export async function fetchImagePaths(
  dashboardId: string,
  componentId: string,
  max = 50,
  filters: InteractiveFilter[] = [],
  sortBy?: string | null,
  sortDir: 'asc' | 'desc' = 'desc',
): Promise<ImageGridResponse> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_image_paths/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, max, sort_by: sortBy ?? null, sort_dir: sortDir }),
    },
  );
  if (!res.ok) throw new Error(`Failed to fetch image paths: ${res.status}`);
  return (await res.json()) as ImageGridResponse;
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
  if (!res.ok) await throwHttpDetailError(res, 'Failed to render JBrowse');
  return res.json();
}

/** Backend signals "figure cache is being warmed" via HTTP 202. The viewer
 *  should show a skeleton + progress and poll until the figure is ready. */
export interface MultiQCPreparingResponse {
  status: 'preparing';
  dc_id: string;
  component_id: string;
  message: string;
}

export type MultiQCRenderResult =
  | (FigureResponse & { status: 'ready' })
  | MultiQCPreparingResponse;

/** Server-rendered MultiQC Plotly figure (wraps create_multiqc_plot).
 *
 *  Returns a discriminated union: ``status: 'ready'`` when the figure is
 *  available, ``status: 'preparing'`` when the backend is rebuilding caches
 *  (HTTP 202). Callers should re-issue the request after a short delay on
 *  ``preparing``. */
export async function renderMultiQC(
  dashboardId: string,
  componentId: string,
  filters: InteractiveFilter[],
  theme: 'light' | 'dark' = 'light',
): Promise<MultiQCRenderResult> {
  const res = await fetch(
    `${API_BASE}/dashboards/render_multiqc/${dashboardId}/${componentId}`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ filters, theme }),
    },
  );
  if (res.status === 202) {
    const body = (await res.json()) as MultiQCPreparingResponse;
    return { ...body, status: 'preparing' };
  }
  if (!res.ok) await throwHttpDetailError(res, 'Failed to render MultiQC');
  const body = (await res.json()) as FigureResponse;
  return { ...body, status: 'ready' };
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
  if (!res.ok) await throwHttpDetailError(res, 'Failed to render MultiQC General Stats');
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
  if (!res.ok) await throwHttpError(res, 'Failed to update tab');
}

export async function deleteTab(dashboardId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/tab/${dashboardId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to delete tab');
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
  if (!res.ok) await throwHttpError(res, 'Failed to reorder tabs');
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

  const newId = generateObjectId();

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
  if (!res.ok) await throwHttpError(res, 'Failed to create tab');
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
  if (!res.ok) await throwHttpDetailError(res, 'Preview failed');
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
  if (!res.ok) await throwHttpDetailError(res, 'MultiQC preview failed');
  return res.json();
}

/** Cascading module → plot → dataset options for a MultiQC DC.
 *  Mirrors GET /api/v1/multiqc/builder_options — the same shape consumed by
 *  the Component Designer's MultiQCBuilder, lifted here for reuse by the
 *  Project Data Manager's inline DC viewer preview. */
export interface MultiQCBuilderOptions {
  modules: string[];
  plots: Record<string, string[]>;
  datasets: Record<string, string[]>;
  s3_locations: string[];
  general_stats?: Array<{ module: string; plot: string }>;
}

export async function fetchMultiQCBuilderOptions(
  dcId: string,
): Promise<MultiQCBuilderOptions> {
  const res = await fetch(
    `${API_BASE}/multiqc/builder_options?data_collection_id=${dcId}`,
    { headers: authHeaders() },
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch MultiQC options: ${res.status}`);
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
  if (!res.ok) await throwHttpDetailError(res, 'Parameter discovery failed');
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
  if (!res.ok) await throwHttpDetailError(res, 'Visualization list failed');
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
  if (!res.ok) await throwHttpError(res, 'Failed to save component');
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
  if (!res.ok) await throwHttpError(res, 'Login failed');
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
  if (!res.ok) await throwHttpError(res, 'Failed to create temporary user');
  return (await res.json()) as SessionPayload;
}

/** Single-user / public-mode anonymous session for auto-redirects. */
export async function getAnonymousSession(): Promise<SessionPayload> {
  const res = await fetch(`${API_BASE}/auth/public/get_anonymous_user_session`);
  if (!res.ok) await throwHttpError(res, 'Failed to fetch anonymous session');
  return (await res.json()) as SessionPayload;
}

/** Initiate Google OAuth — caller redirects to the returned authorization_url. */
export async function startGoogleOAuth(): Promise<{ authorization_url: string; state: string }> {
  const res = await fetch(`${API_BASE}/auth/google/login`);
  if (!res.ok) await throwHttpError(res, 'Failed to start Google OAuth');
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
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch (err) {
    console.error('Failed to persist auth session:', err);
  }
}

/** Clear the persisted session — used for logout. */
export function clearSession(): void {
  try {
    localStorage.removeItem(SESSION_KEY);
  } catch {
    // ignore — quota / private mode
  }
}

/** Proactively refresh the access token if it's within ``REFRESH_WINDOW_MS``
 *  of expiring. Safe to call at SPA boot or before mounting the auth UI.
 *  Returns true if the session is still valid (or successfully refreshed),
 *  false if there is no session at all. Does NOT raise on refresh failure —
 *  callers can fall back to the unauthenticated path. */
export async function validateSession(): Promise<boolean> {
  const session = readStoredSession();
  if (!session?.access_token) return false;
  await ensureFreshAccessToken();
  return readStoredSession()?.access_token != null;
}

export { authFetch, refreshAccessToken };

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
  if (!res.ok) await throwHttpError(res, 'Failed to list dashboards');
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
  if (!res.ok) await throwHttpError(res, `Failed to fetch project ${projectId}`);
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
  const newId = generateObjectId();
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
  if (!res.ok) await throwHttpError(res, 'Failed to create project');
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
  if (!res.ok) await throwHttpError(res, 'Failed to update project');
}

/** Cascading delete: the backend removes S3 objects, delta tables, files,
 *  data collections, runs, MultiQC, JBrowse refs, AND child dashboards. */
export async function deleteProject(projectId: string): Promise<void> {
  const params = new URLSearchParams({ project_id: projectId });
  const res = await fetch(`${API_BASE}/projects/delete?${params}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to delete project');
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
  if (!res.ok) await throwHttpError(res, 'Failed to toggle project visibility');
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
  if (!res.ok) await throwHttpError(res, 'Failed to update permissions');
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
  if (!res.ok) await throwHttpError(res, 'Failed to import project');
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
  if (!res.ok) await throwHttpError(res, 'User lookup failed');
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
  if (!res.ok) await throwHttpError(res, 'Failed to export project');
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
  if (!res.ok) await throwHttpError(res, 'Failed to fetch MultiQC reports');
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
  if (!res.ok) await throwHttpError(res, 'Failed to rename data collection');
}

/** Delete a data collection by ID. Cascades to files, delta tables, runs. */
export async function deleteDataCollection(dcId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/datacollections/${dcId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to delete data collection');
}

export interface CreateDataCollectionUploadInput {
  projectId: string;
  name: string;
  description?: string;
  dataType?: string;
  fileFormat: string;
  separator: string;
  customSeparator?: string | null;
  compression: string;
  hasHeader: boolean;
  file: File;
  // When both are set, the resulting DC is created with a
  // DCTableCoordinatesConfig payload so Map components can bind to it.
  latColumn?: string | null;
  lonColumn?: string | null;
}

export interface CreateDataCollectionResult {
  success: boolean;
  message?: string;
  data_collection_id?: string;
  workflow_id?: string;
}

/** Upload a file and create a data collection. Wraps the same scan + process
 *  pipeline as `depictio-cli`, but exposed as a single multipart endpoint. */
export async function createDataCollectionFromUpload(
  input: CreateDataCollectionUploadInput,
): Promise<CreateDataCollectionResult> {
  const fd = new FormData();
  fd.append('project_id', input.projectId);
  fd.append('name', input.name);
  fd.append('description', input.description ?? '');
  fd.append('data_type', input.dataType ?? 'table');
  fd.append('file_format', input.fileFormat);
  fd.append('separator', input.separator);
  if (input.customSeparator) fd.append('custom_separator', input.customSeparator);
  fd.append('compression', input.compression);
  fd.append('has_header', input.hasHeader ? 'true' : 'false');
  if (input.latColumn) fd.append('lat_column', input.latColumn);
  if (input.lonColumn) fd.append('lon_column', input.lonColumn);
  fd.append('file', input.file, input.file.name);

  // Strip Content-Type so the browser sets the multipart boundary itself.
  const headers = authHeaders();
  delete headers['Content-Type'];

  const res = await fetch(`${API_BASE}/datacollections/create_from_upload`, {
    method: 'POST',
    headers,
    body: fd,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.message ?? '';
    } catch {
      detail = await res.text().catch(() => '');
    }
    throw new Error(detail || `Upload failed: ${res.status}`);
  }
  return res.json();
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

export async function createDashboard(input: CreateDashboardInput): Promise<string> {
  // The save endpoint requires `permissions.owners` to be set — stamp the
  // current user as the sole owner. Mirrors handle_dashboard_creation() in
  // depictio/dash/layouts/dashboards_management.py:2137-2150.
  const me = await fetchCurrentUser();
  if (!me?.id) {
    throw new Error('You must be signed in to create a dashboard.');
  }
  const newId = generateObjectId();
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
  if (!res.ok) await throwHttpError(res, 'Failed to create dashboard');
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
  if (!res.ok) await throwHttpError(res, 'Failed to edit dashboard');
}

export async function deleteDashboard(dashboardId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/dashboards/delete/${dashboardId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to delete dashboard');
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
  const newId = generateObjectId();
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
  if (!res.ok) await throwHttpError(res, 'Failed to duplicate dashboard');
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
  if (!res.ok) await throwHttpDetailError(res, 'Failed to import dashboard');
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
  if (!res.ok) await throwHttpDetailError(res, 'Failed to import YAML dashboard');
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
  if (!res.ok) await throwHttpError(res, 'Failed to export dashboard');
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
  if (!res.ok) await throwHttpError(res, 'Failed to list users');
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function deleteUser(userId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/delete/${userId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to delete user');
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
  if (!res.ok) await throwHttpError(res, 'Failed to update admin status');
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
  if (!res.ok) await throwHttpError(res, 'Failed to list all projects');
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
  if (!res.ok) await throwHttpError(res, 'Failed to list all dashboards');
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/** A seed project currently present in Mongo — minimal shape for the
 *  Maintenance tab's status row. */
export interface ExampleProject {
  id: string;
  name: string;
}

export async function listExampleProjects(): Promise<ExampleProject[]> {
  const res = await fetch(`${API_BASE}/projects/admin/examples`, { headers: authHeaders() });
  if (!res.ok) await throwHttpError(res, 'Failed to list example projects');
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function cleanExampleProjects(): Promise<{ deleted: ExampleProject[] }> {
  const res = await fetch(`${API_BASE}/projects/admin/clean_examples`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to clean example projects');
  const data = await res.json();
  const deleted = Array.isArray(data?.deleted) ? (data.deleted as ExampleProject[]) : [];
  return { deleted };
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
  if (!res.ok) await throwHttpDetailError(res, 'Password update failed');
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
  if (!res.ok) await throwHttpError(res, 'Failed to list tokens');
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
  if (!res.ok) await throwHttpDetailError(res, 'Failed to create token');
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
  if (!res.ok) await throwHttpDetailError(res, 'Failed to delete token');
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
  if (!res.ok) await throwHttpError(res, 'Failed to generate CLI config');
  return (await res.json()) as CliAgentConfig;
}

// =============================================================================
// Cross-DC links (project-level link CRUD + resolver list)
// =============================================================================

/** Resolver kinds the backend supports. Mirrors
 *  `depictio.api.v1.endpoints.links_endpoints.resolvers`. */
export type LinkResolverName =
  | 'direct'
  | 'sample_mapping'
  | 'pattern'
  | 'regex'
  | 'wildcard';

export interface DCLinkConfig {
  resolver: LinkResolverName;
  /** Canonical → variant map for ``sample_mapping``. */
  mappings?: Record<string, string[]>;
  /** Template like ``{sample}.bam`` for ``pattern``. */
  pattern?: string;
  /** Field in the target DC that the resolved values should match. */
  target_field?: string;
  case_sensitive?: boolean;
}

export type LinkTargetType = 'table' | 'multiqc' | 'image';

export interface DCLink {
  id: string;
  source_dc_id: string;
  source_column: string;
  target_dc_id: string;
  target_type: LinkTargetType;
  link_config: DCLinkConfig;
  description?: string | null;
  enabled: boolean;
}

export interface CreateLinkInput {
  source_dc_id: string;
  source_column: string;
  target_dc_id: string;
  target_type: LinkTargetType;
  link_config?: DCLinkConfig;
  description?: string;
  enabled?: boolean;
}

export type UpdateLinkInput = Partial<CreateLinkInput>;

export interface ResolverInfo {
  name: LinkResolverName;
  label: string;
  description: string;
}

export async function listProjectLinks(projectId: string): Promise<DCLink[]> {
  // Use authFetch (not raw fetch + authHeaders) so a stale access_token gets
  // silently refreshed and retried instead of bubbling up as a 401 "Invalid
  // token". The links endpoint uses strict get_current_user — there's no
  // anonymous fallback to recover from a bad header.
  const res = await authFetch(`${API_BASE}/links/${projectId}`);
  if (!res.ok) await throwHttpError(res, 'Failed to list project links');
  const body = await res.json();
  // Backend returns either {links: [...]} or [...]; accept both.
  if (Array.isArray(body)) return body as DCLink[];
  return (body?.links ?? []) as DCLink[];
}

export async function createProjectLink(
  projectId: string,
  input: CreateLinkInput,
): Promise<DCLink> {
  const res = await authFetch(`${API_BASE}/links/${projectId}`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
  if (!res.ok) await throwHttpDetailError(res, 'Failed to create link');
  return (await res.json()) as DCLink;
}

export async function updateProjectLink(
  projectId: string,
  linkId: string,
  input: UpdateLinkInput,
): Promise<DCLink> {
  const res = await authFetch(`${API_BASE}/links/${projectId}/${linkId}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });
  if (!res.ok) await throwHttpDetailError(res, 'Failed to update link');
  return (await res.json()) as DCLink;
}

export async function deleteProjectLink(projectId: string, linkId: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/links/${projectId}/${linkId}`, {
    method: 'DELETE',
  });
  if (!res.ok) await throwHttpDetailError(res, 'Failed to delete link');
}

// Static label/description so the dropdown stays readable even when the
// backend returns the bare-name list shape from
// /links/{project_id}/resolvers (response_model=list[str]). Without this,
// the FE indexed `.name` on a plain string and Mantine Select crashed with
// "Each option must have value property".
const RESOLVER_LABELS: Record<string, { label: string; description: string }> = {
  direct: { label: 'Direct', description: 'Pass source value through unchanged.' },
  sample_mapping: {
    label: 'Sample mapping',
    description: 'Expand a canonical sample ID to all of its MultiQC variants.',
  },
  pattern: {
    label: 'Pattern',
    description: 'Substitute the source value into a template like {sample}.bam.',
  },
  regex: {
    label: 'Regex',
    description: 'Match target rows whose target_field matches a regex.',
  },
  wildcard: {
    label: 'Wildcard',
    description: 'Glob-style * / ? match against the target_field.',
  },
};

function normalizeResolver(item: unknown): ResolverInfo | null {
  if (typeof item === 'string') {
    const meta = RESOLVER_LABELS[item] || { label: item, description: '' };
    return { name: item as ResolverInfo['name'], ...meta };
  }
  if (item && typeof item === 'object' && 'name' in item) {
    const o = item as Partial<ResolverInfo>;
    if (!o.name) return null;
    const meta = RESOLVER_LABELS[o.name] || {
      label: o.label || o.name,
      description: o.description || '',
    };
    return {
      name: o.name,
      label: o.label || meta.label,
      description: o.description || meta.description,
    };
  }
  return null;
}

export async function listLinkResolvers(projectId: string): Promise<ResolverInfo[]> {
  const res = await fetch(`${API_BASE}/links/${projectId}/resolvers`, {
    headers: authHeaders(),
  });
  if (!res.ok) await throwHttpError(res, 'Failed to list resolvers');
  const body = await res.json();
  const raw: unknown[] = Array.isArray(body) ? body : (body?.resolvers ?? []);
  return raw
    .map(normalizeResolver)
    .filter((r): r is ResolverInfo => r !== null);
}

/** Aggregated canonical → variants map for a MultiQC DC's reports. Used to
 *  populate the ``sample_mapping`` resolver editor. */
export async function fetchMultiQCSampleMappings(
  projectId: string,
  dcId: string,
): Promise<Record<string, string[]>> {
  const res = await fetch(
    `${API_BASE}/links/${projectId}/multiqc/${dcId}/sample-mappings`,
    { headers: authHeaders() },
  );
  if (!res.ok) await throwHttpError(res, 'Failed to fetch sample mappings');
  const body = await res.json();
  if (body?.sample_mappings && typeof body.sample_mappings === 'object') {
    return body.sample_mappings as Record<string, string[]>;
  }
  return (body ?? {}) as Record<string, string[]>;
}

// =============================================================================
// MultiQC DC creation + management (multipart uploads)
// =============================================================================

export interface CreateMultiQCDCInput {
  projectId: string;
  name: string;
  description?: string;
  /** Each File's `name` is expected to carry the ``webkitRelativePath`` so
   *  the backend can group reports by parent folder. The
   *  ``useFolderDropzone`` hook patches this for us. */
  files: File[];
}

export interface MultiQCMutationResult {
  success: boolean;
  message?: string;
  data_collection_id?: string;
  workflow_id?: string;
  ingested_folders?: string[];
  skipped_count?: number;
  deleted_count?: number;
  fetched_from_s3_count?: number;
  cleanup_failed?: number;
}

async function postMultiQCUpload(
  url: string,
  files: File[],
  extraFields: Record<string, string> = {},
): Promise<MultiQCMutationResult> {
  const fd = new FormData();
  for (const [key, value] of Object.entries(extraFields)) fd.append(key, value);
  for (const file of files) fd.append('files', file, file.name);

  const headers = authHeaders();
  delete headers['Content-Type'];

  const res = await fetch(url, { method: 'POST', headers, body: fd });
  if (!res.ok) await throwHttpDetailError(res, 'MultiQC upload failed');
  return (await res.json()) as MultiQCMutationResult;
}

export async function createMultiQCDataCollection(
  input: CreateMultiQCDCInput,
): Promise<MultiQCMutationResult> {
  return postMultiQCUpload(
    `${API_BASE}/datacollections/create_multiqc_from_upload`,
    input.files,
    {
      project_id: input.projectId,
      name: input.name,
      description: input.description ?? '',
    },
  );
}

export interface MultiQCUniformityCheckResult {
  success: boolean;
  message?: string;
  report_count: number;
  skipped_count: number;
}

/** Dry-run the MultiQC uniformity validator on a list of parquets without
 *  creating a DC. Returns success on uniform; throws an Error whose `.message`
 *  is the stringified 422 detail (parseable with the same helper the Create
 *  modal uses) when the checks find a mismatch. */
export async function checkMultiQCUniformity(
  files: File[],
): Promise<MultiQCUniformityCheckResult> {
  const fd = new FormData();
  for (const file of files) fd.append('files', file, file.name);
  const headers = authHeaders();
  delete headers['Content-Type'];
  const res = await fetch(`${API_BASE}/datacollections/multiqc_uniformity_check`, {
    method: 'POST',
    headers,
    body: fd,
  });
  if (!res.ok) await throwHttpDetailError(res, 'MultiQC uniformity check failed');
  return (await res.json()) as MultiQCUniformityCheckResult;
}

export async function appendMultiQCFiles(
  dcId: string,
  files: File[],
): Promise<MultiQCMutationResult> {
  return postMultiQCUpload(
    `${API_BASE}/multiqc/reports/data-collection/${dcId}/append`,
    files,
  );
}

export async function replaceMultiQCFiles(
  dcId: string,
  files: File[],
): Promise<MultiQCMutationResult> {
  return postMultiQCUpload(
    `${API_BASE}/multiqc/reports/data-collection/${dcId}/replace`,
    files,
  );
}

/** Wipe every MultiQC report for a DC. Defaults to also deleting the S3
 *  parquets — the manage modal's Clear flow uses this. */
export async function clearMultiQCDC(dcId: string, deleteS3 = true): Promise<void> {
  const url =
    `${API_BASE}/multiqc/reports/data-collection/${dcId}` +
    `?delete_s3_files=${deleteS3 ? 'true' : 'false'}`;
  const res = await authFetch(url, { method: 'DELETE' });
  if (!res.ok) await throwHttpDetailError(res, 'Failed to clear MultiQC DC');
}

// =============================================================================
// Table DC manage helpers — append/replace/clear, mirroring the MultiQC ones
// against /datacollections/{dc_id}/append|replace|data
// =============================================================================

export interface TableMutationResult {
  success: boolean;
  message?: string;
  data_collection_id: string;
  rows_total?: number;
  rows_added?: number;
  aggregation_version?: number;
}

async function postTableUpload(url: string, files: File[]): Promise<TableMutationResult> {
  const fd = new FormData();
  for (const file of files) fd.append('files', file, file.name);

  const headers = authHeaders();
  delete headers['Content-Type'];

  const res = await fetch(url, { method: 'POST', headers, body: fd });
  if (!res.ok) await throwHttpDetailError(res, 'Table upload failed');
  return (await res.json()) as TableMutationResult;
}

export async function appendTableFiles(
  dcId: string,
  files: File[],
): Promise<TableMutationResult> {
  return postTableUpload(`${API_BASE}/datacollections/${dcId}/append`, files);
}

export async function replaceTableFiles(
  dcId: string,
  files: File[],
): Promise<TableMutationResult> {
  return postTableUpload(`${API_BASE}/datacollections/${dcId}/replace`, files);
}

/** Wipe every row for a Table DC while keeping the DC definition. */
export async function clearTableDC(dcId: string): Promise<TableMutationResult> {
  const res = await authFetch(`${API_BASE}/datacollections/${dcId}/data`, {
    method: 'DELETE',
  });
  if (!res.ok) await throwHttpDetailError(res, 'Failed to clear Table DC');
  return (await res.json()) as TableMutationResult;
}
