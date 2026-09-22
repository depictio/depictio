/**
 * The `genome_view` renderer's data path, without React.
 *
 * `GenomeViewRenderer.tsx` owns the mount, the Mantine chrome and the
 * GenomeSpy embed; everything between "the dashboard's filter list changed"
 * and "here are the rows to draw" lives here, so vitest (node, no jsdom, no
 * testing-library in this workspace) can cover it with a mocked fetcher.
 */

import type { AdvancedVizKind, InteractiveFilter, StoredMetadata } from '../../../api';
import { filtersExcludingOwn, genomePosFilterIndex } from '../../../selection';
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
  },
): Promise<GenomeViewLoadResult> {
  const { metadata, config, filters, selectionColumn } = args;
  const columns = requiredColumns(config, selectionColumn).filter(Boolean);
  if (!metadata.wf_id || !metadata.dc_id || columns.length < 3) {
    throw new Error('genome_view: missing data binding');
  }
  const threshold = config.score_threshold;
  const res = await fetcher({
    wfId: metadata.wf_id,
    dcId: metadata.dc_id,
    columns,
    filters: filtersForGenomeViewFetch(filters, metadata.index),
    vizKind: 'genome_view',
    roles: { chr: config.chr_col, pos: config.pos_col, score: config.score_col },
    tail:
      threshold !== null && threshold !== undefined && Number.isFinite(threshold)
        ? { column: config.score_col, direction: 'high', threshold }
        : undefined,
  });
  return { rows: res.rows, estimated: Boolean(res.sampling?.degraded) };
}
