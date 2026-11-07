/**
 * What a project is made of, in the words of someone who brought data to it:
 * several runs of a pipeline, one run, or plain tables.
 *
 * Detected from the project's workflows rather than chosen up front: the UI
 * wraps every data collection a person adds by hand in a synthetic Python
 * workflow, so "has workflows" says nothing. A real workflow names a pipeline
 * engine or a catalog entry. The owner can override a wrong guess with
 * `project.layout`.
 *
 * Pure functions that tolerate missing fields.
 */
import { splitTemplateId } from 'depictio-react-core';

export type ProjectLayoutKind = 'runs' | 'pipeline' | 'tables';

export const LAYOUT_KINDS: ProjectLayoutKind[] = ['runs', 'pipeline', 'tables'];

/** Where a data collection came from (mirrors `config.origin`). */
export interface DataOriginLike {
  kind: 'upload' | 'url' | 'folder' | 'run' | 'manifest';
  location?: string | null;
  added_at?: string | null;
}

export type ProjectSourceKind =
  | 'upload'
  | 'url'
  | 'folder'
  | 's3'
  | 'run'
  | 'manifest'
  | 'mixed'
  | 'unknown';

export interface ProjectSource {
  kind: ProjectSourceKind;
  location: string | null;
  /** Every run folder, when the project reads several (a run was added). */
  locations?: string[];
}

export interface ProjectLayout {
  /** What the project is treated as (the override, else the detection). */
  kind: ProjectLayoutKind;
  /** What detection alone would say. */
  detectedKind: ProjectLayoutKind;
  /** The owner chose `kind`; detection was not used. */
  overridden: boolean;
  /** Workflows that are not the synthetic one made around manual uploads. */
  realWorkflows: WorkflowLike[];
  /** Runs found by ingestion, across the real workflows. */
  runCount: number;
  runNames: string[];
  /** Names of the real pipelines, deduplicated. */
  pipelines: string[];
}

/** The slice of a project these functions read. Loose on purpose. */
export interface LayoutInput {
  workflows?: unknown;
  layout?: unknown;
  template_origin?: unknown;
  [key: string]: unknown;
}

export interface WorkflowLike {
  data_collections?: unknown;
  name?: unknown;
  workflow_tag?: unknown;
  engine?: unknown;
  catalog?: unknown;
  runs?: unknown;
  data_location?: { structure?: unknown; locations?: unknown; attached_locations?: unknown } | null;
  [key: string]: unknown;
}

function str(v: unknown): string | null {
  return typeof v === 'string' && v ? v : null;
}

function engineName(wf: WorkflowLike): string {
  const e = wf.engine;
  if (typeof e === 'string') return e.toLowerCase();
  if (e && typeof e === 'object') {
    const n = (e as { name?: unknown }).name;
    if (typeof n === 'string') return n.toLowerCase();
  }
  return '';
}

/** A workflow the UI did not make up: it names a pipeline engine or a catalog. */
export function isRealWorkflow(wf: WorkflowLike | null | undefined): boolean {
  if (!wf) return false;
  const engine = engineName(wf);
  return Boolean(wf.catalog) || (engine !== '' && engine !== 'python');
}

function workflowName(wf: WorkflowLike): string {
  return str(wf.workflow_tag) ?? str(wf.name) ?? (engineName(wf) || 'workflow');
}

function workflowsOf(project: LayoutInput | null | undefined): WorkflowLike[] {
  const w = project?.workflows;
  return Array.isArray(w) ? (w as WorkflowLike[]) : [];
}

export interface LayoutOptions {
  /** Run names the server recorded (ingestion report). `workflows[].runs` is
   *  empty for real projects, so these win when given. */
  runNames?: string[] | null;
}

export function projectLayout(
  project: LayoutInput | null | undefined,
  options: LayoutOptions = {},
): ProjectLayout {
  const real = workflowsOf(project).filter(isRealWorkflow);
  let runNames: string[] = [];
  if (options.runNames && options.runNames.length > 0) {
    runNames = [...new Set(options.runNames)];
  } else {
    for (const wf of real) {
      const runs = wf.runs;
      if (runs && typeof runs === 'object') runNames.push(...Object.keys(runs));
    }
  }
  const multi = real.some((wf) => wf.data_location?.structure === 'sequencing-runs');
  // No run names recorded (a run read from S3 or an unrecognised folder): the
  // run folders the project knows stand in, each named by its last segment.
  if (runNames.length === 0 && real.length > 0 && !multi) {
    runNames = [
      ...new Set(
        projectRunFolders(project)
          .map((f) => lastSegment(f))
          .filter((n): n is string => !!n),
      ),
    ];
  }
  const runCount = runNames.length;
  const pipelines = [...new Set(real.map(workflowName))];
  const detectedKind: ProjectLayoutKind =
    runCount > 1 || multi ? 'runs' : real.length > 0 ? 'pipeline' : 'tables';
  const override = project?.layout;
  const overridden = override === 'runs' || override === 'pipeline' || override === 'tables';
  return {
    kind: overridden ? (override as ProjectLayoutKind) : detectedKind,
    detectedKind,
    overridden,
    realWorkflows: real,
    runCount,
    runNames,
    pipelines,
  };
}

/* ------------------------------------------------------------------ */
/* Source                                                              */
/* ------------------------------------------------------------------ */

/** An upload is stored as a single file in a temporary directory of the
 *  server; old documents record no explicit origin, so this is a heuristic. */
const TEMP_DIR = /^\/(tmp|var\/folders|private\/(var|tmp))\//;

function classifyPlace(place: string): ProjectSourceKind {
  if (/^s3:\/\//i.test(place)) return 's3';
  if (/^https?:\/\//i.test(place)) return 'url';
  if (TEMP_DIR.test(place)) return 'upload';
  return 'folder';
}

function allDataCollections(project: LayoutInput | null | undefined): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  for (const wf of workflowsOf(project)) {
    if (Array.isArray(wf.data_collections)) {
      for (const dc of wf.data_collections) {
        if (dc && typeof dc === 'object') out.push(dc as Record<string, unknown>);
      }
    }
  }
  return out;
}

function originOf(dc: Record<string, unknown>): DataOriginLike | null {
  const config = dc.config as { origin?: unknown } | null | undefined;
  const o = config?.origin as Partial<DataOriginLike> | null | undefined;
  if (!o || typeof o !== 'object' || typeof o.kind !== 'string') return null;
  return { kind: o.kind, location: str(o.location), added_at: str(o.added_at) };
}

/** The base names of the files the project's collections were made from
 *  (an upload records the file name, a folder table its file's location). */
export function projectSourceFileNames(project: LayoutInput | null | undefined): Set<string> {
  const names = new Set<string>();
  for (const dc of allDataCollections(project)) {
    const o = originOf(dc);
    if (!o?.location || (o.kind !== 'upload' && o.kind !== 'folder')) continue;
    const base = trimSlash(o.location).split('/').pop();
    if (base) names.add(base.toLowerCase());
  }
  return names;
}

/** Every place the project reads data from (the heuristic for old documents). */
function heuristicPlaces(project: LayoutInput): string[] {
  const places: string[] = [];
  const root = str((project.template_origin as { data_root?: unknown } | null | undefined)?.data_root);
  if (root) places.push(root);
  for (const wf of workflowsOf(project)) {
    const locations = wf.data_location?.locations;
    if (Array.isArray(locations)) {
      for (const l of locations) {
        const v = str(l);
        if (v) places.push(v);
      }
    }
  }
  for (const dc of allDataCollections(project)) {
    const config = dc.config as { scan?: { scan_parameters?: Record<string, unknown> } } | undefined;
    const params = config?.scan?.scan_parameters;
    for (const key of ['url', 'manifest_url']) {
      const v = str(params?.[key]);
      if (v) places.push(v);
    }
  }
  return [...new Set(places)];
}

function trimSlash(place: string): string {
  return place.replace(/\/+$/, '');
}

function lastSegment(place: string): string | null {
  const seg = trimSlash(place).split('/').pop();
  return seg ? seg : null;
}

/** The folder holding a file location. A folder origin's location is always
 *  the file it read, whatever its name looks like. */
function parentOf(location: string): string {
  const loc = trimSlash(location);
  const cut = loc.lastIndexOf('/');
  const dir = loc.slice(0, cut);
  // "s3://bucket/file.csv" -> "s3://bucket"; "/file.csv" -> "/".
  return dir === '' ? '/' : dir;
}

/** Every folder the real workflows read: their locations, the folders added
 *  later with "Add a run" (`attached_locations`), and the origin's data root
 *  (usually the first of them). Deduplicated, in the order recorded. */
export function projectRunFolders(project: LayoutInput | null | undefined): string[] {
  if (!project) return [];
  const places: string[] = [];
  const root = str((project.template_origin as { data_root?: unknown } | null | undefined)?.data_root);
  if (root) places.push(root);
  for (const wf of workflowsOf(project).filter(isRealWorkflow)) {
    for (const key of ['locations', 'attached_locations'] as const) {
      const list = wf.data_location?.[key];
      if (Array.isArray(list)) {
        for (const l of list) {
          const v = str(l);
          if (v) places.push(v);
        }
      }
    }
  }
  const seen = new Set<string>();
  return places.filter((p) => {
    const key = trimSlash(p);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function projectSource(project: LayoutInput | null | undefined): ProjectSource {
  const base = baseSource(project);
  const folders = projectRunFolders(project);
  const folderLike = base.kind === 'folder' || base.kind === 's3' || base.kind === 'run' || base.kind === 'unknown';
  // Several run folders: name them all, not the first.
  if (folders.length > 1 && (folderLike || base.kind === 'mixed')) {
    const kind: ProjectSourceKind = folders.every((f) => /^s3:\/\//i.test(f)) ? 's3' : 'folder';
    return { kind, location: folders[0], locations: folders };
  }
  return base;
}

function baseSource(project: LayoutInput | null | undefined): ProjectSource {
  if (!project) return { kind: 'unknown', location: null };
  const found: ProjectSource[] = [];
  for (const dc of allDataCollections(project)) {
    const o = originOf(dc);
    if (!o) continue;
    let location = o.location ?? null;
    const kind: ProjectSourceKind =
      location && /^s3:\/\//i.test(location) ? 's3' : (o.kind as ProjectSourceKind);
    // A folder table records the file's location: the source is its folder.
    if (o.kind === 'folder' && location) location = parentOf(location);
    found.push({ kind, location });
  }
  if (found.length === 0) {
    for (const place of heuristicPlaces(project)) {
      const kind = classifyPlace(place);
      found.push({ kind, location: kind === 'upload' ? null : place });
    }
  }
  if (found.length === 0) return { kind: 'unknown', location: null };
  const uploadNames = (): string[] =>
    [...new Set(found.filter((f) => f.kind === 'upload').map((f) => f.location).filter((l): l is string => !!l))].sort(
      (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }),
    );
  const folderPlaces = [
    ...new Set(
      found
        .filter((f) => (f.kind === 'folder' || f.kind === 's3') && f.location)
        .map((f) => f.location as string),
    ),
  ];
  const kinds = [...new Set(found.map((f) => f.kind))];
  const folderOnly = kinds.every((k) => k === 'folder' || k === 's3');
  if (folderOnly && folderPlaces.length > 1) {
    const kind: ProjectSourceKind = folderPlaces.every((f) => /^s3:\/\//i.test(f)) ? 's3' : 'folder';
    return { kind, location: folderPlaces[0], locations: folderPlaces };
  }
  if (kinds.length > 1 && !folderOnly) {
    const listed: string[] = [];
    const names = uploadNames();
    if (names.length > 0) listed.push(`Uploaded: ${names.join(', ')}`);
    listed.push(...folderPlaces);
    for (const f of found) {
      if (f.kind !== 'upload' && f.kind !== 'folder' && f.kind !== 's3') {
        const label = f.location ?? f.kind;
        if (!listed.includes(label)) listed.push(label);
      }
    }
    return { kind: 'mixed', location: null, locations: listed.length > 1 ? listed : undefined };
  }
  if (kinds[0] === 'upload') {
    const names = uploadNames();
    return { kind: 'upload', location: names.length > 0 ? names.join(', ') : null };
  }
  const withLocation = found.find((f) => f.location);
  const only = folderOnly && kinds.length > 1 ? (folderPlaces[0]?.startsWith('s3://') ? 's3' : 'folder') : kinds[0];
  return { kind: only, location: withLocation?.location ?? null };
}

/* ------------------------------------------------------------------ */
/* Pipeline and sentence                                               */
/* ------------------------------------------------------------------ */

export interface PipelineInfo {
  name: string;
  version: string | null;
}

/** The pipeline behind the project: from its origin id such as
 *  "nf-core/rnaseq/3.14.0", else the first real workflow's tag and version. */
export function projectPipeline(project: LayoutInput | null | undefined): PipelineInfo | null {
  const originId = str((project?.template_origin as { template_id?: unknown } | null | undefined)?.template_id);
  if (originId) {
    const { pipeline, version } = splitTemplateId(originId);
    if (pipeline) return { name: pipeline, version: version ? version.replace(/^v/i, '') : null };
  }
  const real = workflowsOf(project).filter(isRealWorkflow);
  if (real.length === 0) return null;
  const wf = real[0];
  const rawVersion =
    str(wf.version) ??
    str((wf.engine as { version?: unknown } | null | undefined)?.version) ??
    str((wf.config as { version?: unknown } | null | undefined)?.version);
  return { name: workflowName(wf), version: rawVersion ? rawVersion.replace(/^v/i, '') : null };
}

export function dataCollectionCount(project: LayoutInput | null | undefined): number {
  return allDataCollections(project).length;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function sourcePhrase(source: ProjectSource): string | null {
  switch (source.kind) {
    case 'upload':
      return 'uploaded';
    case 'mixed':
      return 'from several sources';
    case 'manifest':
      return source.location ? `from manifest ${source.location}` : 'from a manifest';
    case 'unknown':
      return null;
    default:
      if (source.locations && source.locations.length > 1) {
        return `from ${plural(source.locations.length, 'folder')}`;
      }
      return source.location ? `from ${source.location}` : 'added by hand';
  }
}

/** One line: what the project is and where it came from. */
export function projectSentence(
  project: LayoutInput | null | undefined,
  options: { dashboards?: number | null; runNames?: string[] | null } = {},
): string {
  const dashboardsCount = options.dashboards;
  const layout = projectLayout(project, { runNames: options.runNames });
  const source = projectSource(project);
  const pipeline = projectPipeline(project);
  const pipelineText = pipeline ? `${pipeline.name}${pipeline.version ? ` ${pipeline.version}` : ''}` : null;
  const from = sourcePhrase(source);
  const parts: string[] = [];

  if (layout.kind === 'runs') {
    if (pipelineText) parts.push(pipelineText);
    parts.push(layout.runCount > 0 ? plural(layout.runCount, 'run') : 'several runs');
    if (!pipelineText && layout.pipelines.length > 0) parts.push(`of ${layout.pipelines[0]}`);
    if (from) parts.push(from);
  } else if (layout.kind === 'pipeline') {
    // Without the run records (the projects list does not fetch them) the
    // count is unknown: name the pipeline rather than guess "1 run".
    if (layout.runCount === 0) {
      parts.push(pipelineText ?? layout.pipelines[0] ?? 'Pipeline results');
    } else {
      const runs = plural(layout.runCount, 'run');
      parts.push(pipelineText ? `${runs} of ${pipelineText}` : runs);
    }
    if (from) parts.push(from);
  } else {
    const n = dataCollectionCount(project);
    parts.push(n > 0 ? plural(n, 'table') : 'No data yet');
    if (n > 0 && from) parts.push(from);
    if (dashboardsCount && dashboardsCount > 0) parts.push(plural(dashboardsCount, 'dashboard'));
    return parts.join(' · ');
  }
  // "12 runs of rnaseq" reads better with its pieces joined by a space; the
  // rest of the separators are middle dots.
  return parts
    .reduce<string[]>((acc, p) => {
      if (p.startsWith('of ') && acc.length > 0) acc[acc.length - 1] += ` ${p}`;
      else acc.push(p);
      return acc;
    }, [])
    .join(' · ');
}
