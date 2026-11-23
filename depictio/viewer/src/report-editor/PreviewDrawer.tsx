import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, Drawer, Group, Loader, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  Z_LAYERS,
  fetchNotebookRenderBlob,
  fetchNotebookRenderStatus,
  startReportPreview,
} from 'depictio-react-core';
import type { NotebookRenderStatus } from 'depictio-react-core';

const POLL_MS = 2000;
const PREVIEW_FRAME_URL = '/depictio/api/v1/dashboards/notebook_export/preview_frame';
/** Must match ``PREVIEW_FRAME_MESSAGE`` in ``notebook_export.py``. */
const PREVIEW_FRAME_MESSAGE = 'depictio-report-preview';

/** What the worker is doing, in the reader's words. */
function phaseLabel(job: NotebookRenderStatus | null): string {
  if (!job || job.status === 'queued') return 'Queued';
  switch (job.phase) {
    case 'embedding':
      return 'Packing the dashboard';
    case 'combining':
      return 'Putting the report and the dashboard together';
    case 'storing':
      return 'Saving';
    default:
      return 'Rendering the report';
  }
}

function elapsedLabel(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

interface PreviewDrawerProps {
  opened: boolean;
  onClose: () => void;
  dashboardId: string;
  /** Write any pending edit first, so the preview shows what is on screen. */
  beforeRun: () => Promise<void>;
}

/**
 * The exact preview: the real report, rendered on a worker with the stored
 * layer, then shown in a frame. Opening the drawer starts a run; "Re-run with
 * fresh data" starts another that bypasses the cached one.
 */
const PreviewDrawer: React.FC<PreviewDrawerProps> = ({ opened, onClose, dashboardId, beforeRun }) => {
  const [job, setJob] = useState<NotebookRenderStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  // A run that is no longer the latest must not touch the state.
  const runRef = useRef(0);
  const startedAtRef = useRef(0);

  const run = useCallback(
    async (force: boolean) => {
      const id = ++runRef.current;
      setStarting(true);
      setError(null);
      setHtml(null);
      setJob(null);
      try {
        await beforeRun();
        const started = await startReportPreview(dashboardId, { force });
        if (runRef.current !== id) return;
        startedAtRef.current = Date.now();
        setElapsed(0);
        setJob(started);
      } catch (err) {
        if (runRef.current === id) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (runRef.current === id) setStarting(false);
      }
    },
    [dashboardId, beforeRun],
  );

  // Opening starts a run; closing abandons whatever is in flight.
  useEffect(() => {
    if (opened) {
      void run(false);
    } else {
      runRef.current += 1;
    }
    // `run` is stable per dashboard; only the drawer opening should restart it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Ask the job where it is until it stops moving.
  const jobId = job?.job_id;
  const jobStatus = job?.status;
  useEffect(() => {
    if (!jobId || jobStatus === 'ready' || jobStatus === 'error') return;
    const controller = new AbortController();
    const tick = window.setInterval(
      () => setElapsed(Math.round((Date.now() - startedAtRef.current) / 1000)),
      1000,
    );
    const poll = window.setInterval(() => {
      fetchNotebookRenderStatus(jobId, controller.signal)
        .then((next) => setJob((prev) => (prev && prev.job_id === next.job_id ? next : prev)))
        .catch((err) => {
          if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
        });
    }, POLL_MS);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
      controller.abort();
    };
  }, [jobId, jobStatus]);

  // The finished report, as text for a frame that cannot reach the app.
  useEffect(() => {
    if (!jobId || jobStatus !== 'ready') return;
    const controller = new AbortController();
    fetchNotebookRenderBlob(jobId, 'html', controller.signal)
      .then((blob) => blob.text())
      .then((text) => {
        if (!controller.signal.aborted) setHtml(text);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
      });
    return () => controller.abort();
  }, [jobId, jobStatus]);

  // The report is written into an empty page the API serves with its own
  // sandboxed policy. A blob: or srcdoc frame would inherit this app's CSP,
  // which refuses the frame and every inline script of a Quarto report.
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  useEffect(() => {
    if (!html) return;
    const onMessage = (event: MessageEvent) => {
      const frame = frameRef.current?.contentWindow;
      if (!frame || event.source !== frame) return;
      if ((event.data as { type?: string } | null)?.type !== `${PREVIEW_FRAME_MESSAGE}-ready`) return;
      // The frame has an opaque origin, so no target origin can name it.
      frame.postMessage({ type: PREVIEW_FRAME_MESSAGE, html }, '*');
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [html]);

  const running = starting || (job !== null && job.status !== 'ready' && job.status !== 'error');
  const failed = job?.status === 'error';

  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size="70%"
      zIndex={Z_LAYERS.nestedOverlay}
      title={
        <Group gap="xs">
          <Icon icon="mdi:file-eye-outline" width={20} />
          <Text fw={600}>Exact preview</Text>
        </Group>
      }
      styles={{ body: { height: 'calc(100% - 60px)' } }}
      data-testid="report-preview-drawer"
    >
      <Stack gap="sm" h="100%">
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" c="dimmed">
            The real report, rendered with what is saved above.
          </Text>
          <Button
            size="xs"
            variant="default"
            leftSection={<Icon icon="mdi:refresh" width={14} />}
            onClick={() => void run(true)}
            disabled={running}
            data-testid="report-preview-rerun"
          >
            Re-run with fresh data
          </Button>
        </Group>

        {error && (
          <Alert color="red" title="The preview failed">
            {error}
          </Alert>
        )}
        {failed && (
          <Alert color="red" title="The preview failed">
            {job?.reason || 'The worker could not render this report.'}
          </Alert>
        )}
        {running && !error && (
          <Alert color="blue" variant="light" data-testid="report-preview-running">
            <Group gap="xs">
              <Loader size="xs" />
              <Text size="sm">
                {starting ? 'Saving your edits' : phaseLabel(job)} · {elapsedLabel(elapsed)}
              </Text>
            </Group>
          </Alert>
        )}
        {job?.status === 'ready' && !html && !error && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm">Opening the report</Text>
          </Group>
        )}

        {html && (
          <Box style={{ flex: 1, minHeight: 0 }}>
            <iframe
              key={jobId}
              ref={frameRef}
              title="Report preview"
              src={PREVIEW_FRAME_URL}
              sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
              style={{ width: '100%', height: '100%', border: 0 }}
              data-testid="report-preview-frame"
            />
          </Box>
        )}
      </Stack>
    </Drawer>
  );
};

export default PreviewDrawer;
