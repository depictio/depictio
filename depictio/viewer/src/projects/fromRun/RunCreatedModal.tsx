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
 * It opens the moment Create is clicked, before the server answered, so
 * nothing sits on a spinner. Each source is one folded section: its summary
 * stays visible, the details are a click away, and the buttons stay in sight
 * below however long the list is.
 *
 * Rendered by `ProjectsApp` (the create modal is already closed by then).
 */
import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  ThemeIcon,
  VisuallyHidden,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import { LinkSuggestions } from '../create/LinkSuggestions';
import type { DetectedTemplate, FromRunReport, ManifestRefreshReport } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';
import IngestionResultTable from '../IngestionResultTable';
import {
  formatElapsed,
  manifestRunOutcome,
  summarizeManifestRun,
  useElapsedMs,
  useManifestRunPoll,
} from '../manifestRun';
import type { ManifestRunOutcome } from '../manifestRun';
import { ScrollWithHint } from '../../components/ScrollWithHint';
import { FileUploadResults } from '../create/FilesDropArea';
import type { TableUploadOutcome } from '../create/FilesDropArea';
import { SourceSection } from '../create/SourceSection';
import { plural } from './plural';
import { RunPreview } from './RunPreview';

/** What the create dialog knew about the run that the report may not carry:
 *  the template's name and what was read in the folder. */
export interface RunCreatedContext {
  /** What the project will be called, shown while it is being created. */
  projectName: string;
  templateTitle: string | null;
  detection: DetectedTemplate | null;
  /** Tables dropped next to the run folder: uploaded once the project exists. */
  extraFiles?: File[];
  /** Collection names the run takes, so the uploads do not clash with them. */
  takenTableNames?: string[];
}

/** `idle`: the report names no run to watch. Once the watcher stops, the
 *  outcome comes from the rows (`manifestRunOutcome`). */
type WatchState = 'idle' | 'running' | ManifestRunOutcome;

/** `summarizeManifestRun`, with collections the run did not produce read as
 *  that rather than as a shortfall ("21 ingested, 2 not in this run"). */
function summarizeRun(report: ManifestRefreshReport): string {
  return summarizeManifestRun(report).replace(/(\d+) skipped/, '$1 not in this run');
}

/** Words for the run once the watcher stopped (`elapsed` is then fixed). */
function describeEndedRun(
  state: ManifestRunOutcome,
  summary: string | null,
  elapsed: string,
): string {
  if (state === 'success') return `Ingestion completed in ${elapsed}: ${summary ?? ''}`;
  if (state === 'stopped') {
    return `Stopped following the ingestion after ${elapsed}${
      summary ? `. Last seen: ${summary}` : ''
    }`;
  }
  return `Ingestion finished with errors in ${elapsed}: ${summary ?? ''}`;
}

/** What the status line says in each state. */
function watchText(
  state: WatchState,
  elapsedMs: number,
  progress: ManifestRefreshReport | null,
): string {
  const elapsed = formatElapsed(elapsedMs);
  const summary = progress ? summarizeRun(progress) : null;
  if (state === 'idle') return 'No ingestion run to watch.';
  if (state === 'running') return `Ingesting (${elapsed} elapsed)` + (summary ? `: ${summary}` : '');
  return describeEndedRun(state, summary, elapsed);
}

/** What a screen reader hears, in a live region: each state change and the
 *  final summary, never the ticking elapsed time nor every row update. */
function announceRun(
  state: WatchState,
  progress: ManifestRefreshReport | null,
  startedAt: number | null,
  finishedAt: number | null,
): string {
  if (state === 'idle') return '';
  if (state === 'running') return 'The ingestion is running.';
  const elapsed = formatElapsed(
    startedAt == null || finishedAt == null ? 0 : finishedAt - startedAt,
  );
  return describeEndedRun(state, progress ? summarizeRun(progress) : null, elapsed);
}

/** What creating the project did, worded from the report: how many of the
 *  template's dashboards were imported, and whether ingestion started. */
function createdText(report: FromRunReport): string {
  const total = report.dashboards.length;
  const imported = report.dashboards.filter((d) => d.success).length;
  let dashboards: string;
  if (total === 0) dashboards = 'no dashboard was imported';
  else if (imported === total) {
    dashboards = total === 1 ? 'its dashboard is imported' : `its ${total} dashboards are imported`;
  } else if (imported === 0) {
    dashboards =
      total === 1
        ? 'its dashboard could not be imported (see below)'
        : `none of its ${total} dashboards could be imported (see below)`;
  } else {
    dashboards = `${imported} of its ${total} dashboards are imported, the others failed (see below)`;
  }
  const parts = [`\u201c${report.project_name}\u201d exists and ${dashboards}.`];
  if (report.run_id) {
    parts.push(
      'The data collections are being ingested in the background; closing this only stops watching.',
    );
    // Every dashboard imported, and still not a success: a collection could
    // not be handed to a worker, and its row says so.
    if (!report.success && imported === total) {
      parts.push('Some data collections could not be handed to the workers: their rows say why.');
    }
  } else {
    parts.push('No data collection was sent for ingestion.');
  }
  return parts.join(' ');
}

/** The glyph beside the status line: a loader while the run goes on. */
const WatchIcon: React.FC<{ state: WatchState; loaderColor: string }> = ({
  state,
  loaderColor,
}) => {
  switch (state) {
    case 'running':
      return <Loader size="xs" color={loaderColor} />;
    case 'success':
      return (
        <ThemeIcon variant="light" size="sm" radius="xl" color="green">
          <Icon icon="mdi:check-circle" width={14} />
        </ThemeIcon>
      );
    case 'failed':
      return (
        <ThemeIcon variant="light" size="sm" radius="xl" color="red">
          <Icon icon="mdi:alert-circle" width={14} />
        </ThemeIcon>
      );
    case 'stopped':
      // A caution, not a failure: the run may still be going.
      return (
        <ThemeIcon variant="light" size="sm" radius="xl" color="yellow">
          <Icon icon="mdi:eye-off-outline" width={14} />
        </ThemeIcon>
      );
    case 'idle':
      return (
        <ThemeIcon variant="light" size="sm" radius="xl" color="gray">
          <Icon icon="mdi:minus-circle-outline" width={14} />
        </ThemeIcon>
      );
  }
};

export const RunCreatedModal: React.FC<{
  opened: boolean;
  /** Null while the project is being created. */
  report: FromRunReport | null;
  context?: RunCreatedContext | null;
  /** Why the project could not be created. */
  error?: string | null;
  /** How the dropped files went, in `context.extraFiles` order. */
  uploads?: TableUploadOutcome[];
  onRetry?: (() => void) | null;
  onClose: () => void;
}> = ({ opened, report, context, error: createError = null, uploads = [], onRetry = null, onClose }) => {
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

  // The watcher stops on a terminal report or when it gives up (`error`);
  // either way the outcome is read from the rows, so a give-up with rows
  // still in flight is `stopped`, not a failure.
  let state: WatchState = 'idle';
  if (runId) state = 'running';
  else if (finishedAt != null) state = manifestRunOutcome(progress);

  const files = context?.extraFiles ?? [];
  const failedFiles = uploads.filter((u) => u.error).length;
  const creating = !report && !createError;
  const name = report?.project_name ?? context?.projectName ?? '';
  // A project still being created has nowhere to open.
  const dashboardReason = report ? noDashboardReason : 'The project is being created.';
  let filesSummary = `${plural(files.length, 'file')} waiting for the project`;
  if (report) {
    filesSummary =
      uploads.length < files.length
        ? `Uploading: ${uploads.length} of ${plural(files.length, 'file')}`
        : `${files.length - failedFiles} of ${plural(files.length, 'file')} added` +
          (failedFiles > 0 ? `, ${failedFiles} failed` : '');
  }

  return (
    <Modal
      opened={opened}
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
          <Text fw={600}>{report ? 'Project created' : `Creating \u201c${name}\u201d`}</Text>
        </Group>
      }
    >
      <Stack gap="md" data-testid="run-created-modal">
        {/* Not a live region: it ticks once a second. The announcer below
            speaks state changes only. */}
        <Group gap="xs" wrap="nowrap">
          {creating ? (
            <Loader size="xs" color={accent.secondary} />
          ) : createError ? (
            <ThemeIcon variant="light" size="sm" radius="xl" color="red">
              <Icon icon="mdi:alert-circle" width={14} />
            </ThemeIcon>
          ) : (
            <WatchIcon state={state} loaderColor={accent.secondary} />
          )}
          <Text size="sm" data-testid="run-created-status" data-state={creating ? 'creating' : state}>
            {creating
              ? 'Creating the project and importing its dashboards...'
              : createError
                ? 'The project could not be created.'
                : watchText(state, elapsedMs, progress)}
          </Text>
        </Group>
        <VisuallyHidden role="status" aria-live="polite">
          {creating ? 'The project is being created.' : announceRun(state, progress, startedAt, finishedAt)}
        </VisuallyHidden>

        {createError && (
          <Alert color="red" variant="light" data-testid="run-created-create-error">
            <Stack gap="xs" align="flex-start">
              <Text size="sm">{createError}</Text>
              {onRetry && (
                <Button size="xs" variant="light" color="red" onClick={onRetry} data-testid="run-created-retry">
                  Try again
                </Button>
              )}
            </Stack>
          </Alert>
        )}

        {error && (
          <Alert
            color={state === 'stopped' ? 'yellow' : 'red'}
            variant="light"
            icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
            title={state === 'stopped' ? 'No longer following the ingestion' : undefined}
            data-testid="run-created-error"
          >
            {error}
          </Alert>
        )}

        <ScrollWithHint mah="calc(100dvh - 300px)">
          <Stack gap="sm" pb="xl">
            <SourceSection
              icon="mdi:folder-check-outline"
              title="Run folder"
              summary={progress ? summarizeRun(progress) : report ? 'Waiting for the first results' : 'Not started yet'}
              testId="run-created-section-run"
            >
              {progress ? (
                <IngestionResultTable
                  rows={progress.refreshed}
                  rowTestIdPrefix="run-progress"
                  emptyText="The ingestion run reported no collection yet."
                  testId="run-progress-results"
                />
              ) : (
                <Text size="sm" c="dimmed">
                  Nothing to show yet.
                </Text>
              )}
            </SourceSection>

            {files.length > 0 && (
              <SourceSection
                icon="mdi:tray-arrow-up"
                title="Files you dropped"
                summary={filesSummary}
                testId="run-created-section-files"
              >
                <FileUploadResults files={files} uploads={uploads} testIdPrefix="run-created-file" />
              </SourceSection>
            )}

            {report?.project_id && (
              <LinkSuggestions
                projectId={report.project_id}
                uploads={uploads}
                ready={
                  uploads.length === files.length && (finishedAt != null || !report.run_id)
                }
                testId="run-created-section-links"
              />
            )}

            {report && (
              <SourceSection
                icon="mdi:text-box-search-outline"
                title="Details of the project"
                summary={`${plural(report.dashboards.filter((d) => d.success).length, 'dashboard')} imported`}
                testId="run-created-section-details"
              >
                <Stack gap="md">
                  <Text size="sm" data-testid="run-created-summary">
                    {createdText(report)}
                  </Text>
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
                  <RunPreview
                    report={report}
                    templateTitle={context?.templateTitle ?? null}
                    detection={context?.detection ?? null}
                  />
                </Stack>
              </SourceSection>
            )}
          </Stack>
        </ScrollWithHint>

        <Stack gap={4}>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onClose} data-testid="run-created-stay">
              Stay on projects
            </Button>
            <GatedButton
              color={accent.secondary}
              leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
              reason={dashboardReason}
              onClick={() => {
                if (dashboardId) window.location.assign(`/dashboard/${dashboardId}`);
              }}
              data-testid="run-created-open-dashboard"
            >
              Open dashboard
            </GatedButton>
          </Group>
          {dashboardReason && !createError && (
            <Group justify="flex-end">
              <DisabledReason reason={dashboardReason} icon="mdi:information-outline" />
            </Group>
          )}
          {!dashboardReason && state === 'running' && (
            <Text size="xs" c="dimmed" ta="right" data-testid="run-created-dashboard-hint">
              Ingestion is still running: the dashboard fills in as collections finish.
            </Text>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
};
