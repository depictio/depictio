/**
 * Where the genome browser opens, and when a new payload may move it.
 *
 * The backend says where its `location` came from (`payload.opening`); the
 * viewer remembers a locus only after the reader has navigated themselves
 * (`.loc.v2`), so an opening the viewer chose is never frozen by a visit.
 * Pure, no React.
 */
import type { JBrowseSessionResponse } from '../../api';

export type Opening = NonNullable<JBrowseSessionResponse['opening']>;

/** Suffix of the per-tile localStorage key holding the locus a reader left the
 *  view at. `v2` on purpose: the old `.loc` also stored the opening view
 *  (the preset's TP53), and reading it back pinned an empty view for good. */
export const PERSISTED_LOCUS_SUFFIX = 'loc.v2';

/** Two regions in one view: a locus and its mate, space separated (the form
 *  `navToLocString` reads as a multi-region view). Just the locus when there
 *  is no mate or the reader has the toggle off. */
export function sidesLocus(
  locus: string | null | undefined,
  mate: string | null | undefined,
  bothSides: boolean,
): string | null {
  if (!locus) return null;
  return bothSides && mate ? `${locus} ${mate}` : locus;
}

/** A contig name without the spellings tools disagree on ("chr6" = "6"). */
function contigKey(name: string): string {
  return name.trim().toLowerCase().replace(/^chr/, '');
}

/** `chr:start..end` or `chr:start-end` (commas allowed) as numbers; null for
 *  anything else, a multi-region locus included. */
function parseLocus(locus: string): { chrom: string; start: number; end: number } | null {
  const m = /^([^:\s]+):([\d,]+)(?:\.\.|-)([\d,]+)$/.exec(locus.trim());
  if (!m) return null;
  const start = Number(m[2].replace(/,/g, ''));
  const end = Number(m[3].replace(/,/g, ''));
  return Number.isFinite(start) && Number.isFinite(end) ? { chrom: m[1], start, end } : null;
}

/** Whether the locus lies inside the region (same contig, within its span; a
 *  region with no end is the whole contig). */
export function locusWithinRegion(
  locus: string,
  region: { chrom: string; start: number; end: number },
): boolean {
  const parsed = parseLocus(locus);
  if (!parsed || contigKey(parsed.chrom) !== contigKey(region.chrom)) return false;
  const end = Number.isFinite(region.end) ? region.end : Number.POSITIVE_INFINITY;
  return parsed.start >= region.start && parsed.end <= end;
}

/**
 * The locus the view is created at, first match wins:
 * 1. a locus another tile handed over (`pending`, see pendingLocus.ts);
 * 2. the genome region in force (`region`, a navigator's brush or default
 *    region), so the browser opens where the navigator above shows, unless
 *    what the reader left the view at, or else the payload's location (a
 *    `locus_from` row), lies inside it: a zoom into it, not a whole contig
 *    where coverage reads as a few spikes;
 * 3. what the reader left the view at;
 * 4. the payload's location.
 * `undefined` lets JBrowse show the whole assembly. The pending one is never
 * written back as the reader's own navigation.
 */
export function initialLocus(args: {
  pending?: string | null;
  region?: { chrom: string; start: number; end: number } | null;
  regionLocus?: string | null;
  persisted: string | null;
  location: string | null;
  mateLocation?: string | null;
  bothSides: boolean;
}): string | undefined {
  if (args.pending) return args.pending;
  if (args.region && args.regionLocus) {
    if (args.persisted && locusWithinRegion(args.persisted, args.region)) return args.persisted;
    if (args.location && locusWithinRegion(args.location, args.region)) return args.location;
    return args.regionLocus;
  }
  return (
    args.persisted || sidesLocus(args.location, args.mateLocation, args.bothSides) || undefined
  );
}

/**
 * Whether a payload for an already open view moves it. Only a location the
 * dashboard itself asked for does: a filter that narrowed `locus_from`, or the
 * YAML `location`. The other openings (first call, data probe, preset) are
 * defaults for a view that has just been created, and re-applying them on a
 * refetch would pull the reader away from where they are. An older backend
 * sends no `opening`: it always moved the view, and keeps doing so.
 */
export function shouldRenavigate(
  opening: Opening | undefined,
  location: string | null,
  lastLocation: string | null,
): boolean {
  if (!location || location === lastLocation) return false;
  return opening === undefined || opening === 'filter' || opening === 'yaml';
}

/**
 * Where a followed region should take an open view when it is too wide to
 * read: a whole contig, or more than `maxSpan`, holds the payload's location
 * (the best `locus_from` row), so the view goes there instead of to the whole
 * region, where every feature track asks for a force load. Null when the
 * region is narrow enough to show as is, or the location is not inside it.
 */
export function wideRegionTarget(
  region: { chrom: string; start: number; end: number },
  location: string | null | undefined,
  maxSpan: number,
): string | null {
  const wide = !Number.isFinite(region.end) || region.end - region.start > maxSpan;
  if (!wide || !location) return null;
  return locusWithinRegion(location, region) ? location : null;
}
