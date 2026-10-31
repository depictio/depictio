/**
 * The GenomeSpy side of the view-window link: what the genome axis shows, as a
 * `ViewWindowPayload` other genome tiles can follow (see `highlight/
 * viewWindow.ts`). Pure helpers; the hook that listens to the axis is in
 * `useViewWindowPublish.ts`.
 */
import { contigSpellings } from '../../../highlight/genomicHover';
import type { ViewWindowPayload } from '../../../highlight/viewWindow';
import type { Contig } from './genomeSpySpec';

/** Debounce of a pan or a zoom before it is published, as the browser's. */
export const VIEW_WINDOW_DEBOUNCE_MS = 150;

/** How long after a zoom issued from code the axis' domain events are still
 *  read as the zoom's own, not as the reader's gesture. */
export const CODE_ZOOM_QUIET_MS = 350;

const locusOf = (x: unknown) => x as { chrom?: unknown; pos?: unknown } | null | undefined;

/**
 * The window a GenomeSpy domain (a pair of `{chrom, pos}` loci, as
 * `readViewDomain` returns it) puts on the bus: 1-based, inclusive, rounded
 * outwards to whole bases and kept inside the contig. `null` when the axis
 * spans more than one contig (a genome-wide view has no single window to
 * follow) or the domain cannot be read.
 */
export function windowFromDomain(
  domain: readonly unknown[] | null | undefined,
  contigs?: readonly Contig[] | null,
): Omit<ViewWindowPayload, 'sourceIndex'> | null {
  if (!domain || domain.length < 2) return null;
  const lo = locusOf(domain[0]);
  const hi = locusOf(domain[domain.length - 1]);
  if (!lo || !hi || lo.chrom == null || hi.chrom == null) return null;
  if (String(lo.chrom) !== String(hi.chrom)) return null;
  const p0 = Number(lo.pos);
  const p1 = Number(hi.pos);
  if (!Number.isFinite(p0) || !Number.isFinite(p1) || p1 <= p0) return null;
  const entity = String(lo.chrom);
  const size = contigs?.find((c) => c.name === entity)?.size;
  const start = Math.max(1, Math.floor(p0));
  const end = Math.max(start, size && size > 0 ? Math.min(size, Math.ceil(p1)) : Math.ceil(p1));
  const aliases = contigSpellings(entity);
  return { entity, start, end, ...(aliases ? { entityAliases: aliases } : {}) };
}

/** Two windows that put a follower in the same place, give or take the
 *  rounding a round trip through another tile adds (a base or two, or 0.2%). */
export function approxSameWindow(
  a: { entity: string; start: number; end: number } | null | undefined,
  b: { entity: string; start: number; end: number } | null | undefined,
): boolean {
  if (!a || !b || a.entity !== b.entity) return false;
  const slack = Math.max(2, Math.round((b.end - b.start) * 0.002));
  return Math.abs(a.start - b.start) <= slack && Math.abs(a.end - b.end) <= slack;
}
