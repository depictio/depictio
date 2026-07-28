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

import React, { useCallback, useEffect, useRef, useState } from 'react';
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

const TERMINAL = new Set(['success', 'failed', 'cancelled']);

export const ProjectIngestionTrigger: React.FC<{
  projectId: string;
  /** Called once a run has been started, so the parent can switch to History. */
  onStarted?: (runId: string | null) => void;
  /** Called when the job reaches a terminal state, to refresh the panel. */
  onFinished?: (status: string) => void;
}> = ({ projectId, onStarted, onFinished }) => {
  const [status, setStatus] = useState<IngestionTriggerStatus | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const pollRef = useRef<number | null>(null);

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

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Unmounting mid-ingestion must not leave a timer firing into a dead
  // component — the run carries on server-side regardless.
  useEffect(() => stopPolling, [stopPolling]);

  const poll = useCallback(
    (jobId: string) => {
      const tick = async () => {
        // Next delay comes from the response itself rather than from state:
        // reading it from `job` would capture whatever was set when this
        // callback was created, which is null on the first tick and stale
        // after.
        let delaySeconds = 3;
        try {
          const next = await fetchJob(jobId);
          setJob(next);
          if (TERMINAL.has(next.status)) {
            onFinished?.(next.status);
            notifications.show({
              color: next.status === 'success' ? 'green' : 'red',
              title: next.status === 'success' ? 'Ingestion finished' : 'Ingestion failed',
              message: next.error || next.detail || `Job ${next.status}.`,
            });
            return;
          }
          delaySeconds = Math.max(1, next.poll_after_seconds ?? 3);
        } catch {
          // A transient poll failure is not a failed ingestion — back off a
          // little and keep asking rather than declaring the run lost.
          delaySeconds = 10;
        }
        pollRef.current = window.setTimeout(tick, delaySeconds * 1000);
      };
      pollRef.current = window.setTimeout(tick, 1500);
    },
    [onFinished],
  );

  const start = async () => {
    setStarting(true);
    try {
      const result = await triggerProjectIngestion(projectId, { overwrite });
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
      poll(result.job_id);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not start ingestion',
        message: (err as Error).message,
      });
    } finally {
      setStarting(false);
    }
  };

  if (!status?.enabled) return null;

  const running = job != null && !TERMINAL.has(job.status);
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
