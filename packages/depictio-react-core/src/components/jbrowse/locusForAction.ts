/**
 * The locus an "Open in genome browser" action takes from a genomic tile.
 *
 * Three sources, in this order: the last point the reader clicked, the active
 * `genome_selection` region, the visible window when it covers one
 * chromosome. The same module reads a region back off the dashboard filters
 * for the browser itself, which follows a brush without being filtered by it.
 * Pure, no React.
 */
import type { InteractiveFilter } from '../../api';
import { filterComponentIndex } from '../../filterShare';
import { isRegionFilter, regionFromFilters } from '../../selection';

/** A point the reader clicked: a contig and a 1-based position. */
export interface GenomePoint {
  chrom: string;
  pos: number;
}

/** A stretch of one contig. `end` may be `Infinity`: the whole contig. */
export interface GenomeWindow {
  chrom: string;
  start: number;
  end: number;
}

/** What a tile knows about where it is looking, read when the action is used. */
export interface OpenLocusSource {
  point?: GenomePoint | null;
  window?: GenomeWindow | null;
}

/** Reads a tile's current source; null when it has nothing to offer yet. */
export type OpenLocusReader = () => OpenLocusSource | null;

/** Bases kept on each side of a clicked point: room to read its neighbours. */
export const POINT_PADDING_BP = 500;

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

function spanLocus(chrom: string, start: number, end: number): string {
  const lo = Math.max(1, Math.floor(start));
  const hi = Math.max(lo, Math.ceil(end));
  return `${chrom}:${lo}-${hi}`;
}

/** A locus string for a point, padded on both sides. Null without a contig or
 *  a finite position. */
export function pointLocus(point: GenomePoint | null | undefined, pad = POINT_PADDING_BP): string | null {
  if (!point || !point.chrom || !finite(point.pos)) return null;
  return spanLocus(point.chrom, point.pos - pad, point.pos + pad);
}

/** A locus string for a window; an open end (a whole contig) is the contig's
 *  name alone, which the browser reads as the whole of it. */
export function windowLocus(win: GenomeWindow | null | undefined): string | null {
  if (!win || !win.chrom || !finite(win.start)) return null;
  if (!finite(win.end)) return win.chrom;
  if (win.end < win.start) return null;
  return spanLocus(win.chrom, win.start, win.end);
}

/**
 * The region the dashboard's `genome_selection` filters carry, whichever tile
 * or sidebar control wrote it: the columns come from the filters themselves (a
 * multi-select names the contig column, a range slider the position one), so
 * the browser needs no binding of its own. With several emitters the last one
 * wins. Null unless exactly one contig is selected.
 */
export function genomeSelectionRegion(
  filters: readonly InteractiveFilter[] | undefined | null,
): GenomeWindow | null {
  const region = (filters ?? []).filter(isRegionFilter);
  if (region.length === 0) return null;
  const columnOf = (f: InteractiveFilter) => f.column_name ?? f.metadata?.column_name ?? null;
  const chromEntries = region.filter(
    (f) => f.interactive_component_type === 'MultiSelect' && columnOf(f),
  );
  const rangeEntries = region.filter(
    (f) => f.interactive_component_type === 'RangeSlider' && columnOf(f),
  );
  const chromEntry = chromEntries[chromEntries.length - 1];
  if (!chromEntry) return null;
  const chrom = columnOf(chromEntry) as string;
  const start = rangeEntries.length ? (columnOf(rangeEntries[rangeEntries.length - 1]) as string) : '';
  return regionFromFilters(region as InteractiveFilter[], { chrom, start: start || `${chrom}\u0000` });
}

/** Index of the tile whose region `genomeSelectionRegion` reads (the last
 *  contig emitter), without the `::pos` suffix of its position half. */
export function genomeSelectionSource(
  filters: readonly InteractiveFilter[] | undefined | null,
): string | null {
  const chromEntries = (filters ?? []).filter(
    (f) => isRegionFilter(f) && f.interactive_component_type === 'MultiSelect',
  );
  const last = chromEntries[chromEntries.length - 1];
  return last ? filterComponentIndex(String(last.index)) : null;
}

/**
 * The locus to open, or null when none of the three sources gives one.
 * `region` is the active genome selection, `window` the tile's visible window
 * (null when it spans several contigs).
 */
export function locusForAction(args: {
  point?: GenomePoint | null;
  region?: GenomeWindow | null;
  window?: GenomeWindow | null;
  pad?: number;
}): string | null {
  return pointLocus(args.point, args.pad) ?? windowLocus(args.region) ?? windowLocus(args.window);
}

/**
 * The window a tile on a cumulative genome axis shows, when it covers a
 * single contig: `range` is the axis' visible `[lo, hi]`, `offsets` the
 * cumulative offset each drawn contig starts at. Null when the range reaches
 * into two contigs (the genome-wide view), or into none.
 */
export function windowOnOneChrom(
  range: readonly [number, number] | null | undefined,
  offsets: ReadonlyMap<string, number>,
): GenomeWindow | null {
  if (!range || !finite(range[0]) || !finite(range[1]) || range[1] <= range[0]) return null;
  const ordered = [...offsets.entries()].sort((a, b) => a[1] - b[1]);
  const hit: Array<{ chrom: string; offset: number }> = [];
  ordered.forEach(([chrom, offset], i) => {
    const next = i + 1 < ordered.length ? ordered[i + 1][1] : Number.POSITIVE_INFINITY;
    if (range[0] < next && range[1] > offset) hit.push({ chrom, offset });
  });
  if (hit.length !== 1) return null;
  const { chrom, offset } = hit[0];
  return { chrom, start: Math.max(0, range[0] - offset), end: range[1] - offset };
}

/** The contig and position under an x on a cumulative genome axis: the last
 *  contig starting at or before it. Null on an empty axis. */
export function pointOnAxis(
  x: number,
  offsets: ReadonlyMap<string, number>,
): GenomePoint | null {
  if (!finite(x)) return null;
  let best: { chrom: string; offset: number } | null = null;
  for (const [chrom, offset] of offsets) {
    if (offset <= x && (!best || offset > best.offset)) best = { chrom, offset };
  }
  return best ? { chrom: best.chrom, pos: Math.round(x - best.offset) } : null;
}

/**
 * Where a browser navigates to follow `region`: its contig by the assembly's
 * own name (`canonical` maps any alias, undefined for a contig it does not
 * know) and the range, or the contig alone when the region names no range.
 */
export function regionNavTarget(
  region: GenomeWindow | null | undefined,
  canonical: (name: string) => string | undefined,
): string | null {
  if (!region) return null;
  const refName = canonical(region.chrom);
  if (!refName) return null;
  return windowLocus({ ...region, chrom: refName });
}

/** The visible x range of a Plotly graph div, or null before it has drawn. */
export function readPlotXRange(gd: unknown): [number, number] | null {
  const g = gd as {
    _fullLayout?: { xaxis?: { range?: unknown } };
    layout?: { xaxis?: { range?: unknown } };
  } | null;
  const range = g?._fullLayout?.xaxis?.range ?? g?.layout?.xaxis?.range;
  if (!Array.isArray(range) || range.length !== 2) return null;
  const lo = Number(range[0]);
  const hi = Number(range[1]);
  return Number.isFinite(lo) && Number.isFinite(hi) ? [Math.min(lo, hi), Math.max(lo, hi)] : null;
}
