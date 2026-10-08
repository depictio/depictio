/**
 * Post-creation modal for a project made from a run folder.
 *
 * Unlike the from-manifest flow, the endpoint answers as soon as the project
 * and its dashboards exist and hands back a `run_id`: the collections are
 * still ingesting on the workers. So the user is never redirected: they watch
 * the run here and open the dashboard when they are ready. Closing this only
 * stops watching; the run carries on server-side and the project's Ingestion
 * tab shows the outcome.
 *
 * Rendered by `ProjectsApp` (the create modal is already closed by then).
 */
import React, { useEffect, useState } from 'react';
import { Alert, Box, Button, Group, Loader, Modal, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type { DetectedTemplate, FromRunReport, ManifestRefreshReport } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';
import IngestionResultTable from '../IngestionResultTable';
import { formatElapsed, summarizeManifestRun, useElapsedMs, useManifestRunPoll } from '../manifestRun';
import { RunPreview } from './RunPreview';

/** What the create dialog knew about the run that the report may not carry:
 *  the template's name and what was read in the folder. */
export interface RunCreatedContext {
  templateTitle: string | null;
  detection: DetectedTemplate | null;
}

type WatchState = 'idle' | 'running' | 'success' | 'failed';

export const RunCreatedModal: React.FC<{
  report: FromRunReport | null;
  context?: RunCreatedContext | null;
  onClose: () => void;
}> = ({ report, context, onClose }) => {
  const accent = useBrandAccents();
  const [progress, setProgress] = useState<ManifestRefreshReport | null>(null);
  /** Run being polled; null while nothing is in flight. */
  const [runId, setRunId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Start watching whenever a new report arrives, and stop when it is cleared.
  useEffect(() => {
    setProgress(null);
    setError(null);
    setFinishedAt(null);
    setStartedAt(report?.run_id ? Date.now() : null);
    setRunId(report?.run_id ?? null);
  }, [report]);

  useManifestRunPoll({
    runId,
    startedAt,
    onReport: setProgress,
    onStop: (pollError) => {
      if (pollError) setError(pollError);
      setRunId(null);
      setFinishedAt(Date.now());
    },
    pollErrorMessage: (err) =>
      `Lost track of the ingestion run: ${err.message}. ` +
      "The workers keep going; the project's Ingestion tab shows the outcome.",
    timeoutMessage:
      'Stopped polling after 30 minutes. Ingestion may still be running; ' +
      "the project's Ingestion tab shows the outcome.",
  });

  const elapsedMs = useElapsedMs(Boolean(runId), startedAt, finishedAt);

  const dashboardId =
    report?.dashboards.find((d) => d.success && d.dashboard_id)?.dashboard_id ?? null;
  const noDashboardReason = dashboardId ? null : 'No dashboard was imported for this project.';

  let state: WatchState = 'idle';
  if (runId) {
    state = 'running';
  } else if (progress && finishedAt != null) {
    state = progress.success ? 'success' : 'failed';
  } else if (error) {
    state = 'failed';
  }

  return (
    <Modal
      opened={Boolean(report)}
      onClose={onClose}
      centered
      size="xl"
      title={
        <Group gap="xs" wrap="nowrap">
          <Icon
            icon="mdi:rocket-launch-outline"
            width={20}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Text fw={600}>Project created</Text>
        </Group>
      }
    >
      {report && (
        <Stack gap="md" data-testid="run-created-modal">
          <Alert
            color={report.success ? accent.secondary : 'orange'}
            variant="light"
            icon={<Icon icon="mdi:information-outline" width={16} />}
          >
            <Text size="sm">
              &ldquo;{report.project_name}&rdquo; exists and its dashboards are imported. The
              data collections are being ingested in the background; closing this only stops
              watching.
            </Text>
          </Alert>

          {report.storage_saved && (
            <Group gap="xs" wrap="nowrap" align="flex-start" data-testid="run-created-storage-saved">
              <ThemeIcon variant="light" size="sm" radius="xl" color="teal">
                <Icon icon="mdi:cloud-lock-outline" width={14} />
              </ThemeIcon>
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm">Storage settings saved for this project</Text>
                <Text size="xs" c="dimmed">
                  The private bucket&apos;s connection details are used for every read of its
                  data. Change them in Project settings, Storage.
                </Text>
              </Stack>
            </Group>
          )}

          <Box aria-live="polite" role="status">
            <Group gap="xs" wrap="nowrap">
              {state === 'running' && <Loader size="xs" color={accent.secondary} />}
              {(state === 'success' || state === 'failed') && (
                <ThemeIcon
                  variant="light"
                  size="sm"
                  radius="xl"
                  color={state === 'success' ? 'green' : 'red'}
                >
                  <Icon
                    icon={state === 'success' ? 'mdi:check-circle' : 'mdi:alert-circle'}
                    width={14}
                  />
                </ThemeIcon>
              )}
              {state === 'idle' && (
                <ThemeIcon variant="light" size="sm" radius="xl" color="gray">
                  <Icon icon="mdi:minus-circle-outline" width={14} />
                </ThemeIcon>
              )}
              <Text size="sm" data-testid="run-created-status" data-state={state}>
                {state === 'idle' && 'No ingestion run to watch.'}
                {state === 'running' &&
                  `Ingesting (${formatElapsed(elapsedMs)} elapsed)` +
                    (progress ? `: ${summarizeManifestRun(progress)}` : '')}
                {state === 'success' &&
                  progress &&
                  `Ingestion completed in ${formatElapsed(elapsedMs)}: ${summarizeManifestRun(progress)}`}
                {state === 'failed' &&
                  (progress
                    ? `Ingestion finished with errors in ${formatElapsed(elapsedMs)}: ${summarizeManifestRun(progress)}`
                    : 'Ingestion failed')}
              </Text>
            </Group>
          </Box>

          {error && (
            <Alert
              color="red"
              variant="light"
              icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
              data-testid="run-created-error"
            >
              {error}
            </Alert>
          )}

          {progress && (
            <IngestionResultTable
              rows={progress.refreshed}
              rowTestIdPrefix="run-progress"
              emptyText="The ingestion run reported no collection yet."
              testId="run-progress-results"
            />
          )}

          <RunPreview
            report={report}
            templateTitle={context?.templateTitle ?? null}
            detection={context?.detection ?? null}
          />

          <Stack gap={4}>
            <Group justify="flex-end" gap="xs">
              <Button variant="default" onClick={onClose} data-testid="run-created-stay">
                Stay on projects
              </Button>
              <GatedButton
                color={accent.secondary}
                leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
                reason={noDashboardReason}
                onClick={() => {
                  if (dashboardId) window.location.assign(`/dashboard/${dashboardId}`);
                }}
                data-testid="run-created-open-dashboard"
              >
                Open dashboard
              </GatedButton>
            </Group>
            {noDashboardReason ? (
              <Group justify="flex-end">
                <DisabledReason reason={noDashboardReason} icon="mdi:information-outline" />
              </Group>
            ) : (
              state === 'running' && (
                <Text size="xs" c="dimmed" ta="right" data-testid="run-created-dashboard-hint">
                  Ingestion is still running: the dashboard fills in as collections finish.
                </Text>
              )
            )}
          </Stack>
        </Stack>
      )}
    </Modal>
  );
};
