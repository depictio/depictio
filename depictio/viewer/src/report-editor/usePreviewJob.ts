import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchNotebookRenderStatus, startReportPreview } from 'depictio-react-core';
import type { NotebookRenderStatus } from 'depictio-react-core';

/** Consecutive failed polls before the job is reported lost. */
const MAX_POLL_FAILURES = 5;
const POLL_MS = 1000;
/** A state change waits this long, so a burst of filter edits renders once. */
const RESTART_DEBOUNCE_MS = 500;

export interface PreviewJobApi {
  /** The address of the last finished preview, or null before the first. */
  previewUrl: string | null;
  /** A render is running (the first one, or one for a changed state). */
  running: boolean;
  /** The running render replaces one already on screen: the filters changed. */
  rerendering: boolean;
  phase: string;
  elapsed: number;
  error: string | null;
  /** Start again, bypassing the cache. */
  rerun: () => void;
}

/** What the worker is doing, in the reader's words. */
function phaseLabel(job: NotebookRenderStatus | null, starting: boolean): string {
  if (starting) return 'Saving your edits';
  if (!job || job.status === 'queued') return 'Waiting for a worker';
  return job.phase === 'storing' ? 'Saving the preview' : 'Rendering the report';
}

/**
 * The preview job behind the right-hand frame.
 *
 * The report is rendered once, on a neutral layer: only the filter state (and
 * the data) change what the worker produces, so only a change of `stateKey`
 * starts another job. Everything else is applied to the finished report in the
 * browser. While a new job runs the previous preview stays on screen.
 */
export function usePreviewJob(
  dashboardId: string,
  ready: boolean,
  stateKey: string,
  beforeStart: () => Promise<unknown>,
): PreviewJobApi {
  const [job, setJob] = useState<NotebookRenderStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const runRef = useRef(0);
  const startedAtRef = useRef(0);
  const beforeStartRef = useRef(beforeStart);
  beforeStartRef.current = beforeStart;
  const renderedKeyRef = useRef<string | null>(null);

  const start = useCallback(
    async (force: boolean, key: string) => {
      const id = ++runRef.current;
      renderedKeyRef.current = key;
      setStarting(true);
      setError(null);
      startedAtRef.current = Date.now();
      setElapsed(0);
      try {
        await beforeStartRef.current();
        const started = await startReportPreview(dashboardId, { force });
        if (runRef.current !== id) return;
        setJob(started);
      } catch (err) {
        if (runRef.current === id) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (runRef.current === id) setStarting(false);
      }
    },
    [dashboardId],
  );

  // The first render, once the layer is there; later ones when the state changes.
  useEffect(() => {
    if (!ready) return;
    if (renderedKeyRef.current === null) {
      void start(false, stateKey);
      return;
    }
    if (renderedKeyRef.current === stateKey) return;
    const timer = window.setTimeout(() => void start(false, stateKey), RESTART_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [ready, stateKey, start]);

  // Abandon whatever is in flight on unmount.
  useEffect(
    () => () => {
      runRef.current += 1;
    },
    [],
  );

  const jobId = job?.job_id;
  const jobStatus = job?.status;
  useEffect(() => {
    if (!jobId || jobStatus === 'ready' || jobStatus === 'error') return;
    const controller = new AbortController();
    const tick = window.setInterval(
      () => setElapsed(Math.round((Date.now() - startedAtRef.current) / 1000)),
      1000,
    );
    // A failed poll (a blip, a restart) is retried; only a run of them is an
    // error, and the next answer clears it.
    let failures = 0;
    const poll = window.setInterval(() => {
      fetchNotebookRenderStatus(jobId, controller.signal)
        .then((next) => {
          failures = 0;
          setError(null);
          setJob((prev) => (prev && prev.job_id === next.job_id ? next : prev));
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          failures += 1;
          if (failures < MAX_POLL_FAILURES) return;
          window.clearInterval(poll);
          window.clearInterval(tick);
          setError(err instanceof Error ? err.message : String(err));
        });
    }, POLL_MS);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
      controller.abort();
    };
  }, [jobId, jobStatus]);

  useEffect(() => {
    if (jobStatus === 'ready') {
      if (job?.preview_url) {
        setPreviewUrl(job.preview_url);
      } else {
        setError('The server rendered the report but gave no address to preview it at.');
      }
    } else if (jobStatus === 'error') {
      setError(job?.reason || 'The worker could not render this report.');
    }
    // `job` changes only with the status fields read here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, jobStatus, job?.preview_url]);

  const running = starting || (job !== null && jobStatus !== 'ready' && jobStatus !== 'error');
  const rerun = useCallback(() => {
    if (renderedKeyRef.current !== null) void start(true, renderedKeyRef.current);
  }, [start]);

  return {
    previewUrl,
    running: running && !error,
    rerendering: running && !error && previewUrl !== null,
    phase: phaseLabel(job, starting),
    elapsed,
    error,
    rerun,
  };
}
