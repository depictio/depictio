/**
 * Rendering for the "From a run folder" flow: the dry-run plan shown on the
 * Preview step, and the post-create modal that watches the ingestion the
 * server kicked off.
 *
 * These live outside `CreateProjectModal` because the created-modal is
 * rendered by `ProjectsApp` (the create modal is already closed by then) and
 * because the preview table is the screen this whole flow exists for: it is
 * where a data root set one level too high becomes visible.
 */

import React, { useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { useBrandAccents } from 'depictio-react-core';
import type {
  FromRunDCPreview,
  FromRunReport,
  ManifestRefreshReport,
} from 'depictio-react-core';

import {
  MANIFEST_RUN_STATUS_META,
  formatElapsed,
  summarizeManifestRun,
  useElapsedMs,
  useManifestRunPoll,
} from './manifestRun';

/** Visual treatment per resolved-collection status. Colors are Mantine
 *  palette names (theme tokens), not literals. `pruned` is dimmed rather
 *  than coloured: a template conditional dropped the collection on purpose,
 *  so it is neither good news nor bad. */
const FROM_RUN_STATUS_META: Record<
  FromRunDCPreview['status'],
  { color: string; icon: string; label: string; dim?: boolean }
> = {
  ok: { color: 'green', icon: 'mdi:check-circle', label: 'OK' },
  empty: { color: 'gray', icon: 'mdi:tray-remove', label: 'Empty' },
  missing: { color: 'red', icon: 'mdi:file-remove-outline', label: 'Missing' },
  pruned: { color: 'gray', icon: 'mdi:minus-circle-outline', label: 'Pruned', dim: true },
};

/** How many collections found something, out of the ones that were looked
 *  for. Pruned collections are excluded from both counts: the template chose
 *  to drop them, so they say nothing about whether the data root is right. */
export function fromRunMatchTotals(report: FromRunReport): {
  matched: number;
  considered: number;
} {
  const considered = report.data_collections.filter((dc) => dc.status !== 'pruned');
  return {
    matched: considered.filter((dc) => dc.matched > 0).length,
    considered: considered.length,
  };
}

/** True when nothing at all was found under the data root. Almost always a
 *  prefix one level too high or too low, which is why Create is blocked on
 *  it rather than left to fail halfway through ingestion. */
export function fromRunFoundNothing(report: FromRunReport): boolean {
  const { matched, considered } = fromRunMatchTotals(report);
  return considered === 0 || matched === 0;
}

/** Paths the server looked for and did not find, verbatim and wrapped rather
 *  than truncated: with every row at 0 these are the only thing on the screen
 *  that says which directory level the data root is off by. */
const MissingSources: React.FC<{ dc: FromRunDCPreview }> = ({ dc }) => (
  <Table.Tr data-testid={`run-missing-sources-${dc.data_collection_tag}`}>
    <Table.Td colSpan={5} style={{ paddingTop: 0 }}>
      <Stack gap={2}>
        <Text size="xs" c="dimmed">
          Looked for, not found:
        </Text>
        {dc.missing_sources.map((source) => (
          <Text
            key={source}
            size="xs"
            ff="monospace"
            c="red"
            style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
          >
            {source}
          </Text>
        ))}
      </Stack>
    </Table.Td>
  </Table.Tr>
);

/** The dry-run plan: what each data collection of the template resolved to
 *  under the given data root. Also renders the real report after creation,
 *  where the dashboards that failed to import are listed as well. */
export const FromRunPreviewReport: React.FC<{ report: FromRunReport }> = ({ report }) => {
  const accent = useBrandAccents();
  const { matched, considered } = fromRunMatchTotals(report);
  const failedDashboards = report.dashboards.filter((d) => !d.success);
  const variables = Object.entries(report.resolved_variables ?? {});

  return (
    <Stack gap="sm" data-testid="run-preview-report">
      <Group gap="xs" wrap="wrap">
        <Badge variant="light" color={accent.secondary} radius="sm">
          {report.project_name}
        </Badge>
        <Badge variant="light" color="gray" radius="sm">
          {report.template_id}
        </Badge>
        <Badge
          variant="light"
          color={matched === 0 ? 'red' : matched < considered ? 'yellow' : 'green'}
          radius="sm"
          data-testid="run-match-summary"
        >
          {matched} of {considered} collection{considered === 1 ? '' : 's'} matched
        </Badge>
      </Group>

      <Text
        size="xs"
        c="dimmed"
        ff="monospace"
        style={{ wordBreak: 'break-all' }}
        data-testid="run-preview-data-root"
      >
        {report.data_root}
      </Text>

      {report.truncated && (
        <Alert
          color="yellow"
          variant="light"
          icon={<Icon icon="mdi:information-outline" width={16} />}
          data-testid="run-truncated-warning"
        >
          <Text size="sm">
            The listing was cut short, so every file count below is a lower bound.
            More files will be picked up at ingestion.
          </Text>
        </Alert>
      )}

      <Table verticalSpacing="xs" striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Data collection</Table.Th>
            <Table.Th>Kind</Table.Th>
            <Table.Th>Mode</Table.Th>
            <Table.Th>Files</Table.Th>
            <Table.Th>Status</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {report.data_collections.map((dc) => {
            const meta = FROM_RUN_STATUS_META[dc.status] ?? FROM_RUN_STATUS_META.missing;
            return (
              <React.Fragment key={dc.data_collection_tag}>
                <Table.Tr
                  data-testid={`run-preview-row-${dc.data_collection_tag}`}
                  data-status={dc.status}
                  style={meta.dim ? { opacity: 0.6 } : undefined}
                >
                  <Table.Td>
                    <Stack gap={0}>
                      <Group gap={6} wrap="nowrap">
                        <Text size="sm" fw={600}>
                          {dc.data_collection_tag}
                        </Text>
                        {dc.optional && (
                          <Badge variant="outline" color="gray" size="xs" radius="sm">
                            optional
                          </Badge>
                        )}
                      </Group>
                      <Text
                        size="xs"
                        c="dimmed"
                        ff="monospace"
                        style={{ wordBreak: 'break-all' }}
                      >
                        {dc.location}
                      </Text>
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{dc.kind}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" c={dc.mode ? undefined : 'dimmed'}>
                      {dc.mode ?? 'n/a'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" fw={dc.matched > 0 ? 600 : 400}>
                      {dc.matched}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge
                      variant="light"
                      color={meta.color}
                      size="sm"
                      leftSection={<Icon icon={meta.icon} width={12} />}
                    >
                      {meta.label}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
                {dc.missing_sources.length > 0 && <MissingSources dc={dc} />}
              </React.Fragment>
            );
          })}
        </Table.Tbody>
      </Table>

      {report.detected_runs.length > 0 && (
        <Group gap="xs" wrap="wrap">
          <Text size="xs" c="dimmed">
            Detected runs:
          </Text>
          {report.detected_runs.map((run) => (
            <Badge key={run} variant="light" color="gray" size="sm" radius="sm">
              {run}
            </Badge>
          ))}
        </Group>
      )}

      {variables.length > 0 && (
        <Stack gap={2} data-testid="run-resolved-variables">
          <Text size="xs" c="dimmed">
            Resolved variables:
          </Text>
          {variables.map(([key, value]) => (
            <Text key={key} size="xs" ff="monospace" style={{ wordBreak: 'break-all' }}>
              {key} = {value}
            </Text>
          ))}
        </Stack>
      )}

      {report.pruned_optional_dcs.length > 0 && (
        <Group gap="xs" wrap="wrap">
          <Text size="xs" c="dimmed">
            Skipped optional collections:
          </Text>
          {report.pruned_optional_dcs.map((tag) => (
            <Badge key={tag} variant="light" color="gray" size="sm" radius="sm">
              {tag}
            </Badge>
          ))}
        </Group>
      )}

      {failedDashboards.length > 0 && (
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            Dashboards that failed to import:
          </Text>
          {failedDashboards.map((d) => (
            <Group key={d.path} gap="xs" wrap="nowrap">
              <Badge variant="light" color="red" size="sm" radius="sm">
                {d.title || d.path}
              </Badge>
              {d.error && (
                <Text size="xs" c="red">
                  {d.error}
                </Text>
              )}
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

type WatchState = 'idle' | 'running' | 'success' | 'failed';

/** Post-creation modal for a from-run project.
 *
 *  Unlike the from-manifest flow, the endpoint answers as soon as the project
 *  and its dashboards exist and hands back a `run_id`: the collections are
 *  still ingesting on the workers. So the user is never redirected: they
 *  watch the run here and open the dashboard when they are ready. Closing
 *  this only stops watching; the run carries on server-side and the project's
 *  Ingestion tab shows the outcome. */
export const FromRunCreatedModal: React.FC<{
  report: FromRunReport | null;
  onClose: () => void;
}> = ({ report, onClose }) => {
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
              &ldquo;{report.project_name}&rdquo; exists and its dashboards are
              imported. The data collections are being ingested in the background;
              closing this only stops watching.
            </Text>
          </Alert>

          <Group gap="xs" wrap="nowrap">
            {state === 'running' && <Loader size="xs" color={accent.secondary} />}
            {state === 'success' && (
              <Icon icon="mdi:check-circle" width={16} color="var(--mantine-color-green-6)" />
            )}
            {state === 'failed' && (
              <Icon icon="mdi:alert-circle" width={16} color="var(--mantine-color-red-6)" />
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

          {error && (
            <Alert
              color="red"
              variant="light"
              icon={<Icon icon="mdi:alert-circle" width={16} />}
              data-testid="run-created-error"
            >
              {error}
            </Alert>
          )}

          {progress && progress.refreshed.length > 0 && (
            <Table verticalSpacing="xs" striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Data collection</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Entries</Table.Th>
                  <Table.Th>Message</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {progress.refreshed.map((entry) => {
                  const meta =
                    MANIFEST_RUN_STATUS_META[entry.status] ?? MANIFEST_RUN_STATUS_META.failed;
                  return (
                    <Table.Tr
                      key={entry.data_collection_tag}
                      data-testid={`run-progress-row-${entry.data_collection_tag}`}
                      data-status={entry.status}
                    >
                      <Table.Td>
                        <Text size="sm" fw={600}>
                          {entry.data_collection_tag}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge
                          variant="light"
                          color={meta.color}
                          size="sm"
                          leftSection={<Icon icon={meta.icon} width={12} />}
                        >
                          {meta.label}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{entry.entries}</Text>
                      </Table.Td>
                      <Table.Td>
                        {entry.message && (
                          <Text size="xs" c={entry.status === 'failed' ? 'red' : 'dimmed'}>
                            {entry.message}
                          </Text>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          )}

          <FromRunPreviewReport report={report} />

          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onClose} data-testid="run-created-stay">
              Stay on projects
            </Button>
            <Button
              color={accent.secondary}
              leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
              disabled={!dashboardId}
              title={
                dashboardId
                  ? state === 'running'
                    ? 'Ingestion is still running; the dashboard fills in as collections finish'
                    : undefined
                  : 'No dashboard was imported for this project'
              }
              onClick={() => {
                if (dashboardId) window.location.assign(`/dashboard/${dashboardId}`);
              }}
              data-testid="run-created-open-dashboard"
            >
              Open dashboard
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
};
