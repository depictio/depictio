/**
 * Spec builder for file-backed `genome_view` tracks (`source: 'file'`).
 *
 * The table-backed path (`genomeSpySpec.ts`) fetches rows from
 * `/advanced_viz/data` and hands GenomeSpy a materialised dataset. That cannot
 * work for a 200 MB VCF or a bigWig: the point of those formats is that the
 * *browser* reads only the visible window, over HTTP range requests, through
 * the file's own index. GenomeSpy calls this a `lazy` data source, and it ships
 * one per format: indexedFasta (.fai), bigwig, bigbed, tabix, vcf (.tbi),
 * gff3 (.tbi) and bam (.bai). There is no CRAM source.
 *
 * So this file builds a different spec shape. No `datasets`, no `data.name`, no
 * `api.datasets.set()`: each lane declares its own `data.lazy` block pointing at
 * a presigned URL, and the domain the reader is looking at is what decides which
 * bytes get fetched. One lane per sample, vertically concatenated on the shared
 * genome axis, the same way the table path facets.
 *
 * Pure: no DOM, no React, no colour literals. `fileSpec.test.ts` covers it.
 *
 * Per-format layouts follow GenomeSpy's own published examples, which are the
 * reference for what each lazy source actually emits:
 *
 * - vcf: sticks and balls (a `rule` to a baseline plus a `point`), INFO keys
 *   promoted to columns by `formula` transforms, x from `CHROM`/`POS`.
 *   (`clinvar-variants.json`, windowSize 1000000)
 * - bigwig: `rect` bars from a baseline with `pixelsPerBin: 1`, x from
 *   `chrom`/`start`/`end`, y from `score`. (`sashimi-plot.json`)
 * - gff3: packed transcript lanes, `flatten` over child features then `pileup`
 *   into lanes. (`gff3-gene-annotations.json`, windowSize 2000000)
 * - bigbed / tabix: `rect` intervals, BED field names.
 * - bam: reads through the `coverage` transform (a profile) or the `pileup`
 *   transform (stacked reads).
 * - fasta: a reference sequence lane, only legible at base resolution.
 */

import type { Contig, GenomeSpyThemeColors } from './genomeSpySpec';
import { DATA_ASSEMBLY, GENOME_SCALE_NAME, BRUSH_PARAM, BUILTIN_ASSEMBLIES } from './genomeSpySpec';

/** Formats the `indexed_file` DC type accepts, mirroring the Pydantic Literal. */
export type IndexedFileFormat = 'vcf' | 'bam' | 'bigwig' | 'bigbed' | 'gff3' | 'fasta' | 'tabix';

export const INDEXED_FILE_FORMATS: readonly IndexedFileFormat[] = [
  'vcf',
  'bam',
  'bigwig',
  'bigbed',
  'gff3',
  'fasta',
  'tabix',
];

/** One sample's object, as `GET /files/indexed/{dc_id}` reports it. */
export interface IndexedFileEntry {
  sample: string;
  name: string;
  size_bytes?: number | null;
  /** Presigned, range-capable URL. Expires; see the manifest's `expires_in`. */
  url: string;
  /** Presigned URL of the index sidecar, or null for a self-indexed format. */
  index_url?: string | null;
}

/** The manifest route's payload. */
export interface IndexedFileManifest {
  data_collection_id: string;
  format: IndexedFileFormat;
  index_suffix: string;
  assembly: string | null;
  sample_col: string;
  expires_in: number;
  files: IndexedFileEntry[];
}

/**
 * Window sizes, in bases, below which each lazy source starts fetching.
 *
 * Not arbitrary: they are the values GenomeSpy's own examples use, and they are
 * the one setting that decides whether a track is usable or hammers the bucket.
 * A VCF at whole-genome zoom would otherwise try to parse every variant.
 * Formats absent here keep the library's default.
 */
export const DEFAULT_WINDOW_SIZE: Partial<Record<IndexedFileFormat, number>> = {
  vcf: 1_000_000,
  gff3: 2_000_000,
  bigbed: 1_000_000,
  tabix: 1_000_000,
};

/** Columns assumed for a bgzip+tabix interval file when the config names none. */
export const DEFAULT_TABIX_COLUMNS: readonly string[] = [
  'chrom',
  'chromStart',
  'chromEnd',
  'name',
  'score',
  'strand',
];

export interface FileTrackOptions {
  /** Prepend `chr` (true) or a custom string to the file's contig names. */
  addChrPrefix?: boolean | string;
  /** Override the per-format window size, in bases. */
  windowSize?: number | null;
  /** bigwig only: bin width in pixels. 1 is the per-pixel coverage look. */
  pixelsPerBin?: number;
  /** vcf only: INFO keys promoted to top-level columns before encoding. */
  infoFields?: readonly string[] | null;
  /** vcf only: which promoted field drives the y axis and the colour. */
  categoryField?: string | null;
  /** vcf only: ordinal domain for `categoryField`, in the order to draw it. */
  categories?: readonly string[] | null;
  /** tabix only: field names, in file column order. */
  tabixColumns?: readonly string[] | null;
  /** bam only: a coverage profile or stacked reads. */
  bamView?: 'coverage' | 'pileup';
  /** Upper bound on lanes; samples beyond it are reported, not drawn. */
  maxLanes?: number;
  /** Mark opacity, from the tile's cosmetic controls. */
  opacity?: number;
  /** Point diameter in pixels, for the vcf balls. */
  pointSize?: number;
}

export interface BuildFileSpecInput {
  manifest: IndexedFileManifest;
  options?: FileTrackOptions;
  colors: GenomeSpyThemeColors;
  /** Contigs of a built-in assembly; null derives nothing and leaves the axis
   *  to the assembly name, which a lazy source needs to linearise positions. */
  assemblyContigs?: readonly Contig[] | null;
  /** Assembly override from the component config; falls back to the DC's. */
  assembly?: string | null;
  /** Declare the region brush param on the root. */
  regionBrushEnabled?: boolean;
}

export interface BuiltFileSpec {
  spec: Record<string, unknown>;
  /** Contigs the locus scale linearises over, for turning a brush back into a
   *  region. Empty when the assembly is a built-in one resolved by GenomeSpy. */
  contigs: Contig[];
  /** Samples that got a lane, in manifest order. */
  lanes: string[];
  /** Samples `maxLanes` left out. */
  droppedLanes: number;
  format: IndexedFileFormat;
}

const LANE_HEIGHT = 70;
const PILEUP_LANE_HEIGHT = 140;

/** True when `format` needs an index sidecar the manifest must supply. */
export function needsIndexUrl(format: IndexedFileFormat): boolean {
  return format === 'vcf' || format === 'gff3' || format === 'tabix' || format === 'bam' || format === 'fasta';
}

/**
 * The `data.lazy` block for one file.
 *
 * `indexUrl` is passed explicitly rather than left to the library's
 * `url + ".tbi"` default: our URLs are presigned, so the index's signature is a
 * different query string and cannot be derived from the primary file's.
 */
export function lazyDataFor(
  format: IndexedFileFormat,
  entry: IndexedFileEntry,
  options: FileTrackOptions = {},
): { lazy: Record<string, unknown> } {
  const windowSize =
    options.windowSize === null || options.windowSize === undefined
      ? DEFAULT_WINDOW_SIZE[format]
      : options.windowSize;

  const lazy: Record<string, unknown> = { type: format === 'fasta' ? 'indexedFasta' : format, url: entry.url };
  if (needsIndexUrl(format)) {
    if (!entry.index_url) {
      throw new Error(`${format} track for ${entry.sample}: the index sidecar is missing`);
    }
    lazy.indexUrl = entry.index_url;
  }
  if (windowSize !== undefined && format !== 'bigwig') {
    lazy.windowSize = windowSize;
  }
  if (format === 'bigwig') {
    lazy.pixelsPerBin = options.pixelsPerBin ?? 1;
  }
  if (
    (format === 'vcf' || format === 'gff3' || format === 'tabix') &&
    options.addChrPrefix !== undefined &&
    options.addChrPrefix !== false
  ) {
    lazy.addChrPrefix = options.addChrPrefix;
  }
  if (format === 'tabix') {
    lazy.columns = [...(options.tabixColumns ?? DEFAULT_TABIX_COLUMNS)];
  }
  return { lazy };
}

/**
 * `formula` transforms promoting VCF INFO keys to top-level columns.
 *
 * Two things the expression has to survive, both observed against the public
 * ClinVar VCF:
 *
 * - a record can have no INFO at all, so `datum.INFO` is guarded;
 * - @gmod/vcf returns every INFO value as an **array**, even a single one
 *   (`CLNSIG` comes back as `["Pathogenic"]`). Left as an array it never
 *   matches an ordinal scale's domain, and the lane draws nothing at all, so
 *   the first element is taken. GenomeSpy's own ClinVar example hides this by
 *   passing the value straight to `replace()`, which coerces it to a string.
 */
export function infoFieldTransforms(fields: readonly string[] | null | undefined): unknown[] {
  if (!fields || fields.length === 0) return [];
  return fields.map((name) => {
    // Bracket access keeps keys with dots or dashes (ANN, CSQ, gnomAD_AF)
    // addressable.
    const value = `datum.INFO[${JSON.stringify(name)}]`;
    return {
      type: 'formula',
      expr: `datum.INFO == null ? null : (isArray(${value}) ? ${value}[0] : ${value})`,
      as: name,
    };
  });
}

function vcfLane(entry: IndexedFileEntry, options: FileTrackOptions, colors: GenomeSpyThemeColors) {
  const category = options.categoryField || null;
  const transforms: unknown[] = infoFieldTransforms(options.infoFields);

  const encoding: Record<string, unknown> = {
    x: { chrom: 'CHROM', pos: 'POS', type: 'locus', offset: 1, scale: { name: GENOME_SCALE_NAME } },
  };
  if (category) {
    const domain = options.categories && options.categories.length ? [...options.categories] : undefined;
    encoding.y = {
      field: category,
      type: 'ordinal',
      ...(domain ? { scale: { domain } } : {}),
      axis: { title: category },
    };
    encoding.color = {
      field: category,
      type: 'ordinal',
      ...(domain ? { scale: { domain, range: domain.map((_, i) => colors.palette[i % colors.palette.length]) } } : {}),
      legend: null,
    };
  } else {
    // No category to rank by: one row of balls on a constant lane, which is
    // the plain "where are the variants" view.
    encoding.y = { datum: 1, type: 'quantitative', scale: { domain: [0, 2] }, axis: null };
    encoding.color = { value: colors.palette[0] };
  }

  // The sticks run from each variant's band down to the bottom of the axis, so
  // the lane reads as a lollipop rather than a row of disconnected bands. With
  // an ordinal y that baseline is the first category; without one it is zero.
  const baseline =
    category && options.categories && options.categories.length ? options.categories[0] : 0;
  // One band per category, as the ClinVar example lays it out: a fixed lane
  // height would squeeze six classes into a few pixels each.
  const height =
    category && options.categories && options.categories.length ? { step: 14 } : undefined;

  return {
    name: `vcf-${entry.sample}`,
    title: { text: entry.sample, style: 'overlay' },
    ...(height ? { height } : {}),
    data: lazyDataFor('vcf', entry, options),
    ...(transforms.length ? { transform: transforms } : {}),
    encoding,
    layer: [
      {
        name: 'sticks',
        mark: { type: 'rule', tooltip: false, color: colors.gridColor },
        encoding: { y2: { datum: baseline } },
      },
      {
        name: 'balls',
        mark: {
          type: 'point',
          size: (options.pointSize ?? 5) ** 2 * 3,
          opacity: options.opacity ?? 0.85,
          geometricZoomBound: 13,
        },
      },
    ],
  };
}

function bigWigLane(entry: IndexedFileEntry, options: FileTrackOptions, colors: GenomeSpyThemeColors) {
  return {
    name: `bigwig-${entry.sample}`,
    title: { text: entry.sample, style: 'overlay' },
    data: lazyDataFor('bigwig', entry, options),
    transform: [{ type: 'filter', expr: 'datum.score > 0' }],
    encoding: {
      x: { chrom: 'chrom', pos: 'start', type: 'locus', scale: { name: GENOME_SCALE_NAME } },
      x2: { chrom: 'chrom', pos: 'end' },
      y: {
        field: 'score',
        type: 'quantitative',
        scale: { nice: true, zero: true },
        title: 'Coverage',
      },
    },
    mark: {
      type: 'rect',
      color: colors.palette[0],
      opacity: options.opacity ?? 0.85,
      // Sub-pixel bins would otherwise disappear between two ticks.
      minWidth: 0.5,
      minOpacity: 1,
      tooltip: null,
    },
  };
}

function intervalLane(
  format: 'bigbed' | 'tabix',
  entry: IndexedFileEntry,
  options: FileTrackOptions,
  colors: GenomeSpyThemeColors,
) {
  const columns = format === 'tabix' ? (options.tabixColumns ?? DEFAULT_TABIX_COLUMNS) : DEFAULT_TABIX_COLUMNS;
  const [chromField, startField, endField] = columns;
  return {
    name: `${format}-${entry.sample}`,
    title: { text: entry.sample, style: 'overlay' },
    data: lazyDataFor(format, entry, options),
    transform: [
      { type: 'collect', sort: { field: [chromField, startField] } },
      { type: 'pileup', start: startField, end: endField, as: '_lane' },
    ],
    encoding: {
      x: { chrom: chromField, pos: startField, type: 'locus', offset: 1, scale: { name: GENOME_SCALE_NAME } },
      x2: { chrom: chromField, pos: endField },
      y: {
        field: '_lane',
        type: 'index',
        scale: { zoom: false, reverse: true, domain: [0, 10], padding: 0.3 },
        axis: null,
      },
      color: { value: colors.palette[0] },
    },
    mark: { type: 'rect', minWidth: 1, minOpacity: 1, opacity: options.opacity ?? 0.85 },
  };
}

function gff3Lane(entry: IndexedFileEntry, options: FileTrackOptions, colors: GenomeSpyThemeColors) {
  // Shape lifted from GenomeSpy's own gff3-gene-annotations example: the source
  // emits genes with nested `child_features`, so the transcripts have to be
  // flattened out before they can be packed into lanes.
  return {
    name: `gff3-${entry.sample}`,
    title: { text: entry.sample, style: 'overlay' },
    data: lazyDataFor('gff3', entry, options),
    transform: [
      { type: 'flatten' },
      { type: 'formula', expr: 'datum.attributes.gene_name', as: 'gene_name' },
      { type: 'flatten', fields: ['child_features'] },
      { type: 'flatten', fields: ['child_features'], as: ['child_feature'] },
      {
        type: 'project',
        fields: [
          'gene_name',
          'child_feature.type',
          'child_feature.strand',
          'child_feature.seq_id',
          'child_feature.start',
          'child_feature.end',
          'child_feature.attributes.transcript_id',
        ],
        as: ['gene_name', 'type', 'strand', 'seq_id', 'start', 'end', 'transcript_id'],
      },
      { type: 'collect', sort: { field: ['seq_id', 'start', 'transcript_id'] } },
      { type: 'pileup', start: 'start', end: 'end', as: '_lane' },
    ],
    encoding: {
      x: { chrom: 'seq_id', pos: 'start', type: 'locus', offset: 1, scale: { name: GENOME_SCALE_NAME } },
      x2: { chrom: 'seq_id', pos: 'end' },
      y: {
        field: '_lane',
        type: 'index',
        scale: { zoom: false, reverse: true, domain: [0, 20], padding: 0.5 },
        axis: null,
      },
    },
    layer: [
      {
        name: 'transcript-body',
        mark: { type: 'rule', color: colors.gridColor, size: 1, tooltip: null },
      },
      {
        name: 'transcript-label',
        mark: {
          type: 'text',
          align: 'right',
          baseline: 'middle',
          dx: -6,
          color: colors.textColor,
          size: 10,
        },
        encoding: { text: { field: 'gene_name' } },
      },
    ],
  };
}

function bamLane(entry: IndexedFileEntry, options: FileTrackOptions, colors: GenomeSpyThemeColors) {
  const pileup = options.bamView === 'pileup';
  return {
    name: `bam-${entry.sample}`,
    title: { text: entry.sample, style: 'overlay' },
    data: lazyDataFor('bam', entry, options),
    transform: pileup
      ? [
          { type: 'collect', sort: { field: ['start'] } },
          { type: 'pileup', start: 'start', end: 'end', as: '_lane' },
        ]
      : [
          { type: 'collect', sort: { field: ['start'] } },
          { type: 'coverage', chrom: 'chrom', start: 'start', end: 'end', as: 'coverage' },
        ],
    encoding: pileup
      ? {
          x: { chrom: 'chrom', pos: 'start', type: 'locus', scale: { name: GENOME_SCALE_NAME } },
          x2: { chrom: 'chrom', pos: 'end' },
          y: {
            field: '_lane',
            type: 'index',
            scale: { zoom: false, reverse: true, domain: [0, 30], padding: 0.3 },
            axis: null,
          },
          color: { value: colors.palette[0] },
        }
      : {
          x: { chrom: 'chrom', pos: 'start', type: 'locus', scale: { name: GENOME_SCALE_NAME } },
          x2: { chrom: 'chrom', pos: 'end' },
          y: {
            field: 'coverage',
            type: 'quantitative',
            scale: { nice: true, zero: true },
            title: 'Coverage',
          },
          color: { value: colors.palette[0] },
        },
    mark: {
      type: 'rect',
      minWidth: pileup ? 1 : 0.5,
      minOpacity: 1,
      opacity: options.opacity ?? 0.85,
      ...(pileup ? {} : { tooltip: null }),
    },
  };
}

function fastaLane(entry: IndexedFileEntry, options: FileTrackOptions, colors: GenomeSpyThemeColors) {
  // A reference lane only legible at base resolution; the lazy source fetches
  // nothing until the visible span is under its window size.
  return {
    name: `fasta-${entry.sample}`,
    height: 20,
    data: lazyDataFor('fasta', entry, options),
    transform: [{ type: 'flattenSequence', field: 'sequence', as: ['rawPos', 'base'] }],
    encoding: {
      x: { chrom: 'chrom', pos: 'rawPos', type: 'locus', offset: 0.5, scale: { name: GENOME_SCALE_NAME } },
      color: { field: 'base', type: 'nominal', scale: { scheme: 'category10' }, legend: null },
      text: { field: 'base', type: 'nominal' },
    },
    mark: { type: 'text', size: 11, color: colors.textColor },
  };
}

/** One lane view for one sample's file, per format. */
export function laneSpecFor(
  format: IndexedFileFormat,
  entry: IndexedFileEntry,
  options: FileTrackOptions,
  colors: GenomeSpyThemeColors,
): Record<string, unknown> {
  switch (format) {
    case 'vcf':
      return vcfLane(entry, options, colors);
    case 'bigwig':
      return bigWigLane(entry, options, colors);
    case 'bigbed':
    case 'tabix':
      return intervalLane(format, entry, options, colors);
    case 'gff3':
      return gff3Lane(entry, options, colors);
    case 'bam':
      return bamLane(entry, options, colors);
    case 'fasta':
      return fastaLane(entry, options, colors);
    default: {
      const never: never = format;
      throw new Error(`Unsupported indexed file format: ${String(never)}`);
    }
  }
}

/**
 * The whole tile: one lane per sample on a shared genome axis.
 *
 * Returns `contigs` so the renderer can turn a brushed interval back into a
 * chromosome and a range, exactly as the table path does. A lazy source needs
 * the assembly to linearise its own coordinates, so a file-backed tile with no
 * assembly (neither on the DC nor on the config) is an error the renderer
 * reports rather than an empty canvas.
 */
export function buildFileGenomeSpec(input: BuildFileSpecInput): BuiltFileSpec {
  const { manifest, colors, assemblyContigs, regionBrushEnabled } = input;
  const options = input.options ?? {};
  const format = manifest.format;
  const assembly = input.assembly || manifest.assembly || null;

  if (!assembly) {
    throw new Error(
      'File-backed tracks need a genome assembly: set it on the data collection or on the tile.',
    );
  }

  const maxLanes = Math.max(1, options.maxLanes ?? 8);
  const usable = manifest.files.filter((f) => f.url && (!needsIndexUrl(format) || f.index_url));
  const lanes = usable.slice(0, maxLanes);
  const droppedLanes = usable.length - lanes.length;

  // Same two cases as the table path: a built-in assembly is named at the root
  // and GenomeSpy resolves its contigs, anything else ships its contig list
  // under the data-derived assembly name. A lazy source cannot derive contigs
  // from rows it has not fetched yet, so the caller must supply them.
  const builtin = BUILTIN_ASSEMBLIES.includes(assembly);
  const contigs: Contig[] = assemblyContigs ? [...assemblyContigs] : [];
  if (!builtin && contigs.length === 0) {
    throw new Error(
      `File-backed tracks on assembly "${assembly}" need its contig sizes; ` +
        'use a built-in assembly (hg38, hg19, hg18, mm10, mm9, dm6) or supply contigs.',
    );
  }
  const laneHeight =
    format === 'bam' && options.bamView === 'pileup' ? PILEUP_LANE_HEIGHT : LANE_HEIGHT;

  const spec: Record<string, unknown> = {
    config: {
      view: { fill: null, stroke: null },
      axis: {
        labelColor: colors.textColor,
        titleColor: colors.textColor,
        tickColor: colors.gridColor,
        domainColor: colors.gridColor,
        gridColor: colors.gridColor,
      },
    },
    assembly: builtin ? assembly : DATA_ASSEMBLY,
    // One genome axis under the whole stack; y stays per lane, because two
    // samples' coverage ranges are not comparable across formats.
    resolve: { axis: { x: 'shared' }, scale: { x: 'shared', y: 'independent' } },
    spacing: 8,
    vconcat: lanes.map((entry) => ({
      height: laneHeight,
      ...laneSpecFor(format, entry, options, colors),
    })),
  };
  if (!builtin) {
    spec.genomes = { [DATA_ASSEMBLY]: { contigs } };
  }

  if (regionBrushEnabled) {
    // Declared on the vconcat root, not per lane: GenomeSpy builds one
    // container-wide selection overlay for an interval param owned by a grid
    // view, so one drag brushes every lane at once.
    spec.params = [{ name: BRUSH_PARAM, select: { type: 'interval', encodings: ['x'] } }];
  }

  return { spec, contigs, lanes: lanes.map((l) => l.sample), droppedLanes, format };
}

/**
 * Read the `file_*` half of a `genome_view` config into track options.
 *
 * One place translates the config's names into this module's, so the renderer
 * never reads a config key the model does not declare
 * (`test_renderer_only_reads_config_keys_the_model_declares`).
 */
export function fileTrackOptions(
  config: GenomeViewConfigLike,
  overrides: Pick<FileTrackOptions, 'opacity' | 'pointSize'> = {},
): FileTrackOptions {
  return {
    addChrPrefix: config.file_add_chr_prefix ? true : undefined,
    windowSize: config.file_window_size ?? null,
    infoFields: config.file_info_fields ?? null,
    categoryField: config.file_category_field ?? null,
    categories: config.file_categories ?? null,
    tabixColumns: config.file_tabix_columns ?? null,
    bamView: config.file_bam_view ?? 'coverage',
    maxLanes: config.file_max_lanes ?? 8,
    opacity: overrides.opacity ?? config.opacity,
    pointSize: overrides.pointSize ?? config.point_size,
  };
}

/** The `genome_view` config keys this module reads, and only those. */
export interface GenomeViewConfigLike {
  opacity?: number;
  point_size?: number;
  file_info_fields?: string[] | null;
  file_category_field?: string | null;
  file_categories?: string[] | null;
  file_add_chr_prefix?: boolean;
  file_window_size?: number | null;
  file_max_lanes?: number;
  file_tabix_columns?: string[] | null;
  file_bam_view?: 'coverage' | 'pileup';
}

/** Fetch the manifest for a DC. Thin, so the renderer's effect stays readable
 *  and the tests can hand in their own fetcher. */
export async function fetchIndexedFileManifest(
  dcId: string,
  fetcher: (url: string) => Promise<Response>,
  apiBase = '',
): Promise<IndexedFileManifest> {
  const res = await fetcher(`${apiBase}/depictio/api/v1/files/indexed/${dcId}`);
  if (!res.ok) {
    throw new Error(`Indexed file manifest unavailable (${res.status})`);
  }
  return (await res.json()) as IndexedFileManifest;
}
