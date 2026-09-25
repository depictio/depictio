/**
 * The `genome_view` renderer's data path, without React.
 *
 * `GenomeViewRenderer.tsx` owns the mount, the Mantine chrome and the
 * GenomeSpy embed; everything between "the dashboard's filter list changed"
 * and "here are the rows to draw" lives here, so vitest (node, no jsdom, no
 * testing-library in this workspace) can cover it with a mocked fetcher.
 */

import type { AdvancedVizKind, InteractiveFilter, StoredMetadata } from '../../../api';
import {
  filtersExcludingOwn,
  genomePosFilterIndex,
  genomeRegionFilters,
  regionFromFilters,
} from '../../../selection';
import { requiredColumns } from './genomeSpySpec';
import type { GenomeViewConfig } from './genomeSpySpec';

/** The shape of `fetchAdvancedVizData`, narrowed to what this kind uses. */
export interface GenomeViewFetcher {
  (req: {
    wfId: string;
    dcId: string;
    columns: string[];
    filters: InteractiveFilter[];
    vizKind: AdvancedVizKind;
    roles?: Record<string, string>;
    tail?: { column: string; direction: 'low' | 'high' | 'both'; threshold: number };
  }): Promise<{ rows: Record<string, unknown[]>; sampling?: { degraded?: boolean } }>;
}

/**
 * Every dashboard filter except the ones this tile emitted itself.
 *
 * Three entries, not one: the click selection (`scatter_selection`) and both
 * halves of the region brush (`genome_selection` on the tile's own index and
 * on its `::pos` sibling). A tile narrowed by its own brush could never widen
 * the brush again, which is the same rule every other selection source
 * follows.
 */
export function filtersForGenomeViewFetch(
  filters: InteractiveFilter[],
  componentIndex: string,
): InteractiveFilter[] {
  const withoutPick = filtersExcludingOwn(filters, componentIndex, 'scatter_selection');
  const withoutChr = filtersExcludingOwn(withoutPick, componentIndex, 'genome_selection');
  return filtersExcludingOwn(withoutChr, genomePosFilterIndex(componentIndex), 'genome_selection');
}

// ---- Fetching only the window around the tile's own region -----------------

/** Index suffix of the window pair. It is sent with the fetch only, never
 *  published, so it can never be mistaken for the tile's own region. */
export const NAVIGATOR_WINDOW_INDEX_SUFFIX = '::window';

/**
 * The region this tile itself published (locus field, `default_region`,
 * brush), read off its own `genome_selection` pair only.
 */
export function ownRegion(
  filters: readonly InteractiveFilter[],
  componentIndex: string,
  chrColumn: string,
  posColumn: string,
): { chrom: string; start: number; end: number } | null {
  const posIndex = genomePosFilterIndex(componentIndex);
  const own = filters.filter(
    (f) =>
      f.source === 'genome_selection' && (f.index === componentIndex || f.index === posIndex),
  );
  if (!own.length) return null;
  return regionFromFilters([...own], chrColumn, posColumn);
}

/**
 * The window a navigator fetches around its own region: the region's whole
 * chromosome.
 *
 * Why a window at all: GenomeSpy uploads every row it is given to the GPU in
 * one go, and a whole-genome table of a few hundred thousand intervals stalls
 * that upload for seconds while the reader looks at one locus. Why the whole
 * chromosome rather than a margin: the navigator is still the section's
 * overview, so a zoom-out or a brush anywhere along the chromosome finds its
 * rows already there, and only a jump to another chromosome (locus field,
 * brush across contigs) refetches. The genome axis itself comes from the
 * assembly, so every other contig is still drawn, just empty.
 */
export function navigatorWindow(
  region: { chrom: string; start: number; end: number } | null,
): { chroms: string[]; range: [number, number] | null } | null {
  if (!region || !region.chrom) return null;
  return { chroms: [region.chrom], range: null };
}

/** The window as the filter pair the fetch carries, on the tile's own columns. */
export function navigatorWindowFilters(
  metadata: Pick<StoredMetadata, 'index' | 'dc_id'>,
  chrColumn: string,
  posColumn: string,
  window: { chroms: string[]; range: [number, number] | null } | null,
): InteractiveFilter[] {
  if (!window || !window.chroms.length) return [];
  const pair = genomeRegionFilters(
    { ...metadata, index: `${metadata.index}${NAVIGATOR_WINDOW_INDEX_SUFFIX}` } as StoredMetadata,
    chrColumn,
    posColumn,
    window,
  );
  // A chromosome-only window has an empty position half; sending it is noise.
  return pair.filter((f) => Array.isArray(f.value) && f.value.length > 0);
}

export interface GenomeViewLoadResult {
  rows: Record<string, unknown[]>;
  /** True when the server had to sample, so the tile can say so. */
  estimated: boolean;
}

/**
 * Fetch the rows one `genome_view` tile needs.
 *
 * `tail` mirrors the Manhattan's rule: the threshold is the cut the server
 * must not sample across, so every row above it arrives whole even when the
 * collection is far larger than the row budget.
 *
 * Throws `Error('genome_view: missing data binding')` rather than fetching
 * with a half-built request, so an unbound tile reports the reason instead of
 * a 422.
 */
export async function loadGenomeViewRows(
  fetcher: GenomeViewFetcher,
  args: {
    metadata: Pick<StoredMetadata, 'index' | 'wf_id' | 'dc_id'>;
    config: GenomeViewConfig;
    filters: InteractiveFilter[];
    selectionColumn?: string;
    /** Extra filters narrowing the fetch to a window (`navigatorWindowFilters`). */
    windowFilters?: InteractiveFilter[];
  },
): Promise<GenomeViewLoadResult> {
  const { metadata, config, filters, selectionColumn, windowFilters } = args;
  const columns = requiredColumns(config, selectionColumn).filter(Boolean);
  if (!metadata.wf_id || !metadata.dc_id || columns.length < 3) {
    throw new Error('genome_view: missing data binding');
  }
  const threshold = config.score_threshold;
  const res = await fetcher({
    wfId: metadata.wf_id,
    dcId: metadata.dc_id,
    columns,
    filters: [...filtersForGenomeViewFetch(filters, metadata.index), ...(windowFilters ?? [])],
    vizKind: 'genome_view',
    roles: { chr: config.chr_col, pos: config.pos_col, score: config.score_col },
    tail:
      threshold !== null && threshold !== undefined && Number.isFinite(threshold)
        ? { column: config.score_col, direction: 'high', threshold }
        : undefined,
  });
  return { rows: res.rows, estimated: Boolean(res.sampling?.degraded) };
}
