/**
 * What the selected version changed, for the drawer and the canvas marks.
 *
 * Same shape as `useVersionHistory` — plain `useState` + `useEffect`, no
 * react-query — including its `requestId` race guard. That guard is not
 * theoretical here: arrow-key stepping fires a request per keypress, so a slow
 * response for a version the user has already stepped past would otherwise
 * overwrite the current one.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchVersionDiff, type VersionDiff } from 'depictio-react-core';

interface UseVersionDiff {
  diff: VersionDiff | null;
  loading: boolean;
  error: string | null;
}

export function useVersionDiff(
  versionId: string | null,
  against: 'previous' | 'current' = 'previous',
  enabled = true,
): UseVersionDiff {
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestId = useRef(0);

  const load = useCallback(async () => {
    if (!versionId || !enabled) {
      setDiff(null);
      return;
    }
    const ticket = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetchVersionDiff(versionId, against);
      if (ticket === requestId.current) setDiff(result);
    } catch (err) {
      if (ticket === requestId.current) {
        setDiff(null);
        setError(err instanceof Error ? err.message : 'Failed to load changes');
      }
    } finally {
      if (ticket === requestId.current) setLoading(false);
    }
  }, [versionId, against, enabled]);

  useEffect(() => {
    void load();
  }, [load]);

  return { diff, loading, error };
}
