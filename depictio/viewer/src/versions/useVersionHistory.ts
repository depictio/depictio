/**
 * Version-timeline state for one dashboard.
 *
 * Plain `useState` + `useEffect` — this tree has no react-query, and the
 * monitoring panes fetch the same way. Loads on first open rather than on
 * mount, so a user who never opens the drawer never pays for it.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  fetchDashboardVersions,
  type DashboardVersionListResponse,
  type DashboardVersionSummary,
} from 'depictio-react-core';

interface UseVersionHistory {
  versions: DashboardVersionSummary[];
  currentVersionId: string | null;
  total: number;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

export function useVersionHistory(
  dashboardId: string | null,
  opened: boolean,
  limit = 100,
): UseVersionHistory {
  const [data, setData] = useState<DashboardVersionListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guards against a slow response for a previous dashboard landing after the
  // user has switched to another one.
  const requestId = useRef(0);

  const load = useCallback(async () => {
    if (!dashboardId) return;
    const ticket = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchDashboardVersions(dashboardId, { limit });
      if (ticket === requestId.current) setData(result);
    } catch (err) {
      if (ticket === requestId.current) {
        setError(err instanceof Error ? err.message : 'Failed to load version history');
      }
    } finally {
      if (ticket === requestId.current) setLoading(false);
    }
  }, [dashboardId, limit]);

  useEffect(() => {
    if (opened) void load();
  }, [opened, load]);

  return {
    versions: data?.versions ?? [],
    currentVersionId: data?.current_version_id ?? null,
    total: data?.total ?? 0,
    loading,
    error,
    reload: load,
  };
}
