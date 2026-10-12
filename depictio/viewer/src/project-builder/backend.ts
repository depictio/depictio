/**
 * Client for the local Project Builder authoring API (`/project-builder/*`), served by
 * depictio/project_builder/server.py. Plain fetch.
 *
 * In the single-file production bundle the Project Builder is served same-origin, so the
 * relative `/project-builder` base just works. For `vite dev`, point the dev server proxy
 * (or VITE_PROJECT_BUILDER_BASE) at the running `depictio project-builder` server.
 */

const BASE =
  (typeof import.meta !== 'undefined' && (import.meta as { env?: Record<string, string> }).env?.VITE_PROJECT_BUILDER_BASE) ||
  '/project-builder';

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

/** What a recursive scan glob will ingest: the files it matches, the regex it
 *  becomes, and whether those files agree on schema. */
export interface ScanPreview {
  glob: string;
  regex: string;
  matched: string[];
  match_count: number;
  schema: Record<string, string>;
  consistent: boolean;
  mismatches: { path: string; issue: string }[];
  truncated: boolean;
}

/** One Data Collection the wizard is assembling (frontend cart shape). The
 *  backend `/export/project` maps `path` + `mode` + `glob` into a Scan block. */
export interface DcDraft {
  /** Data-collection tag (unique per project). */
  dc_tag: string;
  /** The picked example file, relative to the Project Builder root. */
  path: string;
  /** 'single' → ScanSingle(filename); 'recursive' → regex from the glob. */
  mode: 'single' | 'recursive';
  /** Config-by-example glob (recursive mode only); seeds `pattern`. */
  glob?: string;
  /** Regex written to `regex_config.pattern` (recursive; editable, overrides glob). */
  pattern?: string;
  /** ScanRecursive.max_depth (recursive, optional). */
  max_depth?: number | null;
  /** ScanRecursive.ignore (recursive, optional). */
  ignore?: string[];
  /** Files this DC resolved to at add-time — used to tag them in the file tree. */
  matched?: string[];
  /** Auto-sniffed format, shown read-only in the review step. */
  format?: string;
  description?: string;
}

/** One workflow the wizard is assembling: its engine + data_location (folder +
 *  structure) and the DCs scanned under it. Maps to a `Workflow` at export. */
export interface WorkflowDraft {
  /** Workflow name (unique per project); becomes `{engine}/{name}` workflow_tag. */
  name: string;
  /** Engine name — free-form; defaults to 'python'. */
  engine: string;
  /** data_location folder, relative to the Project Builder launch dir ('' = launch dir). */
  folder: string;
  /** data_location.structure. */
  structure: 'flat' | 'sequencing-runs';
  /** Required by the model when structure is 'sequencing-runs'. */
  runs_regex?: string;
  /** Optional provenance (may be auto-filled from repo metadata). */
  repository_url?: string;
  version?: string;
  catalog?: { name: string; url: string };
  data_collections: DcDraft[];
}

export interface ExportProjectBody {
  name: string;
  workflows: WorkflowDraft[];
}

/** Best-effort metadata extracted from a workflow's repository URL. */
export interface WorkflowMetadata {
  repository_url: string;
  name?: string;
  engine?: string;
  version?: string;
  catalog?: { name: string; url: string };
  description?: string;
  author?: string;
  license?: string;
  homepage?: string;
  /** Pipeline logo (data URIs), light/dark theme variants, when the repo ships one. */
  logo?: string;
  logo_dark?: string;
  /** Which sources contributed (ro-crate, nextflow.config, github, nf-core, logo). */
  sources: string[];
}

export interface ExportResult {
  project_yaml: string;
  project: Record<string, unknown>;
  written_path: string;
}

// ---- endpoints ------------------------------------------------------------ //
export const getContext = () => get<{ root: string }>('/context');
export const getTree = (path = '') => get<TreeNode>(`/tree?path=${encodeURIComponent(path)}`);
export const previewData = (path: string) => post<PreviewData>('/preview-data', { path });
export const recognize = (path: string, examples: string[] = []) =>
  post<RecognizeResult>('/recognize', { path, examples });
export const scanPreview = (
  glob: string,
  regex?: string,
  max_depth?: number | null,
  ignore?: string[],
  subroot?: string,
  structure?: 'flat' | 'sequencing-runs',
  runs_regex?: string,
) =>
  post<ScanPreview>('/scan-preview', {
    glob,
    regex,
    max_depth,
    ignore,
    subroot,
    structure,
    runs_regex,
  });
export const fetchWorkflowMetadata = (repo_url: string) =>
  post<WorkflowMetadata>('/workflow-metadata', { repo_url });
export const exportProject = (body: ExportProjectBody) =>
  post<ExportResult>('/export/project', body);
