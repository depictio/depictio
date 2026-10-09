import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  ThemeIcon,
  VisuallyHidden,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { getManifestRefreshRun, refreshManifest, Z_LAYERS } from 'depictio-react-core';
import type { ManifestRefreshReport, ManifestRefreshStatus } from 'depictio-react-core';

import { DisabledReason, Field, GatedButton } from '../../components/settings/SettingsSections';
import IngestionResultTable, { INGESTION_STATUS_META } from '../IngestionResultTable';

/** The slice of a project data collection this panel reads: its tag and the
 *  raw `config` bag, whose `scan.mode` says whether the server can re-read the
 *  collection's source. */
export interface ManifestRefreshDc {
  data_collection_tag?: string;
  config?: Record<string, unknown>;
}

const POLL_INTERVAL_MS = 2_000;
/** Give up polling after this long; the run keeps going server-side. */
const MAX_POLL_MS = 30 * 60 * 1_000;
/** Transient poll failures tolerated before the panel stops and reports. */
const MAX_CONSECUTIVE_POLL_ERRORS = 3;

/** Order of the statuses in the "3 ingested, 1 failed" summary. */
const SUMMARY_ORDER: ManifestRefreshStatus[] = [
  'ingested',
  'planned',
  'dispatched',
  'running',
  'failed',
];

const EDITORS_ONLY = 'Only project owners and editors can refresh the data.';

/** Scan modes whose source the server reads over the network, so it can read
 *  it again. The server never re-reads a local path on a user's behalf: data
 *  ingested from a local folder is refreshed with the CLI. */
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

/** Outcome of a terminal report, read from its rows rather than from
 *  `report.success`: a poll that lands between the worker's last step write
 *  and the run's finalization sees every row final while `success` is still
 *  false. */
function hasFailedRow(report: ManifestRefreshReport): boolean {
  return report.refreshed.some((entry) => entry.status === 'failed');
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1_000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/** "3 ingested, 1 failed" style summary of the per-collection statuses. */
export function summarizeRefresh(report: ManifestRefreshReport): string {
  const counts = new Map<ManifestRefreshStatus, number>();
  for (const entry of report.refreshed) {
    counts.set(entry.status, (counts.get(entry.status) ?? 0) + 1);
  }
  const parts: string[] = [];
  for (const status of SUMMARY_ORDER) {
    const n = counts.get(status);
    if (n) parts.push(`${n} ${INGESTION_STATUS_META[status].label.toLowerCase()}`);
  }
  return parts.length > 0 ? parts.join(', ') : 'no collections refreshed';
}

/** `stopped` is neither an outcome nor a failure: the page stopped polling
 *  (the poll kept failing, or the run outlasted MAX_POLL_MS) while rows were
 *  still queued or running, and the run may well go on server-side. */
export type RefreshState = 'idle' | 'starting' | 'running' | 'success' | 'failed' | 'stopped';

/** States in which a run has ended, as far as this page knows. */
export function isRefreshEnded(state: RefreshState): boolean {
  return state === 'success' || state === 'failed' || state === 'stopped';
}

/** Everything the Data refresh section shows, held by `useManifestRefresh`
 *  above the dialog so a run keeps being followed while the reader switches
 *  sections or closes the dialog. */
export interface ManifestRefreshController {
  refreshableTags: string[];
  selectedTag: string | null;
  setSelectedTag: (tag: string | null) => void;
  report: ManifestRefreshReport | null;
  error: string | null;
  state: RefreshState;
  startedAt: number | null;
  finishedAt: number | null;
  start: () => void;
}

/**
 * Dispatches a refresh of the collections whose source the server can read
 * again, then polls the run until every collection is either ingested or
 * failed. Call it where it outlives the dialog body (the dialog remounts its
 * page on every open and shows one section at a time).
 */
export function useManifestRefresh(
  projectId: string,
  dataCollections: ReadonlyArray<ManifestRefreshDc>,
): ManifestRefreshController {
  const refreshableTags = useMemo(() => refreshableTagsOf(dataCollections), [dataCollections]);

  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [report, setReport] = useState<ManifestRefreshReport | null>(null);
  /** Run being polled; null while nothing is in flight. */
  const [runId, setRunId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
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
          'Stopped following the refresh after 30 minutes. It may still be running; ' +
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

  // Drop a selection that no longer matches a refreshable collection (the DC
  // may have been renamed or deleted since it was picked).
  useEffect(() => {
    if (selectedTag && !refreshableTags.includes(selectedTag)) setSelectedTag(null);
  }, [refreshableTags, selectedTag]);

  const run = async () => {
    const started = Date.now();
    setSubmitting(true);
    setError(null);
    setReport(null);
    setRunId(null);
    setFinishedAt(null);
    setStartedAt(started);
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
      setError((err as Error).message || 'The refresh did not start.');
      setFinishedAt(Date.now());
    } finally {
      setSubmitting(false);
    }
  };

  // Polling only stops with rows still in flight when the page lost track of
  // the run or gave up waiting: that is `stopped`, not an outcome.
  const state: RefreshState = submitting
    ? 'starting'
    : runId
      ? 'running'
      : report && finishedAt != null
        ? !isTerminal(report)
          ? 'stopped'
          : hasFailedRow(report)
            ? 'failed'
            : 'success'
        : error
          ? 'failed'
          : 'idle';

  return {
    refreshableTags,
    selectedTag,
    setSelectedTag,
    report,
    error,
    state,
    startedAt,
    finishedAt,
    start: () => void run(),
  };
}

/** Words for the run as a whole once it has ended (`elapsed` is then fixed). */
function describeEndedRefresh(
  state: RefreshState,
  summary: string | null,
  elapsed: string,
): string {
  if (state === 'success') return `Refresh completed in ${elapsed}: ${summary ?? ''}`;
  if (state === 'stopped') {
    return `Stopped following the refresh after ${elapsed}${
      summary ? `. Last seen: ${summary}` : ''
    }`;
  }
  return summary
    ? `Refresh finished with errors in ${elapsed}: ${summary}`
    : 'The refresh failed';
}

/** What a screen reader hears, in a live region: each state change and the
 *  final summary, never the ticking elapsed time nor every row update. */
function announceRefresh(
  state: RefreshState,
  report: ManifestRefreshReport | null,
  startedAt: number | null,
  finishedAt: number | null,
): string {
  if (state === 'idle') return '';
  if (state === 'starting') return 'Starting the refresh.';
  if (state === 'running') return 'The refresh is running.';
  const elapsed = formatElapsed(
    startedAt == null || finishedAt == null ? 0 : finishedAt - startedAt,
  );
  return describeEndedRefresh(state, report ? summarizeRefresh(report) : null, elapsed);
}

/** Icon per ended state. `stopped` reads as a caution, not as a failure. */
const ENDED_ICON: Record<'success' | 'failed' | 'stopped', { color: string; icon: string }> = {
  success: { color: 'green', icon: 'mdi:check-circle' },
  failed: { color: 'red', icon: 'mdi:alert-circle' },
  stopped: { color: 'yellow', icon: 'mdi:eye-off-outline' },
};

/** Icon, colour and words for the run as a whole, plus the elapsed time,
 *  ticking once a second while the run is in flight. Not a live region: the
 *  panel announces state changes separately (`announceRefresh`). */
const RefreshStatusLine: React.FC<{
  state: RefreshState;
  report: ManifestRefreshReport | null;
  startedAt: number | null;
  finishedAt: number | null;
}> = ({ state, report, startedAt, finishedAt }) => {
  const live = state === 'starting' || state === 'running';
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    setNow(Date.now());
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, [live]);

  if (state === 'idle') return null;
  const elapsed = formatElapsed(startedAt == null ? 0 : (finishedAt ?? now) - startedAt);
  const summary = report ? summarizeRefresh(report) : null;
  let text: string;
  if (state === 'starting') text = 'Starting the refresh...';
  else if (state === 'running') {
    text = `Refreshing (${elapsed} elapsed)${summary ? `: ${summary}` : ''}`;
  } else text = describeEndedRefresh(state, summary, elapsed);
  const ended =
    state === 'success' || state === 'failed' || state === 'stopped' ? ENDED_ICON[state] : null;

  return (
    <Group gap="xs" wrap="nowrap">
      {ended ? (
        <ThemeIcon variant="light" size="sm" radius="xl" color={ended.color}>
          <Icon icon={ended.icon} width={14} />
        </ThemeIcon>
      ) : (
        <Loader size="xs" />
      )}
      <Text size="sm" data-testid="manifest-refresh-status" data-state={state}>
        {text}
      </Text>
    </Group>
  );
};

interface ManifestRefreshPanelProps {
  refresh: ManifestRefreshController;
  /** Owners, editors and admins may refresh (same gate as the DC actions). */
  canMutate: boolean;
  /** Why the reader may not refresh on this deployment (public/demo mode for
   *  non-admins, or still unknown while it loads); null otherwise. */
  publicModeReason: string | null;
  /** Reload the project document so the delta locations and aggregation
   *  times on the page reflect the refresh. */
  onReloadProject?: () => void;
}

/** The Data refresh section of the project settings: pick the collections to
 *  re-read, start the refresh, and follow it row by row. */
const ManifestRefreshPanel: React.FC<ManifestRefreshPanelProps> = ({
  refresh,
  canMutate,
  publicModeReason,
  onReloadProject,
}) => {
  const { refreshableTags, selectedTag, setSelectedTag, report, error, state } = refresh;
  const inFlight = state === 'starting' || state === 'running';
  const empty = refreshableTags.length === 0;

  // Disabled, never hidden: the affordance stays discoverable and the reason
  // is spelled out (same rule as the storage section and the DC actions).
  const gateReason = publicModeReason ?? (canMutate ? null : EDITORS_ONLY);
  // The empty state below already says why there is nothing to refresh, so
  // that reason goes to the tooltip only.
  const disabledReason =
    gateReason ?? (empty ? 'No data collection here has a source the server can re-read.' : null);

  return (
    <Stack gap="lg" data-testid="manifest-refresh-panel">
      <Text size="sm" c="dimmed">
        Re-read each refreshable collection from its own source and rebuild its table: a
        manifest is fetched again and the entries it lists now are used, a URL or a prefix is
        read again. A collection whose source no longer yields its type is reported failed and
        left untouched.
      </Text>

      {empty ? (
        <Group gap="sm" wrap="nowrap" align="flex-start" data-testid="manifest-refresh-empty">
          <ThemeIcon variant="light" color="gray" size="lg" radius="md">
            <Icon icon="mdi:sync-off" width={20} />
          </ThemeIcon>
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text size="sm" fw={500}>
              Nothing to refresh
            </Text>
            <Text size="xs" c="dimmed" lh={1.35}>
              Refresh re-reads collections whose source is a manifest, a URL or a bucket
              prefix. This project has none: its collections were uploaded or read from
              local folders.
            </Text>
          </Stack>
        </Group>
      ) : (
        <Field
          label="Collections"
          description={
            refreshableTags.length === 1
              ? 'One collection can be re-read from its source.'
              : `${refreshableTags.length} collections can be re-read from their source. Refresh them all, or pick one.`
          }
        >
          {refreshableTags.length > 1 ? (
            <Select
              size="sm"
              maw={360}
              placeholder="All refreshable collections"
              aria-label="Collection to refresh"
              data={refreshableTags}
              value={selectedTag}
              onChange={setSelectedTag}
              clearable
              disabled={inFlight || Boolean(gateReason)}
              comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
              data-testid="manifest-refresh-dc-select"
            />
          ) : (
            <Text size="sm" ff="monospace">
              {refreshableTags[0]}
            </Text>
          )}
        </Field>
      )}

      <Stack gap={6}>
        <Group gap="xs">
          <GatedButton
            size="xs"
            data-testid="manifest-refresh-button"
            leftSection={<Icon icon="mdi:refresh" width={14} />}
            onClick={refresh.start}
            loading={inFlight}
            reason={disabledReason}
          >
            Refresh now
          </GatedButton>
          {isRefreshEnded(state) && report && onReloadProject && (
            <Button
              size="xs"
              variant="subtle"
              leftSection={<Icon icon="mdi:reload" width={14} />}
              onClick={onReloadProject}
              data-testid="manifest-refresh-reload"
            >
              Reload project
            </Button>
          )}
        </Group>
        <DisabledReason reason={gateReason} />
      </Stack>

      <RefreshStatusLine
        state={state}
        report={report}
        startedAt={refresh.startedAt}
        finishedAt={refresh.finishedAt}
      />
      <VisuallyHidden role="status" aria-live="polite">
        {announceRefresh(state, report, refresh.startedAt, refresh.finishedAt)}
      </VisuallyHidden>

      {error && (
        <Alert
          color={state === 'stopped' ? 'yellow' : 'red'}
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
          title={state === 'stopped' ? 'No longer following the refresh' : 'Refresh problem'}
          data-testid="manifest-refresh-error"
        >
          {error}
        </Alert>
      )}

      {report && (
        <IngestionResultTable
          rows={report.refreshed}
          rowTestIdPrefix="manifest-refresh"
          emptyText="The refresh reported no collection."
          testId="manifest-refresh-results"
        />
      )}
    </Stack>
  );
};

export default ManifestRefreshPanel;
