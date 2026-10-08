/**
 * Version-timeline state for one dashboard family.
 *
 * The editor holds **one** instance of this and hands it to everything that
 * reads the timeline: the tile menu's History entry (offered only once a
 * version exists), the per-component history modal, and the History section of
 * the settings. A second instance would be a second list going stale on its
 * own, which is how a tile's History entry could stay hidden after the save
 * that recorded the dashboard's first version.
 *
 * Plain `useState` + `useEffect`: this tree has no react-query, and the
 * monitoring panes fetch the same way.
 *
 * - `reload()` refetches what is on screen. Call it after anything that writes
 *   or changes a version: a save, a restore, a pin or label change, a delete.
 *   It keeps the current list while it fetches (no loader on every autosave)
 *   and asks for as many rows as are loaded, so bookmarking an old version
 *   does not fold the list back to its first page.
 * - `loadOlder()` appends the page before the oldest loaded row (`before_seq`).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchDashboardVersions,
  type DashboardVersionListResponse,
  type DashboardVersionSummary,
} from 'depictio-react-core';

/** The list endpoint's `limit` ceiling (`versions_routes.py`). */
const MAX_LIMIT = 200;

/** One empty list, so "nothing loaded" keeps its identity across renders. */
const NO_VERSIONS: DashboardVersionSummary[] = [];

export interface VersionHistory {
  /** Newest first. */
  versions: DashboardVersionSummary[];
  /** The row matching the live dashboard, or null when the live state has
   *  drifted from every loaded version. */
  currentVersionId: string | null;
  total: number;
  /** More rows exist before the oldest loaded one. */
  hasMore: boolean;
  /** The first page is in flight and there is nothing to show yet. A reload
   *  of a list already on screen leaves this false. */
  loading: boolean;
  loadingOlder: boolean;
  /** The last (re)load of the list failed. */
  error: string | null;
  /** The last `loadOlder` failed; the rows already loaded are still good. */
  olderError: string | null;
  reload: () => Promise<void>;
  loadOlder: () => Promise<void>;
}

const errorMessage = (err: unknown, fallback: string) =>
  err instanceof Error ? err.message : fallback;

export function useVersionHistory(
  dashboardId: string | null,
  enabled: boolean,
  pageSize = 100,
): VersionHistory {
  const [data, setData] = useState<DashboardVersionListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [olderError, setOlderError] = useState<string | null>(null);

  // Bumped by every reload. A response is applied only if no reload started
  // after it was requested: a slow answer must not overwrite a newer one, and
  // an older page asked for before a reload must not be appended to the list
  // that reload replaced.
  const generation = useRef(0);
  // Read by the callbacks without making them change identity on every
  // response (`reload` sits in effect dependency lists).
  const dataRef = useRef<DashboardVersionListResponse | null>(null);
  dataRef.current = data;
  const olderInFlight = useRef(false);

  const reload = useCallback(async () => {
    if (!dashboardId) return;
    const ticket = ++generation.current;
    const loaded = dataRef.current?.versions.length ?? 0;
    if (!dataRef.current) setLoading(true);
    setError(null);
    try {
      const result = await fetchDashboardVersions(dashboardId, {
        limit: Math.min(MAX_LIMIT, Math.max(pageSize, loaded)),
      });
      if (ticket === generation.current) setData(result);
    } catch (err) {
      if (ticket === generation.current) {
        setError(errorMessage(err, 'Failed to load version history'));
      }
    } finally {
      if (ticket === generation.current) setLoading(false);
    }
  }, [dashboardId, pageSize]);

  const loadOlder = useCallback(async () => {
    const current = dataRef.current;
    const oldest = current?.versions[current.versions.length - 1];
    if (!dashboardId || !oldest || olderInFlight.current) return;
    const ticket = generation.current;
    olderInFlight.current = true;
    setLoadingOlder(true);
    setOlderError(null);
    try {
      const page = await fetchDashboardVersions(dashboardId, {
        limit: pageSize,
        beforeSeq: oldest.seq,
      });
      if (ticket !== generation.current) return;
      setData((prev) => {
        if (!prev) return prev;
        const seen = new Set(prev.versions.map((v) => v.version_id));
        return {
          ...prev,
          total: page.total,
          // The server picks the current row within each page. The first
          // page's answer is the newest match, so an older page only fills a
          // gap rather than overriding it.
          current_version_id: prev.current_version_id ?? page.current_version_id,
          versions: [...prev.versions, ...page.versions.filter((v) => !seen.has(v.version_id))],
        };
      });
    } catch (err) {
      if (ticket === generation.current) {
        setOlderError(errorMessage(err, 'Failed to load older versions'));
      }
    } finally {
      olderInFlight.current = false;
      setLoadingOlder(false);
    }
  }, [dashboardId, pageSize]);

  // Another dashboard is another family: drop the old list rather than show
  // it under the new one while the first page loads.
  useEffect(() => {
    generation.current += 1;
    setData(null);
    setError(null);
    setOlderError(null);
  }, [dashboardId]);

  useEffect(() => {
    if (enabled) void reload();
  }, [enabled, reload]);

  const versions = data?.versions ?? NO_VERSIONS;
  const total = data?.total ?? 0;
  return {
    versions,
    currentVersionId: data?.current_version_id ?? null,
    total,
    hasMore: versions.length < total,
    loading,
    loadingOlder,
    error,
    olderError,
    reload,
    loadOlder,
  };
}
