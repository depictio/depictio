import { useEffect, useRef, useState } from 'react';

import {
  fetchJBrowseCallDensity,
  type InteractiveFilter,
  type JBrowseCallDensity,
} from '../../api';
import { binsBucket, type DensityGroup, type DensityRegion } from './densityBins';

interface UseCallDensityArgs {
  dashboardId: string;
  index: string;
  /** The filters the tile renders with (its own selection excluded). */
  filters: InteractiveFilter[];
  /** The data-version request body; the pins are forwarded to the density read. */
  versionBody: Record<string, unknown>;
  /** Off for a tile with no `locus_from`, or while the strip is hidden. */
  enabled: boolean;
  /** Anything that makes the loaded density stale (filters, pins, a refresh). */
  resetKey: string;
  /** Names of the enabled sources. */
  sources: string[];
  /** The assembly's regions, in order. */
  regions: DensityRegion[];
  /** Bins asked for; rounded up to whole 200s so a resize does not refetch. */
  bins: number;
  group: DensityGroup;
}

export interface CallDensity {
  /** The last density read; kept while a newer one loads, null before the first. */
  data: JBrowseCallDensity | null;
  loading: boolean;
  error: string | null;
}

/**
 * The tile's regions binned over the genome, for the density strip. Read again
 * when `resetKey`, the sources, the grouping, the regions or the bins bucket
 * change, never on a pan; a request still in flight is aborted by the next.
 */
export function useCallDensity({
  dashboardId,
  index,
  filters,
  versionBody,
  enabled,
  resetKey,
  sources,
  regions,
  bins,
  group,
}: UseCallDensityArgs): CallDensity {
  const [data, setData] = useState<JBrowseCallDensity | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Keyed by content: a caller that rebuilds the arrays each render must not refetch.
  const sourcesKey = JSON.stringify(sources);
  const regionsKey = regions.map((r) => `${r.refName}:${r.length}`).join('|');
  const bucket = binsBucket(bins);
  const argsRef = useRef({ filters, versionBody, sources, regions });
  argsRef.current = { filters, versionBody, sources, regions };

  useEffect(() => {
    const a = argsRef.current;
    if (!enabled || !a.regions.length || !a.sources.length) {
      setData(null);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchJBrowseCallDensity(
      dashboardId,
      index,
      {
        filters: a.filters,
        regions: a.regions,
        bins: bucket,
        sources: a.sources,
        group,
        ...(a.versionBody.as_of_version !== undefined
          ? { as_of_version: a.versionBody.as_of_version as string | null }
          : {}),
        ...(a.versionBody.data_versions !== undefined
          ? { data_versions: a.versionBody.data_versions as Record<string, unknown> | null }
          : {}),
      },
      controller.signal,
    )
      .then((res) => {
        if (controller.signal.aborted) return;
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        // The strip is a convenience: without it the tile just shows none.
        console.warn('jbrowse: cannot read the region density', err);
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => controller.abort();
  }, [enabled, dashboardId, index, resetKey, sourcesKey, regionsKey, bucket, group]);

  return { data, loading, error };
}
