import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Box,
  Card,
  Code,
  CopyButton,
  Group,
  Loader,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';

import {
  fetchAppLogs,
  fetchIngestionRuns,
  fetchLogCaptureLevel,
  fetchMonitoringHealth,
  fetchMonitoringTasks,
  setLogCaptureLevel,
  useMonitoringEvents,
  type MonitoringAppLog,
  type MonitoringHealth,
  type MonitoringIngestionRun,
  type MonitoringIngestionStep,
  type MonitoringLiveEvent,
  type MonitoringTaskEvent,
} from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';
import {
  absTime,
  formatDuration,
  matchesQuery,
  relTime,
  spanMs,
  stepTally,
} from '../monitoring/format';
import {
  DetailBlock,
  Field,
  PaneHeader,
  PathTip,
  SearchInput,
  SectionLabel,
  TimeText,
} from '../monitoring/primitives';
import {
  ACCORDION_STYLES,
  CODE_STYLES,
  KIND_COLORS,
  LOG_LEVEL_COLORS,
  PANE_SCROLL_H,
  statusColor,
} from '../monitoring/tokens';
import { usePolling, useLivePolling } from '../monitoring/usePolling';
import { AgentsPane } from '../monitoring/AgentsPane';
import { IngestionStepTimeline } from '../monitoring/IngestionStepTimeline';
import { TriggerBadge } from '../monitoring/TriggerBadge';

/**
 * Admin > Monitoring ("Log & Task") tab.
 *
 * Five panes (Tasks / Ingestion / Agents / Logs / Health) over a small-font,
 * collapsible, badge-tagged UI. Data is the durable MongoDB ledger surfaced by
 * `/depictio/api/v1/monitoring/*`. Refreshes on an interval (toggleable), with
 * live push over the events WebSocket when enabled.
 *
 * The shared formatting helpers, visual tokens, primitives and polling hooks
 * live in `../monitoring/` so the project-scoped panels reuse them rather than
 * growing near-copies.
 *
 * Hidden in public/demo mode (no real admin surface) — the parent AdminApp
 * already gates on `is_admin`, and we additionally bail in those modes here.
 */

type Pane = 'tasks' | 'ingestion' | 'agents' | 'logs' | 'health';

// ── Tasks pane ────────────────────────────────────────────────────────────

const TasksPane: React.FC<{ liveSignal: number }> = ({ liveSignal }) => {
  const [auto, setAuto] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
  const [q, setQ] = useState('');
  // Controlled open rows: only the expanded item mounts its CodeHighlight blocks,
  // so a pane of 200 tasks doesn't run 200 syntax-highlight passes (which froze
  // the UI) on load and on every auto-refresh.
  const [open, setOpen] = useState<string[]>([]);
  const load = useCallback(
    () =>
      fetchMonitoringTasks({
        status: status || undefined,
        kind: kind || undefined,
        limit: 200,
      }),
    [status, kind],
  );
  const { data, loading, error, refresh } = usePolling<MonitoringTaskEvent[]>(load, auto, liveSignal);
  const tasks = (data ?? []).filter((t) =>
    matchesQuery(q, t.task_name, t.task_id, t.kind, t.status, t.worker, t.dashboard_id, t.dc_id, t.error),
  );

  return (
    <Stack gap="sm">
      <PaneHeader
        title="Celery tasks"
        loading={loading}
        auto={auto}
        onAuto={setAuto}
        onRefresh={() => void refresh()}
        extra={
          <Group gap="xs" wrap="nowrap">
            <SearchInput value={q} onChange={setQ} />
            <Select
              size="xs"
              placeholder="Status"
              clearable
              w={130}
              value={status}
              onChange={setStatus}
              data={['pending', 'started', 'success', 'failure', 'retry', 'revoked']}
            />
            <Select
              size="xs"
              placeholder="Kind"
              clearable
              w={140}
              value={kind}
              onChange={setKind}
              data={['figure', 'screenshot', 'multiqc', 'advanced_viz', 'deltatable', 'other']}
            />
          </Group>
        }
      />
      {error && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      )}
      {!loading && tasks.length === 0 && !error ? (
        <Text size="xs" c="dimmed">
          No task events recorded.
        </Text>
      ) : (
        <ScrollArea h={PANE_SCROLL_H} type="auto">
          <Accordion
            variant="contained"
            chevronPosition="left"
            multiple
            value={open}
            onChange={setOpen}
            styles={ACCORDION_STYLES}
          >
            {tasks.map((t) => (
            <Accordion.Item key={t.task_id} value={t.task_id}>
              <Accordion.Control>
                <Group gap="sm" wrap="nowrap">
                  <Box w={84} style={{ flexShrink: 0 }}>
                    <Badge size="xs" fullWidth color={statusColor(t.status)} variant="filled">
                      {t.status}
                    </Badge>
                  </Box>
                  <Box w={88} style={{ flexShrink: 0 }}>
                    <Badge
                      size="xs"
                      fullWidth
                      color={KIND_COLORS[t.kind] || 'gray'}
                      variant="light"
                    >
                      {t.kind}
                    </Badge>
                  </Box>
                  <Text
                    size="xs"
                    fw={500}
                    truncate
                    style={{ fontFamily: 'monospace', flex: 1, minWidth: 0 }}
                  >
                    {t.task_name || t.task_id}
                  </Text>
                  <Text size="xs" c="dimmed" w={60} ta="right" style={{ flexShrink: 0 }}>
                    {formatDuration(t.duration_ms)}
                  </Text>
                  <Box w={68} style={{ flexShrink: 0, textAlign: 'right' }}>
                    <TimeText iso={t.updated_at} />
                  </Box>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                {open.includes(t.task_id) && (
                <Stack gap={6}>
                  <Group gap="lg">
                    <Text size="xs" c="dimmed">
                      task_id: <Code>{t.task_id}</Code>
                    </Text>
                    {t.worker && (
                      <Text size="xs" c="dimmed">
                        worker: {t.worker}
                      </Text>
                    )}
                    {t.dashboard_id && (
                      <Text size="xs" c="dimmed">
                        dashboard: {t.dashboard_id}
                      </Text>
                    )}
                    {t.dc_id && (
                      <Text size="xs" c="dimmed">
                        dc: {t.dc_id}
                      </Text>
                    )}
                  </Group>
                  {t.args_repr && (
                    <DetailBlock label="Arguments">
                      <CodeHighlight
                        code={t.args_repr}
                        language="python"
                        copyLabel="Copy"
                        styles={CODE_STYLES}
                      />
                    </DetailBlock>
                  )}
                  {t.result_summary && (
                    <DetailBlock label="Result">
                      <CodeHighlight
                        code={t.result_summary}
                        language="python"
                        copyLabel="Copy"
                        styles={CODE_STYLES}
                      />
                    </DetailBlock>
                  )}
                  {t.error && (
                    <DetailBlock label="Error">
                      <Alert color="red" variant="light" p="xs">
                        <Text size="xs">{t.error}</Text>
                      </Alert>
                    </DetailBlock>
                  )}
                  {t.traceback && (
                    <DetailBlock label="Traceback">
                      <CodeHighlight
                        code={t.traceback}
                        language="text"
                        copyLabel="Copy"
                        styles={CODE_STYLES}
                      />
                    </DetailBlock>
                  )}
                  {t.logs && t.logs.length > 0 && (
                    <DetailBlock label="Logs">
                      <CodeHighlight
                        code={t.logs.join('\n')}
                        language="text"
                        copyLabel="Copy"
                        styles={CODE_STYLES}
                      />
                    </DetailBlock>
                  )}
                </Stack>
                )}
              </Accordion.Panel>
            </Accordion.Item>
          ))}
          </Accordion>
        </ScrollArea>
      )}
    </Stack>
  );
};

// ── Ingestion pane ──────────────────────────────────────────────────────────

/**
 * Apply a live ingestion event to the cached run list.
 *
 * Returns `null` to mean "I can't apply this" — no data yet, a different event
 * kind, or a run we've never seen (one that started after our last fetch).
 * `useLivePolling` turns that into a refetch, so an unknown run appears
 * promptly instead of being dropped.
 */
function applyIngestionEvent(
  current: MonitoringIngestionRun[] | null,
  event: MonitoringLiveEvent,
): MonitoringIngestionRun[] | null {
  if (event.event_type !== 'ingestion_event' || !current) return null;
  const payload = (event.payload ?? {}) as {
    run_id?: string;
    status?: string;
    current_step?: string | null;
    step?: MonitoringIngestionStep;
    progress?: MonitoringIngestionRun['progress'];
    counters?: Record<string, number>;
  };
  const runId = payload.run_id;
  if (!runId) return null;

  const index = current.findIndex((r) => r.run_id === runId);
  if (index === -1) return null;

  const run = current[index];
  // Upsert the step by name — the server keys them the same way, so a step
  // reported twice (start then finish) updates rather than duplicates.
  let steps = run.steps ?? [];
  if (payload.step) {
    const stepIndex = steps.findIndex((s) => s.name === payload.step!.name);
    steps =
      stepIndex === -1
        ? [...steps, payload.step]
        : steps.map((s, i) => (i === stepIndex ? payload.step! : s));
  }

  const updated: MonitoringIngestionRun = {
    ...run,
    steps,
    status: (payload.status as MonitoringIngestionRun['status']) ?? run.status,
    current_step: payload.current_step !== undefined ? payload.current_step : run.current_step,
    progress: payload.progress ?? run.progress,
    counters: payload.counters ?? run.counters,
  };
  const next = [...current];
  next[index] = updated;
  return next;
}

const IngestionPane: React.FC<{ lastEvent: MonitoringLiveEvent | null }> = ({ lastEvent }) => {
  const [auto, setAuto] = useState(true);
  const [q, setQ] = useState('');
  // Controlled open rows: only the expanded run mounts its field grid + steps
  // table, keeping a large run list light on load and on refresh.
  const [open, setOpen] = useState<string[]>([]);
  const load = useCallback(() => fetchIngestionRuns({ limit: 200 }), []);
  // Patch in place rather than refetch: a run emits one event per step, so
  // refetching 200 full runs each time would put this pane under continuous
  // load for the whole of a run — and a watcher never stops producing them.
  const { data, loading, error, refresh } = useLivePolling<
    MonitoringIngestionRun[],
    MonitoringLiveEvent
  >(load, auto, lastEvent, { patch: applyIngestionEvent });
  const runs = (data ?? []).filter((r) =>
    matchesQuery(
      q,
      r.project_name,
      r.project_id,
      r.command,
      r.cli_instance_label,
      r.cli_hostname,
      r.email,
      r.status,
      r.run_id,
    ),
  );

  return (
    <Stack gap="sm">
      <PaneHeader
        title="Ingestion runs"
        loading={loading}
        auto={auto}
        onAuto={setAuto}
        onRefresh={() => void refresh()}
        extra={<SearchInput value={q} onChange={setQ} />}
      />
      {error && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      )}
      {!loading && runs.length === 0 && !error ? (
        <Text size="xs" c="dimmed">
          No ingestion runs recorded.
        </Text>
      ) : (
        <ScrollArea h={PANE_SCROLL_H} type="auto">
          <Accordion
            variant="contained"
            chevronPosition="left"
            multiple
            value={open}
            onChange={setOpen}
            styles={ACCORDION_STYLES}
          >
            {runs.map((r) => (
            <Accordion.Item key={r.run_id} value={r.run_id}>
              <Accordion.Control>
                <Group gap="sm" wrap="nowrap">
                  <Box w={84} style={{ flexShrink: 0 }}>
                    <Badge
                      size="xs"
                      fullWidth
                      color={statusColor(r.status)}
                      variant="filled"
                      leftSection={
                        r.status === 'running' ? <Loader size={8} color="white" /> : undefined
                      }
                    >
                      {r.status}
                    </Badge>
                  </Box>
                  <Box w={44} style={{ flexShrink: 0 }}>
                    <Badge
                      size="xs"
                      fullWidth
                      color={r.source === 'ui' ? 'grape' : 'cyan'}
                      variant="light"
                    >
                      {r.source === 'ui' ? 'UI' : 'CLI'}
                    </Badge>
                  </Box>
                  <Box w={130} style={{ flexShrink: 0 }}>
                    <Badge size="xs" fullWidth color="blue" variant="outline">
                      {r.cli_instance_label || r.cli_hostname || 'unknown'}
                    </Badge>
                  </Box>
                  <Text
                    size="xs"
                    fw={500}
                    truncate
                    style={{ flex: 1, minWidth: 0 }}
                  >
                    {r.project_name || r.project_id || r.command}
                  </Text>
                  <Text size="xs" c="dimmed" truncate w={150} style={{ flexShrink: 0 }}>
                    {r.email || '—'}
                  </Text>
                  <Box w={68} style={{ flexShrink: 0, textAlign: 'right' }}>
                    <TimeText iso={r.started_at} />
                  </Box>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                {open.includes(r.run_id) && (
                <Stack gap="sm">
                  <SimpleGrid cols={{ base: 2, xs: 3, sm: 4 }} spacing="md" verticalSpacing="xs">
                    <Field label="Project">{r.project_name || '—'}</Field>
                    <Field label="User">{r.email || '—'}</Field>
                    <Field label="Source">{r.source === 'ui' ? 'UI upload' : 'CLI'}</Field>
                    <Field label="Command">{r.command || '—'}</Field>
                    <Field label="Instance">{r.cli_instance_label || '—'}</Field>
                    <Field label="Host">{r.cli_hostname || '—'}</Field>
                    <Field label="CLI version">{r.cli_version ? `v${r.cli_version}` : '—'}</Field>
                    <Field label="Duration">
                      {formatDuration(spanMs(r.started_at, r.finished_at))}
                    </Field>
                    <Field label="Started">
                      {absTime(r.started_at)}{' '}
                      <Text component="span" size="xs" c="dimmed">
                        (<TimeText iso={r.started_at} />)
                      </Text>
                    </Field>
                    <Field label="Finished">
                      {r.finished_at ? (
                        <>
                          {absTime(r.finished_at)}{' '}
                          <Text component="span" size="xs" c="dimmed">
                            (<TimeText iso={r.finished_at} />)
                          </Text>
                        </>
                      ) : (
                        '—'
                      )}
                    </Field>
                    <Field label="Steps">{stepTally(r.steps)}</Field>
                    <Field label="Trigger">
                      <TriggerBadge trigger={r.trigger} reason={r.trigger_reason} />
                    </Field>
                  </SimpleGrid>
                  {r.command_line && (
                    <DetailBlock label="Command">
                      <Code
                        block
                        fz="11px"
                        style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}
                      >
                        {r.command_line}
                      </Code>
                    </DetailBlock>
                  )}
                  <Group gap="xl" wrap="wrap">
                    <Field label="Run ID">
                      <Code fz="10px">{r.run_id}</Code>
                    </Field>
                    {r.project_id && (
                      <Field label="Project ID">
                        <Code fz="10px">{r.project_id}</Code>
                      </Field>
                    )}
                    {r.user_id && (
                      <Field label="User ID">
                        <Code fz="10px">{r.user_id}</Code>
                      </Field>
                    )}
                  </Group>
                  {(r.cli_config_path || r.project_config_path || r.data_root) && (
                    <Group gap="xl" wrap="wrap">
                      {r.cli_config_path && (
                        <Field label="CLI config">
                          <PathTip path={r.cli_config_path} />
                        </Field>
                      )}
                      {r.project_config_path && (
                        <Field label="Project config">
                          <PathTip path={r.project_config_path} />
                        </Field>
                      )}
                      {r.data_root && (
                        <Field label="Data root">
                          <PathTip path={r.data_root} />
                        </Field>
                      )}
                    </Group>
                  )}
                  {r.data_collections && r.data_collections.length > 0 && (
                    <DetailBlock label={`Data collections (${r.data_collections.length})`}>
                      <Table.ScrollContainer minWidth={560}>
                        <Table withTableBorder withColumnBorders fz="xs" layout="auto">
                          <Table.Thead>
                            <Table.Tr>
                              <Table.Th>Tag</Table.Th>
                              <Table.Th>Type</Table.Th>
                              <Table.Th>Format</Table.Th>
                              <Table.Th>Scan</Table.Th>
                              <Table.Th>Pattern / file</Table.Th>
                              <Table.Th>Local paths</Table.Th>
                              <Table.Th ta="right">Files</Table.Th>
                            </Table.Tr>
                          </Table.Thead>
                          <Table.Tbody>
                            {r.data_collections.map((dc, i) => (
                              <Table.Tr key={`${r.run_id}-dc-${i}`}>
                                <Table.Td fw={500}>{dc.tag}</Table.Td>
                                <Table.Td>{dc.type || '—'}</Table.Td>
                                <Table.Td>{dc.format || '—'}</Table.Td>
                                <Table.Td>{dc.scan_mode || '—'}</Table.Td>
                                <Table.Td>
                                  {dc.scan_mode === 'single' ? (
                                    <PathTip path={dc.scan_pattern} />
                                  ) : dc.scan_pattern ? (
                                    <Code fz="10px">{dc.scan_pattern}</Code>
                                  ) : (
                                    '—'
                                  )}
                                </Table.Td>
                                <Table.Td>
                                  {dc.locations && dc.locations.length > 0 ? (
                                    <Stack gap={2}>
                                      {dc.locations.map((l) => (
                                        <PathTip key={l} path={l} />
                                      ))}
                                    </Stack>
                                  ) : (
                                    '—'
                                  )}
                                </Table.Td>
                                <Table.Td ta="right">{dc.file_count ?? '—'}</Table.Td>
                              </Table.Tr>
                            ))}
                          </Table.Tbody>
                        </Table>
                      </Table.ScrollContainer>
                    </DetailBlock>
                  )}
                  {r.steps && r.steps.length > 0 && (
                    <DetailBlock label="Steps">
                      <IngestionStepTimeline
                        steps={r.steps}
                        currentStep={r.status === 'running' ? r.current_step : null}
                      />
                    </DetailBlock>
                  )}
                  {r.error && (
                    <Alert color="red" variant="light" p="xs">
                      <Text size="xs">{r.error}</Text>
                    </Alert>
                  )}
                </Stack>
                )}
              </Accordion.Panel>
            </Accordion.Item>
          ))}
          </Accordion>
        </ScrollArea>
      )}
    </Stack>
  );
};

// ── Logs pane ────────────────────────────────────────────────────────────────

const LogsPane: React.FC = () => {
  const [auto, setAuto] = useState(true);
  const [level, setLevel] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [q, setQ] = useState('');
  // Server-side capture floor (what actually gets persisted), distinct from the
  // client-side `level` filter above which only narrows already-captured rows.
  const [captureLevel, setCaptureLevel] = useState<string | null>(null);
  // Controlled open rows: only the expanded log mounts its CodeHighlight, so a
  // 400-row pane doesn't run 400 syntax passes (which froze the UI) on load and
  // on every auto-refresh.
  const [open, setOpen] = useState<string[]>([]);
  const load = useCallback(
    () => fetchAppLogs({ level: level || undefined, source: source || undefined, limit: 400 }),
    [level, source],
  );
  const { data, loading, error, refresh } = usePolling<MonitoringAppLog[]>(load, auto);

  useEffect(() => {
    fetchLogCaptureLevel()
      .then(setCaptureLevel)
      .catch(() => undefined);
  }, []);

  const onCaptureLevelChange = useCallback(
    (v: string | null) => {
      if (!v) return;
      setCaptureLevel(v);
      setLogCaptureLevel(v)
        .then(() => refresh())
        .catch(() => undefined);
    },
    [refresh],
  );
  // Search spans the log content (message) plus logger/source/level/path.
  const logs = (data ?? []).filter((l) =>
    matchesQuery(q, l.message, l.logger, l.level, l.source, l.pathname),
  );

  return (
    <Stack gap="sm">
      <PaneHeader
        title="Application logs"
        loading={loading}
        auto={auto}
        onAuto={setAuto}
        onRefresh={() => void refresh()}
        extra={
          <Group gap="xs" wrap="nowrap">
            <SearchInput value={q} onChange={setQ} />
            <Tooltip
              label="Capture floor — minimum level the server persists (live)"
              withArrow
            >
              <Select
                size="xs"
                leftSection={<Icon icon="mdi:filter-cog-outline" width={14} />}
                w={130}
                value={captureLevel}
                onChange={onCaptureLevelChange}
                allowDeselect={false}
                data={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']}
              />
            </Tooltip>
            <Select
              size="xs"
              placeholder="Level"
              clearable
              w={120}
              value={level}
              onChange={setLevel}
              data={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']}
            />
            <Select
              size="xs"
              placeholder="Source"
              clearable
              w={110}
              value={source}
              onChange={setSource}
              data={['api', 'celery']}
            />
          </Group>
        }
      />
      {error && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      )}
      {!loading && logs.length === 0 && !error ? (
        <Text size="xs" c="dimmed">
          No log records captured. Logs at/above the configured minimum level appear here.
        </Text>
      ) : (
        <ScrollArea h={PANE_SCROLL_H} type="auto">
          <Accordion
            variant="contained"
            chevronPosition="left"
            multiple
            value={open}
            onChange={setOpen}
            styles={ACCORDION_STYLES}
          >
            {logs.map((l, i) => {
              const key = `${l.ts}-${i}`;
              return (
              <Accordion.Item key={key} value={key}>
                <Accordion.Control>
                  <Group gap="sm" wrap="nowrap">
                    <Box w={84} style={{ flexShrink: 0 }}>
                      <Badge
                        size="xs"
                        fullWidth
                        color={LOG_LEVEL_COLORS[l.level] || 'gray'}
                        variant="filled"
                      >
                        {l.level}
                      </Badge>
                    </Box>
                    <Box w={64} style={{ flexShrink: 0 }}>
                      <Badge size="xs" fullWidth color="gray" variant="outline">
                        {l.source}
                      </Badge>
                    </Box>
                    <Tooltip label={l.ts} withArrow>
                      <Text
                        size="xs"
                        c="dimmed"
                        w={72}
                        style={{ fontFamily: 'monospace', flexShrink: 0 }}
                      >
                        {absTime(l.ts)}
                      </Text>
                    </Tooltip>
                    <Text size="xs" truncate style={{ fontFamily: 'monospace', flex: 1, minWidth: 0 }}>
                      {l.message}
                    </Text>
                  </Group>
                </Accordion.Control>
                <Accordion.Panel>
                  {open.includes(key) && (
                  <Stack gap={6}>
                    <Group gap="lg">
                      <Text size="xs" c="dimmed">
                        logger: <Code>{l.logger}</Code>
                      </Text>
                      {l.pathname && (
                        <Text size="xs" c="dimmed">
                          {l.pathname}
                          {l.lineno != null ? `:${l.lineno}` : ''}
                        </Text>
                      )}
                    </Group>
                    <CodeHighlight
                      code={l.message}
                      language="text"
                      copyLabel="Copy"
                      styles={CODE_STYLES}
                    />
                  </Stack>
                  )}
                </Accordion.Panel>
              </Accordion.Item>
              );
            })}
          </Accordion>
        </ScrollArea>
      )}
    </Stack>
  );
};

// ── Health pane ──────────────────────────────────────────────────────────────

const HealthPane: React.FC = () => {
  const [auto, setAuto] = useState(true);
  const load = useCallback(() => fetchMonitoringHealth(), []);
  const { data, loading, error, refresh } = usePolling<MonitoringHealth>(load, auto);

  return (
    <Stack gap="sm">
      <PaneHeader
        title="Worker health"
        loading={loading}
        auto={auto}
        onAuto={setAuto}
        onRefresh={() => void refresh()}
      />
      {error && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      )}
      {data && (
        <Group gap="md" align="stretch" wrap="wrap">
          <Card withBorder radius="md" p="md" miw={160}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Status
            </Text>
            <Badge mt={4} color={data.status === 'ok' ? 'green' : 'red'} variant="light">
              {data.status}
            </Badge>
          </Card>
          <Card withBorder radius="md" p="md" miw={160}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Workers
            </Text>
            <Text size="xl" fw={700}>
              {data.worker_count}
            </Text>
          </Card>
          <Card withBorder radius="md" p="md" miw={160}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Active tasks
            </Text>
            <Text size="xl" fw={700}>
              {data.active_count}
            </Text>
          </Card>
          <Card withBorder radius="md" p="md" miw={200}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Live updates
            </Text>
            <Badge mt={4} color={data.live_updates ? 'green' : 'gray'} variant="light">
              {data.live_updates ? 'on (WebSocket)' : 'off (polling)'}
            </Badge>
          </Card>
        </Group>
      )}
      {data && data.workers.length > 0 && (
        <Stack gap={2}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            Worker nodes
          </Text>
          {data.workers.map((w) => (
            <Code key={w}>{w}</Code>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

// ── Panel shell ──────────────────────────────────────────────────────────────

const AdminMonitoringPanel: React.FC = () => {
  const { isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const [pane, setPane] = useState<Pane>('tasks');
  const [liveSignal, setLiveSignal] = useState(0);
  const [lastEvent, setLastEvent] = useState<MonitoringLiveEvent | null>(null);

  // Match AdminApp's gate: single-user always allowed; only pure public/demo hides.
  const visible = isSingleUserMode || (!isPublicMode && !isDemoMode);

  // Live push. Two shapes on purpose: panes that refetch wholesale still use
  // the counter, while the ingestion pane takes the event itself so it can
  // patch one run in place. Ingestion is the only pane whose event rate scales
  // with the work being done — the others fire a handful of times per run.
  // No-op (socket never delivers) when events are disabled.
  const { status: liveStatus } = useMonitoringEvents({
    enabled: visible,
    onEvent: useCallback((event: MonitoringLiveEvent) => {
      setLastEvent(event);
      setLiveSignal((n) => n + 1);
    }, []),
  });

  const body = useMemo(() => {
    switch (pane) {
      case 'ingestion':
        return <IngestionPane lastEvent={lastEvent} />;
      case 'agents':
        return <AgentsPane liveSignal={liveSignal} />;
      case 'logs':
        return <LogsPane />;
      case 'health':
        return <HealthPane />;
      default:
        return <TasksPane liveSignal={liveSignal} />;
    }
  }, [pane, liveSignal, lastEvent]);

  if (!visible) {
    return (
      <Text size="sm" c="dimmed">
        Monitoring is not available in this deployment mode.
      </Text>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="nowrap">
        <SegmentedControl
          size="xs"
          value={pane}
          onChange={(v) => setPane(v as Pane)}
          data={[
            { value: 'tasks', label: 'Tasks' },
            { value: 'ingestion', label: 'Ingestion' },
            { value: 'agents', label: 'Agents' },
            { value: 'logs', label: 'Logs' },
            { value: 'health', label: 'Health' },
          ]}
        />
        {liveStatus === 'connected' && (
          <Badge size="xs" color="green" variant="dot">
            Live
          </Badge>
        )}
      </Group>
      <Card withBorder radius="md" p="md">
        {body}
      </Card>
    </Stack>
  );
};

export default AdminMonitoringPanel;
