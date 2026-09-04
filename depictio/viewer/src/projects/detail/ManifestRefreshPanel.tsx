import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Paper,
  Select,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { getManifestRefreshRun, refreshManifest, useBrandAccents } from 'depictio-react-core';
import type {
  ManifestRefreshReport,
  ManifestRefreshStatus,
} from 'depictio-react-core';

import { useCurrentUser } from '../../hooks/useCurrentUser';

/** The slice of a project data collection this panel reads: its tag and the
 *  raw `config` bag, where `scan.mode === "manifest"` marks it as
 *  manifest-backed. */
export interface ManifestRefreshDc {
  data_collection_tag?: string;
  config?: Record<string, unknown>;
}

interface ManifestRefreshPanelProps {
  projectId: string;
  /** Owners, editors and admins may refresh (same gate as the DC actions). */
  canMutate: boolean;
  dataCollections: ReadonlyArray<ManifestRefreshDc>;
  /** Reload the project document so the delta locations and aggregation
   *  times reflect the refresh. Offered as a button rather than called
   *  automatically: the parent's reload remounts this panel, which would
   *  wipe the per-collection report the user is looking at. */
  onReloadProject?: () => void;
}

const POLL_INTERVAL_MS = 2_000;
/** Give up polling after this long; the run keeps going server-side. */
const MAX_POLL_MS = 30 * 60 * 1_000;
/** Transient poll failures tolerated before the panel stops and reports. */
const MAX_CONSECUTIVE_POLL_ERRORS = 3;

/** Visual treatment per refresh status. Colors are Mantine palette names
 *  (theme tokens), not literals, mirroring IngestionReportPanel. */
const STATUS_META: Record<
  ManifestRefreshStatus,
  { color: string; icon: string; label: string }
> = {
  ingested: { color: 'green', icon: 'mdi:check-circle', label: 'Ingested' },
  planned: { color: 'blue', icon: 'mdi:clock-outline', label: 'Planned' },
  dispatched: { color: 'blue', icon: 'mdi:tray-arrow-down', label: 'Queued' },
  running: { color: 'blue', icon: 'mdi:progress-clock', label: 'Running' },
  failed: { color: 'red', icon: 'mdi:alert-circle', label: 'Failed' },
};

/** Scan modes whose source the server reads over the network, so it can always
 *  read it again. A local source depends on whether the data root is mounted in
 *  the API container, which only the server can know, so those are left out
 *  here: a server that does have the mount still accepts them on the API. */
const REMOTE_SCAN_MODES = new Set(['manifest', 'url', 's3_prefix']);

/** Tags of the collections the server can re-read, and so re-ingest. */
function refreshableTagsOf(dcs: ReadonlyArray<ManifestRefreshDc>): string[] {
  const tags: string[] = [];
  for (const dc of dcs) {
    const scan = dc.config?.scan as { mode?: unknown } | undefined;
    const mode = typeof scan?.mode === 'string' ? scan.mode.toLowerCase() : '';
    if (REMOTE_SCAN_MODES.has(mode) && dc.data_collection_tag) {
      tags.push(dc.data_collection_tag);
    }
  }
  return tags;
}

/** A report is final once no row is still queued for, or running on, a
 *  worker. The poll endpoint has no run-level status field, so this is the
 *  only terminal signal a client gets. */
function isTerminal(report: ManifestRefreshReport): boolean {
  return report.refreshed.every(
    (entry) => entry.status !== 'dispatched' && entry.status !== 'running',
  );
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1_000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/** "3 ingested, 1 failed" style summary of the per-collection statuses. */
function summarize(report: ManifestRefreshReport): string {
  const counts = new Map<ManifestRefreshStatus, number>();
  for (const entry of report.refreshed) {
    counts.set(entry.status, (counts.get(entry.status) ?? 0) + 1);
  }
  const parts: string[] = [];
  (Object.keys(STATUS_META) as ManifestRefreshStatus[]).forEach((status) => {
    const n = counts.get(status);
    if (n) parts.push(`${n} ${STATUS_META[status].label.toLowerCase()}`);
  });
  return parts.length > 0 ? parts.join(', ') : 'no collections refreshed';
}

type PanelState = 'idle' | 'starting' | 'running' | 'success' | 'failed';

/** "Refresh from manifest" for projects with manifest-backed collections.
 *  Dispatches the refresh to the workers and polls the run until every
 *  collection is either ingested or failed, showing the rows live. */
const ManifestRefreshPanel: React.FC<ManifestRefreshPanelProps> = ({
  projectId,
  canMutate,
  dataCollections,
  onReloadProject,
}) => {
  const accent = useBrandAccents();
  const { user, isPublicMode } = useCurrentUser();

  const refreshableTags = useMemo(() => refreshableTagsOf(dataCollections), [dataCollections]);

  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [report, setReport] = useState<ManifestRefreshReport | null>(null);
  /** Run being polled; null while nothing is in flight. */
  const [runId, setRunId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);

  // Poll the run every POLL_INTERVAL_MS until it is terminal, the deadline
  // passes, or the poll itself keeps failing. Cleanup cancels the pending
  // timer and drops any response that lands after unmount or a new run.
  useEffect(() => {
    if (!runId || startedAt == null) return;
    let cancelled = false;
    let timer: number | undefined;
    let consecutiveErrors = 0;
    const stop = () => {
      setRunId(null);
      setFinishedAt(Date.now());
    };
    const tick = async () => {
      let next: ManifestRefreshReport | null = null;
      try {
        next = await getManifestRefreshRun(runId);
        consecutiveErrors = 0;
      } catch (err) {
        if (cancelled) return;
        consecutiveErrors += 1;
        if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          setError(
            `Lost track of the refresh run: ${(err as Error).message}. ` +
              'The workers keep going; the Ingestion tab shows the outcome.',
          );
          stop();
          return;
        }
      }
      if (cancelled) return;
      if (next) {
        setReport(next);
        if (isTerminal(next)) {
          stop();
          return;
        }
      }
      if (Date.now() - startedAt >= MAX_POLL_MS) {
        setError(
          'Stopped polling after 30 minutes. The refresh may still be running; ' +
            'the Ingestion tab shows the outcome.',
        );
        stop();
        return;
      }
      timer = window.setTimeout(tick, POLL_INTERVAL_MS);
    };
    timer = window.setTimeout(tick, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [runId, startedAt]);

  // One-second ticker for the elapsed-time display while a run is in flight.
  useEffect(() => {
    if (!runId) return;
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [runId]);

  // Drop a selection that no longer matches a refreshable collection (the DC
  // may have been renamed or deleted since it was picked).
  useEffect(() => {
    if (selectedTag && !refreshableTags.includes(selectedTag)) setSelectedTag(null);
  }, [refreshableTags, selectedTag]);

  const handleRefresh = async () => {
    const started = Date.now();
    setSubmitting(true);
    setError(null);
    setReport(null);
    setRunId(null);
    setFinishedAt(null);
    setStartedAt(started);
    setNow(started);
    try {
      const first = await refreshManifest({
        projectId,
        dataCollectionTag: selectedTag,
        asyncRun: true,
      });
      setReport(first);
      // No run_id means the backend answered synchronously, and a run whose
      // rows are all final already (every collection failed pre-flight) has
      // nothing left to poll.
      if (first.run_id && !isTerminal(first)) {
        setRunId(first.run_id);
      } else {
        setFinishedAt(Date.now());
      }
    } catch (err) {
      setError((err as Error).message || 'Failed to refresh from manifest.');
      setFinishedAt(Date.now());
    } finally {
      setSubmitting(false);
    }
  };

  // Disabled, never hidden: the affordance stays discoverable and the reason
  // is spelled out (same rule as the storage panel and the DC actions).
  const publicGate = isPublicMode && !user?.is_admin;
  const disabledReason = !canMutate
    ? 'Owner permission required'
    : refreshableTags.length === 0
      ? 'No data collection has a source this server can re-read'
      : publicGate
        ? 'Refresh is disabled in public/demo mode for non-admin users'
        : null;

  const inFlight = submitting || Boolean(runId);
  const state: PanelState = submitting
    ? 'starting'
    : runId
      ? 'running'
      : report && finishedAt != null
        ? report.success
          ? 'success'
          : 'failed'
        : error
          ? 'failed'
          : 'idle';
  const elapsedMs = startedAt == null ? 0 : (finishedAt ?? now) - startedAt;

  return (
    <Paper withBorder radius="md" p="sm" data-testid="manifest-refresh-panel">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Group gap="xs" wrap="nowrap">
          <Icon
            icon="mdi:file-sync-outline"
            width={20}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Title order={4}>Refresh data</Title>
          <Badge variant="light" size="sm" color="gray">
            {refreshableTags.length} refreshable collection
            {refreshableTags.length === 1 ? '' : 's'}
          </Badge>
        </Group>
        <Group gap="xs" wrap="nowrap">
          {refreshableTags.length > 1 && (
            <Select
              size="xs"
              w={220}
              placeholder="All refreshable collections"
              aria-label="Collection to refresh"
              data={refreshableTags}
              value={selectedTag}
              onChange={setSelectedTag}
              clearable
              disabled={inFlight || Boolean(disabledReason)}
              data-testid="manifest-refresh-dc-select"
            />
          )}
          <Button
            size="xs"
            data-testid="manifest-refresh-button"
            leftSection={<Icon icon="mdi:refresh" width={14} />}
            onClick={handleRefresh}
            loading={inFlight}
            disabled={Boolean(disabledReason) || inFlight}
            title={disabledReason ?? undefined}
          >
            Refresh from manifest
          </Button>
        </Group>
      </Group>

      <Text size="sm" c="dimmed" pt="xs">
        Re-fetch the stored manifest of each manifest-backed collection and rebuild
        its table from the entries it lists now. A collection whose type vanished
        from the manifest is reported failed and left untouched.
        {disabledReason && ` ${disabledReason}.`}
      </Text>

      {state !== 'idle' && (
        <Group gap="xs" pt="sm" wrap="nowrap">
          {(state === 'starting' || state === 'running') && (
            <Loader size="xs" color={accent.secondary} />
          )}
          {state === 'success' && (
            <Icon
              icon="mdi:check-circle"
              width={16}
              color="var(--mantine-color-green-6)"
            />
          )}
          {state === 'failed' && (
            <Icon
              icon="mdi:alert-circle"
              width={16}
              color="var(--mantine-color-red-6)"
            />
          )}
          <Text size="sm" data-testid="manifest-refresh-status" data-state={state}>
            {state === 'starting' && 'Starting the refresh...'}
            {state === 'running' &&
              `Refreshing (${formatElapsed(elapsedMs)} elapsed)` +
                (report ? `: ${summarize(report)}` : '')}
            {state === 'success' &&
              report &&
              `Refresh completed in ${formatElapsed(elapsedMs)}: ${summarize(report)}`}
            {state === 'failed' &&
              (report
                ? `Refresh finished with errors in ${formatElapsed(elapsedMs)}: ${summarize(report)}`
                : 'Refresh failed')}
          </Text>
          {(state === 'success' || state === 'failed') && report && onReloadProject && (
            <Button size="compact-xs" variant="subtle" onClick={onReloadProject}>
              Reload project
            </Button>
          )}
        </Group>
      )}

      {error && (
        <Alert
          mt="sm"
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle" width={16} />}
          data-testid="manifest-refresh-error"
        >
          {error}
        </Alert>
      )}

      {report && report.refreshed.length > 0 && (
        <Table verticalSpacing="xs" mt="sm" striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Data collection</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Entries</Table.Th>
              <Table.Th>Message</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {report.refreshed.map((entry) => {
              const meta = STATUS_META[entry.status] ?? STATUS_META.failed;
              return (
                <Table.Tr
                  key={entry.data_collection_tag}
                  data-testid={`manifest-refresh-row-${entry.data_collection_tag}`}
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
    </Paper>
  );
};

export default ManifestRefreshPanel;
