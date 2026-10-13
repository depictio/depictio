/**
 * "Run ingestion" — start a server-side ingestion from the project page.
 *
 * Only useful where the API can read the same filesystem the data sits on (a
 * shared PVC, a mounted export). On a deployment whose data lives on an HPC
 * node the API cannot see, the server says so and the button is disabled with
 * that as its reason — the alternative, a button that starts a run which finds
 * nothing and reports success, is much worse.
 *
 * The whole control is hidden when the server does not offer the feature at
 * all; a permanently dead button on every deployment that never turns the flag
 * on is noise rather than an affordance.
 */

import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Group, Modal, Progress, Stack, Switch, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';
import {
  fetchIngestionTriggerStatus,
  fetchJob,
  triggerProjectIngestion,
  type IngestionTriggerStatus,
  type JobStatusResponse,
} from 'depictio-react-core';

import { TERMINAL_JOB_STATUSES, followJob, type JobFollowEnd } from './followJob';

/** What to tell the user when the server stops reporting the job. The run is
 *  not known to have failed, so neither message says it did. */
function refusedMessage(status: number, detail: string): string {
  const where = 'The ingestion may still be running: its outcome will appear in the history.';
  if (status === 404) {
    return `The server no longer reports this job to you. It may have been started by another user, or have expired. ${where}`;
  }
  return `The server refused to report this job (${status}: ${detail}). ${where}`;
}

export const ProjectIngestionTrigger: React.FC<{
  projectId: string;
  /** Called once a run has been started, so the parent can switch to History. */
  onStarted?: (runId: string | null) => void;
  /** Called when the button stops following the job: a terminal status, or
   *  `'refused'` when the server would not report it. Refreshes the panel. */
  onFinished?: (status: string) => void;
}> = ({ projectId, onStarted, onFinished }) => {
  const [status, setStatus] = useState<IngestionTriggerStatus | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  // Every await below can resolve after the component is gone. The run
  // carries on server-side regardless; this only stops the bookkeeping.
  const mountedRef = useRef(false);
  const stopFollowingRef = useRef<(() => void) | null>(null);
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stopFollowingRef.current?.();
      stopFollowingRef.current = null;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchIngestionTriggerStatus(projectId)
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const onFollowEnd = (end: JobFollowEnd) => {
    stopFollowingRef.current = null;
    if (end.kind === 'refused') {
      // Free the button: nothing here can learn more about this job.
      setJob(null);
      onFinishedRef.current?.('refused');
      notifications.show({
        color: 'yellow',
        title: 'Stopped following the ingestion',
        message: refusedMessage(end.status, end.message),
      });
      return;
    }
    const next = end.job;
    onFinishedRef.current?.(next.status);
    // A run where some collections or joins failed still ends `success`, with
    // the failures summarised in `error`.
    const partial = next.status === 'success' && Boolean(next.error);
    notifications.show({
      color: partial ? 'yellow' : next.status === 'success' ? 'green' : 'red',
      title: partial
        ? 'Ingestion finished with errors'
        : next.status === 'success'
          ? 'Ingestion finished'
          : 'Ingestion failed',
      message: next.error || next.detail || `Job ${next.status}.`,
    });
  };

  const follow = (jobId: string) => {
    stopFollowingRef.current?.();
    stopFollowingRef.current = followJob(jobId, {
      fetchJob,
      onUpdate: setJob,
      onEnd: onFollowEnd,
    });
  };

  const start = async () => {
    setStarting(true);
    try {
      const result = await triggerProjectIngestion(projectId, { overwrite });
      if (!mountedRef.current) return;
      setConfirmOpen(false);
      onStarted?.(result.run_id);
      if (result.already_running) {
        notifications.show({
          color: 'blue',
          title: 'Already running',
          message: 'An ingestion for this project is already in progress; following that one.',
        });
      }
      setJob({ job_id: result.job_id, kind: 'project.ingest', status: 'pending' });
      follow(result.job_id);
    } catch (err) {
      if (!mountedRef.current) return;
      notifications.show({
        color: 'red',
        title: 'Could not start ingestion',
        message: (err as Error).message,
      });
    } finally {
      if (mountedRef.current) setStarting(false);
    }
  };

  if (!status?.enabled) return null;

  const running = job != null && !TERMINAL_JOB_STATUSES.has(job.status);
  const button = (
    <Button
      size="xs"
      variant="light"
      color="teal"
      disabled={!status.available || running}
      loading={starting}
      onClick={() => setConfirmOpen(true)}
      leftSection={<Icon icon="mdi:play-circle-outline" width={16} />}
    >
      Run ingestion
    </Button>
  );

  return (
    <>
      <Group gap="sm" wrap="nowrap">
        {status.reason ? (
          <Tooltip label={status.reason} multiline w={300} withArrow withinPortal>
            <span>{button}</span>
          </Tooltip>
        ) : (
          button
        )}
        {running && (
          <Group gap={6} wrap="nowrap">
            <Text size="xs" c="dimmed">
              {job?.step ? `${job.step}${job.detail ? ` · ${job.detail}` : ''}` : 'Starting…'}
            </Text>
            {job?.progress?.total ? (
              <Progress
                w={90}
                size="sm"
                value={((job.progress.current ?? 0) / job.progress.total) * 100}
              />
            ) : null}
          </Group>
        )}
      </Group>

      <Modal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Run ingestion"
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            The server will re-scan this project's data locations and rebuild its data
            collections. Existing dashboards keep working while it runs.
          </Text>
          <Switch
            checked={overwrite}
            onChange={(event) => setOverwrite(event.currentTarget.checked)}
            label="Overwrite existing tables"
            description="Rebuild every data collection from scratch instead of only what changed."
          />
          {overwrite && (
            <Alert color="yellow" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
              Every table will be rewritten. On a large project this takes considerably longer.
            </Alert>
          )}
          <Group justify="flex-end">
            <Button variant="subtle" size="sm" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button color="teal" size="sm" loading={starting} onClick={start}>
              Start
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default ProjectIngestionTrigger;
