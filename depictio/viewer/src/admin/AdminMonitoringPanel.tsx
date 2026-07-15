import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Box,
  Card,
  Code,
  Group,
  Loader,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import { Icon } from '@iconify/react';

import {
  fetchAppLogs,
  fetchIngestionRuns,
  fetchMonitoringHealth,
  fetchMonitoringTasks,
  useMonitoringEvents,
  type MonitoringAppLog,
  type MonitoringHealth,
  type MonitoringIngestionRun,
  type MonitoringTaskEvent,
} from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';

/**
 * Admin > Monitoring ("Log & Task") tab.
 *
 * Four panes (Tasks / Ingestion / Logs / Health) over a small-font, collapsible,
 * badge-tagged UI. Data is the durable MongoDB ledger surfaced by
 * `/depictio/api/v1/monitoring/*`. Refreshes on an interval (toggleable); a
 * future live-push layer rides the events WebSocket when enabled.
 *
 * Hidden in public/demo mode (no real admin surface) — the parent AdminApp
 * already gates on `is_admin`, and we additionally bail in those modes here.
 */

type Pane = 'tasks' | 'ingestion' | 'logs' | 'health';

const REFRESH_MS = 8000;

const STATUS_COLORS: Record<string, string> = {
  success: 'green',
  failure: 'red',
  failed: 'red',
  started: 'yellow',
  running: 'yellow',
  retry: 'orange',
  revoked: 'gray',
  pending: 'gray',
  partial: 'orange',
};

const KIND_COLORS: Record<string, string> = {
  figure: 'blue',
  screenshot: 'grape',
  multiqc: 'teal',
  advanced_viz: 'indigo',
  deltatable: 'cyan',
  other: 'gray',
};

const LOG_LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'gray',
  INFO: 'blue',
  WARNING: 'yellow',
  ERROR: 'red',
  CRITICAL: 'red',
};

function statusColor(status?: string): string {
  return STATUS_COLORS[(status || '').toLowerCase()] || 'gray';
}

/** Compact relative-time string from an ISO timestamp, with absolute tooltip. */
function relTime(iso?: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function formatDuration(ms?: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

const TimeText: React.FC<{ iso?: string | null }> = ({ iso }) => (
  <Tooltip label={iso || 'n/a'} disabled={!iso} withArrow>
    <Text component="span" size="xs" c="dimmed">
      {relTime(iso)}
    </Text>
  </Tooltip>
);

/** Shared header: title + auto-refresh toggle + manual refresh + last-updated. */
const PaneHeader: React.FC<{
  title: string;
  loading: boolean;
  auto: boolean;
  onAuto: (v: boolean) => void;
  onRefresh: () => void;
  extra?: React.ReactNode;
}> = ({ title, loading, auto, onAuto, onRefresh, extra }) => (
  <Group justify="space-between" wrap="nowrap">
    <Group gap="xs">
      <Title order={6}>{title}</Title>
      {loading && <Loader size="xs" />}
    </Group>
    <Group gap="sm" wrap="nowrap">
      {extra}
      <Switch
        size="xs"
        label="Auto"
        checked={auto}
        onChange={(e) => onAuto(e.currentTarget.checked)}
      />
      <Tooltip label="Refresh now" withArrow>
        <ActionIcon variant="subtle" color="gray" onClick={onRefresh} aria-label="Refresh">
          <Icon icon="mdi:refresh" width={16} />
        </ActionIcon>
      </Tooltip>
    </Group>
  </Group>
);

/** Generic polling hook: runs `load` immediately and (when `auto`) every
 *  interval. Also refreshes whenever `liveSignal` increments — the panel bumps
 *  it on each live WebSocket push so the active pane updates instantly. */
function usePolling<T>(
  load: () => Promise<T>,
  auto: boolean,
  liveSignal = 0,
): { data: T | null; loading: boolean; error: string | null; refresh: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await loadRef.current();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    if (!auto) return undefined;
    const id = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(id);
  }, [auto, refresh]);

  // Live push: refresh on each signal bump (skip the initial 0 to avoid a
  // duplicate of the mount fetch above).
  useEffect(() => {
    if (liveSignal > 0) void refresh();
  }, [liveSignal, refresh]);

  return { data, loading, error, refresh };
}

// ── Tasks pane ────────────────────────────────────────────────────────────

const TasksPane: React.FC<{ liveSignal: number }> = ({ liveSignal }) => {
  const [auto, setAuto] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [kind, setKind] = useState<string | null>(null);
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
  const tasks = data ?? [];

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
        <Accordion variant="separated" chevronPosition="left" multiple>
          {tasks.map((t) => (
            <Accordion.Item key={t.task_id} value={t.task_id}>
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  <Badge size="xs" color={statusColor(t.status)} variant="filled">
                    {t.status}
                  </Badge>
                  <Badge size="xs" color={KIND_COLORS[t.kind] || 'gray'} variant="light">
                    {t.kind}
                  </Badge>
                  <Text size="xs" fw={500} style={{ fontFamily: 'monospace' }}>
                    {t.task_name || t.task_id}
                  </Text>
                  <Text size="xs" c="dimmed">
                    · {formatDuration(t.duration_ms)}
                  </Text>
                  <Box style={{ marginLeft: 'auto' }}>
                    <TimeText iso={t.updated_at} />
                  </Box>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
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
                    <CodeHighlight code={t.args_repr} language="python" copyLabel="Copy" />
                  )}
                  {t.error && (
                    <Alert color="red" variant="light" p="xs">
                      <Text size="xs">{t.error}</Text>
                    </Alert>
                  )}
                  {t.traceback && (
                    <CodeHighlight code={t.traceback} language="text" copyLabel="Copy" />
                  )}
                  {t.logs && t.logs.length > 0 && (
                    <CodeHighlight code={t.logs.join('\n')} language="text" copyLabel="Copy" />
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
};

// ── Ingestion pane ──────────────────────────────────────────────────────────

const IngestionPane: React.FC<{ liveSignal: number }> = ({ liveSignal }) => {
  const [auto, setAuto] = useState(true);
  const load = useCallback(() => fetchIngestionRuns({ limit: 200 }), []);
  const { data, loading, error, refresh } = usePolling<MonitoringIngestionRun[]>(
    load,
    auto,
    liveSignal,
  );
  const runs = data ?? [];

  return (
    <Stack gap="sm">
      <PaneHeader
        title="CLI ingestion runs"
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
      {!loading && runs.length === 0 && !error ? (
        <Text size="xs" c="dimmed">
          No ingestion runs recorded.
        </Text>
      ) : (
        <Accordion variant="separated" chevronPosition="left" multiple>
          {runs.map((r) => (
            <Accordion.Item key={r.run_id} value={r.run_id}>
              <Accordion.Control>
                <Group gap="xs" wrap="nowrap">
                  <Badge size="xs" color={statusColor(r.status)} variant="filled">
                    {r.status}
                  </Badge>
                  <Badge size="xs" color="blue" variant="light">
                    {r.cli_instance_label || r.cli_hostname || 'unknown CLI'}
                  </Badge>
                  <Text size="xs" fw={500}>
                    {r.project_name || r.project_id || r.command}
                  </Text>
                  <Text size="xs" c="dimmed">
                    · {r.email || '—'}
                  </Text>
                  <Box style={{ marginLeft: 'auto' }}>
                    <TimeText iso={r.started_at} />
                  </Box>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <Stack gap={6}>
                  <Group gap="lg">
                    <Text size="xs" c="dimmed">
                      run_id: <Code>{r.run_id}</Code>
                    </Text>
                    <Text size="xs" c="dimmed">
                      host: {r.cli_hostname || '—'}
                    </Text>
                    <Text size="xs" c="dimmed">
                      finished: <TimeText iso={r.finished_at} />
                    </Text>
                  </Group>
                  {r.steps && r.steps.length > 0 && (
                    <Table withTableBorder withColumnBorders fz="xs">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Step</Table.Th>
                          <Table.Th>Status</Table.Th>
                          <Table.Th>Detail</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {r.steps.map((s, i) => (
                          <Table.Tr key={`${r.run_id}-${i}`}>
                            <Table.Td>{s.name}</Table.Td>
                            <Table.Td>
                              <Badge size="xs" color={statusColor(s.status)} variant="light">
                                {s.status}
                              </Badge>
                            </Table.Td>
                            <Table.Td>{s.detail || '—'}</Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  )}
                  {r.error && (
                    <Alert color="red" variant="light" p="xs">
                      <Text size="xs">{r.error}</Text>
                    </Alert>
                  )}
                </Stack>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
};

// ── Logs pane ────────────────────────────────────────────────────────────────

const LogsPane: React.FC = () => {
  const [auto, setAuto] = useState(true);
  const [level, setLevel] = useState<string | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const load = useCallback(
    () => fetchAppLogs({ level: level || undefined, source: source || undefined, limit: 400 }),
    [level, source],
  );
  const { data, loading, error, refresh } = usePolling<MonitoringAppLog[]>(load, auto);
  const logs = data ?? [];

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
        <ScrollArea h={520} type="auto">
          <Table fz="xs" highlightOnHover stickyHeader>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={90}>Time</Table.Th>
                <Table.Th w={80}>Level</Table.Th>
                <Table.Th w={70}>Src</Table.Th>
                <Table.Th>Message</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {logs.map((l, i) => (
                <Table.Tr key={`${l.ts}-${i}`}>
                  <Table.Td>
                    <TimeText iso={l.ts} />
                  </Table.Td>
                  <Table.Td>
                    <Badge size="xs" color={LOG_LEVEL_COLORS[l.level] || 'gray'} variant="light">
                      {l.level}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {l.source}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                      {l.message}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
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

  // Match AdminApp's gate: single-user always allowed; only pure public/demo hides.
  const visible = isSingleUserMode || (!isPublicMode && !isDemoMode);

  // Live push: bump a signal on each task/ingestion event so the active pane
  // refreshes instantly. No-op (socket never delivers) when events are disabled.
  const { status: liveStatus } = useMonitoringEvents({
    enabled: visible,
    onEvent: useCallback(() => setLiveSignal((n) => n + 1), []),
  });

  const body = useMemo(() => {
    switch (pane) {
      case 'ingestion':
        return <IngestionPane liveSignal={liveSignal} />;
      case 'logs':
        return <LogsPane />;
      case 'health':
        return <HealthPane />;
      default:
        return <TasksPane liveSignal={liveSignal} />;
    }
  }, [pane, liveSignal]);

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
