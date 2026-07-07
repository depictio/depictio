/**
 * Client for the local studio authoring API (`/studio/*`), served by
 * depictio/authoring/server.py. Plain fetch — these calls are NOT the shimmed
 * render-data path (that stays in mockApi.ts, fed from window.__CATALOG_PREVIEW__).
 *
 * In the single-file production bundle the studio is served same-origin, so the
 * relative `/studio` base just works. For `vite dev`, point the dev server proxy
 * (or VITE_STUDIO_BASE) at the running `depictio studio` server.
 */

const BASE =
  (typeof import.meta !== 'undefined' && (import.meta as { env?: Record<string, string> }).env?.VITE_STUDIO_BASE) ||
  '/studio';

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

// ---- types ---------------------------------------------------------------- //
export interface TreeNode {
  name: string;
  path: string;
  type: 'dir' | 'file';
  previewable?: boolean;
  size?: number | null;
  children?: TreeNode[];
}

export interface PreviewData {
  path: string;
  format: string;
  separator: string;
  columns: string[];
  schema: Record<string, string>;
  rows: Record<string, unknown>[];
  n_rows_preview: number;
  truncated: boolean;
}

export interface ConfigByExample {
  path_glob: string;
  matched: string[];
  match_count: number;
}

export interface RecognizeResult {
  path: string;
  recognized: boolean;
  matches: { tool_id: string; output_id: string; renders: string[]; mode: string | null }[];
  config_by_example: ConfigByExample;
  catalog_renders?: Record<string, unknown>[];
}

export interface VizSuggestion {
  viz_kind: string;
  score: number;
  role_candidates: Record<string, string[]>;
  unmet_roles: string[];
  weak_roles: string[];
}

export interface RenderPayload {
  output: unknown;
  fixturePreview: unknown;
  theme: 'light' | 'dark';
  renders: Record<string, unknown>[];
  data: Record<string, unknown>;
}

export interface ExportResult {
  project_yaml: string;
  dashboard_yaml: string;
  project: Record<string, unknown>;
}

// ---- endpoints ------------------------------------------------------------ //
export const getTree = (path = '') => get<TreeNode>(`/tree?path=${encodeURIComponent(path)}`);
export const previewData = (path: string) => post<PreviewData>('/preview-data', { path });
export const recognize = (path: string, examples: string[] = []) =>
  post<RecognizeResult>('/recognize', { path, examples });
export const suggest = (schema: Record<string, string>, dc_type?: string) =>
  post<{ suggestions: VizSuggestion[] }>('/suggest', { schema, dc_type });
export const renderSpec = (path: string, spec: Record<string, unknown>, theme = 'light') =>
  post<RenderPayload>('/render', { path, spec, theme });
export const exportDashboard = (body: unknown) => post<ExportResult>('/export/dashboard', body);
