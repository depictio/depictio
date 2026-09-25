/**
 * Lane layout for the `transcript_structure` kind.
 *
 * The renderer draws one gene at a time: every transcript of that gene becomes
 * a lane, its exon and CDS rows become blocks on the lane, and the gaps between
 * consecutive blocks become the introns. All of that is arithmetic on the rows,
 * so it lives here with its own tests rather than inside a `useMemo`.
 *
 * Coordinates stay in base pairs throughout. The GTF convention (1-based,
 * both ends inclusive) is kept as the recipe read it: shifting it here would
 * make the hover disagree with every other tool the reader has open.
 */

/** One exon or CDS row, already narrowed from the fetched columns. */
export interface TranscriptBlock {
  transcriptId: string;
  geneId: string;
  geneName: string;
  chrom: string;
  start: number;
  end: number;
  /** `true` when the row is a coding block, which is drawn taller. */
  coding: boolean;
  /** Normalised to `+` / `-`. */
  strand: string;
  sample: string | null;
  transcriptClass: string | null;
  expression: number | null;
}

/** Column names the fetched frame carries each block fact under. */
export interface BlockColumns {
  transcriptId: string;
  geneId: string;
  chrom: string;
  start: string;
  end: string;
  feature: string;
  strand: string;
  sample?: string | null;
  geneName?: string | null;
  transcriptClass?: string | null;
  expression?: string | null;
}

/** Which `feature` values become a block, as the author's config spells them.
 *  Compared case-insensitively: a GTF writes `CDS`, a GFF3 may write `cds`. */
export interface BlockFeatures {
  exon: string;
  cds: string;
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/** `-` when the value reads as minus, `+` for everything else, including the
 *  GFF3 "unknown strand" dot, which still has to point somewhere. */
export function normStrand(v: unknown): string {
  const s = String(v ?? '')
    .trim()
    .toLowerCase();
  return s.startsWith('-') || s === 'minus' || s === 'rev' || s === 'reverse' ? '-' : '+';
}

/**
 * The fetched column-oriented frame as blocks, dropping every row that is
 * neither an exon nor a CDS.
 *
 * A frame straight off the annotation carries transcript rows, gene rows and
 * whatever else the pipeline emitted; only the two block features are drawable,
 * and a row missing either coordinate cannot be placed at all.
 */
export function toBlocks(
  rows: Record<string, unknown[]> | null | undefined,
  columns: BlockColumns,
  features: BlockFeatures,
): TranscriptBlock[] {
  if (!rows) return [];
  const exonFeature = features.exon.toLowerCase();
  const cdsFeature = features.cds.toLowerCase();

  const txs = rows[columns.transcriptId] || [];
  const genes = rows[columns.geneId] || [];
  const chroms = rows[columns.chrom] || [];
  const starts = rows[columns.start] || [];
  const ends = rows[columns.end] || [];
  const featureValues = rows[columns.feature] || [];
  const strands = rows[columns.strand] || [];
  const samples = columns.sample ? rows[columns.sample] : undefined;
  const names = columns.geneName ? rows[columns.geneName] : undefined;
  const classes = columns.transcriptClass ? rows[columns.transcriptClass] : undefined;
  const expressions = columns.expression ? rows[columns.expression] : undefined;

  const out: TranscriptBlock[] = [];
  for (let i = 0; i < txs.length; i++) {
    const s = num(starts[i]);
    const e = num(ends[i]);
    if (s === null || e === null) continue;
    const feature = String(featureValues[i] ?? '').toLowerCase();
    if (feature !== exonFeature && feature !== cdsFeature) continue;
    const geneId = String(genes[i] ?? '(unknown gene)');
    const cls = classes ? String(classes[i] ?? '') : '';
    out.push({
      transcriptId: String(txs[i] ?? `transcript ${i + 1}`),
      geneId,
      geneName: names ? String(names[i] ?? geneId) : geneId,
      chrom: String(chroms[i] ?? ''),
      // A GTF block is stored low-to-high whatever the strand, but a writer
      // that puts start above end must not make the block vanish.
      start: Math.min(s, e),
      end: Math.max(s, e),
      coding: feature === cdsFeature,
      strand: normStrand(strands[i]),
      sample: samples ? String(samples[i] ?? '') : null,
      transcriptClass: cls || null,
      expression: expressions ? num(expressions[i]) : null,
    });
  }
  return out;
}

/** A gene the fetched frame carries, for the gene selector. */
export interface GeneOption {
  id: string;
  name: string;
  transcripts: number;
  blocks: number;
}

/** One transcript of the drawn gene, with its blocks in ascending order. */
export interface TranscriptLane {
  /** Unique within the figure: the transcript, scoped by sample when needed. */
  key: string;
  transcriptId: string;
  sample: string | null;
  strand: string;
  transcriptClass: string | null;
  expression: number | null;
  blocks: TranscriptBlock[];
  start: number;
  end: number;
  /** True when at least one block of the transcript is coding. */
  hasCoding: boolean;
}

export interface LaneOptions {
  /** Gene to draw. Rows of every other gene are dropped. */
  geneId: string;
  /** Restrict to one sample; `null` keeps every sample and scopes the lanes by it. */
  sample: string | null;
  /** Lanes kept after ordering. */
  maxTranscripts: number;
}

export interface LaneResult {
  lanes: TranscriptLane[];
  /** Transcripts of this gene that the lane budget left out. */
  truncated: number;
  /** Distinct samples among the gene's rows, in first-seen order. */
  samples: string[];
}

/**
 * Genes present in the frame, most isoforms first.
 *
 * The order is what picks the default gene: a viewer opening the tile should
 * land on the locus that has something to compare, not on whichever gene the
 * annotation happens to list first.
 */
export function listGenes(blocks: TranscriptBlock[]): GeneOption[] {
  const byGene = new Map<string, { name: string; transcripts: Set<string>; blocks: number }>();
  for (const b of blocks) {
    let entry = byGene.get(b.geneId);
    if (!entry) {
      entry = { name: b.geneName || b.geneId, transcripts: new Set(), blocks: 0 };
      byGene.set(b.geneId, entry);
    }
    entry.transcripts.add(b.transcriptId);
    entry.blocks += 1;
  }
  return Array.from(byGene.entries())
    .map(([id, e]) => ({ id, name: e.name, transcripts: e.transcripts.size, blocks: e.blocks }))
    .sort(
      (a, b) => b.transcripts - a.transcripts || b.blocks - a.blocks || a.id.localeCompare(b.id),
    );
}

/**
 * Lanes of one gene, ordered by expression and cut to the lane budget.
 *
 * Ordering by expression and only then truncating is the point of the budget:
 * a locus with forty assembled isoforms is read for the ones that carry the
 * signal, and dropping by row order would keep an arbitrary forty.
 */
export function buildLanes(blocks: TranscriptBlock[], options: LaneOptions): LaneResult {
  const { geneId, sample, maxTranscripts } = options;
  const samples: string[] = [];
  const seenSamples = new Set<string>();
  const ofGene: TranscriptBlock[] = [];
  for (const b of blocks) {
    if (b.geneId !== geneId) continue;
    if (b.sample !== null && !seenSamples.has(b.sample)) {
      seenSamples.add(b.sample);
      samples.push(b.sample);
    }
    if (sample !== null && b.sample !== sample) continue;
    ofGene.push(b);
  }

  // One lane per transcript, or per (sample, transcript) when several samples
  // are on screen: the same isoform assembled in two libraries is two rows to
  // compare, not one lane whose blocks overlap each other.
  const perSample = sample === null && samples.length > 1;
  const byKey = new Map<string, TranscriptLane>();
  for (const b of ofGene) {
    const key = perSample && b.sample !== null ? `${b.sample}\u0000${b.transcriptId}` : b.transcriptId;
    let lane = byKey.get(key);
    if (!lane) {
      lane = {
        key,
        transcriptId: b.transcriptId,
        sample: b.sample,
        strand: b.strand,
        transcriptClass: b.transcriptClass,
        expression: b.expression,
        blocks: [],
        start: b.start,
        end: b.end,
        hasCoding: false,
      };
      byKey.set(key, lane);
    }
    lane.blocks.push(b);
    lane.start = Math.min(lane.start, b.start);
    lane.end = Math.max(lane.end, b.end);
    lane.hasCoding = lane.hasCoding || b.coding;
    // A transcript's class and expression are per-transcript facts repeated on
    // every one of its blocks; the first non-null wins so a partially annotated
    // block cannot blank them.
    if (lane.transcriptClass === null) lane.transcriptClass = b.transcriptClass;
    if (lane.expression === null) lane.expression = b.expression;
  }

  const lanes = Array.from(byKey.values());
  for (const lane of lanes) lane.blocks.sort((a, b) => a.start - b.start || a.end - b.end);
  lanes.sort((a, b) => {
    const ea = a.expression;
    const eb = b.expression;
    if (ea !== null && eb !== null && ea !== eb) return eb - ea;
    if (ea !== null && eb === null) return -1;
    if (ea === null && eb !== null) return 1;
    return b.blocks.length - a.blocks.length || a.key.localeCompare(b.key);
  });

  const budget = Math.max(1, Math.floor(maxTranscripts));
  return { lanes: lanes.slice(0, budget), truncated: Math.max(lanes.length - budget, 0), samples };
}

/**
 * The gaps between a lane's blocks, in base pairs.
 *
 * Only gaps wider than nothing are returned: two exons that abut (or a CDS
 * drawn on top of the exon that contains it) leave no intron to draw, and a
 * zero-width line would still paint a chevron in the middle of a block.
 */
export function intronSpans(lane: TranscriptLane): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  let reach = -Infinity;
  for (const block of lane.blocks) {
    if (reach !== -Infinity && block.start > reach + 1) spans.push([reach, block.start]);
    reach = Math.max(reach, block.end);
  }
  return spans;
}

/**
 * Where to paint the strand chevrons inside a set of introns.
 *
 * Evenly spaced at `stepBp`, and never more than `maxPerSpan` in one intron so
 * a 200 kb intron on a zoomed-out view does not turn into a solid bar. An
 * intron too short for a mark gets one at its midpoint, because a gap with no
 * direction on it is the one thing the reader cannot infer.
 */
export function chevronPoints(
  spans: Array<[number, number]>,
  stepBp: number,
  maxPerSpan = 6,
): number[] {
  const step = stepBp > 0 ? stepBp : 1;
  const points: number[] = [];
  for (const [x0, x1] of spans) {
    const width = x1 - x0;
    if (width <= 0) continue;
    const count = Math.min(Math.max(Math.floor(width / step), 1), maxPerSpan);
    const gap = width / (count + 1);
    for (let i = 1; i <= count; i++) points.push(x0 + gap * i);
  }
  return points;
}

/** One drawn block, in the shape a horizontal Plotly bar takes it. */
export interface BlockBar {
  /** Left edge in base pairs (Plotly `base`). */
  base: number;
  /** Length in base pairs (Plotly `x` for a horizontal bar). */
  width: number;
  /** Lane index. */
  y: number;
  /** Bar thickness in lane units: this is the exon-versus-CDS distinction. */
  height: number;
  coding: boolean;
  expression: number | null;
  /** Row of `customdata` behind the hover label. */
  hover: unknown[];
}

export interface BlockBarOptions {
  exonHeight: number;
  cdsHeight: number;
  /** What the hover calls each block type, as the author's config spells it. */
  exonLabel: string;
  cdsLabel: string;
  /** Group the bars by transcript class (one trace per class) or into one. */
  byClass: boolean;
}

/**
 * The lanes' blocks as bars, grouped into the traces that will draw them.
 *
 * Coding blocks come last within each group. A CDS is drawn taller than the
 * exon that carries it and Plotly paints a trace in array order, so emitting
 * them after the exons is what leaves the UTR visible either side of the ORF.
 */
export function blockBars(
  lanes: TranscriptLane[],
  options: BlockBarOptions,
): Map<string, BlockBar[]> {
  const groups = new Map<string, BlockBar[]>();
  lanes.forEach((lane, y) => {
    const group = options.byClass ? (lane.transcriptClass ?? '') : '';
    let bucket = groups.get(group);
    if (!bucket) {
      bucket = [];
      groups.set(group, bucket);
    }
    for (const b of lane.blocks) {
      bucket.push({
        base: b.start,
        width: Math.max(b.end - b.start, 1),
        y,
        height: b.coding ? options.cdsHeight : options.exonHeight,
        coding: b.coding,
        expression: lane.expression,
        hover: [
          lane.transcriptId,
          lane.sample ?? '',
          b.geneName,
          b.chrom,
          b.start,
          b.end,
          b.coding ? options.cdsLabel : options.exonLabel,
          lane.strand,
          lane.transcriptClass ?? '',
          lane.expression,
        ],
      });
    }
  });
  for (const bucket of groups.values()) {
    bucket.sort((a, b) => Number(a.coding) - Number(b.coding));
  }
  return groups;
}

/**
 * The y-axis tick text: the transcript, badged with its class and, when
 * several samples share the figure, with the library it was assembled in.
 *
 * A class that carries no novelty claim is left off: badging every lane
 * `[known]` on a reference annotation is noise, and the badge exists to make
 * the handful of novel ones findable.
 */
export function laneLabels(
  lanes: TranscriptLane[],
  options: { perSample: boolean; neutralClasses: ReadonlySet<string> },
): string[] {
  return lanes.map((lane) => {
    const parts = [lane.transcriptId];
    const cls = lane.transcriptClass;
    if (cls && !options.neutralClasses.has(cls.toLowerCase())) parts.push(`[${cls}]`);
    if (options.perSample && lane.sample) parts.push(`· ${lane.sample}`);
    return parts.join(' ');
  });
}
