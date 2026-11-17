/**
 * How a chord talks to the other genome tiles: the breakpoint a hover points
 * at (on the highlight bus, as a `genomic` interval), and the region a click
 * hands a genome browser (the same chromosome + position filter pair a brush
 * emits). Pure, so the choices are testable without an SVG.
 */
import type { HighlightPayload } from '../../../highlight/bus';
import { contigSpellings } from '../../../highlight/genomicHover';
import type { GenomeRegionSelection } from '../../../selection';
import type { ChordLink, Point } from './chordLayout';

/** The two ends of a link: `a` is the first chromosome / position pair. */
export type ChordSide = 'a' | 'b';

/** Bases kept on each side of a breakpoint when a browser is sent to it. */
export const BREAKPOINT_PAD_BP = 2_500;

/** The contig and position of one end. */
export function breakpointOf(link: ChordLink, side: ChordSide): { chrom: string; pos: number } {
  return side === 'a'
    ? { chrom: link.chromA, pos: link.posA }
    : { chrom: link.chromB, pos: link.posB };
}

/**
 * The end of the chord the pointer is nearer to: the "hovered side" of a link
 * whose two ends are far apart on the ring. `a` and `b` are the ends'
 * positions on the ring, `at` the pointer, all in the same coordinates.
 */
export function nearestSide(at: Point, a: Point, b: Point): ChordSide {
  const d = (p: Point) => (p.x - at.x) ** 2 + (p.y - at.y) ** 2;
  return d(a) <= d(b) ? 'a' : 'b';
}

/**
 * The bus event for a hovered breakpoint: its position as a `genomic` interval
 * (a browser draws a band there, a coverage track a cursor), the other
 * spelling of its contig as an alias, the mark's colour so the band wears it,
 * and the link's label as a row key for a table that rings rows.
 */
export function breakpointHighlight(
  link: ChordLink,
  side: ChordSide,
  opts: { color?: string | null; positionColumn?: string; rowKey?: string | null } = {},
): HighlightPayload {
  const { chrom, pos } = breakpointOf(link, side);
  const aliases = contigSpellings(chrom);
  return {
    entity: chrom,
    start: pos,
    end: pos,
    ...(aliases ? { entityAliases: aliases } : {}),
    ...(opts.positionColumn ? { positionColumn: opts.positionColumn } : {}),
    ...(opts.color ? { color: opts.color } : {}),
    ...(opts.rowKey ? { rowKeys: [opts.rowKey] } : {}),
    genomic: { refName: chrom, start: pos, end: pos, ...(aliases ? { aliases } : {}) },
  };
}

/** The region a click on one end sends a browser to: the breakpoint's contig
 *  and `pad` bases either side (never below position 0). */
export function breakpointRegion(
  link: ChordLink,
  side: ChordSide,
  pad: number = BREAKPOINT_PAD_BP,
): GenomeRegionSelection {
  const { chrom, pos } = breakpointOf(link, side);
  return { chroms: [chrom], range: [Math.max(0, Math.round(pos - pad)), Math.round(pos + pad)] };
}

/** The chromosome and position columns of one end, for the region filters. */
export function sideColumns(
  config: { chrom_a_col: string; pos_a_col: string; chrom_b_col: string; pos_b_col: string },
  side: ChordSide,
): { chrom: string; pos: string } {
  return side === 'a'
    ? { chrom: config.chrom_a_col, pos: config.pos_a_col }
    : { chrom: config.chrom_b_col, pos: config.pos_b_col };
}
