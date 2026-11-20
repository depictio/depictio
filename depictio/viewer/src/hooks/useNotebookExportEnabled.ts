import { useServerInfo } from './useServerInfo';

/** Whether this instance offers the Quarto notebook export (the `.qmd` and the
 *  rendered report). Set by `DEPICTIO_NOTEBOOK_EXPORT_ENABLED`; off, and off
 *  while the answer is pending, so nothing renders or is requested until the
 *  server says yes. The API 404s the notebook export routes while it is off. */
export function useNotebookExportEnabled(): boolean {
  const { info } = useServerInfo();
  return info?.features?.notebook_export === true;
}
