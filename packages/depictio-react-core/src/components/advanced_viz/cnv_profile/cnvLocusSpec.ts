/**
 * Pure GenomeSpy spec builder for the `cnv_profile` locus view.
 *
 * The layout is GenomeSpy's ASCAT example (genomespy.app playground,
 * `spec=ASCAT`), bound to the `cnv_profile` roles instead of ASCAT's own file
 * names. Top to bottom, per sample:
 *
 * 1. allele-specific copy number: nMajor and nMinor as two rules per segment,
 *    offset a few pixels apart so a balanced call reads as two parallel lines
 *    and an LOH as one line sitting on zero (only when `copy_number_col` is
 *    bound; a single total copy-number rule when the minor allele is not);
 * 2. log2 ratio: every bin as a point, the called segments as thick rules
 *    coloured gain / neutral / loss, the two thresholds as dotted rules;
 * 3. B-allele frequency: every bin as a point and the segment's BAF drawn
 *    mirrored (`baf` and `1 - baf`), which is how an allelic imbalance reads.
 *
 * One genome axis runs under the whole stack, zoomable, with the bundled gene
 * lane at the bottom when the tile asks for one. No DOM, no React, no colour
 * literals: vitest covers it in the node environment.
 */
import {
  BRUSH_PARAM,
  DATASET_NAME,
  DATA_ASSEMBLY,
  GENES_DATASET_NAME,
  GENOME_SCALE_NAME,
  contigsFromRows,
} from '../genomespy/genomeSpySpec';
import type { Contig, GeneRow } from '../genomespy/genomeSpySpec';
import { chromosomeSortKey, classifyLog2, decimateBins } from './cnvLayout';
import type { CnvClass, CnvRow } from './cnvLayout';

/** One row as GenomeSpy reads it. Field names are this module's own, not the
 *  collection's, so the spec never depends on how a template named its columns. */
export interface LocusDatum {
  sample: string;
  chrom: string;
  start: number;
  end: number;
  mid: number;
  log2: number;
  baf: number | null;
  /** `1 - baf` on segments: the mirrored band of an allelic imbalance. */
  baf_mirror: number | null;
  cn: number | null;
  minor: number | null;
  major: number | null;
  kind: 'bin' | 'segment';
  cls: CnvClass;
  label: string | null;
}

export interface CnvLocusColors {
  textColor: string;
  gridColor: string;
  bin: string;
  baf: string;
  segment: Record<CnvClass, string>;
  major: string;
  minor: string;
  gene: string;
}

export interface CnvLocusInput {
  data: readonly LocusDatum[];
  /** One entry per sample that gets its own set of tracks. A single entry
   *  when the tile is not faceted; the dataset then holds that sample only. */
  lanes: readonly string[];
  faceted: boolean;
  showBaf: boolean;
  yRange: number;
  pointSize: number;
  gainThreshold: number;
  lossThreshold: number;
  colors: CnvLocusColors;
  genes?: readonly GeneRow[] | null;
  /** Declare the interval brush that becomes the dashboard's region filter. */
  brush: boolean;
}

export interface BuiltCnvLocusSpec {
  spec: Record<string, unknown>;
  contigs: Contig[];
  geneCount: number;
  /** Which optional tracks made it into the spec, for the tile's echo line. */
  tracks: { copyNumber: 'allelic' | 'total' | null; baf: boolean };
}

/** Upper bound of the copy-number axis; higher calls are clamped onto it,
 *  exactly as ASCAT's own plot does. */
export const CN_AXIS_MAX = 6;
/** Samples a faceted tile stacks at most: three tracks each. */
export const MAX_LOCUS_LANES = 4;

const CN_TRACK_HEIGHT = 56;
const ANNOTATION_LANE_HEIGHT = 34;

/**
 * Parsed rows to the locus dataset.
 *
 * `samples` narrows to the samples that get tracks (null keeps every row). The
 * bins are averaged per sample down to `maxBins` in total, the same guard the
 * Plotly view applies; segments are never reduced, a call is what the reader
 * is reading.
 */
export function toLocusData(
  rows: readonly CnvRow[],
  opts: { samples: readonly string[] | null; gain: number; loss: number; maxBins: number },
): LocusDatum[] {
  const keep = opts.samples ? new Set(opts.samples) : null;
  const inScope = rows.filter((r) => keep === null || r.sample === '' || keep.has(r.sample));
  const bySample = new Map<string, CnvRow[]>();
  const segments: CnvRow[] = [];
  for (const r of inScope) {
    if (r.kind === 'segment') {
      segments.push(r);
      continue;
    }
    const list = bySample.get(r.sample);
    if (list) list.push(r);
    else bySample.set(r.sample, [r]);
  }
  const perSample = Math.max(1, Math.floor(opts.maxBins / Math.max(1, bySample.size)));
  const bins: CnvRow[] = [];
  for (const list of bySample.values()) {
    list.sort((a, b) => {
      const d = chromosomeSortKey(a.chrom) - chromosomeSortKey(b.chrom);
      if (d !== 0) return d;
      const c = a.chrom.localeCompare(b.chrom);
      return c !== 0 ? c : a.start - b.start;
    });
    bins.push(...decimateBins(list, perSample));
  }

  const out: LocusDatum[] = [];
  for (const r of [...bins, ...segments]) {
    const isSegment = r.kind === 'segment';
    const minor = r.minorCopyNumber ?? null;
    const major = minor !== null && r.copyNumber !== null ? Math.max(0, r.copyNumber - minor) : null;
    out.push({
      sample: r.sample,
      chrom: r.chrom,
      start: r.start,
      end: r.end,
      mid: (r.start + r.end) / 2,
      log2: r.log2,
      baf: r.baf,
      baf_mirror: isSegment && r.baf !== null ? 1 - r.baf : null,
      cn: r.copyNumber,
      minor,
      major,
      kind: r.kind,
      cls: classifyLog2(r.log2, opts.gain, opts.loss),
      label: r.label,
    });
  }
  return out;
}

function kindFilter(kind: 'bin' | 'segment', sample: string | null, extra?: string) {
  const parts = [`datum.kind === ${JSON.stringify(kind)}`];
  if (sample !== null) parts.push(`datum.sample === ${JSON.stringify(sample)}`);
  if (extra) parts.push(extra);
  return [{ type: 'filter', expr: parts.join(' && ') }];
}

const LOCUS_X = {
  chrom: 'chrom',
  pos: 'start',
  type: 'locus',
  scale: { name: GENOME_SCALE_NAME },
  axis: { chromGrid: true, grid: false, title: null },
};
const LOCUS_X2 = { chrom: 'chrom', pos: 'end' };
const POINT_X = { ...LOCUS_X, pos: 'mid' };

function segmentRule(
  name: string,
  sample: string | null,
  y: Record<string, unknown>,
  color: Record<string, unknown>,
  opts: { size?: number; yOffset?: number; extraFilter?: string } = {},
): Record<string, unknown> {
  return {
    name,
    transform: kindFilter('segment', sample, opts.extraFilter),
    mark: {
      type: 'rule',
      minLength: 3,
      size: opts.size ?? 3,
      ...(opts.yOffset ? { yOffset: opts.yOffset } : {}),
    },
    encoding: { x: LOCUS_X, x2: LOCUS_X2, y, color },
  };
}

function binPoints(
  name: string,
  sample: string | null,
  field: 'log2' | 'baf',
  color: string,
  pointSize: number,
  scale: Record<string, unknown>,
  title: string,
): Record<string, unknown> {
  return {
    name,
    transform: kindFilter('bin', sample, field === 'baf' ? 'datum.baf !== null' : undefined),
    mark: { type: 'point', size: pointSize ** 2, strokeWidth: 0 },
    encoding: {
      x: POINT_X,
      y: { field, type: 'quantitative', scale, title, axis: { grid: false } },
      color: { value: color },
      opacity: { value: 0.35 },
    },
  };
}

function horizontalRule(name: string, level: number, color: string): Record<string, unknown> {
  return {
    name,
    data: { values: [{}] },
    mark: { type: 'rule', color, strokeDash: [4, 4], tooltip: null },
    encoding: { y: { datum: level, type: 'quantitative' } },
  };
}

function copyNumberTrack(
  input: CnvLocusInput,
  sample: string | null,
  suffix: string,
  title: string,
  allelic: boolean,
): Record<string, unknown> {
  const { colors } = input;
  const scale = { domain: [0, CN_AXIS_MAX], padding: 0.04, clamp: true, zero: true };
  const axis = { tickMinStep: 1, grid: false };
  const layers = allelic
    ? [
        segmentRule(
          `cn-minor${suffix}`,
          sample,
          { field: 'minor', type: 'quantitative', scale, axis, title },
          { value: colors.minor },
          { size: 4, yOffset: -3, extraFilter: 'datum.minor !== null' },
        ),
        segmentRule(
          `cn-major${suffix}`,
          sample,
          { field: 'major', type: 'quantitative', title: null },
          { value: colors.major },
          { size: 4, yOffset: 3, extraFilter: 'datum.major !== null' },
        ),
      ]
    : [
        segmentRule(
          `cn-total${suffix}`,
          sample,
          { field: 'cn', type: 'quantitative', scale, axis, title },
          { value: colors.major },
          { size: 4, extraFilter: 'datum.cn !== null' },
        ),
      ];
  return { name: `cn${suffix}`, height: CN_TRACK_HEIGHT, layer: layers };
}

function log2Track(
  input: CnvLocusInput,
  sample: string | null,
  suffix: string,
  title: string,
): Record<string, unknown> {
  const { colors } = input;
  const scale = { domain: [-input.yRange, input.yRange], clamp: true };
  const classes: CnvClass[] = ['loss', 'neutral', 'gain'];
  return {
    name: `log2${suffix}`,
    height: { grow: 2, minPx: 80 },
    layer: [
      binPoints(`log2-bins${suffix}`, sample, 'log2', colors.bin, input.pointSize, scale, title),
      horizontalRule(`log2-gain${suffix}`, input.gainThreshold, colors.gridColor),
      horizontalRule(`log2-loss${suffix}`, input.lossThreshold, colors.gridColor),
      segmentRule(
        `log2-segments${suffix}`,
        sample,
        { field: 'log2', type: 'quantitative', title: null },
        {
          field: 'cls',
          type: 'nominal',
          legend: null,
          scale: { domain: classes, range: classes.map((c) => colors.segment[c]) },
        },
        { size: 4 },
      ),
    ],
  };
}

function bafTrack(
  input: CnvLocusInput,
  sample: string | null,
  suffix: string,
  title: string,
): Record<string, unknown> {
  const { colors } = input;
  const scale = { domain: [0, 1] };
  const segColour = { value: colors.textColor };
  return {
    name: `baf${suffix}`,
    height: { grow: 1, minPx: 60 },
    layer: [
      binPoints(`baf-bins${suffix}`, sample, 'baf', colors.baf, input.pointSize, scale, title),
      horizontalRule(`baf-half${suffix}`, 0.5, colors.gridColor),
      segmentRule(
        `baf-segments${suffix}`,
        sample,
        { field: 'baf', type: 'quantitative', title: null },
        segColour,
        { extraFilter: 'datum.baf !== null' },
      ),
      segmentRule(
        `baf-mirror${suffix}`,
        sample,
        { field: 'baf_mirror', type: 'quantitative', title: null },
        segColour,
        { extraFilter: 'datum.baf_mirror !== null' },
      ),
    ],
  };
}

function annotationLane(genes: readonly GeneRow[], colors: CnvLocusColors): Record<string, unknown> {
  return {
    name: 'annotation',
    height: ANNOTATION_LANE_HEIGHT,
    data: { name: GENES_DATASET_NAME },
    layer: [
      {
        name: 'annotation-genes',
        mark: { type: 'rect', minWidth: 1, minOpacity: 0.4 },
        encoding: {
          x: LOCUS_X,
          x2: LOCUS_X2,
          y: { value: 0.3 },
          y2: { value: 0.7 },
          color: { value: colors.gene },
        },
      },
      {
        name: 'annotation-labels',
        // Semantic zoom: names only once the window is small enough to read them.
        opacity: { unitsPerPixel: [100000, 20000], values: [0, 1] },
        mark: { type: 'text', size: 10, align: 'center', baseline: 'middle', tooltip: null },
        encoding: {
          x: LOCUS_X,
          x2: LOCUS_X2,
          y: { value: 0.5 },
          text: { field: 'name' },
          color: { value: colors.textColor },
        },
      },
    ],
  };
}

/** Build the ASCAT-layout root spec for the rows and switches given. */
export function buildCnvLocusSpec(input: CnvLocusInput): BuiltCnvLocusSpec {
  const data = input.data;
  const contigs = contigsFromRows(
    data as unknown as Record<string, unknown>[],
    'chrom',
    'start',
    'end',
  );
  const hasCn = data.some((d) => d.kind === 'segment' && d.cn !== null);
  const allelic = hasCn && data.some((d) => d.kind === 'segment' && d.minor !== null);
  const hasBaf = input.showBaf && data.some((d) => d.baf !== null);

  const lanes: Record<string, unknown>[] = [];
  const samples = input.faceted ? input.lanes.slice(0, MAX_LOCUS_LANES) : [input.lanes[0] ?? ''];
  samples.forEach((sample, i) => {
    const filterSample = input.faceted ? sample : null;
    const suffix = input.faceted ? `_${i}` : '';
    const prefix = input.faceted && sample ? `${sample} ` : '';
    if (hasCn) {
      lanes.push(
        copyNumberTrack(input, filterSample, suffix, `${prefix}${allelic ? 'nMajor / nMinor' : 'CN'}`, allelic),
      );
    }
    lanes.push(log2Track(input, filterSample, suffix, `${prefix}log2 ratio`));
    if (hasBaf) lanes.push(bafTrack(input, filterSample, suffix, `${prefix}BAF`));
  });

  const sizeOf = new Map(contigs.map((c) => [c.name, c.size]));
  const genes = (input.genes ?? []).filter((g) => {
    const size = sizeOf.get(g.chrom);
    return size !== undefined && g.start < size;
  });
  if (genes.length) lanes.push(annotationLane(genes, input.colors));

  const datasets: Record<string, unknown[]> = { [DATASET_NAME]: data as unknown as unknown[] };
  if (genes.length) datasets[GENES_DATASET_NAME] = genes as unknown[];

  const spec: Record<string, unknown> = {
    config: {
      view: { fill: null, stroke: null },
      axis: {
        labelColor: input.colors.textColor,
        titleColor: input.colors.textColor,
        tickColor: input.colors.gridColor,
        domainColor: input.colors.gridColor,
        gridColor: input.colors.gridColor,
      },
    },
    assembly: DATA_ASSEMBLY,
    genomes: { [DATA_ASSEMBLY]: { contigs } },
    datasets,
    data: { name: DATASET_NAME },
    // One genome ruler under the stack; each track keeps its own y.
    resolve: { axis: { x: 'shared' }, scale: { x: 'shared', y: 'independent' } },
    vconcat: lanes,
    // Room for the edge tick labels of two stacked y axes.
    spacing: 14,
  };
  if (input.brush) {
    // On the vconcat root, so one drag brushes every track at once (see
    // genomeSpySpec.ts for why a grid-owned interval param is the supported way).
    spec.params = [{ name: BRUSH_PARAM, select: { type: 'interval', encodings: ['x'] } }];
  }

  return {
    spec,
    contigs,
    geneCount: genes.length,
    tracks: { copyNumber: hasCn ? (allelic ? 'allelic' : 'total') : null, baf: hasBaf },
  };
}
