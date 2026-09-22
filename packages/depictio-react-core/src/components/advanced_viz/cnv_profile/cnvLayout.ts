/**
 * Pure layout maths for the `cnv_profile` kind.
 *
 * Everything here is free of React, Plotly and the DOM so vitest can cover it
 * in the node environment: row parsing, the genome-wide x axis (chromosome
 * offsets, the same rule `ManhattanRenderer` uses), the bin decimation and the
 * gain / neutral / loss classification. The renderer keeps only the figure
 * assembly and the settings panel.
 *
 * Row contract (canonical `cnv_profile` roles):
 *   sample, chrom, start, end, log2   required
 *   baf, copy_number, segment, label  optional
 * `segment` is the row-type column: a row whose value reads as `segment` is a
 * called segment and is drawn as a thick horizontal line, every other row is a
 * bin and is drawn as a point.
 */

/** A bin (one window of the ratio track) or a called segment. */
export type CnvRowKind = 'bin' | 'segment';

/** One parsed row, with every optional role resolved to a value or null. */
export interface CnvRow {
  sample: string;
  chrom: string;
  start: number;
  end: number;
  log2: number;
  baf: number | null;
  copyNumber: number | null;
  label: string | null;
  kind: CnvRowKind;
}

/** Column names the renderer binds, straight off `CnvProfileConfig`. */
export interface CnvColumns {
  sample: string;
  chrom: string;
  start: string;
  end: string;
  log2: string;
  baf?: string | null;
  copyNumber?: string | null;
  segment?: string | null;
  label?: string | null;
}

/**
 * Values of the `segment` role that mark a called segment. The canonical
 * recipes write the literal `segment` (the bins write `bin`), but a
 * hand-bound collection may carry a boolean flag instead, so the truthy
 * spellings are accepted too.
 */
const SEGMENT_VALUES: ReadonlySet<string> = new Set([
  'segment',
  'segments',
  'seg',
  'true',
  '1',
  'yes',
]);

/** Whether a `segment` role value marks the row as a called segment. */
export function isSegmentValue(value: unknown): boolean {
  if (value === true) return true;
  if (value === null || value === undefined) return false;
  return SEGMENT_VALUES.has(String(value).trim().toLowerCase());
}

/** Finite number or null, for values that arrive as strings from the API. */
export function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Natural chromosome order: chr1..chr22, chrX, chrY, chrM(T), then anything
 * unrecognised, alphabetically. Same rule as `ManhattanRenderer` and the
 * GenomeSpy spec builder, restated here rather than imported so this kind does
 * not depend on another kind's module.
 */
export function chromosomeSortKey(label: string): number {
  const stripped = label.replace(/^chr/i, '').toUpperCase();
  if (stripped === 'X') return 23;
  if (stripped === 'Y') return 24;
  if (stripped === 'MT' || stripped === 'M') return 25;
  const n = Number.parseInt(stripped, 10);
  return Number.isFinite(n) ? n : 100;
}

/** Distinct chromosome labels in natural order. */
export function sortChromosomes(labels: Iterable<string>): string[] {
  return Array.from(new Set(labels)).sort((a, b) => {
    const d = chromosomeSortKey(a) - chromosomeSortKey(b);
    return d !== 0 ? d : a.localeCompare(b);
  });
}

/**
 * Column-oriented rows (what `/advanced_viz/data` returns) to `CnvRow[]`.
 *
 * A row with no usable chromosome, start or log2 is dropped: it can neither be
 * placed on the axis nor drawn. `end` falls back to `start` so a collection
 * that only carries point positions still renders (the segment then draws as a
 * zero-width tick rather than disappearing).
 */
export function parseCnvRows(rows: Record<string, unknown[]>, cols: CnvColumns): CnvRow[] {
  const samples = rows[cols.sample] ?? [];
  const chroms = rows[cols.chrom] ?? [];
  const starts = rows[cols.start] ?? [];
  const ends = rows[cols.end] ?? [];
  const log2s = rows[cols.log2] ?? [];
  const bafs = cols.baf ? (rows[cols.baf] ?? []) : [];
  const cns = cols.copyNumber ? (rows[cols.copyNumber] ?? []) : [];
  const kinds = cols.segment ? (rows[cols.segment] ?? []) : [];
  const labels = cols.label ? (rows[cols.label] ?? []) : [];

  const n = Math.min(chroms.length, starts.length, log2s.length);
  const out: CnvRow[] = [];
  for (let i = 0; i < n; i += 1) {
    const chrom = chroms[i];
    const start = num(starts[i]);
    const log2 = num(log2s[i]);
    if (chrom === null || chrom === undefined || chrom === '') continue;
    if (start === null || log2 === null) continue;
    const end = num(ends[i]);
    out.push({
      sample:
        samples[i] === null || samples[i] === undefined ? '' : String(samples[i]),
      chrom: String(chrom),
      start,
      end: end === null ? start : end,
      log2,
      baf: cols.baf ? num(bafs[i]) : null,
      copyNumber: cols.copyNumber ? num(cns[i]) : null,
      label:
        cols.label && labels[i] !== null && labels[i] !== undefined && labels[i] !== ''
          ? String(labels[i])
          : null,
      kind: cols.segment && isSegmentValue(kinds[i]) ? 'segment' : 'bin',
    });
  }
  return out;
}

/** Where one chromosome sits on the concatenated genome axis. */
export interface ChromSpan {
  start: number;
  end: number;
  mid: number;
}

/** The genome-wide x axis: cumulative offsets, ticks and the drawn range. */
export interface GenomeAxis {
  /** Chromosomes on the axis, in natural order. */
  chroms: string[];
  /** Cumulative bp offset added to a position on that chromosome. */
  offset: Map<string, number>;
  /** Where each chromosome's block starts, ends and centres. */
  span: Map<string, ChromSpan>;
  /** Tick positions (chromosome centres) and their labels. */
  tickvals: number[];
  ticktext: string[];
  /** Boundaries between chromosomes, for the separator rules. */
  boundaries: number[];
  /** x range with half a pad at each end. */
  range: [number, number];
}

/**
 * Lay the chromosomes end to end, in natural order, padded by ~2% of the
 * largest one so neighbouring blocks do not butt against each other. Built
 * over the chromosomes actually drawn, so narrowing to one chromosome zooms
 * the axis onto it instead of stranding it in an empty genome.
 */
export function buildGenomeAxis(rows: readonly CnvRow[], chroms: readonly string[]): GenomeAxis {
  const extent = new Map<string, number>();
  for (const row of rows) {
    const prev = extent.get(row.chrom) ?? 0;
    const far = Math.max(row.start, row.end);
    if (far > prev) extent.set(row.chrom, far);
  }
  const ordered = chroms.filter((c) => extent.has(c));
  const largest = ordered.reduce((acc, c) => Math.max(acc, extent.get(c) ?? 0), 0);
  const padding = Math.max(1, Math.round(largest * 0.02));

  const offset = new Map<string, number>();
  const span = new Map<string, ChromSpan>();
  const tickvals: number[] = [];
  const ticktext: string[] = [];
  const boundaries: number[] = [];
  let cursor = 0;
  ordered.forEach((chrom, i) => {
    const width = extent.get(chrom) ?? 0;
    offset.set(chrom, cursor);
    span.set(chrom, { start: cursor, end: cursor + width, mid: cursor + width / 2 });
    tickvals.push(cursor + width / 2);
    ticktext.push(chrom);
    cursor += width;
    if (i < ordered.length - 1) {
      boundaries.push(cursor + padding / 2);
      cursor += padding;
    }
  });

  return {
    chroms: ordered,
    offset,
    span,
    tickvals,
    ticktext,
    boundaries,
    range: [-padding / 2, Math.max(1, cursor) + padding / 2],
  };
}

/** Genome-axis x of a position, or null when the chromosome is not drawn. */
export function genomeX(axis: GenomeAxis, chrom: string, pos: number): number | null {
  const off = axis.offset.get(chrom);
  return off === undefined ? null : off + pos;
}

/**
 * Average consecutive bins down to at most `maxBins` rows.
 *
 * Windows never cross a chromosome boundary, and the emitted row keeps the
 * window's span (`start` of the first bin, `end` of the last) so the decimated
 * track still covers the same genome. `log2`, `baf` and `copyNumber` are
 * means over the non-null values in the window; a window with no BAF at all
 * stays null rather than collapsing to 0.
 *
 * Segments are never passed through here: a called segment is the answer the
 * caller is reading off the plot, so it is always drawn in full.
 */
export function decimateBins(bins: readonly CnvRow[], maxBins: number): CnvRow[] {
  if (maxBins <= 0 || bins.length <= maxBins) return bins.slice();
  const factor = Math.ceil(bins.length / maxBins);

  const out: CnvRow[] = [];
  let window: CnvRow[] = [];

  const flush = () => {
    if (window.length === 0) return;
    const first = window[0];
    const last = window[window.length - 1];
    out.push({
      sample: first.sample,
      chrom: first.chrom,
      start: first.start,
      end: Math.max(first.end, last.end),
      log2: mean(window.map((r) => r.log2)) ?? first.log2,
      baf: mean(window.map((r) => r.baf)),
      copyNumber: mean(window.map((r) => r.copyNumber)),
      label: first.label,
      kind: 'bin',
    });
    window = [];
  };

  for (const bin of bins) {
    if (window.length > 0 && (window[0].chrom !== bin.chrom || window.length >= factor)) flush();
    window.push(bin);
  }
  flush();
  return out;
}

function mean(values: readonly (number | null)[]): number | null {
  let sum = 0;
  let seen = 0;
  for (const v of values) {
    if (v === null || !Number.isFinite(v)) continue;
    sum += v;
    seen += 1;
  }
  return seen === 0 ? null : sum / seen;
}

/** How a segment reads against the two thresholds. */
export type CnvClass = 'gain' | 'neutral' | 'loss';

/** Classify a log2 ratio. A NaN or missing value reads as neutral. */
export function classifyLog2(log2: number | null, gain: number, loss: number): CnvClass {
  if (log2 === null || !Number.isFinite(log2)) return 'neutral';
  if (log2 >= gain) return 'gain';
  if (log2 <= loss) return 'loss';
  return 'neutral';
}

/**
 * Integer copy number to one of five colour buckets, the ramp CNVkit and
 * ASCAT plots use: homozygous loss, loss, neutral (2 copies), gain, high-level
 * amplification. Returns an index into a five-entry colour ramp.
 */
export function copyNumberBucket(cn: number | null): number {
  if (cn === null || !Number.isFinite(cn)) return 2;
  const rounded = Math.round(cn);
  if (rounded <= 0) return 0;
  if (rounded === 1) return 1;
  if (rounded === 2) return 2;
  if (rounded <= 4) return 3;
  return 4;
}

/** A genomic coordinate as a short human string: 1 234 567 -> `1.23 Mb`. */
export function formatBp(value: number): string {
  if (!Number.isFinite(value)) return '';
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(2)} Mb`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(1)} kb`;
  return `${Math.round(value)} bp`;
}

/**
 * Plotly hover text for one bin or segment: where it is, what it is worth,
 * and whichever of the optional roles the collection bound. Kept out of the
 * renderer so the "what does the reader see on hover" rule is testable.
 */
export function hoverText(row: CnvRow, valueLabel: string): string {
  const span =
    row.end > row.start ? `${formatBp(row.start)} - ${formatBp(row.end)}` : formatBp(row.start);
  const parts = [`<b>${row.chrom}</b> ${span}`, `${valueLabel}: ${row.log2.toFixed(3)}`];
  if (row.copyNumber !== null) parts.push(`copy number: ${row.copyNumber}`);
  if (row.baf !== null) parts.push(`BAF: ${row.baf.toFixed(3)}`);
  if (row.label) parts.push(row.label);
  return parts.join('<br>');
}

/**
 * One Plotly `lines` trace drawing every segment of a class as its own
 * horizontal stroke: a `null` between segments breaks the line, so two
 * neighbouring calls never get joined by a diagonal that means nothing.
 *
 * A segment on a chromosome the axis does not draw is skipped rather than
 * placed at the origin.
 */
export function segmentStrokes(
  segments: readonly CnvRow[],
  axis: GenomeAxis,
): { x: (number | null)[]; y: (number | null)[]; hover: (string | null)[] } {
  const x: (number | null)[] = [];
  const y: (number | null)[] = [];
  const hover: (string | null)[] = [];
  for (const seg of segments) {
    const offset = axis.offset.get(seg.chrom);
    if (offset === undefined) continue;
    const text = hoverText(seg, 'segment log2');
    x.push(offset + seg.start, offset + Math.max(seg.end, seg.start), null);
    y.push(seg.log2, seg.log2, null);
    hover.push(text, text, null);
  }
  return { x, y, hover };
}
