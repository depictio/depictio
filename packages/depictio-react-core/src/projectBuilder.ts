/**
 * The Project Builder's draft: the project a reader assembles from a folder
 * (workflows, each holding data collections), the reducer every edit goes
 * through, and the rules `POST /projects/builder/template` enforces, checked
 * here first so the page can say what is wrong before asking the server.
 *
 * The shapes mirror the HTTP contract of `/depictio/api/v1/projects/builder/*`
 * (`BuilderDcDraft`, `BuilderWorkflowDraft`, `BuilderProjectDraft`). The
 * reducer's state adds what only the page needs (a stable id per workflow,
 * the repository metadata last fetched, the files each collection claimed),
 * and `toProjectDraft` strips it before anything is sent.
 *
 * A draft is kept in localStorage per data root, so a refresh does not lose
 * the work. The private bucket's connection details never enter the draft:
 * they stay in the page's state.
 */

import type { BuilderRepoMetadata, RunStorageIn } from './api';

// ── Contract shapes ─────────────────────────────────────────────────────────

export type BuilderDcType =
  | 'table'
  | 'multiqc'
  | 'image'
  | 'indexed_file'
  | 'geojson'
  | 'phylogeny';

/** Every type, in the order the type picker lists them. */
export const BUILDER_DC_TYPES: readonly BuilderDcType[] = [
  'table',
  'multiqc',
  'image',
  'indexed_file',
  'geojson',
  'phylogeny',
];

/** Types that read exactly one file (the server refuses a scan for them). */
export const SINGLE_FILE_DC_TYPES: ReadonlySet<BuilderDcType> = new Set<BuilderDcType>([
  'geojson',
  'phylogeny',
]);

export type BuilderScanMode = 'single' | 'recursive';

export interface BuilderTableProps {
  kind: 'table';
  format: string;
  separator?: string | null;
  columns_description?: Record<string, string>;
}

export interface BuilderMultiQCProps {
  kind: 'multiqc';
}

export interface BuilderImageProps {
  kind: 'image';
  format: string;
  separator?: string | null;
  image_column: string;
  /** Folder of the images, relative to the data root. */
  local_images_path?: string | null;
  s3_base_folder?: string | null;
}

export interface BuilderIndexedFileProps {
  kind: 'indexed_file';
  format: string;
  index_suffix?: string | null;
  sample_regex?: string | null;
  sample_col?: string;
  assembly?: string | null;
  max_file_size_mb?: number;
}

export interface BuilderGeoJSONProps {
  kind: 'geojson';
  feature_id_key: string;
}

export interface BuilderPhylogenyProps {
  kind: 'phylogeny';
  format: 'newick' | 'nexus';
  ladderize?: boolean;
  metadata_dc_tag?: string | null;
  metadata_taxon_column?: string | null;
  tip_label_strategy?: 'taxon' | 'first_token';
}

export type BuilderDcProps =
  | BuilderTableProps
  | BuilderMultiQCProps
  | BuilderImageProps
  | BuilderIndexedFileProps
  | BuilderGeoJSONProps
  | BuilderPhylogenyProps;

export interface BuilderDcDraft {
  /** Unique across the whole project. */
  tag: string;
  description?: string;
  type: BuilderDcType;
  mode: BuilderScanMode;
  /** Single mode: the file, relative to the data root (POSIX). */
  path?: string | null;
  /** Recursive mode: matched against each file's name first, against its
   *  path relative to the data root when it contains a `/`. */
  regex?: string | null;
  /** What the reader typed, kept in step with `regex`; never read by the
   *  server. */
  glob?: string | null;
  /** Recursive, local roots only. */
  max_depth?: number | null;
  /** fnmatch globs; recursive, local roots only. */
  ignore?: string[];
  optional?: boolean;
  props: BuilderDcProps;
}

export type BuilderCatalogName = 'nf-core' | 'workflowhub' | 'smk-wf-catalog';

export const BUILDER_CATALOGS: readonly BuilderCatalogName[] = [
  'nf-core',
  'workflowhub',
  'smk-wf-catalog',
];

export interface BuilderWorkflowCatalog {
  name: BuilderCatalogName;
  url: string;
}

export type BuilderWorkflowStructure = 'flat' | 'sequencing-runs';

export interface BuilderWorkflowDraft {
  /** Unique within the project. */
  name: string;
  /** Lowercase: python, r, nextflow, snakemake, galaxy, ... */
  engine: string;
  engine_version?: string | null;
  version?: string | null;
  repository_url?: string | null;
  catalog?: BuilderWorkflowCatalog | null;
  structure: BuilderWorkflowStructure;
  /** Required for `sequencing-runs`: which sub-folders are runs. */
  runs_regex?: string | null;
  data_collections: BuilderDcDraft[];
}

export interface BuilderProjectDraft {
  name: string;
  description?: string;
  is_public?: boolean;
  realtime?: boolean;
  workflows: BuilderWorkflowDraft[];
}

/** Where the files are: an absolute local path or an `s3://` location, with
 *  the private bucket's connection details when it needs them. */
export interface BuilderRootSpec {
  data_root: string;
  storage?: RunStorageIn | null;
}

// ── Page state ──────────────────────────────────────────────────────────────

export interface BuilderWorkflowState extends BuilderWorkflowDraft {
  /** Stable across renames; never sent. */
  id: string;
  /** The repository metadata last fetched, for display; never sent. */
  meta?: BuilderRepoMetadata | null;
}

export interface BuilderProjectFields {
  name: string;
  description: string;
  is_public: boolean;
  realtime: boolean;
}

export interface BuilderState {
  version: 1;
  project: BuilderProjectFields;
  workflows: BuilderWorkflowState[];
  activeWorkflowId: string;
  /** The files each collection matched when it was saved, by tag: the file
   *  tree tags them. Never sent. */
  claimed: Record<string, string[]>;
  /** Next workflow id number. */
  nextId: number;
}

/** The workflow every draft starts with, so a single-workflow project never
 *  has to think about workflows at all. */
export const DEFAULT_WORKFLOW_NAME = 'main';
export const DEFAULT_ENGINE = 'python';
/** Sub-folders treated as runs when a workflow switches to sequencing runs. */
export const DEFAULT_RUNS_REGEX = 'run_.*';

function newWorkflow(id: string, name: string): BuilderWorkflowState {
  return {
    id,
    name,
    engine: DEFAULT_ENGINE,
    structure: 'flat',
    data_collections: [],
  };
}

export function initialBuilderState(): BuilderState {
  return {
    version: 1,
    project: { name: '', description: '', is_public: false, realtime: false },
    workflows: [newWorkflow('wf-0', DEFAULT_WORKFLOW_NAME)],
    activeWorkflowId: 'wf-0',
    claimed: {},
    nextId: 1,
  };
}

// ── Lookups ─────────────────────────────────────────────────────────────────

export interface LocatedDc {
  workflowId: string;
  dc: BuilderDcDraft;
}

/** Every collection of the project, with the workflow holding it. */
export function allBuilderDcs(state: BuilderState): LocatedDc[] {
  return state.workflows.flatMap((w) =>
    w.data_collections.map((dc) => ({ workflowId: w.id, dc })),
  );
}

export function findBuilderDc(state: BuilderState, tag: string): LocatedDc | null {
  return allBuilderDcs(state).find((l) => l.dc.tag === tag) ?? null;
}

/** True when another collection than `exceptTag` already uses `tag`. */
export function isTagTaken(
  state: BuilderState,
  tag: string,
  exceptTag?: string | null,
): boolean {
  const wanted = tag.trim();
  if (!wanted) return false;
  return allBuilderDcs(state).some(({ dc }) => dc.tag !== exceptTag && dc.tag.trim() === wanted);
}

/** True when another workflow than `exceptId` already uses `name`. */
export function isWorkflowNameTaken(
  state: BuilderState,
  name: string,
  exceptId?: string | null,
): boolean {
  const wanted = name.trim();
  if (!wanted) return false;
  return state.workflows.some((w) => w.id !== exceptId && w.name.trim() === wanted);
}

/** `base`, else `base_2`, `base_3`... whichever no other collection uses. */
export function uniqueTag(state: BuilderState, base: string, exceptTag?: string | null): string {
  const stem = base.trim() || 'data_collection';
  if (!isTagTaken(state, stem, exceptTag)) return stem;
  let n = 2;
  while (isTagTaken(state, `${stem}_${n}`, exceptTag)) n += 1;
  return `${stem}_${n}`;
}

/** `base`, else `base_2`, `base_3`... whichever no workflow uses. */
export function uniqueWorkflowName(state: BuilderState, base: string): string {
  const stem = base.trim() || 'workflow';
  if (!isWorkflowNameTaken(state, stem)) return stem;
  let n = 2;
  while (isWorkflowNameTaken(state, `${stem}_${n}`)) n += 1;
  return `${stem}_${n}`;
}

/** A file's stem as a snake_case tag: `results/Sample-Counts.tsv` gives
 *  `sample_counts`. */
export function tagFromPath(path: string): string {
  const base = path.split('/').filter(Boolean).pop() ?? path;
  const stem = base.replace(/\.(gz|bz2|zst|xz)$/i, '').replace(/\.[^.]+$/, '');
  return (
    stem
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'data_collection'
  );
}

/** Tags of the table collections, for a phylogeny's metadata table. */
export function tableTags(state: BuilderState, exceptTag?: string | null): string[] {
  return allBuilderDcs(state)
    .filter(({ dc }) => dc.type === 'table' && dc.tag !== exceptTag)
    .map(({ dc }) => dc.tag);
}

/** The table format a file name suggests, and its separator. */
export function formatFromPath(path: string): { format: string; separator: string | null } {
  const name = path.toLowerCase().replace(/\.(gz|bz2|zst|xz)$/, '');
  if (name.endsWith('.tsv') || name.endsWith('.tab') || name.endsWith('.txt')) {
    return { format: 'tsv', separator: '\t' };
  }
  if (name.endsWith('.csv')) return { format: 'csv', separator: ',' };
  if (name.endsWith('.parquet')) return { format: 'parquet', separator: null };
  if (name.endsWith('.feather') || name.endsWith('.arrow')) {
    return { format: 'feather', separator: null };
  }
  if (name.endsWith('.xlsx') || name.endsWith('.xls')) return { format: 'xlsx', separator: null };
  const ext = name.match(/\.([a-z0-9]+)$/)?.[1];
  return { format: ext ?? 'csv', separator: ext ? null : ',' };
}

/** Fresh properties for `type`, seeded from what is known of the file. */
export function defaultDcProps(
  type: BuilderDcType,
  hint: { format?: string | null; separator?: string | null; path?: string | null } = {},
): BuilderDcProps {
  const guessed = hint.path ? formatFromPath(hint.path) : null;
  const format = hint.format ?? guessed?.format ?? 'csv';
  const separator = hint.separator ?? guessed?.separator ?? null;
  switch (type) {
    case 'table':
      return { kind: 'table', format, separator };
    case 'multiqc':
      return { kind: 'multiqc' };
    case 'image':
      return { kind: 'image', format, separator, image_column: '' };
    case 'indexed_file': {
      const ext = hint.path?.toLowerCase().replace(/\.gz$/, '').match(/\.([a-z0-9]+)$/)?.[1];
      const known = ['vcf', 'bam', 'cram', 'bed', 'bigwig', 'bw', 'gff', 'gff3'];
      const fmt = ext && known.includes(ext) ? (ext === 'bw' ? 'bigwig' : ext === 'gff3' ? 'gff' : ext) : 'vcf';
      return { kind: 'indexed_file', format: fmt };
    }
    case 'geojson':
      return { kind: 'geojson', feature_id_key: '' };
    case 'phylogeny': {
      const nexus = /\.(nex|nexus)$/i.test(hint.path ?? '');
      return { kind: 'phylogeny', format: nexus ? 'nexus' : 'newick', ladderize: true };
    }
    default:
      return { kind: 'table', format, separator };
  }
}

// ── Reducer ─────────────────────────────────────────────────────────────────

export type BuilderWorkflowPatch = Partial<
  Omit<BuilderWorkflowState, 'id' | 'data_collections'>
>;

export type BuilderAction =
  | { type: 'project/patch'; patch: Partial<BuilderProjectFields> }
  | { type: 'workflow/add'; name?: string }
  | { type: 'workflow/patch'; id: string; patch: BuilderWorkflowPatch }
  | { type: 'workflow/remove'; id: string }
  | { type: 'workflow/select'; id: string }
  | {
      type: 'dc/save';
      workflowId: string;
      dc: BuilderDcDraft;
      /** The tag of the collection being edited; absent for a new one. */
      originalTag?: string | null;
      /** The files the collection matched, for the file tree. */
      files?: string[];
    }
  | { type: 'dc/remove'; tag: string }
  | { type: 'dc/move'; tag: string; workflowId: string }
  | { type: 'state/replace'; state: BuilderState };

function mapDcs(
  state: BuilderState,
  fn: (dc: BuilderDcDraft) => BuilderDcDraft,
): BuilderWorkflowState[] {
  return state.workflows.map((w) => ({ ...w, data_collections: w.data_collections.map(fn) }));
}

/** Every edit of the draft. An edit the rules refuse (a tag another
 *  collection uses, removing the last workflow, an unknown id) returns the
 *  state unchanged. */
export function builderReducer(state: BuilderState, action: BuilderAction): BuilderState {
  switch (action.type) {
    case 'project/patch':
      return { ...state, project: { ...state.project, ...action.patch } };

    case 'workflow/add': {
      const id = `wf-${state.nextId}`;
      const name = uniqueWorkflowName(state, action.name ?? `workflow_${state.workflows.length + 1}`);
      return {
        ...state,
        workflows: [...state.workflows, newWorkflow(id, name)],
        activeWorkflowId: id,
        nextId: state.nextId + 1,
      };
    }

    case 'workflow/patch': {
      if (!state.workflows.some((w) => w.id === action.id)) return state;
      return {
        ...state,
        workflows: state.workflows.map((w) => {
          if (w.id !== action.id) return w;
          const next: BuilderWorkflowState = { ...w, ...action.patch };
          if (action.patch.structure === 'flat') next.runs_regex = null;
          if (action.patch.structure === 'sequencing-runs' && !next.runs_regex) {
            next.runs_regex = DEFAULT_RUNS_REGEX;
          }
          return next;
        }),
      };
    }

    case 'workflow/remove': {
      if (state.workflows.length <= 1) return state;
      const doomed = state.workflows.find((w) => w.id === action.id);
      if (!doomed) return state;
      const workflows = state.workflows.filter((w) => w.id !== action.id);
      const claimed = { ...state.claimed };
      for (const dc of doomed.data_collections) delete claimed[dc.tag];
      return {
        ...state,
        workflows,
        claimed,
        activeWorkflowId:
          state.activeWorkflowId === action.id ? workflows[0].id : state.activeWorkflowId,
      };
    }

    case 'workflow/select':
      if (!state.workflows.some((w) => w.id === action.id)) return state;
      return { ...state, activeWorkflowId: action.id };

    case 'dc/save': {
      const tag = action.dc.tag.trim();
      const original = action.originalTag ?? null;
      if (!tag) return state;
      if (!state.workflows.some((w) => w.id === action.workflowId)) return state;
      if (isTagTaken(state, tag, original)) return state;
      const dc: BuilderDcDraft = { ...action.dc, tag };
      const holder = original ? findBuilderDc(state, original) : null;
      const renamed = Boolean(original && holder && original !== tag);

      let workflows = state.workflows.map((w) => {
        if (holder && w.id === holder.workflowId && w.id === action.workflowId) {
          // Edited in place: keep its position.
          return {
            ...w,
            data_collections: w.data_collections.map((d) => (d.tag === original ? dc : d)),
          };
        }
        if (holder && w.id === holder.workflowId) {
          return { ...w, data_collections: w.data_collections.filter((d) => d.tag !== original) };
        }
        if (w.id === action.workflowId) {
          return { ...w, data_collections: [...w.data_collections, dc] };
        }
        return w;
      });

      if (renamed) {
        // A phylogeny reading the renamed table follows it.
        workflows = mapDcs({ ...state, workflows }, (d) =>
          d.props.kind === 'phylogeny' && d.props.metadata_dc_tag === original
            ? { ...d, props: { ...d.props, metadata_dc_tag: tag } }
            : d,
        );
      }

      const claimed = { ...state.claimed };
      const previous = original ? claimed[original] : undefined;
      if (original) delete claimed[original];
      claimed[tag] = action.files ?? previous ?? (dc.mode === 'single' && dc.path ? [dc.path] : []);
      return { ...state, workflows, claimed };
    }

    case 'dc/remove': {
      if (!findBuilderDc(state, action.tag)) return state;
      const claimed = { ...state.claimed };
      delete claimed[action.tag];
      return {
        ...state,
        claimed,
        workflows: state.workflows.map((w) => ({
          ...w,
          data_collections: w.data_collections.filter((d) => d.tag !== action.tag),
        })),
      };
    }

    case 'dc/move': {
      const located = findBuilderDc(state, action.tag);
      if (!located || located.workflowId === action.workflowId) return state;
      if (!state.workflows.some((w) => w.id === action.workflowId)) return state;
      return {
        ...state,
        workflows: state.workflows.map((w) => {
          if (w.id === located.workflowId) {
            return {
              ...w,
              data_collections: w.data_collections.filter((d) => d.tag !== action.tag),
            };
          }
          if (w.id === action.workflowId) {
            return { ...w, data_collections: [...w.data_collections, located.dc] };
          }
          return w;
        }),
      };
    }

    case 'state/replace':
      return action.state;

    default:
      return state;
  }
}

// ── What is sent ────────────────────────────────────────────────────────────

const blankToNull = (value: string | null | undefined): string | null => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
};

function normalizeProps(dc: BuilderDcDraft): BuilderDcProps {
  const props =
    dc.props && dc.props.kind === dc.type ? dc.props : defaultDcProps(dc.type, { path: dc.path });
  switch (props.kind) {
    case 'table': {
      const out: BuilderTableProps = { kind: 'table', format: props.format.trim() || 'csv' };
      const sep = props.separator ?? null;
      if (sep) out.separator = sep;
      const described = Object.entries(props.columns_description ?? {}).filter(
        ([column, text]) => column.trim() && text.trim(),
      );
      if (described.length) {
        out.columns_description = Object.fromEntries(
          described.map(([column, text]) => [column, text.trim()]),
        );
      }
      return out;
    }
    case 'multiqc':
      return { kind: 'multiqc' };
    case 'image': {
      const out: BuilderImageProps = {
        kind: 'image',
        format: props.format.trim() || 'csv',
        image_column: props.image_column.trim(),
      };
      if (props.separator) out.separator = props.separator;
      const local = blankToNull(props.local_images_path);
      const s3 = blankToNull(props.s3_base_folder);
      if (local) out.local_images_path = local;
      if (s3) out.s3_base_folder = s3;
      return out;
    }
    case 'indexed_file': {
      const out: BuilderIndexedFileProps = {
        kind: 'indexed_file',
        format: props.format.trim() || 'vcf',
      };
      const suffix = blankToNull(props.index_suffix);
      const sampleRegex = blankToNull(props.sample_regex);
      const assembly = blankToNull(props.assembly);
      if (suffix) out.index_suffix = suffix;
      if (sampleRegex) out.sample_regex = sampleRegex;
      if (props.sample_col?.trim()) out.sample_col = props.sample_col.trim();
      if (assembly) out.assembly = assembly;
      if (typeof props.max_file_size_mb === 'number' && props.max_file_size_mb > 0) {
        out.max_file_size_mb = props.max_file_size_mb;
      }
      return out;
    }
    case 'geojson':
      return { kind: 'geojson', feature_id_key: props.feature_id_key.trim() };
    case 'phylogeny': {
      const out: BuilderPhylogenyProps = { kind: 'phylogeny', format: props.format };
      if (props.ladderize !== undefined) out.ladderize = props.ladderize;
      const meta = blankToNull(props.metadata_dc_tag);
      if (meta) {
        out.metadata_dc_tag = meta;
        const column = blankToNull(props.metadata_taxon_column);
        if (column) out.metadata_taxon_column = column;
      }
      if (props.tip_label_strategy) out.tip_label_strategy = props.tip_label_strategy;
      return out;
    }
    default:
      return props;
  }
}

/** One collection as the server reads it: trimmed, empty optional fields
 *  dropped, and only the fields its mode uses. On an `s3://` root the local
 *  walk bounds (`max_depth`, `ignore`) are dropped: S3 scans list the whole
 *  prefix. */
export function normalizeDcDraft(
  dc: BuilderDcDraft,
  options: { remote?: boolean } = {},
): BuilderDcDraft {
  const out: BuilderDcDraft = {
    tag: dc.tag.trim(),
    type: dc.type,
    mode: dc.mode,
    props: normalizeProps(dc),
  };
  const description = dc.description?.trim();
  if (description) out.description = description;
  if (dc.optional) out.optional = true;
  if (dc.mode === 'single') {
    out.path = blankToNull(dc.path);
  } else {
    out.regex = blankToNull(dc.regex);
    out.glob = blankToNull(dc.glob);
    if (!options.remote) {
      if (typeof dc.max_depth === 'number' && dc.max_depth >= 0) out.max_depth = dc.max_depth;
      const ignore = (dc.ignore ?? []).map((g) => g.trim()).filter(Boolean);
      if (ignore.length) out.ignore = ignore;
    }
  }
  return out;
}

/** One workflow as the server reads it (no page-only fields). */
export function normalizeWorkflowDraft(
  workflow: BuilderWorkflowDraft,
  options: { remote?: boolean } = {},
): BuilderWorkflowDraft {
  const out: BuilderWorkflowDraft = {
    name: workflow.name.trim(),
    engine: (workflow.engine || DEFAULT_ENGINE).trim().toLowerCase(),
    structure: workflow.structure,
    data_collections: workflow.data_collections.map((dc) => normalizeDcDraft(dc, options)),
  };
  const engineVersion = blankToNull(workflow.engine_version);
  const version = blankToNull(workflow.version);
  const repo = blankToNull(workflow.repository_url);
  if (engineVersion) out.engine_version = engineVersion;
  if (version) out.version = version;
  if (repo) out.repository_url = repo;
  if (workflow.catalog && workflow.catalog.url.trim()) {
    out.catalog = { name: workflow.catalog.name, url: workflow.catalog.url.trim() };
  }
  if (workflow.structure === 'sequencing-runs') out.runs_regex = blankToNull(workflow.runs_regex);
  return out;
}

/** The draft as `POST /projects/builder/template` takes it. */
export function toProjectDraft(
  state: BuilderState,
  options: { remote?: boolean } = {},
): BuilderProjectDraft {
  const draft: BuilderProjectDraft = {
    name: state.project.name.trim(),
    workflows: state.workflows.map((w) => normalizeWorkflowDraft(w, options)),
  };
  const description = state.project.description.trim();
  if (description) draft.description = description;
  if (state.project.is_public) draft.is_public = true;
  if (state.project.realtime) draft.realtime = true;
  return draft;
}

// ── Rules ───────────────────────────────────────────────────────────────────

export interface BuilderIssue {
  /** Errors block the template; warnings only inform. */
  level: 'error' | 'warning';
  code: string;
  message: string;
  workflowId?: string;
  tag?: string;
}

/** What the template endpoint would refuse, and what deserves a look. On an
 *  `s3://` root (`remote`) indexed files cannot be read yet. */
export function validateBuilderState(
  state: BuilderState,
  options: { remote?: boolean } = {},
): BuilderIssue[] {
  const issues: BuilderIssue[] = [];
  const error = (code: string, message: string, extra: Partial<BuilderIssue> = {}) =>
    issues.push({ level: 'error', code, message, ...extra });
  const warn = (code: string, message: string, extra: Partial<BuilderIssue> = {}) =>
    issues.push({ level: 'warning', code, message, ...extra });

  if (!state.project.name.trim()) error('project_name', 'Give the project a name.');

  const dcs = allBuilderDcs(state);
  if (dcs.length === 0) error('no_collections', 'Add at least one data collection.');

  const names = new Map<string, number>();
  for (const w of state.workflows) {
    const name = w.name.trim();
    if (name) names.set(name, (names.get(name) ?? 0) + 1);
  }
  for (const w of state.workflows) {
    const name = w.name.trim();
    const extra = { workflowId: w.id };
    if (!name) error('workflow_name_empty', 'A workflow has no name.', extra);
    else if ((names.get(name) ?? 0) > 1) {
      error('workflow_name_duplicate', `Two workflows are named “${name}”.`, extra);
    }
    if (w.data_collections.length === 0) {
      error(
        'workflow_empty',
        `Workflow “${name || '(unnamed)'}” has no data collection: add one or remove it.`,
        extra,
      );
    }
    if (w.structure === 'sequencing-runs' && !w.runs_regex?.trim()) {
      error(
        'runs_regex_missing',
        `Workflow “${name || '(unnamed)'}” reads sequencing runs: say which folders are runs.`,
        extra,
      );
    }
  }

  const tags = new Map<string, number>();
  for (const { dc } of dcs) {
    const tag = dc.tag.trim();
    if (tag) tags.set(tag, (tags.get(tag) ?? 0) + 1);
  }
  const tables = new Set(dcs.filter(({ dc }) => dc.type === 'table').map(({ dc }) => dc.tag.trim()));
  const reported = new Set<string>();

  for (const { workflowId, dc } of dcs) {
    const tag = dc.tag.trim();
    const label = tag || '(untagged)';
    const extra = { workflowId, tag: dc.tag };
    if (!tag) error('dc_tag_empty', 'A data collection has no tag.', extra);
    else if ((tags.get(tag) ?? 0) > 1 && !reported.has(tag)) {
      reported.add(tag);
      error('dc_tag_duplicate', `Two data collections are tagged “${tag}”.`, extra);
    }
    if (dc.mode === 'single' && !dc.path?.trim()) {
      error('dc_path_missing', `“${label}” has no file.`, extra);
    }
    if (dc.mode === 'recursive' && !dc.regex?.trim()) {
      error('dc_regex_missing', `“${label}” has no scan pattern.`, extra);
    }
    const props = dc.props;
    if (!props || props.kind !== dc.type) {
      warn('dc_props_reset', `“${label}” will use the default ${dc.type} settings.`, extra);
      continue;
    }
    if (dc.mode === 'recursive' && SINGLE_FILE_DC_TYPES.has(dc.type)) {
      error('single_file_type_scanned', `“${label}” reads one file: a ${dc.type} collection cannot scan.`, extra);
    }
    if (props.kind === 'image' && options.remote) {
      error(
        'image_remote',
        `“${label}” is an image collection: its images are uploaded from a folder on this computer, not an S3 prefix.`,
        extra,
      );
    }
    if (props.kind === 'indexed_file' && options.remote) {
      error(
        'indexed_file_remote',
        `“${label}” is an indexed file: those cannot be read from S3 yet. Use a local folder.`,
        extra,
      );
    }
    if (props.kind === 'image' && !props.image_column.trim()) {
      error('image_column_missing', `“${label}”: name the column holding the image paths.`, extra);
    }
    if (props.kind === 'geojson' && !props.feature_id_key.trim()) {
      error('feature_id_key_missing', `“${label}”: name the feature property that identifies each shape.`, extra);
    }
    if (props.kind === 'phylogeny' && props.metadata_dc_tag?.trim()) {
      const meta = props.metadata_dc_tag.trim();
      if (!tables.has(meta)) {
        error(
          'phylogeny_metadata_missing',
          `“${label}” reads its metadata from “${meta}”, which is not a table collection of this project.`,
          extra,
        );
      }
    }
  }
  return issues;
}

/** The errors among `issues`. */
export function blockingIssues(issues: BuilderIssue[]): BuilderIssue[] {
  return issues.filter((i) => i.level === 'error');
}

// ── Glob ↔ regex ────────────────────────────────────────────────────────────

const REGEX_SPECIAL = new Set(['.', '*', '+', '?', '^', '$', '{', '}', '(', ')', '|', '[', ']', '\\']);

const escapeLiteral = (text: string): string =>
  [...text].map((c) => (REGEX_SPECIAL.has(c) ? `\\${c}` : c)).join('');

/**
 * The scan regex a glob stands for, written for Python's `re.match` (anchored
 * at the start, so only the end gets a `$`). A glob without a `/` matches file
 * names, like the regex it becomes; with one, it matches paths relative to
 * the data root and `*` stops at `/`. A leading `**\/` is dropped: a file-name
 * pattern already reaches every depth.
 */
export function globToRegex(glob: string): string {
  let g = glob.trim();
  while (g.startsWith('**/')) g = g.slice(3);
  if (!g) return '';
  const pathLike = g.includes('/');
  let out = '';
  for (let i = 0; i < g.length; i += 1) {
    const c = g[i];
    if (c === '*') {
      if (g[i + 1] === '*') {
        if (g[i + 2] === '/') {
          out += '(?:.*/)?';
          i += 2;
        } else {
          out += '.*';
          i += 1;
        }
      } else {
        out += pathLike ? '[^/]*' : '.*';
      }
    } else if (c === '?') {
      out += pathLike ? '[^/]' : '.';
    } else if (c === '[') {
      const end = g.indexOf(']', i + 2);
      if (end === -1) {
        out += '\\[';
      } else {
        let body = g.slice(i + 1, end);
        if (body.startsWith('!')) body = `^${body.slice(1)}`;
        out += `[${body.replace(/\\/g, '\\\\')}]`;
        i = end;
      }
    } else if (c === '{') {
      const end = g.indexOf('}', i);
      if (end === -1) {
        out += '\\{';
      } else {
        const alternatives = g.slice(i + 1, end).split(',').map(escapeLiteral);
        out += `(?:${alternatives.join('|')})`;
        i = end;
      }
    } else {
      out += escapeLiteral(c);
    }
  }
  return `${out}$`;
}

const QUANTIFIERS = new Set(['*', '+', '?', '{']);
const GLOB_SPECIAL = new Set(['*', '?', '[', ']', '{', '}', ',']);

/**
 * The glob a scan regex reads as, when it is that simple: wildcards, literal
 * characters, character classes and plain alternatives. Null for anything a
 * glob cannot say (quantified atoms, nested groups, look-arounds...), which
 * the page shows as a hand-written regex.
 */
export function regexToGlob(regex: string): string | null {
  let r = regex.trim();
  if (!r) return null;
  if (r.startsWith('^')) r = r.slice(1);
  let anchored = false;
  if (r.endsWith('$') && !r.endsWith('\\$')) {
    anchored = true;
    r = r.slice(0, -1);
  }
  let out = '';
  let i = 0;
  const next = (n = 0) => r[i + n];
  while (i < r.length) {
    if (r.startsWith('(?:.*/)?', i)) {
      out += '**/';
      i += 8;
      continue;
    }
    if (r.startsWith('[^/]*', i)) {
      out += '*';
      i += 5;
      continue;
    }
    if (r.startsWith('[^/]', i) && !QUANTIFIERS.has(r[i + 4] ?? '')) {
      out += '?';
      i += 4;
      continue;
    }
    const c = next();
    if (c === '.') {
      const q = next(1);
      if (q === '*') {
        out += '*';
        i += next(2) === '?' ? 3 : 2;
        continue;
      }
      if (q === '+') {
        out += '?*';
        i += next(2) === '?' ? 3 : 2;
        continue;
      }
      if (q && QUANTIFIERS.has(q)) return null;
      out += '?';
      i += 1;
      continue;
    }
    if (c === '\\') {
      const escaped = next(1);
      if (escaped === undefined) return null;
      if (QUANTIFIERS.has(next(2) ?? '')) return null;
      if (escaped === 'd') out += '[0-9]';
      else if (/[A-Za-z0-9]/.test(escaped)) return null;
      else if (GLOB_SPECIAL.has(escaped)) return null;
      else out += escaped;
      i += 2;
      continue;
    }
    if (c === '[') {
      const end = r.indexOf(']', i + 2);
      if (end === -1) return null;
      if (QUANTIFIERS.has(r[end + 1] ?? '')) return null;
      let body = r.slice(i + 1, end);
      if (body.includes('\\')) return null;
      if (body.startsWith('^')) body = `!${body.slice(1)}`;
      out += `[${body}]`;
      i = end + 1;
      continue;
    }
    if (c === '(') {
      const start = r.startsWith('(?:', i) ? i + 3 : r.startsWith('(?', i) ? -1 : i + 1;
      if (start === -1) return null;
      const end = r.indexOf(')', start);
      if (end === -1) return null;
      if (QUANTIFIERS.has(r[end + 1] ?? '')) return null;
      const alternatives = r.slice(start, end).split('|');
      const literals: string[] = [];
      for (const alt of alternatives) {
        const glob = regexToGlob(`${alt}$`);
        if (glob === null || /[*?[{]/.test(glob)) return null;
        literals.push(glob);
      }
      out += literals.length === 1 ? literals[0] : `{${literals.join(',')}}`;
      i = end + 1;
      continue;
    }
    if (c === ')' || c === '|' || c === '^' || c === '$' || c === ']' || c === '{' || c === '}') {
      return null;
    }
    if (QUANTIFIERS.has(c)) return null;
    if (QUANTIFIERS.has(next(1) ?? '')) return null;
    if (GLOB_SPECIAL.has(c)) return null;
    out += c;
    i += 1;
  }
  if (!anchored && !out.endsWith('*')) out += '*';
  return out;
}

// ── Draft persistence ───────────────────────────────────────────────────────

/** What persistence needs of `Storage`; tests hand in a plain object. */
export type BuilderStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export const BUILDER_DRAFT_KEY_PREFIX = 'depictio:project-builder:draft:v1:';

export function builderDraftKey(dataRoot: string): string {
  return `${BUILDER_DRAFT_KEY_PREFIX}${dataRoot.trim()}`;
}

function defaultStorage(kind: 'localStorage' | 'sessionStorage'): BuilderStorage | null {
  try {
    const storage = (globalThis as Record<string, unknown>)[kind] as BuilderStorage | undefined;
    return storage ?? null;
  } catch {
    // Blocked storage (privacy settings, sandboxed frame) throws on access.
    return null;
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

function parseDc(raw: unknown): BuilderDcDraft | null {
  if (!isRecord(raw)) return null;
  if (typeof raw.tag !== 'string') return null;
  if (!BUILDER_DC_TYPES.includes(raw.type as BuilderDcType)) return null;
  if (raw.mode !== 'single' && raw.mode !== 'recursive') return null;
  const dc = raw as unknown as BuilderDcDraft;
  const props = isRecord(raw.props) && raw.props.kind === raw.type
    ? (raw.props as unknown as BuilderDcProps)
    : defaultDcProps(dc.type, { path: typeof raw.path === 'string' ? raw.path : null });
  return { ...dc, props };
}

function parseWorkflow(raw: unknown): BuilderWorkflowState | null {
  if (!isRecord(raw)) return null;
  if (typeof raw.id !== 'string' || typeof raw.name !== 'string') return null;
  if (!Array.isArray(raw.data_collections)) return null;
  const dcs = raw.data_collections.map(parseDc);
  if (dcs.some((d) => d === null)) return null;
  return {
    ...(raw as unknown as BuilderWorkflowState),
    engine: typeof raw.engine === 'string' && raw.engine ? raw.engine : DEFAULT_ENGINE,
    structure: raw.structure === 'sequencing-runs' ? 'sequencing-runs' : 'flat',
    data_collections: dcs as BuilderDcDraft[],
  };
}

/** A stored draft, checked; null for anything that does not hold together. */
export function parseBuilderState(raw: unknown): BuilderState | null {
  if (!isRecord(raw) || raw.version !== 1) return null;
  if (!Array.isArray(raw.workflows) || raw.workflows.length === 0) return null;
  const workflows = raw.workflows.map(parseWorkflow);
  if (workflows.some((w) => w === null)) return null;
  const project = isRecord(raw.project) ? raw.project : {};
  const typed = workflows as BuilderWorkflowState[];
  const ids = typed.map((w) => Number(/^wf-(\d+)$/.exec(w.id)?.[1] ?? -1));
  const claimed: Record<string, string[]> = {};
  if (isRecord(raw.claimed)) {
    for (const [tag, files] of Object.entries(raw.claimed)) {
      if (Array.isArray(files)) claimed[tag] = files.filter((f): f is string => typeof f === 'string');
    }
  }
  const active =
    typeof raw.activeWorkflowId === 'string' && typed.some((w) => w.id === raw.activeWorkflowId)
      ? raw.activeWorkflowId
      : typed[0].id;
  return {
    version: 1,
    project: {
      name: typeof project.name === 'string' ? project.name : '',
      description: typeof project.description === 'string' ? project.description : '',
      is_public: project.is_public === true,
      realtime: project.realtime === true,
    },
    workflows: typed,
    activeWorkflowId: active,
    claimed,
    nextId: Math.max(typeof raw.nextId === 'number' ? raw.nextId : 0, Math.max(...ids) + 1),
  };
}

/** The draft saved for `dataRoot`, or null (none, unreadable, storage off). */
export function loadBuilderDraft(
  dataRoot: string,
  storage: BuilderStorage | null = defaultStorage('localStorage'),
): BuilderState | null {
  if (!storage || !dataRoot.trim()) return null;
  try {
    const raw = storage.getItem(builderDraftKey(dataRoot));
    return raw ? parseBuilderState(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

/** Save the draft for `dataRoot`; best effort (quota, storage off). */
export function saveBuilderDraft(
  dataRoot: string,
  state: BuilderState,
  storage: BuilderStorage | null = defaultStorage('localStorage'),
): void {
  if (!storage || !dataRoot.trim()) return;
  try {
    storage.setItem(builderDraftKey(dataRoot), JSON.stringify(state));
  } catch {
    // Quota exceeded or storage disabled: the draft just is not kept.
  }
}

export function clearBuilderDraft(
  dataRoot: string,
  storage: BuilderStorage | null = defaultStorage('localStorage'),
): void {
  if (!storage || !dataRoot.trim()) return;
  try {
    storage.removeItem(builderDraftKey(dataRoot));
  } catch {
    // Nothing to do.
  }
}

// ── Hand-off from the run-folder wizard ────────────────────────────────────

/** Where the run-folder wizard leaves the folder it could not match to a
 *  template, for the builder page to pick up once (sessionStorage). */
export const BUILDER_HANDOFF_KEY = 'depictio:project-builder:handoff';

export interface BuilderHandoff {
  dataRoot: string;
  storage: RunStorageIn | null;
}

export function writeBuilderHandoff(
  handoff: BuilderHandoff,
  storage: BuilderStorage | null = defaultStorage('sessionStorage'),
): boolean {
  if (!storage || !handoff.dataRoot.trim()) return false;
  try {
    storage.setItem(BUILDER_HANDOFF_KEY, JSON.stringify(handoff));
    return true;
  } catch {
    return false;
  }
}

/** The hand-off left for the builder, removed as it is read: it is used
 *  once, and the connection details it may carry do not linger. */
export function takeBuilderHandoff(
  storage: BuilderStorage | null = defaultStorage('sessionStorage'),
): BuilderHandoff | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(BUILDER_HANDOFF_KEY);
    storage.removeItem(BUILDER_HANDOFF_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed) || typeof parsed.dataRoot !== 'string' || !parsed.dataRoot.trim()) {
      return null;
    }
    const s = isRecord(parsed.storage) ? parsed.storage : null;
    const text = (v: unknown) => (typeof v === 'string' && v ? v : null);
    return {
      dataRoot: parsed.dataRoot.trim(),
      storage: s
        ? {
            endpoint_url: text(s.endpoint_url),
            region: text(s.region),
            access_key_id: text(s.access_key_id),
            secret_access_key: text(s.secret_access_key),
          }
        : null,
    };
  } catch {
    return null;
  }
}
