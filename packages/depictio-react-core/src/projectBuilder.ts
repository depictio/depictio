/**
 * The Project Builder's draft: the project a reader assembles from a folder
 * (workflows, each holding data collections, and the links between those
 * collections), the reducer every edit goes through, and the rules `POST
 * /projects/builder/template` enforces, checked here first so the page can
 * say what is wrong before asking the server.
 *
 * The shapes mirror the HTTP contract of `/depictio/api/v1/projects/builder/*`
 * (`BuilderDcDraft`, `BuilderWorkflowDraft`, `BuilderProjectDraft`, contract
 * v2). The reducer's state adds what only the page needs (a stable id per
 * workflow, the repository metadata last fetched, the files and the schema
 * each collection matched), and `toProjectDraft` strips it before anything is
 * sent.
 *
 * What the server can build is not fixed: `GET /builder/capabilities` lists
 * the collection types, table formats, reader options and link targets it
 * takes. A type it does not have is offered disabled and never sent; until
 * the capabilities are read, the page assumes the v1 builder
 * (`fallbackBuilderCapabilities`).
 *
 * A draft is kept in localStorage per data root, so a refresh does not lose
 * the work. The private bucket's connection details never enter the draft:
 * they stay in the page's state.
 */

import type { BuilderCapabilities, BuilderRepoMetadata, RunStorageIn } from './api';

// ── Contract shapes ─────────────────────────────────────────────────────────

export type BuilderDcType =
  | 'table'
  | 'multiqc'
  | 'image'
  | 'indexed_file'
  | 'geojson'
  | 'phylogeny'
  | 'genomic_tracks'
  | 'bioimage';

/** Every type, in the order the type picker lists them. */
export const BUILDER_DC_TYPES: readonly BuilderDcType[] = [
  'table',
  'multiqc',
  'image',
  'indexed_file',
  'genomic_tracks',
  'bioimage',
  'geojson',
  'phylogeny',
];

/** The types every server builds: what the picker offers until the server's
 *  capabilities say more. */
export const CORE_DC_TYPES: readonly BuilderDcType[] = [
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

/** Types whose metatype can be set by hand (automatic otherwise). */
export const METATYPE_DC_TYPES: ReadonlySet<BuilderDcType> = new Set<BuilderDcType>([
  'table',
  'image',
  'genomic_tracks',
]);

/** Null/absent is automatic: one file is Metadata, a scan Aggregate. */
export type BuilderMetatype = 'Metadata' | 'Aggregate';

export type BuilderScanMode = 'single' | 'recursive';

/** A `{name}` placeholder of a scan regex and the regex its value matches:
 *  each becomes a column of the collection (e.g. the sample, from its
 *  folder). */
export interface BuilderWildcard {
  name: string;
  regex: string;
}

/** Reader options of a csv/tsv table (polars `read_csv` arguments). */
export interface BuilderReaderOptions {
  has_header?: boolean;
  skip_rows?: number;
  comment_prefix?: string;
  null_values?: string[];
  quote_char?: string;
  decimal_comma?: boolean;
}

/** The table formats reader options apply to. */
export const READER_FORMATS: ReadonlySet<string> = new Set(['csv', 'tsv']);

/** A table read from a SpatialData store (a capability-gated table format). */
export const SPATIALDATA_FORMAT = 'spatialdata';

/** The coordinate system every map defaults to. */
export const DEFAULT_CRS = 'EPSG:4326';

export type BuilderSpatialCoordinates = 'auto' | 'obsm' | 'region';

/** Which parts of a SpatialData store a table collection reads. */
export interface BuilderSpatialDataTableSource {
  /** `tables/<name>`; the server defaults to `tables/table`. */
  table?: string;
  /** `images/<name>`. */
  image?: string | null;
  coordinates?: BuilderSpatialCoordinates;
  genes?: string[];
  layer?: string | null;
}

export interface BuilderTableProps {
  kind: 'table';
  format: string;
  separator?: string | null;
  columns_description?: Record<string, string>;
  /** csv/tsv only. */
  reader?: BuilderReaderOptions | null;
  /** Map coordinates: both or none. */
  lat_column?: string | null;
  lon_column?: string | null;
  crs?: string | null;
  /** Required iff `format` is `spatialdata`. */
  spatialdata?: BuilderSpatialDataTableSource | null;
}

export interface BuilderMultiQCProps {
  kind: 'multiqc';
}

export interface BuilderImageProps {
  kind: 'image';
  /** The table listing the images: csv, tsv, parquet, ..., or `mixed`. */
  format: string;
  separator?: string | null;
  image_column: string;
  /** Folder of the images, relative to the data root. */
  local_images_path?: string | null;
  /** `s3://...`: where `depictio ingest` uploads the images. */
  s3_base_folder?: string | null;
  /** csv/tsv only. */
  reader?: BuilderReaderOptions | null;
  columns_description?: Record<string, string>;
  /** Pixels, 50 to 1000. */
  thumbnail_size?: number | null;
  /** Image extensions to accept (`.png`...). */
  supported_formats?: string[] | null;
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

/** A reference genome the server has no preset for. Each `*_uri` is a path
 *  relative to the data root, or an `https://` or `s3://` location. */
export interface BuilderCustomAssembly {
  name: string;
  display_name?: string | null;
  aliases?: string[];
  twobit_uri?: string | null;
  chrom_sizes_uri?: string | null;
  fasta_uri?: string | null;
  fai_uri?: string | null;
  gzi_uri?: string | null;
  refname_aliases_uri?: string | null;
}

/** The manifest-table columns a genomic tracks collection can map. */
export const TRACK_COLUMN_FIELDS = [
  'uri_column',
  'sample_column',
  'format_column',
  'index_column',
  'name_column',
  'color_column',
  'category_column',
  'order_column',
  'track_id_column',
] as const;

export type BuilderTrackColumnField = (typeof TRACK_COLUMN_FIELDS)[number];

/** Genomic tracks: a manifest table, one row per track file. */
export interface BuilderGenomicTracksProps {
  kind: 'genomic_tracks';
  /** The MANIFEST's format (csv, tsv, parquet...). */
  format: string;
  separator?: string | null;
  uri_column?: string;
  sample_column?: string | null;
  format_column?: string | null;
  index_column?: string | null;
  name_column?: string | null;
  color_column?: string | null;
  category_column?: string | null;
  order_column?: string | null;
  track_id_column?: string | null;
  default_format?: string | null;
  /** A preset of the server (`capabilities.genomic_tracks.assemblies`), or a
   *  custom one. */
  assembly: string | BuilderCustomAssembly;
  /** The folder relative URIs resolve against, relative to the data root:
   *  absent for the manifest's own folder, `''` for the data root. */
  tracks_base_path?: string | null;
}

export type BuilderBioimageFormat = 'ome-zarr' | 'ome-tiff' | 'spatialdata';

export const BUILDER_BIOIMAGE_FORMATS: readonly BuilderBioimageFormat[] = [
  'ome-zarr',
  'ome-tiff',
  'spatialdata',
];

export interface BuilderBioimageProps {
  kind: 'bioimage';
  format: BuilderBioimageFormat;
  /** Null: any version. */
  ngff_version?: '0.4' | '0.5' | null;
  /** Default true; false only references the files (the server must see the
   *  same path). */
  upload?: boolean;
  /** `images/<name>` of a store; required for `spatialdata`. */
  image_path?: string | null;
}

export type BuilderDcProps =
  | BuilderTableProps
  | BuilderMultiQCProps
  | BuilderImageProps
  | BuilderIndexedFileProps
  | BuilderGeoJSONProps
  | BuilderPhylogenyProps
  | BuilderGenomicTracksProps
  | BuilderBioimageProps;

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
  /** Null/absent: automatic. Table, image and genomic tracks only. */
  metatype?: BuilderMetatype | null;
  /** Recursive only: the `{name}` placeholders of `regex`. */
  wildcards?: BuilderWildcard[];
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

export type BuilderLinkResolver = 'direct' | 'sample_mapping' | 'pattern' | 'regex' | 'wildcard';

export const BUILDER_LINK_RESOLVERS: readonly BuilderLinkResolver[] = [
  'direct',
  'sample_mapping',
  'pattern',
  'regex',
  'wildcard',
];

/** A dashboard filter on one collection that follows another. The target's
 *  type is derived server-side from the target collection. */
export interface BuilderLinkDraft {
  source_tag: string;
  source_column: string;
  target_tag: string;
  resolver?: BuilderLinkResolver;
  /** The target column (table, image), `sample_name` (MultiQC), the sample
   *  column (genomic tracks). */
  target_field?: string | null;
  /** Resolver `pattern` only; holds `{sample}`. */
  pattern?: string | null;
  description?: string | null;
}

/** The types a link may read from. */
export const LINK_SOURCE_TYPES: ReadonlySet<BuilderDcType> = new Set<BuilderDcType>([
  'table',
  'image',
  'genomic_tracks',
]);

export interface BuilderProjectDraft {
  name: string;
  description?: string;
  is_public?: boolean;
  realtime?: boolean;
  data_management_platform_project_url?: string | null;
  workflows: BuilderWorkflowDraft[];
  links?: BuilderLinkDraft[];
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
  /** Optional: the project's page on a data management platform. */
  data_management_platform_project_url: string;
}

export interface BuilderState {
  version: 1;
  project: BuilderProjectFields;
  workflows: BuilderWorkflowState[];
  activeWorkflowId: string;
  /** Between collections of any workflow, by tag. */
  links: BuilderLinkDraft[];
  /** The files each collection matched when it was saved, by tag: the file
   *  tree tags them. Never sent. */
  claimed: Record<string, string[]>;
  /** column → dtype of each collection's first file when it was saved, by
   *  tag: the link editor's column pickers. Never sent. */
  schemas: Record<string, Record<string, string>>;
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

export const EMPTY_PROJECT_FIELDS: BuilderProjectFields = {
  name: '',
  description: '',
  is_public: false,
  realtime: false,
  data_management_platform_project_url: '',
};

export function initialBuilderState(): BuilderState {
  return {
    version: 1,
    project: { ...EMPTY_PROJECT_FIELDS },
    workflows: [newWorkflow('wf-0', DEFAULT_WORKFLOW_NAME)],
    activeWorkflowId: 'wf-0',
    links: [],
    claimed: {},
    schemas: {},
    nextId: 1,
  };
}

// ── Capabilities ────────────────────────────────────────────────────────────

/** The table formats every server reads. */
export const CORE_TABLE_FORMATS: readonly string[] = ['csv', 'tsv', 'parquet', 'feather', 'xlsx'];

/** What the page assumes until the server says what it builds, or when it
 *  cannot: the v1 builder (the six core types, the core table formats, no
 *  reader options nor links, realtime status unknown). */
export function fallbackBuilderCapabilities(
  mode: 'server' | 'standalone' = 'server',
): BuilderCapabilities {
  return {
    mode,
    dc_types: CORE_DC_TYPES.map((type) => ({ type, available: true, reason: null })),
    table_formats: [...CORE_TABLE_FORMATS],
    reader_options: [],
    link_target_types: [],
    realtime: { events_enabled: null, reason: null },
    genomic_tracks: null,
    bioimage: null,
  };
}

export interface DcTypeAvailability {
  type: BuilderDcType;
  available: boolean;
  /** Why not; null when available. */
  reason: string | null;
}

/** Whether the server builds `type`, and why not. A type it does not list
 *  is unavailable. */
export function dcTypeAvailability(
  type: BuilderDcType,
  capabilities: BuilderCapabilities,
): DcTypeAvailability {
  const listed = capabilities.dc_types.find((t) => t.type === type);
  if (!listed) {
    return { type, available: false, reason: 'This server does not build this kind of collection.' };
  }
  if (listed.available) return { type, available: true, reason: null };
  return { type, available: false, reason: listed.reason || 'Not available on this server.' };
}

/** The types the picker lists (available or not, as the server reports
 *  them), in the picker's order. */
export function offeredDcTypes(capabilities: BuilderCapabilities): BuilderDcType[] {
  const listed = new Set(capabilities.dc_types.map((t) => t.type));
  return BUILDER_DC_TYPES.filter((type) => listed.has(type));
}

/** True when a link may target a collection of `type`. */
export function linkTargetAllowed(type: BuilderDcType, capabilities: BuilderCapabilities): boolean {
  return capabilities.link_target_types.includes(type);
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
  const stem = base
    .replace(/\.(gz|bz2|zst|xz)$/i, '')
    .replace(/\.ome\.(tiff?|zarr)$/i, '')
    .replace(/\.[^.]+$/, '');
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

/** A `*.zarr` folder: read as one store, never opened. */
export function isStorePath(path: string): boolean {
  return /\.zarr$/i.test(path.trim().replace(/\/+$/, ''));
}

const TRACK_FILE = /\.(bw|bigwig|bb|bigbed|bam|cram|bedgraph|narrowpeak|broadpeak|gff3|gtf|bed|vcf)(\.gz)?$/i;

/** A genomic track file (bigWig, BAM, VCF, BED...), as opposed to a table
 *  listing tracks. */
export function isTrackFilePath(path: string): boolean {
  return TRACK_FILE.test(path.trim());
}

/** The table format a file name suggests, and its separator. */
export function formatFromPath(path: string): { format: string; separator: string | null } {
  const name = path.toLowerCase().replace(/\/+$/, '').replace(/\.(gz|bz2|zst|xz)$/, '');
  if (name.endsWith('.tsv') || name.endsWith('.tab') || name.endsWith('.txt')) {
    return { format: 'tsv', separator: '\t' };
  }
  if (name.endsWith('.csv')) return { format: 'csv', separator: ',' };
  if (name.endsWith('.parquet')) return { format: 'parquet', separator: null };
  if (name.endsWith('.feather') || name.endsWith('.arrow')) {
    return { format: 'feather', separator: null };
  }
  if (name.endsWith('.xlsx')) return { format: 'xlsx', separator: null };
  if (name.endsWith('.xls')) return { format: 'xls', separator: null };
  if (name.endsWith('.zarr')) return { format: SPATIALDATA_FORMAT, separator: null };
  const ext = name.match(/\.([a-z0-9]+)$/)?.[1];
  return { format: ext ?? 'csv', separator: ext ? null : ',' };
}

/** The server's indexed-file format for a file name (IndexedFileFormat): VCF
 *  unless the extension says otherwise; any other bgzipped table is tabix. */
export function indexedFormatOf(path: string): string {
  const name = path.toLowerCase();
  const byExtension: [RegExp, string][] = [
    [/\.vcf(\.gz)?$/, 'vcf'],
    [/\.bam$/, 'bam'],
    [/\.(bw|bigwig)$/, 'bigwig'],
    [/\.(bb|bigbed)$/, 'bigbed'],
    [/\.gff3?(\.gz)?$/, 'gff3'],
    [/\.(fa|fasta|fna)$/, 'fasta'],
    [/\.gz$/, 'tabix'],
  ];
  return byExtension.find(([pattern]) => pattern.test(name))?.[1] ?? 'vcf';
}

/** The assembly a genomic tracks collection starts with when the server
 *  lists no presets (standalone: the presets live in the API). */
export const DEFAULT_FREE_ASSEMBLY = 'hg38';

/** Properties seeded with what the server offers: a genomic tracks
 *  collection's assembly starts as `hg38` when there are no presets to pick
 *  from. */
export function seedPropsForCapabilities(
  props: BuilderDcProps,
  capabilities: BuilderCapabilities,
): BuilderDcProps {
  if (
    props.kind === 'genomic_tracks' &&
    props.assembly === '' &&
    (capabilities.genomic_tracks?.assemblies ?? []).length === 0
  ) {
    return { ...props, assembly: DEFAULT_FREE_ASSEMBLY };
  }
  return props;
}

/** The bioimage format of a path: OME-TIFF for `*.ome.tif(f)`, else the
 *  format given when it is one, else OME-Zarr. */
export function bioimageFormatOf(path: string | null | undefined, format?: string | null): BuilderBioimageFormat {
  if (/\.ome\.tiff?$/i.test(path ?? '')) return 'ome-tiff';
  if (format && (BUILDER_BIOIMAGE_FORMATS as readonly string[]).includes(format)) {
    return format as BuilderBioimageFormat;
  }
  return 'ome-zarr';
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
      return format === SPATIALDATA_FORMAT
        ? { kind: 'table', format, spatialdata: {} }
        : { kind: 'table', format, separator };
    case 'multiqc':
      return { kind: 'multiqc' };
    case 'image':
      return { kind: 'image', format, separator, image_column: '' };
    case 'indexed_file':
      return { kind: 'indexed_file', format: indexedFormatOf(hint.path ?? '') };
    case 'geojson':
      return { kind: 'geojson', feature_id_key: '' };
    case 'phylogeny': {
      const nexus = /\.(nex|nexus)$/i.test(hint.path ?? '');
      return { kind: 'phylogeny', format: nexus ? 'nexus' : 'newick', ladderize: true };
    }
    case 'genomic_tracks': {
      // The manifest's format: the path's when it is a table, else TSV (a
      // track file was picked; its manifest is still to come).
      const path = hint.path ?? '';
      const manifest =
        path && !isTrackFilePath(path) && !isStorePath(path)
          ? formatFromPath(path)
          : { format: 'tsv', separator: '\t' };
      return {
        kind: 'genomic_tracks',
        format: manifest.format,
        separator: manifest.separator,
        uri_column: 'uri',
        assembly: '',
      };
    }
    case 'bioimage':
      return { kind: 'bioimage', format: bioimageFormatOf(hint.path, hint.format), upload: true };
    default:
      return { kind: 'table', format, separator };
  }
}

// ── Links ───────────────────────────────────────────────────────────────────

/** The resolver a link to a collection of `targetType` starts with. */
export function defaultLinkResolver(targetType: BuilderDcType | null | undefined): BuilderLinkResolver {
  return targetType === 'multiqc' ? 'sample_mapping' : 'direct';
}

/** The target field a link to `target` starts with: `sample_name` for
 *  MultiQC, the sample column of genomic tracks, else the source column when
 *  the target has it. */
export function defaultLinkTargetField(
  target: BuilderDcDraft | null | undefined,
  sourceColumn: string,
  targetColumns: string[] = [],
): string | null {
  if (!target) return null;
  if (target.type === 'multiqc') return 'sample_name';
  if (target.props.kind === 'genomic_tracks') return target.props.sample_column?.trim() || null;
  if (sourceColumn && targetColumns.includes(sourceColumn)) return sourceColumn;
  return null;
}

/** Collections a link may read from: tables, images and genomic tracks. */
export function linkSourceTags(state: BuilderState): string[] {
  return allBuilderDcs(state)
    .filter(({ dc }) => LINK_SOURCE_TYPES.has(dc.type))
    .map(({ dc }) => dc.tag);
}

/** Collections a link from `sourceTag` may target: any other whose type the
 *  server takes as a link target. */
export function linkTargetTags(
  state: BuilderState,
  capabilities: BuilderCapabilities,
  sourceTag: string | null,
): string[] {
  return allBuilderDcs(state)
    .filter(({ dc }) => dc.tag !== sourceTag && linkTargetAllowed(dc.type, capabilities))
    .map(({ dc }) => dc.tag);
}

/** A fresh link: the first source and target that fit. */
export function newLinkDraft(state: BuilderState, capabilities: BuilderCapabilities): BuilderLinkDraft {
  const source = linkSourceTags(state)[0] ?? '';
  const targetTag = linkTargetTags(state, capabilities, source || null)[0] ?? '';
  const target = targetTag ? findBuilderDc(state, targetTag)?.dc : null;
  return {
    source_tag: source,
    source_column: '',
    target_tag: targetTag,
    resolver: defaultLinkResolver(target?.type),
    target_field: defaultLinkTargetField(target, ''),
  };
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
      /** column → dtype of its first file, for the link editor. */
      schema?: Record<string, string> | null;
    }
  | { type: 'dc/remove'; tag: string }
  | { type: 'dc/move'; tag: string; workflowId: string }
  | { type: 'dc/schema'; tag: string; schema: Record<string, string> }
  | { type: 'link/add'; link: BuilderLinkDraft }
  | { type: 'link/patch'; index: number; patch: Partial<BuilderLinkDraft> }
  | { type: 'link/remove'; index: number }
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
      const schemas = { ...state.schemas };
      for (const dc of doomed.data_collections) {
        delete claimed[dc.tag];
        delete schemas[dc.tag];
      }
      return {
        ...state,
        workflows,
        claimed,
        schemas,
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

      let { links } = state;
      if (renamed) {
        // A phylogeny reading the renamed table follows it, and so do links.
        workflows = mapDcs({ ...state, workflows }, (d) =>
          d.props.kind === 'phylogeny' && d.props.metadata_dc_tag === original
            ? { ...d, props: { ...d.props, metadata_dc_tag: tag } }
            : d,
        );
        links = links.map((l) => ({
          ...l,
          source_tag: l.source_tag === original ? tag : l.source_tag,
          target_tag: l.target_tag === original ? tag : l.target_tag,
        }));
      }

      const claimed = { ...state.claimed };
      const previous = original ? claimed[original] : undefined;
      if (original) delete claimed[original];
      claimed[tag] = action.files ?? previous ?? (dc.mode === 'single' && dc.path ? [dc.path] : []);

      const schemas = { ...state.schemas };
      const previousSchema = original ? schemas[original] : undefined;
      if (original) delete schemas[original];
      const schema = action.schema ?? previousSchema;
      if (schema) schemas[tag] = schema;
      return { ...state, workflows, links, claimed, schemas };
    }

    case 'dc/remove': {
      // Links reading it stay, flagged, for the reader to repoint or drop.
      if (!findBuilderDc(state, action.tag)) return state;
      const claimed = { ...state.claimed };
      const schemas = { ...state.schemas };
      delete claimed[action.tag];
      delete schemas[action.tag];
      return {
        ...state,
        claimed,
        schemas,
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

    case 'dc/schema':
      if (!findBuilderDc(state, action.tag)) return state;
      return { ...state, schemas: { ...state.schemas, [action.tag]: action.schema } };

    case 'link/add':
      return { ...state, links: [...state.links, action.link] };

    case 'link/patch':
      if (!state.links[action.index]) return state;
      return {
        ...state,
        links: state.links.map((l, i) => (i === action.index ? { ...l, ...action.patch } : l)),
      };

    case 'link/remove':
      if (!state.links[action.index]) return state;
      return { ...state, links: state.links.filter((_, i) => i !== action.index) };

    case 'state/replace':
      return action.state;

    default:
      return state;
  }
}

// ── What is sent ────────────────────────────────────────────────────────────

/** Options of the functions that write what is sent. */
export interface BuilderSendOptions {
  /** The data root is an `s3://` location. */
  remote?: boolean;
  /** What the server builds: when given, nothing it does not take is sent
   *  (a collection of an unavailable type, a reader option it does not
   *  allow, a link to a target type it refuses, realtime it cannot honour). */
  capabilities?: BuilderCapabilities | null;
}

const blankToNull = (value: string | null | undefined): string | null => {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
};

const nonBlankList = (values: string[] | null | undefined): string[] =>
  (values ?? []).map((v) => v.trim()).filter(Boolean);

function describedColumns(
  described: Record<string, string> | null | undefined,
): Record<string, string> | null {
  const kept = Object.entries(described ?? {}).filter(([column, text]) => column.trim() && text.trim());
  return kept.length ? Object.fromEntries(kept.map(([column, text]) => [column, text.trim()])) : null;
}

/** The reader options as sent: csv/tsv only, defaults and blanks dropped,
 *  and only the options the server allows when it says which. */
export function normalizeReaderOptions(
  reader: BuilderReaderOptions | null | undefined,
  format: string,
  allowed?: readonly string[] | null,
): BuilderReaderOptions | null {
  if (!reader || !READER_FORMATS.has(format.trim().toLowerCase())) return null;
  const ok = (key: keyof BuilderReaderOptions) => !allowed || allowed.includes(key);
  const out: BuilderReaderOptions = {};
  if (reader.has_header === false && ok('has_header')) out.has_header = false;
  if (
    typeof reader.skip_rows === 'number' &&
    Number.isInteger(reader.skip_rows) &&
    reader.skip_rows > 0 &&
    ok('skip_rows')
  ) {
    out.skip_rows = reader.skip_rows;
  }
  const comment = blankToNull(reader.comment_prefix);
  if (comment && ok('comment_prefix')) out.comment_prefix = comment;
  const nulls = nonBlankList(reader.null_values);
  if (nulls.length && ok('null_values')) out.null_values = nulls;
  if (reader.quote_char && ok('quote_char')) out.quote_char = reader.quote_char;
  if (reader.decimal_comma === true && ok('decimal_comma')) out.decimal_comma = true;
  return Object.keys(out).length ? out : null;
}

function normalizeAssembly(
  assembly: string | BuilderCustomAssembly | null | undefined,
): string | BuilderCustomAssembly {
  if (!assembly || typeof assembly === 'string') return (assembly ?? '').trim();
  const out: BuilderCustomAssembly = { name: assembly.name.trim() };
  const display = blankToNull(assembly.display_name);
  if (display) out.display_name = display;
  const aliases = nonBlankList(assembly.aliases);
  if (aliases.length) out.aliases = aliases;
  for (const key of [
    'twobit_uri',
    'chrom_sizes_uri',
    'fasta_uri',
    'fai_uri',
    'gzi_uri',
    'refname_aliases_uri',
  ] as const) {
    const value = blankToNull(assembly[key]);
    if (value) out[key] = value;
  }
  return out;
}

function normalizeProps(dc: BuilderDcDraft, options: BuilderSendOptions): BuilderDcProps {
  const props =
    dc.props && dc.props.kind === dc.type ? dc.props : defaultDcProps(dc.type, { path: dc.path });
  const allowedReader = options.capabilities ? options.capabilities.reader_options : null;
  switch (props.kind) {
    case 'table': {
      const format = props.format.trim() || 'csv';
      const out: BuilderTableProps = { kind: 'table', format };
      const spatial = format === SPATIALDATA_FORMAT;
      const sep = props.separator ?? null;
      if (sep && !spatial) out.separator = sep;
      const described = describedColumns(props.columns_description);
      if (described) out.columns_description = described;
      const reader = normalizeReaderOptions(props.reader, format, allowedReader);
      if (reader) out.reader = reader;
      const lat = blankToNull(props.lat_column);
      const lon = blankToNull(props.lon_column);
      if (lat && lon && !spatial) {
        out.lat_column = lat;
        out.lon_column = lon;
        const crs = blankToNull(props.crs);
        if (crs) out.crs = crs;
      }
      if (spatial) {
        const source = props.spatialdata ?? {};
        const sd: BuilderSpatialDataTableSource = {};
        const table = blankToNull(source.table);
        const image = blankToNull(source.image);
        const layer = blankToNull(source.layer);
        const genes = nonBlankList(source.genes);
        if (table) sd.table = table;
        if (image) sd.image = image;
        if (source.coordinates && source.coordinates !== 'auto') sd.coordinates = source.coordinates;
        if (genes.length) sd.genes = genes;
        if (layer) sd.layer = layer;
        out.spatialdata = sd;
      }
      return out;
    }
    case 'multiqc':
      return { kind: 'multiqc' };
    case 'image': {
      const format = props.format.trim() || 'csv';
      const out: BuilderImageProps = {
        kind: 'image',
        format,
        image_column: props.image_column.trim(),
      };
      if (props.separator) out.separator = props.separator;
      const local = blankToNull(props.local_images_path);
      const s3 = blankToNull(props.s3_base_folder);
      if (local) out.local_images_path = local;
      if (s3) out.s3_base_folder = s3;
      const reader = normalizeReaderOptions(props.reader, format, allowedReader);
      if (reader) out.reader = reader;
      const described = describedColumns(props.columns_description);
      if (described) out.columns_description = described;
      if (typeof props.thumbnail_size === 'number') out.thumbnail_size = props.thumbnail_size;
      const extensions = nonBlankList(props.supported_formats);
      if (extensions.length) out.supported_formats = extensions;
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
    case 'genomic_tracks': {
      const format = props.format.trim() || 'tsv';
      const out: BuilderGenomicTracksProps = {
        kind: 'genomic_tracks',
        format,
        assembly: normalizeAssembly(props.assembly),
      };
      if (props.separator && READER_FORMATS.has(format)) out.separator = props.separator;
      for (const field of TRACK_COLUMN_FIELDS) {
        const value = blankToNull(props[field]);
        if (value) out[field] = value;
      }
      const defaultFormat = blankToNull(props.default_format);
      if (defaultFormat) out.default_format = defaultFormat;
      // `''` is meaningful (the data root); absent is the manifest's folder.
      if (typeof props.tracks_base_path === 'string') {
        out.tracks_base_path = props.tracks_base_path.trim().replace(/^\/+|\/+$/g, '');
      }
      return out;
    }
    case 'bioimage': {
      const out: BuilderBioimageProps = { kind: 'bioimage', format: props.format };
      const zarr = props.format !== 'ome-tiff';
      if (zarr && (props.ngff_version === '0.4' || props.ngff_version === '0.5')) {
        out.ngff_version = props.ngff_version;
      }
      if (props.upload === false) out.upload = false;
      const imagePath = blankToNull(props.image_path);
      if (zarr && imagePath) out.image_path = imagePath;
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
export function normalizeDcDraft(dc: BuilderDcDraft, options: BuilderSendOptions = {}): BuilderDcDraft {
  const out: BuilderDcDraft = {
    tag: dc.tag.trim(),
    type: dc.type,
    mode: dc.mode,
    props: normalizeProps(dc, options),
  };
  const description = dc.description?.trim();
  if (description) out.description = description;
  if (dc.optional) out.optional = true;
  if (dc.metatype && METATYPE_DC_TYPES.has(dc.type)) out.metatype = dc.metatype;
  if (dc.mode === 'single') {
    out.path = blankToNull(dc.path);
  } else {
    out.regex = blankToNull(dc.regex);
    const glob = blankToNull(dc.glob);
    if (glob) out.glob = glob;
    if (!options.remote) {
      if (typeof dc.max_depth === 'number' && dc.max_depth >= 0) out.max_depth = dc.max_depth;
      const ignore = nonBlankList(dc.ignore);
      if (ignore.length) out.ignore = ignore;
    }
    const wildcards = (dc.wildcards ?? [])
      .map((w) => ({ name: w.name.trim(), regex: w.regex.trim() }))
      .filter((w) => w.name || w.regex);
    if (wildcards.length) out.wildcards = wildcards;
  }
  return out;
}

/** One workflow as the server reads it (no page-only fields). */
export function normalizeWorkflowDraft(
  workflow: BuilderWorkflowDraft,
  options: BuilderSendOptions = {},
): BuilderWorkflowDraft {
  const capabilities = options.capabilities;
  const out: BuilderWorkflowDraft = {
    name: workflow.name.trim(),
    engine: (workflow.engine || DEFAULT_ENGINE).trim().toLowerCase(),
    structure: workflow.structure,
    data_collections: workflow.data_collections
      .filter((dc) => !capabilities || dcTypeAvailability(dc.type, capabilities).available)
      .map((dc) => normalizeDcDraft(dc, options)),
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

/** One link as the server reads it. */
export function normalizeLinkDraft(link: BuilderLinkDraft): BuilderLinkDraft {
  const out: BuilderLinkDraft = {
    source_tag: link.source_tag.trim(),
    source_column: link.source_column.trim(),
    target_tag: link.target_tag.trim(),
  };
  if (link.resolver) out.resolver = link.resolver;
  const field = blankToNull(link.target_field);
  if (field) out.target_field = field;
  if (link.resolver === 'pattern') {
    const pattern = blankToNull(link.pattern);
    if (pattern) out.pattern = pattern;
  }
  const description = blankToNull(link.description);
  if (description) out.description = description;
  return out;
}

/** The draft as `POST /projects/builder/template` takes it. */
export function toProjectDraft(state: BuilderState, options: BuilderSendOptions = {}): BuilderProjectDraft {
  const capabilities = options.capabilities;
  const draft: BuilderProjectDraft = {
    name: state.project.name.trim(),
    workflows: state.workflows.map((w) => normalizeWorkflowDraft(w, options)),
  };
  const description = state.project.description.trim();
  if (description) draft.description = description;
  if (state.project.is_public) draft.is_public = true;
  if (state.project.realtime && capabilities?.realtime.events_enabled !== false) draft.realtime = true;
  const dmp = blankToNull(state.project.data_management_platform_project_url);
  if (dmp) draft.data_management_platform_project_url = dmp;

  const sent = new Map(
    draft.workflows.flatMap((w) => w.data_collections.map((dc) => [dc.tag, dc] as const)),
  );
  const links = state.links
    .map(normalizeLinkDraft)
    .filter((l) => {
      const target = sent.get(l.target_tag);
      if (!sent.has(l.source_tag) || !target) return false;
      return !capabilities || linkTargetAllowed(target.type, capabilities);
    });
  if (links.length) draft.links = links;
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
  /** The link it is about, by position. */
  linkIndex?: number;
}

const WILDCARD_NAME = /^[A-Za-z_]\w*$/;
const TEMPLATE_VARIABLE_NAME = /^[A-Z0-9_]+$/;

/** What is wrong with a scan's wildcards: valid, unique names, each used as
 *  `{name}` in the regex, none read as a template variable. Empty for a
 *  single file (its wildcards are not sent). */
export function wildcardIssues(dc: Pick<BuilderDcDraft, 'mode' | 'regex' | 'wildcards'>): string[] {
  if (dc.mode !== 'recursive') return [];
  const messages: string[] = [];
  const regex = dc.regex ?? '';
  const seen = new Set<string>();
  for (const w of dc.wildcards ?? []) {
    const name = w.name.trim();
    if (!name && !w.regex.trim()) continue;
    if (!name) {
      messages.push('A wildcard has no name.');
      continue;
    }
    if (!WILDCARD_NAME.test(name)) {
      messages.push(`“${name}” is not a wildcard name: letters, digits and _, not starting with a digit.`);
    } else if (TEMPLATE_VARIABLE_NAME.test(name)) {
      messages.push(`Use a lowercase name: {${name}} reads as a template variable.`);
    }
    if (seen.has(name)) messages.push(`Two wildcards are named “${name}”.`);
    seen.add(name);
    if (!w.regex.trim()) messages.push(`Wildcard “${name}” has no regex.`);
    if (!regex.includes(`{${name}}`)) {
      messages.push(`The regex does not use {${name}}: write it where its value sits in the path.`);
    }
  }
  return messages;
}

/** What is wrong with a table's map coordinates: both or none, and two
 *  different columns. */
export function coordinatesIssue(props: BuilderTableProps): string | null {
  const lat = props.lat_column?.trim();
  const lon = props.lon_column?.trim();
  if (props.format === SPATIALDATA_FORMAT) return null;
  if (Boolean(lat) !== Boolean(lon)) return 'Map coordinates need both a latitude and a longitude column.';
  if (lat && lat === lon) return 'Latitude and longitude must be two different columns.';
  return null;
}

/** What is wrong with a genomic tracks collection's assembly. */
export function assemblyIssue(props: BuilderGenomicTracksProps): string | null {
  const { assembly } = props;
  if (typeof assembly === 'string') return assembly.trim() ? null : 'Pick the assembly the tracks are on.';
  if (!assembly.name.trim()) return 'Give the custom assembly a name.';
  return null;
}

export interface BuilderValidateOptions {
  /** The data root is an `s3://` location. */
  remote?: boolean;
  /** What the server builds; without it, nothing is checked against it. */
  capabilities?: BuilderCapabilities | null;
  /** Standalone: images are uploaded by `depictio ingest`, which needs their
   *  S3 folder. */
  mode?: 'server' | 'standalone';
}

/** What the template endpoint would refuse, and what deserves a look. On an
 *  `s3://` root (`remote`) indexed files, images and stores cannot be read. */
export function validateBuilderState(
  state: BuilderState,
  options: BuilderValidateOptions = {},
): BuilderIssue[] {
  const issues: BuilderIssue[] = [];
  const { capabilities } = options;
  const error = (code: string, message: string, extra: Partial<BuilderIssue> = {}) =>
    issues.push({ level: 'error', code, message, ...extra });
  const warn = (code: string, message: string, extra: Partial<BuilderIssue> = {}) =>
    issues.push({ level: 'warning', code, message, ...extra });

  if (!state.project.name.trim()) error('project_name', 'Give the project a name.');
  const dmp = state.project.data_management_platform_project_url.trim();
  if (dmp && !/^https?:\/\//.test(dmp)) {
    error('project_dmp_url', 'The data management platform URL must start with http:// or https://.');
  }

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
    if (capabilities) {
      const availability = dcTypeAvailability(dc.type, capabilities);
      if (!availability.available) {
        error('dc_type_unavailable', `“${label}”: ${availability.reason}`, extra);
        continue;
      }
    }
    if (dc.mode === 'single' && !dc.path?.trim()) {
      error('dc_path_missing', `“${label}” has no file.`, extra);
    }
    if (dc.mode === 'recursive' && !dc.regex?.trim()) {
      error('dc_regex_missing', `“${label}” has no scan pattern.`, extra);
    }
    for (const message of wildcardIssues(dc)) {
      error('dc_wildcard_invalid', `“${label}”: ${message}`, extra);
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
    if (props.kind === 'table') {
      const coordinates = coordinatesIssue(props);
      if (coordinates) error('table_coordinates', `“${label}”: ${coordinates}`, extra);
      if (props.format === SPATIALDATA_FORMAT) {
        if (capabilities && !capabilities.table_formats.includes(SPATIALDATA_FORMAT)) {
          error('table_format_unavailable', `“${label}”: this server does not read SpatialData tables.`, extra);
        } else if (options.remote) {
          error(
            'spatialdata_remote',
            `“${label}” reads a SpatialData store: stores are read from local folders, not S3.`,
            extra,
          );
        }
      }
    }
    if (props.kind === 'image') {
      if (!props.image_column.trim()) {
        error('image_column_missing', `“${label}”: name the column holding the image paths.`, extra);
      }
      const size = props.thumbnail_size;
      if (typeof size === 'number' && (size < 50 || size > 1000)) {
        error('image_thumbnail_size', `“${label}”: thumbnails are 50 to 1000 pixels.`, extra);
      }
      const s3 = props.s3_base_folder?.trim();
      if (s3 && !s3.startsWith('s3://')) {
        error('image_s3_base_folder', `“${label}”: the S3 folder of the images starts with s3://.`, extra);
      }
      if (!s3 && options.mode === 'standalone' && !options.remote) {
        warn(
          'image_s3_base_folder_missing',
          `“${label}”: depictio ingest uploads the images to an S3 folder; name it, or ingestion stops there.`,
          extra,
        );
      }
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
    if (props.kind === 'genomic_tracks') {
      const assembly = assemblyIssue(props);
      if (assembly) error('genomic_tracks_assembly', `“${label}”: ${assembly}`, extra);
      if (!props.uri_column?.trim()) {
        error('genomic_tracks_uri_column', `“${label}”: name the manifest column holding each track's file.`, extra);
      }
      if (dc.mode === 'single' && dc.path && isTrackFilePath(dc.path)) {
        error(
          'genomic_tracks_manifest_is_track',
          `“${label}” reads a track file as its manifest: pick a table listing the tracks, or generate one.`,
          extra,
        );
      }
    }
    if (props.kind === 'bioimage') {
      if (options.remote) {
        error(
          'bioimage_remote',
          `“${label}” is a bioimage collection: stores are read from local folders at ingest, not S3.`,
          extra,
        );
      }
      if (props.format === 'spatialdata' && !props.image_path?.trim()) {
        error('bioimage_image_path', `“${label}”: pick the store's image (images/<name>).`, extra);
      }
    }
  }

  issues.push(...linkIssues(state, capabilities ?? null));
  return issues;
}

/** What is wrong with each link: tags that exist, a source that is a table,
 *  an image or genomic tracks, a target the server takes, a source column, and a pattern
 *  holding `{sample}` for the pattern resolver. */
export function linkIssues(state: BuilderState, capabilities: BuilderCapabilities | null): BuilderIssue[] {
  const issues: BuilderIssue[] = [];
  state.links.forEach((link, linkIndex) => {
    const label = `Link ${linkIndex + 1}`;
    const error = (code: string, message: string) =>
      issues.push({ level: 'error', code, message: `${label}: ${message}`, linkIndex });
    const source = link.source_tag.trim() ? findBuilderDc(state, link.source_tag.trim())?.dc : null;
    const target = link.target_tag.trim() ? findBuilderDc(state, link.target_tag.trim())?.dc : null;
    if (!link.source_tag.trim()) error('link_source_missing', 'pick the collection it filters from.');
    else if (!source) error('link_source_missing', `“${link.source_tag}” is not a collection of this project.`);
    else if (!LINK_SOURCE_TYPES.has(source.type)) {
      error('link_source_type', `“${source.tag}” is not a table, image or genomic tracks collection.`);
    }
    if (!link.source_column.trim()) error('link_source_column', 'pick the column it filters on.');
    if (!link.target_tag.trim()) error('link_target_missing', 'pick the collection it filters.');
    else if (!target) error('link_target_missing', `“${link.target_tag}” is not a collection of this project.`);
    else if (source && target.tag === source.tag) error('link_target_same', 'a collection cannot filter itself.');
    else if (capabilities && !linkTargetAllowed(target.type, capabilities)) {
      error('link_target_type', `this server cannot filter a ${target.type} collection from a link.`);
    }
    if (link.resolver === 'pattern') {
      const pattern = link.pattern?.trim() ?? '';
      if (!pattern) error('link_pattern', 'the pattern resolver needs a pattern.');
      else if (!pattern.includes('{sample}')) error('link_pattern', 'the pattern must hold {sample}.');
    }
  });
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

/** Drafts written before the links and the v2 collection fields load as
 *  they are (every new field is optional), so the key keeps its version. */
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

const text = (value: unknown): string => (typeof value === 'string' ? value : '');

function parseDc(raw: unknown): BuilderDcDraft | null {
  if (!isRecord(raw)) return null;
  if (typeof raw.tag !== 'string') return null;
  if (!BUILDER_DC_TYPES.includes(raw.type as BuilderDcType)) return null;
  if (raw.mode !== 'single' && raw.mode !== 'recursive') return null;
  const dc = raw as unknown as BuilderDcDraft;
  const props = isRecord(raw.props) && raw.props.kind === raw.type
    ? (raw.props as unknown as BuilderDcProps)
    : defaultDcProps(dc.type, { path: typeof raw.path === 'string' ? raw.path : null });
  const out: BuilderDcDraft = { ...dc, props };
  if (raw.metatype !== 'Metadata' && raw.metatype !== 'Aggregate') delete out.metatype;
  if (Array.isArray(raw.wildcards)) {
    out.wildcards = raw.wildcards
      .filter(isRecord)
      .map((w) => ({ name: text(w.name), regex: text(w.regex) }));
  } else {
    delete out.wildcards;
  }
  return out;
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

function parseLink(raw: unknown): BuilderLinkDraft | null {
  if (!isRecord(raw)) return null;
  const link: BuilderLinkDraft = {
    source_tag: text(raw.source_tag),
    source_column: text(raw.source_column),
    target_tag: text(raw.target_tag),
  };
  if (BUILDER_LINK_RESOLVERS.includes(raw.resolver as BuilderLinkResolver)) {
    link.resolver = raw.resolver as BuilderLinkResolver;
  }
  if (typeof raw.target_field === 'string') link.target_field = raw.target_field;
  if (typeof raw.pattern === 'string') link.pattern = raw.pattern;
  if (typeof raw.description === 'string') link.description = raw.description;
  return link;
}

/** A stored draft, checked; null for anything that does not hold together.
 *  Fields a draft predates (links, schemas, the platform URL) start empty. */
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
  const schemas: Record<string, Record<string, string>> = {};
  if (isRecord(raw.schemas)) {
    for (const [tag, schema] of Object.entries(raw.schemas)) {
      if (!isRecord(schema)) continue;
      schemas[tag] = Object.fromEntries(
        Object.entries(schema).filter((e): e is [string, string] => typeof e[1] === 'string'),
      );
    }
  }
  const links = Array.isArray(raw.links)
    ? raw.links.map(parseLink).filter((l): l is BuilderLinkDraft => l !== null)
    : [];
  const active =
    typeof raw.activeWorkflowId === 'string' && typed.some((w) => w.id === raw.activeWorkflowId)
      ? raw.activeWorkflowId
      : typed[0].id;
  return {
    version: 1,
    project: {
      name: text(project.name),
      description: text(project.description),
      is_public: project.is_public === true,
      realtime: project.realtime === true,
      data_management_platform_project_url: text(project.data_management_platform_project_url),
    },
    workflows: typed,
    activeWorkflowId: active,
    links,
    claimed,
    schemas,
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
