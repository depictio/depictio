/**
 * Geometry of the star overlay: true five-pointed stars drawn as SVG over the
 * GenomeSpy canvas, for a `genome_view`'s `top_stars`.
 *
 * GenomeSpy cannot draw a star (a point `shape` is one of a fixed set of
 * shader SDFs, and its bundled font has no glyph for one), so the spec keeps
 * the starred rows as an invisible, hoverable point layer and the stars are
 * placed here, exactly: from the lane's last rendered layout bounds, the
 * genome axis' visible domain and the score scale's domain, all of which the
 * public embed API hands out (`views.getLayoutBounds`,
 * `getScaleResolutionByName(...).getDomain()`). Pure functions only; the DOM
 * and the subscriptions are `useStarOverlay`'s.
 */
import { STAR_FIELD } from './genomeSpySpec';
import type { Contig } from './genomeSpySpec';

/** A rectangle in CSS pixels (GenomeSpy's `ViewLayoutBounds`). */
export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A starred row, reduced to what placing it needs. */
export interface StarRow {
  chrom: string;
  /** Zero-based position, the coordinate GenomeSpy's locus scale linearises. */
  pos: number;
  score: number;
  /** 1, 2 or 3: gold, silver, bronze. */
  medal: number;
}

/** A star placed in pixels, relative to the same origin as the bounds. */
export interface PlacedStar {
  x: number;
  y: number;
  medal: number;
}

/**
 * Linear start of each contig, by every name GenomeSpy accepts for it: the
 * name, with and without a `chr` prefix, in the spellings it adds (`CHR`,
 * `Chr`) and its 1-based number. GenomeSpy's genome (`setChromSizes`) lays the
 * contigs end to end in the given order, so this repeats its table.
 */
export function contigOffsets(contigs: readonly Contig[]): Map<string, number> {
  const out = new Map<string, number>();
  let pos = 0;
  contigs.forEach((contig, i) => {
    const plain = contig.name.replace(/^chr/i, '');
    for (const name of [`chr${plain}`, `CHR${plain}`, `Chr${plain}`, String(i + 1), plain, contig.name]) {
      out.set(name, pos);
    }
    pos += contig.size;
  });
  return out;
}

/** The linearised coordinate of `chrom:pos`, or null for a contig the axis lacks. */
export function locusToLinear(offsets: ReadonlyMap<string, number>, chrom: string, pos: number): number | null {
  const offset = offsets.get(chrom);
  if (offset === undefined || !Number.isFinite(pos)) return null;
  return offset + pos;
}

/**
 * Pixel of `value` on a linear scale: `domain` maps onto the span that starts
 * at `start` and runs `length` pixels, backwards when `length` is negative
 * (a y axis, higher on screen is up). A degenerate domain maps to its middle.
 */
export function linearPixel(value: number, domain: readonly [number, number], start: number, length: number): number {
  const span = domain[1] - domain[0];
  if (span === 0 || !Number.isFinite(span)) return start + length / 2;
  return start + ((value - domain[0]) / span) * length;
}

/**
 * Where the stars of `rows` sit in a view.
 *
 * `bounds` is the lane's layout box, `xDomain` the genome axis' visible
 * linearised domain, `yDomain` the score domain. A star whose centre is more
 * than `reach` pixels outside the box (its radius: some of it would still
 * show) is left out; the caller clips the rest to the box. Medals draw
 * bronze first, so the best star lies on top where two overlap.
 */
export function placeStars(opts: {
  rows: readonly StarRow[];
  offsets: ReadonlyMap<string, number>;
  bounds: Bounds;
  xDomain: readonly [number, number];
  yDomain: readonly [number, number];
  reach: number;
}): PlacedStar[] {
  const { rows, offsets, bounds, xDomain, yDomain, reach } = opts;
  const placed: PlacedStar[] = [];
  for (const row of rows) {
    const linear = locusToLinear(offsets, row.chrom, row.pos);
    if (linear === null || !Number.isFinite(row.score)) continue;
    const x = linearPixel(linear, xDomain, bounds.x, bounds.width);
    // Scores grow upwards: the domain's low end is the box's bottom.
    const y = linearPixel(row.score, yDomain, bounds.y + bounds.height, -bounds.height);
    if (x < bounds.x - reach || x > bounds.x + bounds.width + reach) continue;
    if (y < bounds.y - reach || y > bounds.y + bounds.height + reach) continue;
    placed.push({ x, y, medal: row.medal });
  }
  return placed.sort((a, b) => b.medal - a.medal);
}

/** Inner over outer radius of the star: a plump star, like the glyph. */
export const STAR_INNER_RATIO = 0.45;

/** Outer radius, in pixels, of a star beside points of `pointSize`. */
export function starRadius(pointSize: number): number {
  return Math.max(6, pointSize * 1.4);
}

/** The ten vertices of an upright five-pointed star centred on `(cx, cy)`,
 *  the first tip straight up, running clockwise (y down). */
export function starVertices(cx: number, cy: number, outer: number, ratio = STAR_INNER_RATIO): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i < 10; i++) {
    const radius = i % 2 === 0 ? outer : outer * ratio;
    const angle = -Math.PI / 2 + (i * Math.PI) / 5;
    out.push([cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)]);
  }
  return out;
}

const fmt = (n: number) => String(Math.round(n * 100) / 100);

/** SVG path data of {@link starVertices}. */
export function starPath(cx: number, cy: number, outer: number, ratio = STAR_INNER_RATIO): string {
  return `${starVertices(cx, cy, outer, ratio)
    .map(([x, y], i) => `${i ? 'L' : 'M'}${fmt(x)} ${fmt(y)}`)
    .join(' ')}Z`;
}

/** The intersection of two boxes, or null when they do not meet. */
export function intersectBounds(a: Bounds, b: Bounds): Bounds | null {
  const x = Math.max(a.x, b.x);
  const y = Math.max(a.y, b.y);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  return right > x && bottom > y ? { x, y, width: right - x, height: bottom - y } : null;
}

/**
 * The starred rows of `data` (the rows `markTopStars` marked) that a lane
 * draws: every one, or with a `sample`, those whose `sampleCol` is it. Rows
 * without a usable position or score are skipped.
 */
export function starRowsOf(
  data: readonly Record<string, unknown>[] | null | undefined,
  cols: { chr: string; pos: string; score: string; sample?: string | null },
  sample: string | null,
): StarRow[] {
  const out: StarRow[] = [];
  for (const row of data ?? []) {
    const medal = Number(row[STAR_FIELD]);
    if (!(medal >= 1 && medal <= 3)) continue;
    if (sample !== null && cols.sample && String(row[cols.sample]) !== sample) continue;
    const pos = Number(row[cols.pos]);
    const score = Number(row[cols.score]);
    const chrom = row[cols.chr];
    if (chrom === null || chrom === undefined || !Number.isFinite(pos) || !Number.isFinite(score)) continue;
    out.push({ chrom: String(chrom), pos, score, medal });
  }
  return out;
}
