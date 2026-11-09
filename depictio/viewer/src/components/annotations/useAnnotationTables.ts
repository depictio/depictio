import { useEffect, useState } from 'react';
import { fetchAnnotationTables } from 'depictio-react-core';
import type { AnnotationTable } from 'depictio-react-core';

/**
 * The project's tables with whether each can carry session labels: a metadata
 * table linked to the data, never joined, within the row limit. The server
 * decides (`GET /dashboards/annotations/{id}/tables`); an error reads as no
 * table, so the Metadata button stays hidden rather than open on nothing.
 */
export function useAnnotationTables(dashboardId: string | undefined): AnnotationTable[] {
  const [tables, setTables] = useState<AnnotationTable[]>([]);
  useEffect(() => {
    setTables([]);
    if (!dashboardId) return;
    let cancelled = false;
    void fetchAnnotationTables(dashboardId).then((res) => {
      if (!cancelled && res.ok) setTables(res.tables);
    });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);
  return tables;
}
