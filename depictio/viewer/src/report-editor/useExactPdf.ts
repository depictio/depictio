import { useCallback, useRef, useState } from 'react';
import {
  fetchNotebookRenderBlob,
  fetchNotebookRenderStatus,
  startNotebookRender,
} from 'depictio-react-core';
import type { ReportLayer } from 'depictio-react-core';

const POLL_MS = 2000;
const GIVE_UP_MS = 15 * 60 * 1000;

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export interface ExactPdfApi {
  busy: boolean;
  error: string | null;
  /** Render the report with its PDF and open the PDF in a new tab. */
  run: () => void;
}

/**
 * "Exact PDF": the full render, with Quarto's PDF beside the HTML, opened in a
 * new tab. It takes minutes, unlike the live preview, so the tab is opened by
 * the click itself (a window opened after the wait would be blocked) and
 * pointed at the PDF once it exists.
 */
export function useExactPdf(
  dashboardId: string,
  layer: ReportLayer | null,
  flush: () => Promise<void>,
): ExactPdfApi {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);

  const run = useCallback(() => {
    if (busyRef.current || !layer) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    const tab = window.open('', '_blank');
    void (async () => {
      try {
        await flush();
        let job = await startNotebookRender(dashboardId, layer.state, 'paper', {
          output: 'report',
          pdf: true,
          pdfStyle: layer.style ?? 'colour',
        });
        const startedAt = Date.now();
        while (job.status !== 'ready' && job.status !== 'error') {
          if (Date.now() - startedAt > GIVE_UP_MS) throw new Error('The render took too long.');
          await sleep(POLL_MS);
          job = await fetchNotebookRenderStatus(job.job_id);
        }
        if (job.status === 'error') throw new Error(job.reason || 'The report could not be rendered.');
        if (!job.pdf_filename) throw new Error(job.pdf_error || 'No PDF was produced for this report.');
        const blob = await fetchNotebookRenderBlob(job.job_id, 'pdf');
        const url = URL.createObjectURL(blob);
        if (tab && !tab.closed) tab.location.href = url;
        else window.open(url, '_blank');
      } catch (err) {
        tab?.close();
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    })();
  }, [dashboardId, layer, flush]);

  return { busy, error, run };
}
