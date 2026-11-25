import { useEffect, useState } from 'react';
import { fetchReportLayer } from 'depictio-react-core';
import { useReportEditorEnabled } from './useReportEditorEnabled';

/** Whether the reader may edit this dashboard's report, asked of the server.
 *
 *  The client only knows dashboard ownership; the server also lets the
 *  project's editors in (`check_dashboard_mutation_permission`). The layer
 *  route answers 404 to anyone else, so a successful read is the answer.
 *  Asked only when `ask` holds (not already known, not a past version, not a
 *  locked project) and the instance offers the editor. */
export function useReportEditable(dashboardId: string | null, ask: boolean): boolean {
  const enabled = useReportEditorEnabled();
  const [editable, setEditable] = useState(false);
  useEffect(() => {
    setEditable(false);
    if (!enabled || !ask || !dashboardId) return;
    const controller = new AbortController();
    fetchReportLayer(dashboardId, controller.signal)
      .then(() => setEditable(true))
      .catch(() => undefined);
    return () => controller.abort();
  }, [enabled, ask, dashboardId]);
  return editable;
}
