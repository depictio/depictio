/**
 * Rows for the overlays of a `genome_view` (see `buildOverlayLayers` in
 * genomeSpySpec.ts): the region selected on it, and what other tiles draw
 * there, the band of the genome browser's visible window and the rule of a
 * hovered feature; plus the margin a zoom to a region keeps, and the
 * arithmetic the DOM fallback needs when the embed has no named-data API.
 *
 * Pure: no DOM, no React, no GenomeSpy. Contig names are the spec's own (the
 * ones its locus scale knows); an event's contig is matched against them with
 * the same alias and `chr`-prefix tolerance the plots use.
 */
import type { GenomicInterval } from '../../../highlight/genomicHover';
import type { ViewWindowEvent } from '../../../highlight/viewWindow';
import { matchChromosome } from '../crossTileCursor';
import type { Contig } from './genomeSpySpec';

/** One band: `[start, end]` on `chrom`, as the window layer encodes it. */
export interface WindowRow {
  chrom: string;
  start: number;
  end: number;
  /** Text the label layer draws (which browser this window is). */
  label?: string;
}

/** One rule at `pos` on `chrom`, as the hover layer encodes it. */
export interface HoverRow {
  chrom: string;
  pos: number;
  /** CSS colour of the tile that hovered, so the rule wears it. Absent: the
   *  theme's hover colour. */
  color?: string;
}

/** The band for a genome browser's window: one row, or none when the window is
 *  on a contig the view does not draw or has no extent. */
export function windowRows(
  win: Pick<ViewWindowEvent, 'entity' | 'entityAliases' | 'start' | 'end'> | null,
  contigNames: readonly string[],
): WindowRow[] {
  if (!win) return [];
  const chrom = matchChromosome(win.entity, contigNames, win.entityAliases);
  if (chrom === null) return [];
  const start = Number(win.start);
  const end = Number(win.end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return [];
  return [{ chrom, start, end }];
}

/** The selection overlay: the selected region, framed and labelled. */
export interface SelectionRow {
  chrom: string;
  start: number;
  end: number;
  /** Text the label layer draws. */
  label?: string;
}

/** Context kept on each side of a region the view zooms to, as a fraction of
 *  its span: enough for the selection's edges to show against the rest. */
export const REGION_ZOOM_PAD = 0.15;

/** `region` widened by `pad` of its span on each side, kept within its contig
 *  (`[0, size]`, or from 0 only when the size is unknown). An open-ended
 *  region (the whole contig) comes back as is. */
export function paddedRegion<T extends { chrom: string; start: number; end: number }>(
  region: T,
  size: number | null | undefined,
  pad = REGION_ZOOM_PAD,
): T {
  if (!Number.isFinite(region.end) || region.end <= region.start || pad <= 0) return region;
  const slack = (region.end - region.start) * pad;
  const max = size && size > 0 ? size : Infinity;
  return { ...region, start: Math.max(0, region.start - slack), end: Math.min(max, region.end + slack) };
}

/** `chr6:26.00-26.30 Mb`: a span short enough for a label on the canvas, in
 *  the unit its size reads best in. ASCII only: GenomeSpy's bundled font has
 *  no en dash. */
export function compactRegion(chrom: string, start: number, end: number): string {
  if (!Number.isFinite(start) || !Number.isFinite(end)) return chrom;
  // The unit the positions read in, and enough decimals for the span to show.
  const [div, unit] = end >= 1e6 ? [1e6, 'Mb'] : end >= 1e4 ? [1e3, 'kb'] : [1, 'bp'];
  const span = Math.max(end - start, 1);
  const digits = div === 1 ? 0 : Math.max(1, Math.min(3, Math.ceil(-Math.log10(span / div)) + 1));
  const fmt = (n: number) => (n / div).toFixed(digits);
  return `${chrom}:${fmt(start)}-${fmt(end)} ${unit}`;
}

/**
 * The selection overlay for the region in force. None on a contig the view
 * does not draw, or for an open-ended region (the whole contig is selected,
 * so there is no edge to frame).
 */
export function selectionRows(
  region: { chrom: string; start: number; end: number } | null,
  contigs: readonly Contig[],
  label?: string,
): SelectionRow[] {
  if (!region || !Number.isFinite(region.start) || !Number.isFinite(region.end)) return [];
  if (region.end <= region.start) return [];
  const names = contigs.map((c) => c.name);
  const chrom = matchChromosome(region.chrom, names);
  if (chrom === null) return [];
  return [{ chrom, start: region.start, end: region.end, ...(label ? { label } : {}) }];
}

/**
 * Whether the browser's window is the tile's own region, give or take
 * `tolerance` of its span: the browser follows the navigator's region, so
 * the band would then tint the whole view and mark nothing.
 */
export function windowIsRegion(
  rows: readonly WindowRow[],
  region: { chrom: string; start: number; end: number } | null,
  tolerance = 0.1,
): boolean {
  if (rows.length !== 1 || !region || !Number.isFinite(region.end)) return false;
  const [row] = rows;
  if (matchChromosome(row.chrom, [region.chrom]) === null) return false;
  const slack = (region.end - region.start) * tolerance;
  return Math.abs(row.start - region.start) <= slack && Math.abs(row.end - region.end) <= slack;
}

/** The rule(s) for a hovered interval: one at a position, two (its edges) at a
 *  span, so a feature reads as its outline. None on a contig the view does not
 *  draw. `color` is the hovering tile's own colour (`HighlightEvent.color`);
 *  `fallbackColor` fills the rows that have none, since an encoding reading a
 *  `color` field needs the field on every row. */
export function hoverRows(
  interval: GenomicInterval | null,
  contigNames: readonly string[],
  color?: string | null,
  fallbackColor?: string,
): HoverRow[] {
  if (!interval) return [];
  const chrom = matchChromosome(interval.refName, contigNames, interval.aliases);
  if (chrom === null) return [];
  const { start, end } = interval;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return [];
  const wear = color || fallbackColor;
  const row = (pos: number): HoverRow => ({ chrom, pos, ...(wear ? { color: wear } : {}) });
  return end > start ? [row(start), row(end)] : [row(start)];
}

/** Position on the linearised genome axis (contigs laid end to end, in the
 *  order the spec lists them), or `null` for a contig the axis does not have. */
export function toLinear(
  contigs: readonly Contig[],
  chrom: string,
  pos: number,
): number | null {
  let offset = 0;
  for (const c of contigs) {
    if (c.name === chrom) return offset + pos;
    offset += c.size;
  }
  return null;
}

/** Where `linear` sits across a visible `domain` (0 at its left edge, 1 at its
 *  right); outside [0, 1] when it is off screen. */
export function fractionOfDomain(
  linear: number,
  domain: readonly [number, number],
): number | null {
  const span = domain[1] - domain[0];
  if (!Number.isFinite(span) || span <= 0) return null;
  return (linear - domain[0]) / span;
}

export interface OverlayBox {
  kind: 'window' | 'hover';
  /** The hovering tile's colour, for a hover box. */
  color?: string;
  /** Left edge and width as fractions of the plot width. */
  left: number;
  width: number;
}

/**
 * The boxes the DOM fallback paints for the current rows over a visible
 * `domain`, clipped to the plot; anything wholly off screen is dropped.
 * `minWidth` (a fraction) keeps a rule or a narrow band visible.
 */
export function fallbackBoxes(
  contigs: readonly Contig[],
  domain: readonly [number, number] | null,
  win: readonly WindowRow[],
  hover: readonly HoverRow[],
  minWidth = 0.002,
): OverlayBox[] {
  if (!domain) return [];
  const boxes: OverlayBox[] = [];
  const clip = (
    kind: OverlayBox['kind'],
    from: number | null,
    to: number | null,
    color?: string,
  ) => {
    if (from === null || to === null) return;
    const lo = Math.max(0, Math.min(from, to));
    const hi = Math.min(1, Math.max(from, to));
    if (hi < 0 || lo > 1 || hi < lo) return;
    boxes.push({ kind, left: lo, width: Math.max(minWidth, hi - lo), ...(color ? { color } : {}) });
  };
  for (const w of win) {
    const a = toLinear(contigs, w.chrom, w.start);
    const b = toLinear(contigs, w.chrom, w.end);
    clip(
      'window',
      a === null ? null : fractionOfDomain(a, domain),
      b === null ? null : fractionOfDomain(b, domain),
    );
  }
  for (const h of hover) {
    const a = toLinear(contigs, h.chrom, h.pos);
    const f = a === null ? null : fractionOfDomain(a, domain);
    clip('hover', f, f, h.color);
  }
  return boxes;
}

/**
 * Whether the axis still shows the genome browser's window: true when the
 * window lies inside the visible domain (GenomeSpy's complex domain, a pair of
 * `{chrom, pos}` loci), or when the domain cannot be read, so nothing moves on
 * a guess. Contigs are compared by their rank in `contigNames`.
 */
export function windowInDomain(
  domain: unknown[] | null,
  win: WindowRow,
  contigNames: readonly string[],
  tolerance = 0.02,
): boolean {
  if (!domain || domain.length < 2) return true;
  const locus = (x: unknown) => x as { chrom?: unknown; pos?: unknown };
  const [lo, hi] = [locus(domain[0]), locus(domain[domain.length - 1])];
  const rank = (c: unknown) => contigNames.indexOf(String(c));
  const [loRank, hiRank, winRank] = [rank(lo.chrom), rank(hi.chrom), rank(win.chrom)];
  if (loRank < 0 || hiRank < 0 || winRank < 0) return true;
  // A browser that followed this axis reports its window rounded outwards to
  // whole bases and its own block edges: a window a hair past the edge is the
  // same window coming back, not the browser leaving. Only a single-contig
  // domain has a span to take a fraction of.
  const span = loRank === hiRank ? Math.abs(Number(hi.pos) - Number(lo.pos)) : 0;
  const slack = Math.max(2, span * tolerance);
  const after = winRank > loRank || (winRank === loRank && win.start >= Number(lo.pos) - slack);
  const before = winRank < hiRank || (winRank === hiRank && win.end <= Number(hi.pos) + slack);
  return after && before;
}
