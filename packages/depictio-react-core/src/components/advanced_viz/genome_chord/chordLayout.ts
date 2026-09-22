/**
 * Pure layout maths for the `genome_chord` kind.
 *
 * No chord primitive exists in the stack: Plotly has no chord trace and d3 is
 * not a dependency of any package here, so the renderer draws its own SVG. Every
 * number it needs is computed in this module, which keeps the React file down to
 * elements and event handlers and makes the geometry testable without a DOM.
 *
 * Angle convention: radians, 0 at twelve o'clock, increasing clockwise. SVG's y
 * axis points down, so `polarPoint` maps an angle to `(cx + r sin a, cy - r cos a)`
 * and every arc is drawn with sweep-flag 1. Circos and its descendants read
 * clockwise from the top, and matching that is what makes the picture legible to
 * the people who already read those.
 */

/** One chromosome as the ring lays it out. */
export interface ChromSize {
  /** Name as it should be displayed, taken from the data when the data names it. */
  name: string;
  /** Length in base pairs the arc is made proportional to. */
  size: number;
}

/** A chromosome band placed on the ring. */
export interface ChromArc extends ChromSize {
  /** Angle of the first base, radians clockwise from twelve o'clock. */
  start: number;
  /** Angle of the last base. */
  end: number;
  /** Angle halfway along the band, where the label sits. */
  mid: number;
}

export interface RingLayout {
  arcs: ChromArc[];
  /** Arcs keyed by normalised chromosome name, for `angleAt`. */
  byName: Map<string, ChromArc>;
  /** Summed chromosome length the angles are proportional to. */
  totalSize: number;
}

/** One link between two loci, as the renderer hands it to the layout. */
export interface ChordLink {
  chromA: string;
  posA: number;
  chromB: string;
  posB: number;
  /** Name of the link (fusion, structural variant). Drives the selection filter. */
  label: string | null;
  /** Supporting evidence. Null when no weight column is bound: every link then
   *  draws at the same width, which is the honest picture of "no weight given". */
  weight: number | null;
  /** Class of the link (fusion type, SV type). Drives the colour. */
  category: string | null;
  /** Sample the link belongs to, shown in the tooltip when bound. */
  sample: string | null;
  /** Index in the fetched frame, so a stable React key survives re-sorting. */
  row: number;
}

export interface Point {
  x: number;
  y: number;
}

const TAU = Math.PI * 2;

// ---------------------------------------------------------------------------
// Rows to links
// ---------------------------------------------------------------------------

/** Column names the renderer binds, straight off `GenomeChordConfig`. */
export interface ChordColumns {
  chromA: string;
  posA: string;
  chromB: string;
  posB: string;
  label?: string | null;
  weight?: string | null;
  category?: string | null;
  sample?: string | null;
}

/** Finite number or null, for values that arrive as strings from the API. */
function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Non-empty string or null. */
function str(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const s = String(value);
  return s === '' ? null : s;
}

/**
 * Column-oriented rows (what `/advanced_viz/data` returns) to `ChordLink[]`.
 *
 * A link with half a coordinate cannot be placed on the ring, and there is
 * nothing to fall back on: it is dropped rather than drawn somewhere wrong.
 * `row` is the index in the fetched frame, which is what keeps the React key
 * and `prepareLinks`'s tie-break stable across re-sorting.
 */
export function parseChordRows(
  rows: Record<string, unknown[]>,
  cols: ChordColumns,
): ChordLink[] {
  const ca = rows[cols.chromA] ?? [];
  const pa = rows[cols.posA] ?? [];
  const cb = rows[cols.chromB] ?? [];
  const pb = rows[cols.posB] ?? [];
  const labels = cols.label ? (rows[cols.label] ?? []) : null;
  const weights = cols.weight ? (rows[cols.weight] ?? []) : null;
  const cats = cols.category ? (rows[cols.category] ?? []) : null;
  const samples = cols.sample ? (rows[cols.sample] ?? []) : null;

  const out: ChordLink[] = [];
  const n = Math.min(ca.length, pa.length, cb.length, pb.length);
  for (let i = 0; i < n; i += 1) {
    const chromA = str(ca[i]);
    const chromB = str(cb[i]);
    const posA = num(pa[i]);
    const posB = num(pb[i]);
    if (!chromA || !chromB || posA === null || posB === null) continue;
    out.push({
      chromA,
      posA,
      chromB,
      posB,
      label: labels ? str(labels[i]) : null,
      weight: weights ? num(weights[i]) : null,
      category: cats ? str(cats[i]) : null,
      sample: samples ? str(samples[i]) : null,
      row: i,
    });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Assemblies
// ---------------------------------------------------------------------------

/**
 * Primary-assembly chromosome lengths, in the order the ring draws them.
 *
 * A short constant table rather than a fetched asset: three assemblies cover
 * every megatest that produces breakpoint pairs, the numbers are fixed by the
 * assembly, and a ring that has to wait on a network round trip before it can
 * place a single arc is a worse trade than 75 lines of literals. Anything else,
 * including a non-model organism or a draft assembly, falls through to sizes
 * derived from the data (`assembly: null`).
 */
export const ASSEMBLY_CHROM_SIZES: Record<string, Record<string, number>> = {
  hg38: {
    chr1: 248956422,
    chr2: 242193529,
    chr3: 198295559,
    chr4: 190214555,
    chr5: 181538259,
    chr6: 170805979,
    chr7: 159345973,
    chr8: 145138636,
    chr9: 138394717,
    chr10: 133797422,
    chr11: 135086622,
    chr12: 133275309,
    chr13: 114364328,
    chr14: 107043718,
    chr15: 101991189,
    chr16: 90338345,
    chr17: 83257441,
    chr18: 80373285,
    chr19: 58617616,
    chr20: 64444167,
    chr21: 46709983,
    chr22: 50818468,
    chrX: 156040895,
    chrY: 57227415,
    chrM: 16569,
  },
  hg19: {
    chr1: 249250621,
    chr2: 243199373,
    chr3: 198022430,
    chr4: 191154276,
    chr5: 180915260,
    chr6: 171115067,
    chr7: 159138663,
    chr8: 146364022,
    chr9: 141213431,
    chr10: 135534747,
    chr11: 135006516,
    chr12: 133851895,
    chr13: 115169878,
    chr14: 107349540,
    chr15: 102531392,
    chr16: 90354753,
    chr17: 81195210,
    chr18: 78077248,
    chr19: 59128983,
    chr20: 63025520,
    chr21: 48129895,
    chr22: 51304566,
    chrX: 155270560,
    chrY: 59373566,
    chrM: 16571,
  },
  mm10: {
    chr1: 195471971,
    chr2: 182113224,
    chr3: 160039680,
    chr4: 156508116,
    chr5: 151834684,
    chr6: 149736546,
    chr7: 145441459,
    chr8: 129401213,
    chr9: 124595110,
    chr10: 130694993,
    chr11: 122082543,
    chr12: 120129022,
    chr13: 120421639,
    chr14: 124902244,
    chr15: 104043685,
    chr16: 98207768,
    chr17: 94987271,
    chr18: 90702639,
    chr19: 61431566,
    chrX: 171031299,
    chrY: 91744698,
    chrM: 16299,
  },
};

/** The assembly names the ring can lay itself out on. */
export const ASSEMBLY_NAMES = Object.keys(ASSEMBLY_CHROM_SIZES);

/**
 * Chromosomes an assembly table contributes only when the data references them.
 *
 * The mitochondrion is 1/15000th of chr1 in human: on a ring it is a hairline
 * that carries a label, so it earns its place only when a link actually lands
 * on it.
 */
const ONLY_WHEN_REFERENCED = new Set(['m', 'mt']);

/** Padding applied to a data-derived chromosome length so the last locus is not
 *  exactly on the arc boundary. */
const DERIVED_SIZE_PADDING = 1.02;

/** Strip a `chr` / `Chr` prefix and case, so `chr7`, `Chr7` and `7` are one key. */
export function normaliseChrom(name: string): string {
  return name.trim().replace(/^chr/i, '').toLowerCase();
}

/** Sort key giving 1..22, X, Y, M, then anything else alphabetically. */
export function chromOrderKey(name: string): number {
  const k = normaliseChrom(name);
  if (/^\d+$/.test(k)) return Number(k);
  if (k === 'x') return 1000;
  if (k === 'y') return 1001;
  if (k === 'm' || k === 'mt') return 1002;
  return 2000;
}

/** Natural chromosome comparator: numeric first, then X / Y / M, then contigs. */
export function compareChrom(a: string, b: string): number {
  const ka = chromOrderKey(a);
  const kb = chromOrderKey(b);
  if (ka !== kb) return ka - kb;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

/** The size table for an assembly name, or null when it is unknown or unset. */
export function assemblySizes(assembly?: string | null): Record<string, number> | null {
  if (!assembly) return null;
  return ASSEMBLY_CHROM_SIZES[assembly.trim().toLowerCase()] ?? null;
}

/**
 * The chromosomes the ring should carry, with the length each arc is made
 * proportional to.
 *
 * With a known assembly the ring is the whole genome, so an empty region reads
 * as an empty region rather than as a chromosome nobody sequenced. Without one,
 * only the chromosomes the data touches are drawn and each is sized by the
 * furthest locus on it, which is the best available stand-in and is why a
 * derived ring must never be read as genome-wide coverage.
 */
export function chromSizesFor(
  links: readonly ChordLink[],
  assembly?: string | null,
): ChromSize[] {
  const observed = new Map<string, { display: string; max: number }>();
  const note = (chrom: string, pos: number) => {
    if (!chrom) return;
    const key = normaliseChrom(chrom);
    const seen = observed.get(key);
    if (seen) seen.max = Math.max(seen.max, pos);
    else observed.set(key, { display: chrom, max: Math.max(pos, 0) });
  };
  for (const link of links) {
    note(link.chromA, link.posA);
    note(link.chromB, link.posB);
  }

  const table = assemblySizes(assembly);
  if (table) {
    const out: ChromSize[] = [];
    for (const [canonical, size] of Object.entries(table)) {
      const key = normaliseChrom(canonical);
      const seen = observed.get(key);
      if (!seen && ONLY_WHEN_REFERENCED.has(key)) continue;
      // A locus past the table's length would fall off its arc, so the arc grows
      // to hold it rather than silently clamping the link to the chromosome end.
      out.push({ name: seen?.display ?? canonical, size: Math.max(size, seen?.max ?? 0) });
      observed.delete(key);
    }
    // Contigs the assembly table does not name (decoys, alts, patches) still get
    // an arc, sized from the data, so their links are drawn rather than dropped.
    for (const seen of observed.values()) {
      out.push({ name: seen.display, size: Math.max(1, Math.ceil(seen.max * DERIVED_SIZE_PADDING)) });
    }
    return out;
  }

  return [...observed.values()]
    .sort((a, b) => compareChrom(a.display, b.display))
    .map((seen) => ({
      name: seen.display,
      size: Math.max(1, Math.ceil(seen.max * DERIVED_SIZE_PADDING)),
    }));
}

// ---------------------------------------------------------------------------
// The ring
// ---------------------------------------------------------------------------

export interface RingOptions {
  /** Gap between two chromosome bands, in radians. */
  padAngle?: number;
  /** Angle the first band starts at. Defaults to twelve o'clock. */
  startAngle?: number;
}

/**
 * Place the chromosomes on the ring, each band's angular width proportional to
 * its length and separated by a fixed gap.
 */
export function buildRing(sizes: readonly ChromSize[], options: RingOptions = {}): RingLayout {
  const padAngle = options.padAngle ?? 0.012;
  const startAngle = options.startAngle ?? 0;
  const arcs: ChromArc[] = [];
  const byName = new Map<string, ChromArc>();

  const usable = sizes.filter((s) => s.size > 0);
  const totalSize = usable.reduce((acc, s) => acc + s.size, 0);
  if (usable.length === 0 || totalSize <= 0) return { arcs, byName, totalSize: 0 };

  // The gaps come out of the circle before the bands are sized, so the bands
  // always sum to exactly the remaining angle however many chromosomes there are.
  const available = Math.max(0, TAU - padAngle * usable.length);
  let cursor = startAngle;
  for (const size of usable) {
    const span = (size.size / totalSize) * available;
    const arc: ChromArc = {
      name: size.name,
      size: size.size,
      start: cursor,
      end: cursor + span,
      mid: cursor + span / 2,
    };
    arcs.push(arc);
    byName.set(normaliseChrom(size.name), arc);
    cursor += span + padAngle;
  }
  return { arcs, byName, totalSize };
}

/** The angle a locus sits at, or null when its chromosome is not on the ring. */
export function angleAt(layout: RingLayout, chrom: string, pos: number): number | null {
  const arc = layout.byName.get(normaliseChrom(chrom ?? ''));
  if (!arc) return null;
  const fraction = arc.size > 0 ? Math.min(1, Math.max(0, pos / arc.size)) : 0;
  return arc.start + fraction * (arc.end - arc.start);
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

/** Cartesian point for an angle measured clockwise from twelve o'clock. */
export function polarPoint(cx: number, cy: number, r: number, angle: number): Point {
  return { x: cx + r * Math.sin(angle), y: cy - r * Math.cos(angle) };
}

/** Signed angular delta from `a` to `b`, in (-PI, PI]. */
export function signedDelta(a: number, b: number): number {
  let d = (b - a) % TAU;
  if (d <= -Math.PI) d += TAU;
  if (d > Math.PI) d -= TAU;
  return d;
}

/** Angular distance between two angles, in [0, PI]. */
export function angularSeparation(a: number, b: number): number {
  return Math.abs(signedDelta(a, b));
}

/** Angle halfway along the shorter way round from `a` to `b`. */
export function bisectAngle(a: number, b: number): number {
  return a + signedDelta(a, b) / 2;
}

/** Path for one chromosome band: an annulus segment between two radii. */
export function arcPath(
  cx: number,
  cy: number,
  rInner: number,
  rOuter: number,
  a0: number,
  a1: number,
): string {
  const largeArc = Math.abs(a1 - a0) > Math.PI ? 1 : 0;
  const o0 = polarPoint(cx, cy, rOuter, a0);
  const o1 = polarPoint(cx, cy, rOuter, a1);
  const i1 = polarPoint(cx, cy, rInner, a1);
  const i0 = polarPoint(cx, cy, rInner, a0);
  return [
    `M ${o0.x.toFixed(2)} ${o0.y.toFixed(2)}`,
    `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${o1.x.toFixed(2)} ${o1.y.toFixed(2)}`,
    `L ${i1.x.toFixed(2)} ${i1.y.toFixed(2)}`,
    `A ${rInner} ${rInner} 0 ${largeArc} 0 ${i0.x.toFixed(2)} ${i0.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

/**
 * Control point of the chord joining two angles.
 *
 * Its distance from the centre falls to zero as the two loci approach opposite
 * sides of the ring, so a translocation between distant chromosomes is a line
 * through the middle while two loci on the same chromosome are joined by a short
 * arc that hugs the rim. Drawing every chord through the exact centre would turn
 * each intra-chromosomal link into a spike across the whole picture.
 */
export function chordControlPoint(
  cx: number,
  cy: number,
  r: number,
  a0: number,
  a1: number,
  bulge: number,
): Point {
  const closeness = 1 - angularSeparation(a0, a1) / Math.PI;
  return polarPoint(cx, cy, r * closeness * bulge, bisectAngle(a0, a1));
}

/** Quadratic-Bezier path joining two loci on the ring. */
export function chordPath(
  cx: number,
  cy: number,
  r: number,
  a0: number,
  a1: number,
  bulge = 0.8,
): string {
  const p0 = polarPoint(cx, cy, r, a0);
  const p1 = polarPoint(cx, cy, r, a1);
  const c = chordControlPoint(cx, cy, r, a0, a1, bulge);
  return (
    `M ${p0.x.toFixed(2)} ${p0.y.toFixed(2)} ` +
    `Q ${c.x.toFixed(2)} ${c.y.toFixed(2)} ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`
  );
}

/**
 * Chord thickness for a weight, on a log scale.
 *
 * Read support spans orders of magnitude within one caller's output (3 to 300
 * reads in the Arriba megatest), so a linear width would draw one chord as a
 * slab and the rest as hairlines. Log10 of the weight plus one keeps a weight of
 * zero on the scale instead of off it.
 */
export function chordStrokeWidth(
  weight: number | null,
  minWeight: number,
  maxWeight: number,
  minPx: number,
  maxPx: number,
): number {
  if (weight === null || !Number.isFinite(weight)) return minPx + (maxPx - minPx) / 2;
  const l = Math.log10(1 + Math.max(0, weight));
  const l0 = Math.log10(1 + Math.max(0, minWeight));
  const l1 = Math.log10(1 + Math.max(0, maxWeight));
  if (!(l1 > l0)) return minPx + (maxPx - minPx) / 2;
  const t = Math.min(1, Math.max(0, (l - l0) / (l1 - l0)));
  return minPx + t * (maxPx - minPx);
}

// ---------------------------------------------------------------------------
// Ticks and labels
// ---------------------------------------------------------------------------

const TICK_STEPS = [1e6, 5e6, 1e7, 2.5e7, 5e7, 1e8, 2.5e8];

/** A tick spacing giving at most `target` ticks on the longest chromosome. */
export function tickStepFor(maxSize: number, target = 5): number {
  for (const step of TICK_STEPS) {
    if (maxSize / step <= target) return step;
  }
  return TICK_STEPS[TICK_STEPS.length - 1];
}

/** Tick positions along one chromosome, excluding the origin. */
export function ticksFor(size: number, step: number): number[] {
  const out: number[] = [];
  if (step <= 0) return out;
  for (let pos = step; pos < size; pos += step) out.push(pos);
  return out;
}

/** Human-readable base-pair position: `1.8 Mb`, `640 kb`, `812 bp`. */
export function formatBp(pos: number): string {
  if (!Number.isFinite(pos)) return '';
  const abs = Math.abs(pos);
  if (abs >= 1e6) return `${(pos / 1e6).toFixed(abs >= 1e7 ? 0 : 1)} Mb`;
  if (abs >= 1e3) return `${(pos / 1e3).toFixed(0)} kb`;
  return `${Math.round(pos)} bp`;
}

/**
 * What a link says about itself, in reading order: its name, the two loci it
 * joins, its support, its class and its sample. The unbound roles drop out.
 *
 * The SVG `<title>` and the hover card both render this list, joined
 * differently, so neither can start naming something the other does not. The
 * support is handed in already worded because the two spell it differently.
 */
export function linkSummary(link: ChordLink, weight: string | null): string[] {
  return [
    link.label,
    `${link.chromA}:${formatBp(link.posA)} to ${link.chromB}:${formatBp(link.posB)}`,
    weight,
    link.category,
    link.sample,
  ].filter((part): part is string => Boolean(part));
}

// ---------------------------------------------------------------------------
// Link selection
// ---------------------------------------------------------------------------

export interface PrepareLinksOptions {
  /** Drop links lighter than this. Ignored when no weight is bound. */
  minWeight?: number | null;
  /** Keep at most this many links, heaviest first. */
  maxLinks: number;
  /** Draw links whose two loci share a chromosome. */
  intraChromosomal: boolean;
}

export interface PreparedLinks {
  /** The links to draw, heaviest first. */
  kept: ChordLink[];
  /** How many valid links the guards removed. */
  dropped: number;
  /** Lightest and heaviest weight among the kept links, for the width scale. */
  minWeight: number;
  maxWeight: number;
}

/** Whether a link joins two loci on the same chromosome. */
export function isIntraChromosomal(link: ChordLink): boolean {
  return normaliseChrom(link.chromA) === normaliseChrom(link.chromB);
}

/**
 * Apply the guards and pick what is drawn.
 *
 * Sorting by weight before the cap is what makes `max_links` a guard rather than
 * a truncation: a run with 20000 breakends still shows its strongest 500, and
 * the frame says how many were left out. Links tie-break on their row index so
 * the picture is stable across refetches.
 */
export function prepareLinks(
  links: readonly ChordLink[],
  options: PrepareLinksOptions,
): PreparedLinks {
  const cap = Math.max(1, Math.floor(options.maxLinks));
  const threshold = options.minWeight ?? null;
  const eligible = links.filter((link) => {
    if (!options.intraChromosomal && isIntraChromosomal(link)) return false;
    if (threshold !== null && link.weight !== null && link.weight < threshold) return false;
    return true;
  });
  const sorted = [...eligible].sort((a, b) => {
    const wa = a.weight ?? 0;
    const wb = b.weight ?? 0;
    if (wa !== wb) return wb - wa;
    return a.row - b.row;
  });
  const kept = sorted.slice(0, cap);

  let minWeight = Number.POSITIVE_INFINITY;
  let maxWeight = Number.NEGATIVE_INFINITY;
  for (const link of kept) {
    if (link.weight === null) continue;
    minWeight = Math.min(minWeight, link.weight);
    maxWeight = Math.max(maxWeight, link.weight);
  }
  if (!Number.isFinite(minWeight)) {
    minWeight = 0;
    maxWeight = 0;
  }

  return { kept, dropped: links.length - kept.length, minWeight, maxWeight };
}
