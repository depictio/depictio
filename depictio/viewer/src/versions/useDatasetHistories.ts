/**
 * Which dataset versions a dashboard could be shown against.
 *
 * A dashboard references one or more data collections; each Delta-backed one
 * has its own commit history. The picker needs both halves: the set of
 * collections in play (from the dashboard's components) and each one's commits
 * (from the existing `fetchDeltaHistory`, which already merges the Delta log
 * with Mongo's aggregation records — row counts, timestamps, who ran the
 * ingestion — i.e. exactly what someone needs to recognise a commit).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchDeltaHistory,
  type DeltaVersionEntry,
  type StoredMetadata,
} from 'depictio-react-core';

export interface DatasetHistory {
  dcId: string;
  /** Human label, e.g. "iris_versioned_table". Falls back to the id. */
  label: string;
  currentVersion: number | null;
  /** Newest first. Only commits with a real Delta version — see below. */
  commits: DeltaVersionEntry[];
  /** True when the object store was unreachable and only Mongo's view loaded. */
  degraded: boolean;
  error?: string;
}

/** Collections referenced by a dashboard's components, in first-seen order.
 *  Text components carry no `dc_id` and are skipped. */
export function collectDataCollections(
  metadata: StoredMetadata[] | undefined,
): Array<{ dcId: string; label: string }> {
  const seen = new Map<string, string>();
  for (const component of metadata || []) {
    const raw = (component as Record<string, unknown>).dc_id;
    if (!raw) continue;
    const dcId = String(raw);
    if (seen.has(dcId)) continue;
    const tag = (component as Record<string, unknown>).data_collection_tag;
    seen.set(dcId, typeof tag === 'string' && tag ? tag : dcId);
  }
  return Array.from(seen, ([dcId, label]) => ({ dcId, label }));
}

async function loadOne(dcId: string, label: string): Promise<DatasetHistory> {
  try {
    const body = await fetchDeltaHistory(dcId, 50);
    const commits = (body.versions || [])
      // Only Delta-backed commits can be travelled to. A mongo-only row is an
      // aggregation written before `delta_version` was recorded; offering it
      // would be offering a pin the backend cannot honour.
      .filter((v) => typeof v.version === 'number')
      .sort((a, b) => (b.version ?? 0) - (a.version ?? 0));

    return {
      dcId,
      label,
      currentVersion:
        typeof body.current_version === 'number' ? body.current_version : null,
      commits,
      degraded: Boolean(body.degraded),
    };
  } catch (err) {
    return {
      dcId,
      label,
      currentVersion: null,
      commits: [],
      degraded: true,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

/**
 * Load every referenced collection's commit history.
 *
 * Gated on `enabled` so opening a dashboard costs nothing — the histories are
 * fetched only once the user opens the picker.
 */
export function useDatasetHistories(
  metadata: StoredMetadata[] | undefined,
  enabled: boolean,
): { histories: DatasetHistory[]; loading: boolean; reload: () => void } {
  const collections = useMemo(() => collectDataCollections(metadata), [metadata]);
  const key = useMemo(() => collections.map((c) => c.dcId).join('|'), [collections]);

  const [histories, setHistories] = useState<DatasetHistory[]>([]);
  const [loading, setLoading] = useState(false);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled || collections.length === 0) return;
    let cancelled = false;
    setLoading(true);
    Promise.all(collections.map((c) => loadOne(c.dcId, c.label)))
      .then((results) => {
        if (!cancelled) setHistories(results);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, nonce]);

  return { histories, loading, reload };
}

/** "150 rows · write" — enough to recognise a commit without reading ids. */
export function describeCommit(commit: DeltaVersionEntry): string {
  const parts: string[] = [];
  if (typeof commit.rows_total === 'number') {
    parts.push(`${commit.rows_total.toLocaleString()} rows`);
  } else if (typeof commit.rows_added === 'number') {
    parts.push(`+${commit.rows_added.toLocaleString()} rows`);
  }
  if (commit.operation) parts.push(commit.operation.toLowerCase());
  return parts.join(' · ');
}
