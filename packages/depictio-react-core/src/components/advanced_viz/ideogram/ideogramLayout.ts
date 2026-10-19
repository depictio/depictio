/**
 * Pure layout maths for the `ideogram` kind.
 *
 * A karyotype is a set of bars, one per chromosome, all starting at a common
 * origin and drawn to the chromosome's length, with the features on top: a
 * glyph per row (`marks`) or a heat band per bin (`density`). Nothing in the
 * stack draws that, and it is a few rectangles per chromosome, so the renderer
 * draws SVG and every number it needs comes from this module, which is
 * unit-tested without a DOM (`ideogramLayout.test.ts`).
 *
 * The chromosome vocabulary is the genome chord ring's: the same assembly
 * tables (`ASSEMBLY_CHROM_SIZES`), the same `chr` prefix folding and the same
 * natural order (1..22, X, Y, M, then contigs by numeric-aware name), so a
 * chromosome is named and sized identically on both kinds.
 */

import {
  ASSEMBLY_NAMES,
  assemblySizes,
  compareChrom,
  formatBp,
  normaliseChrom,
} from '../genome_chord/chordLayout';

export { ASSEMBLY_NAMES, compareChrom, formatBp, normaliseChrom };

// ---------------------------------------------------------------------------
// Rows to features
// ---------------------------------------------------------------------------

/** Column names the renderer binds, straight off `IdeogramConfig`. */
export interface IdeogramColumns {
  chrom: string;
  start: string;
  end?: string | null;
  value?: string | null;
  category?: string | null;
  sample?: string | null;
  label?: string | null;
  chromLength?: string | null;
}

/** One row placed on a chromosome. */
export interface IdeogramFeature {
  chrom: string;
  start: number;
  end: number;
  value: number | null;
  category: string | null;
  sample: string | null;
  label: string | null;
  /** Chromosome length the row itself states, when a length column is bound. */
  chromLength: number | null;
  /** Index in the fetched frame: a stable React key and tie-break. */
  row: number;
}

function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function str(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const s = String(value).trim();
  return s === '' ? null : s;
}

/**
 * Column-oriented rows (what `/advanced_viz/data` returns) to features.
 *
 * A row with no chromosome or no start cannot be placed and is dropped; a row
 * with no end is a point (end = start), and a reversed interval (an end before
 * its start, as a minus-strand caller may write it) is put the right way round
 * rather than drawn with a negative width.
 */
export function parseIdeogramRows(
  rows: Record<string, unknown[]>,
  cols: IdeogramColumns,
): IdeogramFeature[] {
  const chroms = rows[cols.chrom] ?? [];
  const starts = rows[cols.start] ?? [];
  const ends = cols.end ? (rows[cols.end] ?? []) : null;
  const values = cols.value ? (rows[cols.value] ?? []) : null;
  const cats = cols.category ? (rows[cols.category] ?? []) : null;
  const samples = cols.sample ? (rows[cols.sample] ?? []) : null;
  const labels = cols.label ? (rows[cols.label] ?? []) : null;
  const lengths = cols.chromLength ? (rows[cols.chromLength] ?? []) : null;

  const out: IdeogramFeature[] = [];
  const n = Math.min(chroms.length, starts.length);
  for (let i = 0; i < n; i += 1) {
    const chrom = str(chroms[i]);
    const s = num(starts[i]);
    if (!chrom || s === null) continue;
    const e = ends ? num(ends[i]) : null;
    const end = e === null ? s : e;
    out.push({
      chrom,
      start: Math.max(0, Math.min(s, end)),
      end: Math.max(0, Math.max(s, end)),
      value: values ? num(values[i]) : null,
      category: cats ? str(cats[i]) : null,
      sample: samples ? str(samples[i]) : null,
      label: labels ? str(labels[i]) : null,
      chromLength: lengths ? num(lengths[i]) : null,
      row: i,
    });
  }
  return out;
}

/** Numeric-aware order for sample and genome names (`S2` before `S10`). */
export function compareSample(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

// ---------------------------------------------------------------------------
// Samples
// ---------------------------------------------------------------------------

export interface FacetOptions {
  facetBySample: boolean;
  /** Sample shown when not faceting; null or unknown picks the first. */
  sample?: string | null;
  maxFacets: number;
}

export interface FacetPlan {
  /** Karyotypes to draw, in order. `null` is "every row" (no sample column). */
  shown: (string | null)[];
  /** Every sample present, in order, for a selector. */
  all: string[];
  /** Samples the `max_facets` guard left out. */
  dropped: number;
}

/** Which samples get a karyotype. */
export function planFacets(features: readonly IdeogramFeature[], options: FacetOptions): FacetPlan {
  const seen = new Set<string>();
  for (const f of features) if (f.sample !== null) seen.add(f.sample);
  const all = [...seen].sort(compareSample);
  if (all.length === 0) return { shown: [null], all, dropped: 0 };
  if (!options.facetBySample) {
    const pick = options.sample && seen.has(options.sample) ? options.sample : all[0];
    return { shown: [pick], all, dropped: 0 };
  }
  const cap = Math.max(1, Math.floor(options.maxFacets));
  return { shown: all.slice(0, cap), all, dropped: Math.max(0, all.length - cap) };
}

/** The features of one karyotype. */
export function featuresOf(
  features: readonly IdeogramFeature[],
  sample: string | null,
): IdeogramFeature[] {
  return sample === null ? [...features] : features.filter((f) => f.sample === sample);
}

// ---------------------------------------------------------------------------
// Chromosomes
// ---------------------------------------------------------------------------

/** Where a bar's length came from, for the hover: a stated length is a fact,
 *  a derived one is only the furthest feature. */
export type LengthSource = 'column' | 'assembly' | 'data';

export interface ChromBar {
  /** Display name, taken from the data when the data names it. */
  name: string;
  /** Normalised key (`chr` prefix and case folded). */
  key: string;
  length: number;
  source: LengthSource;
}

export interface ChromosomeOptions {
  assembly?: string | null;
  /** Restrict and order the bars (`IdeogramConfig.chromosomes`). */
  order?: readonly string[] | null;
  maxChromosomes?: number;
}

export interface ChromosomeSet {
  bars: ChromBar[];
  /** Bars the `max_chromosomes` guard removed. */
  dropped: number;
}

/** Chromosomes an assembly table contributes only when a feature lands on them:
 *  the mitochondrion is a hairline beside chr1 and earns a bar only when used. */
const ONLY_WHEN_REFERENCED = new Set(['m', 'mt']);

/**
 * The bars of one karyotype and the length each is drawn to.
 *
 * Length precedence: a length column (the most specific statement: the
 * genome's own FASTA index), then the assembly table, then the furthest
 * feature. A feature past a stated length grows the bar rather than falling
 * off its end. With an assembly every chromosome of it gets a bar, so an empty
 * chromosome reads as empty instead of vanishing; without one only the
 * chromosomes the rows name are drawn.
 *
 * `max_chromosomes` keeps the longest bars (a draft assembly's hundreds of
 * unplaced scaffolds are the short ones) and keeps them in their order.
 */
export function chromosomeBars(
  features: readonly IdeogramFeature[],
  options: ChromosomeOptions = {},
): ChromosomeSet {
  const observed = new Map<string, { display: string; maxEnd: number; stated: number | null }>();
  for (const f of features) {
    const key = normaliseChrom(f.chrom);
    const seen = observed.get(key);
    if (seen) {
      seen.maxEnd = Math.max(seen.maxEnd, f.end);
      if (f.chromLength !== null) seen.stated = Math.max(seen.stated ?? 0, f.chromLength);
    } else {
      observed.set(key, { display: f.chrom, maxEnd: f.end, stated: f.chromLength });
    }
  }

  const bars: ChromBar[] = [];
  const table = assemblySizes(options.assembly);
  if (table) {
    for (const [canonical, size] of Object.entries(table)) {
      const key = normaliseChrom(canonical);
      const seen = observed.get(key);
      if (!seen && ONLY_WHEN_REFERENCED.has(key)) continue;
      const stated = seen?.stated ?? null;
      bars.push({
        name: seen?.display ?? canonical,
        key,
        length: Math.max(stated ?? size, seen?.maxEnd ?? 0),
        source: stated !== null ? 'column' : 'assembly',
      });
      observed.delete(key);
    }
  }
  for (const [key, seen] of observed) {
    bars.push({
      name: seen.display,
      key,
      length: Math.max(1, seen.stated ?? 0, seen.maxEnd),
      source: seen.stated !== null ? 'column' : 'data',
    });
  }

  let ordered: ChromBar[];
  if (options.order && options.order.length > 0) {
    const byKey = new Map(bars.map((b) => [b.key, b]));
    ordered = [];
    for (const name of options.order) {
      const bar = byKey.get(normaliseChrom(name));
      if (bar && !ordered.includes(bar)) ordered.push(bar);
    }
  } else {
    ordered = [...bars].sort((a, b) => compareChrom(a.name, b.name));
  }

  const cap = options.maxChromosomes ?? Number.POSITIVE_INFINITY;
  if (ordered.length <= cap) return { bars: ordered, dropped: 0 };
  const keep = new Set(
    [...ordered]
      .sort((a, b) => b.length - a.length || compareChrom(a.name, b.name))
      .slice(0, Math.max(1, Math.floor(cap))),
  );
  const kept = ordered.filter((b) => keep.has(b));
  return { bars: kept, dropped: ordered.length - kept.length };
}

// ---------------------------------------------------------------------------
// Mode guard and density bins
// ---------------------------------------------------------------------------

export type IdeogramMode = 'marks' | 'density';

/**
 * The mode actually drawn. Above `max_features` marks would be a solid smear
 * (and tens of thousands of DOM nodes), so the tile draws the density bands
 * instead and says so: a guard that switches representation never hides a
 * subset of the features the way a cap on the marks would.
 */
export function effectiveMode(
  mode: IdeogramMode,
  featureCount: number,
  maxFeatures: number,
): { mode: IdeogramMode; guarded: boolean } {
  if (mode === 'marks' && featureCount > Math.max(1, maxFeatures)) {
    return { mode: 'density', guarded: true };
  }
  return { mode, guarded: false };
}

/** 1-2-5 steps, from 1 kb. */
function niceSteps(): number[] {
  const out: number[] = [];
  for (let p = 3; p <= 10; p += 1) for (const m of [1, 2, 5]) out.push(m * 10 ** p);
  return out;
}
const NICE_STEPS = niceSteps();

/** The smallest 1-2-5 bin width giving at most `target` bins on the longest bar. */
export function autoBinSize(maxLength: number, target = 100): number {
  const len = Math.max(1, maxLength);
  for (const step of NICE_STEPS) if (len / step <= target) return step;
  return NICE_STEPS[NICE_STEPS.length - 1];
}

/** One heat band along a chromosome. */
export interface Band {
  start: number;
  end: number;
  /** What the colour encodes: the mean value, or the number of features. */
  value: number;
  /** Features that fell in the band. */
  count: number;
}

export interface DensityOptions {
  /** Explicit bin width; null picks one (or keeps the rows as bins, see below). */
  binSize?: number | null;
  /** Colour by the bound value (mean per bin) rather than by count. */
  useValue: boolean;
}

export interface DensityResult {
  /** Bands per bar key, in position order. */
  bands: Map<string, Band[]>;
  /** The bin width used, or null when the rows are their own bins. */
  binSize: number | null;
  /** Lowest and highest band value, for the colour scale. */
  min: number;
  max: number;
}

/**
 * Density bands for one karyotype.
 *
 * Rows that already are bins (a binned VCF density with its value) are drawn
 * as they are when no `bin_size` is set: re-binning a binned table only blurs
 * it. Otherwise each feature falls in the bin holding its midpoint, and a bin
 * shows the mean value (a density averaged stays a density) or the count. A
 * feature on a chromosome with no bar is not drawn; empty bins are omitted so
 * the bar behind shows through.
 */
export function densityBands(
  features: readonly IdeogramFeature[],
  bars: readonly ChromBar[],
  options: DensityOptions,
): DensityResult {
  const byKey = new Map(bars.map((b) => [b.key, b]));
  const bands = new Map<string, Band[]>();
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  const note = (v: number) => {
    min = Math.min(min, v);
    max = Math.max(max, v);
  };

  if (options.useValue && (options.binSize === null || options.binSize === undefined)) {
    for (const f of features) {
      if (f.value === null) continue;
      const bar = byKey.get(normaliseChrom(f.chrom));
      if (!bar) continue;
      const list = bands.get(bar.key) ?? [];
      list.push({ start: f.start, end: Math.max(f.end, f.start), value: f.value, count: 1 });
      bands.set(bar.key, list);
      note(f.value);
    }
    for (const list of bands.values()) list.sort((a, b) => a.start - b.start);
    return finish(bands, null, min, max, options.useValue);
  }

  const longest = bars.reduce((acc, b) => Math.max(acc, b.length), 0);
  const binSize = Math.max(1, Math.floor(options.binSize ?? autoBinSize(longest)));
  const acc = new Map<string, Map<number, { sum: number; n: number; count: number }>>();
  for (const f of features) {
    const bar = byKey.get(normaliseChrom(f.chrom));
    if (!bar) continue;
    if (options.useValue && f.value === null) continue;
    const bin = Math.floor((f.start + f.end) / 2 / binSize);
    const bins = acc.get(bar.key) ?? new Map();
    const cell = bins.get(bin) ?? { sum: 0, n: 0, count: 0 };
    cell.count += 1;
    if (f.value !== null) {
      cell.sum += f.value;
      cell.n += 1;
    }
    bins.set(bin, cell);
    acc.set(bar.key, bins);
  }
  for (const [key, bins] of acc) {
    const bar = byKey.get(key)!;
    const list: Band[] = [];
    for (const [bin, cell] of [...bins.entries()].sort((a, b) => a[0] - b[0])) {
      const value = options.useValue ? cell.sum / Math.max(1, cell.n) : cell.count;
      const start = bin * binSize;
      list.push({ start, end: Math.min(bar.length, start + binSize), value, count: cell.count });
      note(value);
    }
    bands.set(key, list);
  }
  return finish(bands, binSize, min, max, options.useValue);
}

function finish(
  bands: Map<string, Band[]>,
  binSize: number | null,
  min: number,
  max: number,
  useValue: boolean,
): DensityResult {
  if (!Number.isFinite(min)) return { bands, binSize, min: 0, max: 0 };
  // A count scale starts at zero, so one feature in a bin is never drawn as
  // the "coldest" colour of a scale whose bottom nobody reached.
  return { bands, binSize, min: useValue ? min : 0, max };
}

/** Position of `value` on a colour scale spanning `[min, max]`, in [0, 1].
 *  A flat scale (one value everywhere) sits at its top, not its bottom. */
export function scaleT(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return 0;
  if (!(max > min)) return 1;
  return Math.min(1, Math.max(0, (value - min) / (max - min)));
}

/** Lowest and highest finite value among the features, or null when none. */
export function valueExtent(features: readonly IdeogramFeature[]): [number, number] | null {
  let lo = Number.POSITIVE_INFINITY;
  let hi = Number.NEGATIVE_INFINITY;
  for (const f of features) {
    if (f.value === null) continue;
    lo = Math.min(lo, f.value);
    hi = Math.max(hi, f.value);
  }
  return Number.isFinite(lo) ? [lo, hi] : null;
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

export type Orientation = 'horizontal' | 'vertical';

/** A rectangle in SVG pixels. */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** One chromosome bar placed in a panel. */
export interface BarGeom extends Rect {
  bar: ChromBar;
  /** Where the chromosome name is drawn. */
  labelX: number;
  labelY: number;
  /** Whether this bar's name is drawn (narrow vertical bars skip some). */
  showLabel: boolean;
}

export interface AxisTick {
  pos: number;
  /** Pixel coordinate along the bars (x when horizontal, y when vertical). */
  px: number;
  label: string;
}

/** One karyotype in the tile. */
export interface PanelGeom extends Rect {
  title: string | null;
  bars: BarGeom[];
  ticks: AxisTick[];
  /** Pixel of the origin and of the longest length, along the bars. */
  origin: number;
  far: number;
  /** Length in bp the far edge stands for (shared by every panel). */
  scaleLength: number;
  orientation: Orientation;
}

export interface PanelInput {
  title: string | null;
  bars: ChromBar[];
}

export interface GeometryOptions {
  width: number;
  height: number;
  orientation: Orientation;
}

/** Furniture, in px. Exported so the content demand uses the same numbers. */
export const GEOMETRY = {
  titleH: 18,
  axisH: 22,
  rightPad: 24,
  minPitch: 13,
  maxThickness: 16,
  minThickness: 2,
  minPanelW: 300,
  axisW: 48,
  bottomLabelH: 18,
  verticalPanelH: 280,
  charW: 6.4,
} as const;

/** The 1-2-5 tick step giving at most `target` ticks over `length`. */
export function tickStep(length: number, target: number): number {
  const len = Math.max(1, length);
  const t = Math.max(1, Math.floor(target));
  for (const step of NICE_STEPS) if (len / step <= t) return step;
  return NICE_STEPS[NICE_STEPS.length - 1];
}

/** How many panel columns fit `width`. */
export function facetColumns(width: number, panels: number, orientation: Orientation): number {
  if (panels <= 1) return 1;
  const minW = orientation === 'horizontal' ? GEOMETRY.minPanelW : GEOMETRY.minPanelW * 0.8;
  return Math.max(1, Math.min(panels, Math.floor(Math.max(0, width) / minW)));
}

/** Pixel offset along the bars for a position, in a panel. */
export function alongPx(panel: Pick<PanelGeom, 'origin' | 'far' | 'scaleLength'>, pos: number): number {
  const t = panel.scaleLength > 0 ? pos / panel.scaleLength : 0;
  return panel.origin + t * (panel.far - panel.origin);
}

/** Position under a pixel offset along a bar, clamped to the chromosome. */
export function positionAt(panel: PanelGeom, geom: BarGeom, px: number): number {
  const span = panel.far - panel.origin;
  if (span === 0) return 0;
  const pos = ((px - panel.origin) / span) * panel.scaleLength;
  return Math.round(Math.min(geom.bar.length, Math.max(0, pos)));
}

/**
 * Place the karyotypes in a `width` x `height` box.
 *
 * Panels sit in a grid, as many columns as fit. Every panel shares one scale
 * (the longest chromosome of any of them), so a small genome draws short bars
 * rather than being stretched to look like a large one. Horizontal bars are
 * one row each with the names in a left gutter and the position axis under
 * them; vertical bars stand side by side from a top origin with the names
 * underneath and the axis on the left. Tick labels sit inside the panel's own
 * furniture, so none is cut at the tile edge.
 */
export function layoutPanels(inputs: readonly PanelInput[], options: GeometryOptions): PanelGeom[] {
  const { width, height, orientation } = options;
  if (inputs.length === 0 || width <= 0 || height <= 0) return [];
  const cols = facetColumns(width, inputs.length, orientation);
  const rows = Math.ceil(inputs.length / cols);
  const pw = width / cols;
  const ph = height / rows;
  const scaleLength = inputs.reduce(
    (acc, p) => p.bars.reduce((a, b) => Math.max(a, b.length), acc),
    0,
  );
  const withTitles = inputs.some((p) => p.title !== null);

  return inputs.map((input, i) => {
    const x = (i % cols) * pw;
    const y = Math.floor(i / cols) * ph;
    const titleH = withTitles ? GEOMETRY.titleH : 4;
    const n = Math.max(1, input.bars.length);
    const longestName = input.bars.reduce((acc, b) => Math.max(acc, b.name.length), 1);

    if (orientation === 'horizontal') {
      const labelW = Math.min(110, Math.max(28, longestName * GEOMETRY.charW + 10));
      const origin = x + labelW;
      const far = Math.max(origin + 1, x + pw - GEOMETRY.rightPad);
      const top = y + titleH;
      const bottom = Math.max(top + 1, y + ph - GEOMETRY.axisH);
      const pitch = (bottom - top) / n;
      const thick = Math.max(
        GEOMETRY.minThickness,
        Math.min(GEOMETRY.maxThickness, pitch * 0.62),
      );
      const bars: BarGeom[] = input.bars.map((bar, k) => {
        const by = top + k * pitch + (pitch - thick) / 2;
        const len = alongPx({ origin, far, scaleLength }, bar.length) - origin;
        return {
          bar,
          x: origin,
          y: by,
          w: Math.max(1, len),
          h: thick,
          labelX: origin - 6,
          labelY: by + thick / 2,
          showLabel: true,
        };
      });
      const step = tickStep(scaleLength, Math.max(2, Math.floor((far - origin) / 70)));
      return {
        x,
        y,
        w: pw,
        h: ph,
        title: input.title,
        bars,
        ticks: ticks(scaleLength, step, { origin, far, scaleLength }),
        origin,
        far,
        scaleLength,
        orientation,
      };
    }

    const left = x + GEOMETRY.axisW;
    const right = Math.max(left + 1, x + pw - 8);
    const origin = y + titleH + 6;
    const far = Math.max(origin + 1, y + ph - GEOMETRY.bottomLabelH);
    const pitch = (right - left) / n;
    const thick = Math.max(GEOMETRY.minThickness, Math.min(GEOMETRY.maxThickness + 2, pitch * 0.55));
    // Names under narrow bars collide; draw every k-th so the drawn ones fit.
    const every = Math.max(1, Math.ceil((longestName * GEOMETRY.charW + 4) / Math.max(1, pitch)));
    const bars: BarGeom[] = input.bars.map((bar, k) => {
      const bx = left + k * pitch + (pitch - thick) / 2;
      const len = alongPx({ origin, far, scaleLength }, bar.length) - origin;
      return {
        bar,
        x: bx,
        y: origin,
        w: thick,
        h: Math.max(1, len),
        labelX: bx + thick / 2,
        labelY: far + 13,
        showLabel: k % every === 0,
      };
    });
    const step = tickStep(scaleLength, Math.max(2, Math.floor((far - origin) / 40)));
    return {
      x,
      y,
      w: pw,
      h: ph,
      title: input.title,
      bars,
      ticks: ticks(scaleLength, step, { origin, far, scaleLength }),
      origin,
      far,
      scaleLength,
      orientation,
    };
  });
}

function ticks(
  length: number,
  step: number,
  scale: Pick<PanelGeom, 'origin' | 'far' | 'scaleLength'>,
): AxisTick[] {
  const out: AxisTick[] = [];
  if (!(length > 0) || !(step > 0)) return out;
  for (let pos = 0; pos <= length + 1e-9; pos += step) {
    out.push({ pos, px: alongPx(scale, pos), label: pos === 0 ? '0' : formatBp(pos) });
  }
  return out;
}

/**
 * The rectangle a feature (or a band) covers on its bar.
 *
 * A feature narrower than `minPx` on screen becomes a tick: `minPx` wide along
 * the bar and overhanging it across, which is how a BUSCO gene stays visible
 * on a 200 Mb chromosome. Wider features fill the bar's thickness.
 */
export function spanRect(
  panel: PanelGeom,
  geom: BarGeom,
  start: number,
  end: number,
  options: { minPx?: number; overhang?: number } = {},
): Rect & { tick: boolean } {
  const minPx = options.minPx ?? 1.5;
  const overhang = options.overhang ?? 0;
  const a0 = alongPx(panel, Math.max(0, start));
  const a1 = alongPx(panel, Math.min(geom.bar.length, Math.max(start, end)));
  let lo = Math.min(a0, a1);
  let len = Math.abs(a1 - a0);
  const tick = len < minPx;
  if (tick) {
    lo = (a0 + a1) / 2 - minPx / 2;
    len = minPx;
  }
  const grow = tick ? overhang : 0;
  if (panel.orientation === 'horizontal') {
    return { x: lo, y: geom.y - grow, w: len, h: geom.h + 2 * grow, tick };
  }
  return { x: geom.x - grow, y: lo, w: geom.w + 2 * grow, h: len, tick };
}

/** Pixel coordinate along the bar for a pointer at (`x`, `y`). */
export function pointerAlong(panel: PanelGeom, x: number, y: number): number {
  return panel.orientation === 'horizontal' ? x : y;
}

/**
 * The region a click or a drag on a bar stands for: the whole chromosome for
 * a click (`range` null), the dragged span for a drag of at least `minBp`.
 */
export function regionFromGesture(
  bar: ChromBar,
  fromBp: number,
  toBp: number,
  minBp: number,
): { chroms: string[]; range: [number, number] | null } {
  const lo = Math.max(0, Math.min(fromBp, toBp));
  const hi = Math.min(bar.length, Math.max(fromBp, toBp));
  if (hi - lo < Math.max(1, minBp)) return { chroms: [bar.name], range: null };
  return { chroms: [bar.name], range: [Math.round(lo), Math.round(hi)] };
}

/** The bar of a panel a region names, or null. */
export function barForChrom(panel: PanelGeom, chrom: string): BarGeom | null {
  const key = normaliseChrom(chrom);
  return panel.bars.find((g) => g.bar.key === key) ?? null;
}

// ---------------------------------------------------------------------------
// Sizing and wording
// ---------------------------------------------------------------------------

/**
 * Pixel height the karyotypes need to stay readable at `width`: every bar at
 * least `GEOMETRY.minPitch` apart when horizontal, a fixed panel height when
 * vertical. The tile turns it into a content demand.
 */
export function idealHeight(
  width: number,
  panels: readonly PanelInput[],
  orientation: Orientation,
): number {
  if (panels.length === 0) return 0;
  const cols = facetColumns(width, panels.length, orientation);
  const rows = Math.ceil(panels.length / cols);
  if (orientation === 'vertical') return rows * GEOMETRY.verticalPanelH;
  const maxBars = panels.reduce((acc, p) => Math.max(acc, p.bars.length), 1);
  return rows * (GEOMETRY.titleH + GEOMETRY.axisH + maxBars * GEOMETRY.minPitch);
}

/** What a feature says about itself, in reading order; unbound roles drop out. */
export function featureSummary(f: IdeogramFeature, valueLabel = 'value'): string[] {
  const where =
    f.end > f.start
      ? `${f.chrom}:${formatBp(f.start)}-${formatBp(f.end)}`
      : `${f.chrom}:${formatBp(f.start)}`;
  return [
    f.label,
    where,
    f.category,
    f.value !== null ? `${valueLabel} ${formatValue(f.value)}` : null,
    f.sample,
  ].filter((part): part is string => Boolean(part));
}

/** What a band says about itself. */
export function bandSummary(
  bar: ChromBar,
  band: Band,
  useValue: boolean,
  valueLabel = 'value',
): string {
  const where = `${bar.name}:${formatBp(band.start)}-${formatBp(band.end)}`;
  const what = useValue
    ? `mean ${valueLabel} ${formatValue(band.value)}`
    : `${band.count} feature${band.count === 1 ? '' : 's'}`;
  return `${where}  ·  ${what}`;
}

/** What a bar says about itself: its name, its length and where that came from. */
export function barSummary(bar: ChromBar, featureCount: number): string {
  const source =
    bar.source === 'column' ? '' : bar.source === 'assembly' ? ' (assembly)' : ' (to the last feature)';
  return `${bar.name}  ·  ${formatBp(bar.length)}${source}  ·  ${featureCount} feature${
    featureCount === 1 ? '' : 's'
  }`;
}

/** Compact number for a hover: 3 significant digits, thousands separated. */
export function formatValue(v: number): string {
  if (!Number.isFinite(v)) return '';
  if (Number.isInteger(v)) return v.toLocaleString('en-US');
  const abs = Math.abs(v);
  if (abs >= 100) return Math.round(v).toLocaleString('en-US');
  return Number(v.toPrecision(3)).toString();
}

/** Feature counts per bar key, for the bar hover. */
export function countByChrom(features: readonly IdeogramFeature[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const f of features) {
    const key = normaliseChrom(f.chrom);
    out.set(key, (out.get(key) ?? 0) + 1);
  }
  return out;
}
