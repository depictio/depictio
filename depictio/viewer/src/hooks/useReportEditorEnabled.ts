import { useServerInfo } from './useServerInfo';

/** Whether this instance offers the report editor (`/dashboard-report/{id}`):
 *  the page that edits the report layer around a dashboard's notebook export.
 *  Off, and off while the answer is pending, so no link to it shows until the
 *  server says yes. The API 404s the report layer routes while it is off. */
export function useReportEditorEnabled(): boolean {
  const { info } = useServerInfo();
  return info?.features?.report_editor === true;
}
