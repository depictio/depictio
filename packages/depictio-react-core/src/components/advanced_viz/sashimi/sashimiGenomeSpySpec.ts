/**
 * Pure spec builder for the sashimi kind's `genomespy` view.
 *
 * Follows the GenomeSpy playground's sashimi example: per sample, read
 * coverage drawn from a baseline and the splice junctions drawn over it as
 * `link` marks with `linkShape: 'dome'`, the dome's apex at the junction's
 * read support and its stroke width scaled by the same count. Under the lanes
 * sit the exon model inferred from the junctions and, when the tile names an
 * assembly, the bundled protein-coding gene lane.
 *
 * Shares its vocabulary with `genomespy/genomeSpySpec.ts` (the named genome
 * scale, the dataset names, the data-derived assembly) so the one embed hook,
 * `genomespy/useGenomeSpy.ts`, drives both kinds. No DOM, no React, no colour
 * literals: the renderer resolves every colour from the Mantine theme.
 *
 * Two GenomeSpy 0.88 facts shape the layout (see genomeSpySpec.ts for the
 * long version): there is no area mark, so coverage is `rect` bars anchored at
 * zero; and there is no facet operator, so each sample is its own lane,
 * narrowed by a `filter` transform over the one shared dataset.
 */

import {
  BUILTIN_ASSEMBLIES,
  DATA_ASSEMBLY,
  DATASET_NAME,
  GENES_DATASET_NAME,
  GENOME_SCALE_NAME,
  contigsFromRows,
} from '../genomespy/genomeSpySpec';
import type { Contig, GeneRow, GenomeSpyThemeColors } from '../genomespy/genomeSpySpec';

/** Junctions live in the hook's default dataset, so `setGenomeSpyRows` swaps
 *  them when the min-reads slider or a dashboard filter moves. */
export const JUNCTIONS_DATASET = DATASET_NAME;
export const COVERAGE_DATASET = 'coverage';
export const EXONS_DATASET = 'exons';

/** Height in pixels of the inferred exon model and of the gene lane. */
const EXON_LANE_HEIGHT = 22;
const GENE_LANE_HEIGHT = 34;
/** Label shown for a junction with no annotation value. */
export const UNANNOTATED = 'junction';

export interface SashimiJunctionDatum {
  chrom: string;
  start: number;
  end: number;
  count: number;
  /** `max(count, 1)`: the width channel is log-scaled and log(0) is not. */
  width: number;
  /** A little above `count`: room for the apex label (see junctionGroup). */
  headroom: number;
  lane: string;
  annotation: string;
}

export interface SashimiCoverageDatum {
  chrom: string;
  pos: number;
  end: number;
  value: number;
  lane: string;
}

export interface SashimiExonDatum {
  chrom: string;
  start: number;
  end: number;
  terminal: boolean;
}

export interface SashimiRegion {
  chrom: string;
  start: number;
  end: number;
}

export interface BuildSashimiSpecInput {
  /** Sample lanes, in display order. A single entry means one unnamed lane. */
  lanes: readonly string[];
  /** Junction classes seen in the data, the colour domain of `annotation`. */
  annotations: readonly string[];
  colorBy: 'annotation' | 'sample';
  /** One colour per lane, same order as `lanes`. */
  laneColours: readonly string[];
  /** One colour per annotation class, same order as `annotations`. */
  annotationColours: readonly string[];
  colors: GenomeSpyThemeColors;
  /** Contigs of the axis: the built-in assembly's, or derived from the rows. */
  contigs: readonly Contig[];
  /** Built-in GenomeSpy assembly name, or null for a data-derived axis. */
  assembly: string | null;
  /** The window the embed opens on; later moves go through `zoomToRegion`. */
  initialRegion: SashimiRegion | null;
  junctions: readonly SashimiJunctionDatum[];
  coverage: readonly SashimiCoverageDatum[] | null;
  /** True when the coverage collection has no sample column: every lane then
   *  shows the same profile, so the coverage layer carries no lane filter. */
  coverageShared: boolean;
  coverageTitle: string;
  coverageColour?: string | null;
  exons: readonly SashimiExonDatum[];
  genes: readonly GeneRow[] | null;
  logWidth: boolean;
  /** The tile's `max_arc_width`; the dome width range is derived from it. */
  maxArcWidth: number;
  showCounts: boolean;
}

export interface BuiltSashimiSpec {
  spec: Record<string, unknown>;
  /** Genes drawn in the gene lane, after the contig cut. */
  geneCount: number;
}

/** A filter transform keeping the rows of one lane. */
function laneFilter(lane: string): Record<string, unknown> {
  return { type: 'filter', expr: `datum.lane === ${JSON.stringify(lane)}` };
}

/** Horizontal left-hand title for the two short lanes, whose rotated titles
 *  would be taller than the lane and run into each other. */
function sideTitle(text: string, color: string): Record<string, unknown> {
  return { text, orient: 'left', anchor: 'middle', angle: 0, align: 'right', dx: -4, color };
}

function locusX(pos: string): Record<string, unknown> {
  return { chrom: 'chrom', pos, type: 'locus', scale: { name: GENOME_SCALE_NAME } };
}

function nominalColour(
  field: string,
  domain: readonly string[],
  range: readonly string[],
  fallback: string,
): Record<string, unknown> {
  return {
    field,
    type: 'nominal',
    legend: null,
    scale: {
      domain: Array.from(domain),
      range: domain.map((_, i) => range[i % Math.max(range.length, 1)] ?? fallback),
    },
  };
}

function coverageLayer(
  input: BuildSashimiSpecInput,
  lane: string,
  i: number,
): Record<string, unknown> {
  const fallback = input.colors.gridColor;
  // A shared profile is the same depth under every lane, so it takes one
  // neutral colour rather than the lane's: it is not that sample's coverage.
  const color = input.coverageColour
    ? { value: input.coverageColour }
    : input.coverageShared
      ? { value: fallback }
      : nominalColour('lane', input.lanes, input.laneColours, fallback);
  const layer: Record<string, unknown> = {
    name: `coverage_${i}`,
    data: { name: COVERAGE_DATASET },
    mark: { type: 'rect', minWidth: 0.5, minOpacity: 0.4, tooltip: null },
    encoding: {
      x: locusX('pos'),
      x2: { chrom: 'chrom', pos: 'end' },
      y: {
        field: 'value',
        type: 'quantitative',
        title: input.coverageTitle,
        axis: { grid: false, tickCount: 3 },
      },
      y2: { datum: 0 },
      color,
      opacity: { value: 0.45 },
    },
  };
  // A shared profile has no lane column worth filtering on, and a coverage
  // row with a lane nobody draws would be filtered out of every lane.
  if (!input.coverageShared) layer.transform = [laneFilter(lane)];
  return layer;
}

/**
 * The junction domes of one lane and their count labels, grouped so the two
 * share one y scale (the label sits on the apex) while the lane keeps it
 * independent of the coverage depth.
 */
function junctionGroup(input: BuildSashimiSpecInput, lane: string, i: number): Record<string, unknown> {
  const fallback = input.colors.palette[0] ?? input.colors.textColor;
  const color =
    input.colorBy === 'sample'
      ? nominalColour('lane', input.lanes, input.laneColours, fallback)
      : nominalColour('annotation', input.annotations, input.annotationColours, fallback);
  // `max_arc_width` is sized for the Plotly panel's thin arcs; a dome is read
  // by its thickness, so the GenomeSpy range is twice as wide, never under 4.
  const maxWidth = Math.max(4, input.maxArcWidth * 2);
  const layer: Record<string, unknown>[] = [
    {
      name: `junction_domes_${i}`,
      mark: {
        type: 'link',
        linkShape: 'dome',
        orient: 'vertical',
        // Keeps the apex readable when the dome's middle is panned off screen.
        clampApex: true,
        minPickingSize: 4,
      },
      encoding: {
        // The dome's apex is the primary y channel, its feet the secondary.
        y2: { datum: 0 },
        size: {
          field: 'width',
          type: 'quantitative',
          legend: null,
          scale: { type: input.logWidth ? 'log' : 'linear', range: [1, maxWidth] },
        },
        color,
      },
    },
  ];
  if (input.showCounts) {
    // Invisible marks at `headroom` stretch the shared y domain past the
    // tallest apex, so its label is not cut by the lane's top edge.
    layer.push({
      name: `junction_headroom_${i}`,
      mark: { type: 'point', size: 0, opacity: 0, tooltip: null },
      encoding: { y: { field: 'headroom', type: 'quantitative' } },
    });
    layer.push({
      name: `junction_counts_${i}`,
      mark: { type: 'text', size: 10, dy: -10, tooltip: null },
      // Readable once a locus is a few tens of kb wide; hidden at genome scale
      // where hundreds of labels would stack into a smear.
      opacity: { unitsPerPixel: [2000, 500], values: [0, 1] },
      encoding: {
        text: { field: 'count' },
        color: { value: input.colors.textColor },
      },
    });
  }
  return {
    name: `junctions_${i}`,
    transform: [laneFilter(lane)],
    encoding: {
      x: locusX('start'),
      x2: { chrom: 'chrom', pos: 'end' },
      // The apex labels already print the count, so no second y axis.
      y: { field: 'count', type: 'quantitative', scale: { zero: true, nice: true }, axis: null },
    },
    layer,
  };
}

function sampleLane(input: BuildSashimiSpecInput, lane: string, i: number): Record<string, unknown> {
  const layer: Record<string, unknown>[] = [];
  if (input.coverage) layer.push(coverageLayer(input, lane, i));
  layer.push(junctionGroup(input, lane, i));
  const view: Record<string, unknown> = {
    name: `lane_${i}`,
    data: { name: JUNCTIONS_DATASET },
    // Depth and read support are different measurements, so each keeps its
    // own y scale; only the coverage axis is drawn.
    resolve: { scale: { y: 'independent' }, axis: { y: 'independent' } },
    layer,
  };
  if (input.lanes.length > 1) {
    view.title = { text: lane, orient: 'left', anchor: 'middle', color: input.colors.textColor };
  }
  return view;
}

function exonLane(input: BuildSashimiSpecInput): Record<string, unknown> {
  const blocks = (name: string, expr: string, opacity: number): Record<string, unknown> => ({
    name,
    transform: [{ type: 'filter', expr }],
    mark: { type: 'rect', minWidth: 1, tooltip: null },
    encoding: {
      x: locusX('start'),
      x2: { chrom: 'chrom', pos: 'end' },
      y: { value: 0.2 },
      y2: { value: 0.8 },
      color: { value: input.colors.textColor },
      opacity: { value: opacity },
    },
  });
  return {
    name: 'exon_model',
    height: EXON_LANE_HEIGHT,
    data: { name: EXONS_DATASET },
    title: sideTitle('exons', input.colors.textColor),
    // A terminal exon's outer edge is a guess (nothing splices into or out of
    // it), so it is drawn fainter than the exons the junctions pin down.
    layer: [
      blocks('exon_blocks', '!datum.terminal', 0.8),
      blocks('exon_terminal', 'datum.terminal', 0.3),
    ],
  };
}

function geneLane(input: BuildSashimiSpecInput): Record<string, unknown> {
  const geneColour = input.colors.palette[0] ?? input.colors.gridColor;
  return {
    name: 'genes',
    height: GENE_LANE_HEIGHT,
    data: { name: GENES_DATASET_NAME },
    title: sideTitle('genes', input.colors.textColor),
    layer: [
      {
        name: 'gene_bodies',
        mark: { type: 'rect', minWidth: 1, minOpacity: 0.4 },
        encoding: {
          x: locusX('start'),
          x2: { chrom: 'chrom', pos: 'end' },
          y: { value: 0.55 },
          y2: { value: 0.85 },
          color: { value: geneColour },
        },
      },
      {
        name: 'gene_labels',
        opacity: { unitsPerPixel: [100000, 20000], values: [0, 1] },
        mark: { type: 'text', size: 10, align: 'center', baseline: 'middle', tooltip: null },
        encoding: {
          x: locusX('start'),
          x2: { chrom: 'chrom', pos: 'end' },
          y: { value: 0.22 },
          text: { field: 'label' },
          color: { value: input.colors.textColor },
        },
      },
    ],
  };
}

/** Contigs for a data-derived axis: every chromosome a junction or a coverage
 *  bin sits on, sized to the furthest coordinate either reaches. */
export function sashimiContigs(
  junctions: readonly SashimiJunctionDatum[],
  coverage: readonly SashimiCoverageDatum[] | null,
): Contig[] {
  const points: Record<string, unknown>[] = junctions.map((j) => ({
    chrom: j.chrom,
    pos: j.start,
    end: j.end,
  }));
  for (const c of coverage ?? []) points.push({ chrom: c.chrom, pos: c.pos, end: c.end });
  return contigsFromRows(points, 'chrom', 'pos', 'end');
}

export function buildSashimiGenomeSpySpec(input: BuildSashimiSpecInput): BuiltSashimiSpec {
  const onAxis = new Set(input.contigs.map((c) => c.name));
  // The strand goes into the label, the way a genome browser names a gene
  // when there is no room for chevrons.
  const genes = (input.genes ?? [])
    .filter((g) => onAxis.has(g.chrom))
    .map((g) => ({ ...g, label: g.strand ? `${g.name} (${g.strand})` : g.name }));

  const lanes: Record<string, unknown>[] = input.lanes.map((lane, i) =>
    sampleLane(input, lane, i),
  );
  lanes.push(exonLane(input));
  if (genes.length) lanes.push(geneLane(input));

  const datasets: Record<string, unknown[]> = {
    [JUNCTIONS_DATASET]: Array.from(input.junctions),
    [EXONS_DATASET]: Array.from(input.exons),
  };
  if (input.coverage) datasets[COVERAGE_DATASET] = Array.from(input.coverage);
  if (genes.length) datasets[GENES_DATASET_NAME] = genes;

  const builtin =
    input.assembly && BUILTIN_ASSEMBLIES.includes(input.assembly) ? input.assembly : null;
  const xScale: Record<string, unknown> = { name: GENOME_SCALE_NAME };
  const region = input.initialRegion;
  if (region && onAxis.has(region.chrom) && region.end > region.start) {
    xScale.domain = [
      { chrom: region.chrom, pos: region.start },
      { chrom: region.chrom, pos: region.end },
    ];
  }

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
    assembly: builtin ?? DATA_ASSEMBLY,
    datasets,
    // One shared genome axis, drawn once at the bottom of the stack.
    resolve: { axis: { x: 'shared' }, scale: { x: 'shared' } },
    encoding: {
      x: {
        chrom: 'chrom',
        pos: 'start',
        type: 'locus',
        scale: xScale,
        axis: { chromGrid: false, title: null },
      },
    },
    vconcat: lanes,
    spacing: 4,
  };
  if (!builtin) spec.genomes = { [DATA_ASSEMBLY]: { contigs: Array.from(input.contigs) } };

  return { spec, geneCount: genes.length };
}

// --- Row shaping -------------------------------------------------------------

/** The renderer's junction shape, before it becomes a GenomeSpy datum. */
export interface SashimiJunctionLike {
  chrom: string;
  start: number;
  end: number;
  count: number;
  lane: string;
  annotation: string | null;
}

export function junctionData(junctions: readonly SashimiJunctionLike[]): SashimiJunctionDatum[] {
  return junctions.map((j) => ({
    chrom: j.chrom,
    start: j.start,
    end: j.end,
    count: j.count,
    width: Math.max(1, j.count),
    headroom: j.count * 1.15,
    lane: j.lane,
    annotation: j.annotation || UNANNOTATED,
  }));
}

export interface CoverageColumns {
  chr: string;
  pos: string;
  value: string;
  end?: string | null;
  sample?: string | null;
}

/**
 * Column-oriented coverage rows to GenomeSpy datums. Unlike the Plotly view
 * nothing is pooled here: GenomeSpy draws every bin and lets the reader zoom
 * into them. `log` compresses the depth to `log10(1 + depth)`, since a
 * GenomeSpy quantitative scale has no symlog to do it on the axis.
 */
export function coverageData(
  rows: Record<string, unknown[]>,
  cols: CoverageColumns,
  fallbackLane: string,
  log: boolean,
): SashimiCoverageDatum[] {
  const chroms = rows[cols.chr] ?? [];
  const positions = rows[cols.pos] ?? [];
  const values = rows[cols.value] ?? [];
  const ends = cols.end ? (rows[cols.end] ?? null) : null;
  const samples = cols.sample ? (rows[cols.sample] ?? null) : null;
  const out: SashimiCoverageDatum[] = [];
  for (let i = 0; i < positions.length; i += 1) {
    const chrom = chroms[i];
    const pos = Number(positions[i]);
    const value = Number(values[i]);
    if (chrom === null || chrom === undefined || chrom === '') continue;
    if (!Number.isFinite(pos) || !Number.isFinite(value)) continue;
    const rawEnd = ends ? Number(ends[i]) : Number.NaN;
    out.push({
      chrom: String(chrom),
      pos,
      end: Number.isFinite(rawEnd) && rawEnd > pos ? rawEnd : pos + 1,
      value: log ? Math.log10(1 + Math.max(0, value)) : value,
      lane: samples ? String(samples[i] ?? fallbackLane) : fallbackLane,
    });
  }
  return out;
}
