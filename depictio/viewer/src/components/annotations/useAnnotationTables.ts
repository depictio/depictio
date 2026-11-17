import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAnnotationTables, saveSharedLabels } from 'depictio-react-core';
import type { AnnotationColumn, AnnotationTable } from 'depictio-react-core';

export interface AnnotationTablesState {
  /** The project's tables with whether each can carry labels. */
  tables: AnnotationTable[];
  /** Label columns shared on this dashboard, read-only for most readers. */
  shared: AnnotationColumn[];
  /** Whether this reader may change the shared labels (never on a past version). */
  canShare: boolean;
  /** Replace the shared labels. Resolves to an error message, or null once saved. */
  saveShared: (columns: AnnotationColumn[]) => Promise<string | null>;
}

/**
 * The project's tables with whether each can carry session labels (a
 * metadata table linked to the data, never joined, within the row limit), and
 * the labels shared on the dashboard. The server decides
 * (`GET /dashboards/annotations/{id}/tables`); an error reads as no table, so
 * the Metadata button stays hidden rather than open on nothing.
 *
 * `versionId` reads the shared labels as that version held them, read-only.
 */
export function useAnnotationTables(
  dashboardId: string | undefined,
  versionId: string | null,
): AnnotationTablesState {
  const [tables, setTables] = useState<AnnotationTable[]>([]);
  const [shared, setShared] = useState<AnnotationColumn[]>([]);
  const [canShare, setCanShare] = useState(false);
  const latest = useRef<AnnotationColumn[]>([]);

  useEffect(() => {
    setTables([]);
    setShared([]);
    setCanShare(false);
    latest.current = [];
    if (!dashboardId) return;
    let cancelled = false;
    void fetchAnnotationTables(dashboardId, versionId).then((res) => {
      if (cancelled || !res.ok) return;
      setTables(res.tables);
      setShared(res.shared);
      latest.current = res.shared;
      setCanShare(res.canShare);
    });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, versionId]);

  const saveShared = useCallback(
    async (columns: AnnotationColumn[]): Promise<string | null> => {
      if (!dashboardId) return 'No dashboard.';
      // Shown at once; put back if the server refuses.
      const before = latest.current;
      latest.current = columns;
      setShared(columns);
      const res = await saveSharedLabels(dashboardId, columns);
      if (res.ok) {
        if (latest.current === columns) {
          latest.current = res.shared;
          setShared(res.shared);
        }
        return null;
      }
      if (latest.current === columns) {
        latest.current = before;
        setShared(before);
      }
      if (res.status === 409) return 'This dashboard is published, so its shared labels cannot change.';
      if (res.status === 403) {
        setCanShare(false);
        return res.detail || 'You can no longer change the labels shared on this dashboard.';
      }
      return res.detail || 'The shared labels could not be saved.';
    },
    [dashboardId],
  );

  return { tables, shared, canShare, saveShared };
}
