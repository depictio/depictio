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

/** Wrap long lines and reserve a right gutter so the CodeHighlight copy button
 *  never overlaps the code text. */
const CODE_STYLES = {
  code: { whiteSpace: 'pre-wrap', wordBreak: 'break-word', paddingRight: 44 },
} as const;

/** Ultra-compact accordion: strip every border/divider and shrink control +
 *  label padding to the minimum legible so rows sit directly on top of each
 *  other. Shared by the Tasks / Ingestion / Logs panes. */
const ACCORDION_STYLES = {
  root: { border: 'none' },
  item: { border: 'none', background: 'transparent' },
  control: { paddingTop: 0, paddingBottom: 0 },
  label: { paddingTop: 3, paddingBottom: 3 },
  content: { padding: '2px 8px 6px' },
} as const;

/** Viewport-relative height so the row list fills the available space under the
 *  pane header instead of a short fixed box. */
const PANE_SCROLL_H = 'calc(100vh - 300px)';

function statusColor(status?: string): string {
  return STATUS_COLORS[(status || '').toLowerCase()] || 'gray';
}

/** Case-insensitive substring match of `q` against any of the given fields.
 *  Empty query matches everything. Shared by the pane search boxes. */
function matchesQuery(q: string, ...fields: Array<string | number | null | undefined>): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return fields.some((f) => f != null && String(f).toLowerCase().includes(needle));
}

/** Small search box used in each pane header. */
const SearchInput: React.FC<{ value: string; onChange: (v: string) => void }> = ({
  value,
  onChange,
}) => (
  <TextInput
    size="xs"
    w={180}
    placeholder="Search…"
    leftSection={<Icon icon="mdi:magnify" width={14} />}
    value={value}
    onChange={(e) => onChange(e.currentTarget.value)}
  />
);

/** Parse a backend ISO timestamp to epoch ms. The API stamps with
 *  `datetime.now()` in UTC containers and serializes without an offset, so an
 *  offset-less value must be read as UTC — otherwise JS treats it as local time
 *  (a fresh event reads hours off for non-UTC users). */
function parseTs(iso?: string | null): number {
  if (!iso) return NaN;
  const hasTz = /([zZ]|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasTz ? iso : `${iso}Z`).getTime();
}

/** Compact relative-time string from an ISO timestamp, with absolute tooltip. */
function relTime(iso?: string | null): string {
  if (!iso) return '—';
  const then = parseTs(iso);
  if (Number.isNaN(then)) return '—';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/** Exact local clock time (with seconds) from an ISO timestamp. */
function absTime(iso?: string | null): string {
  const ms = parseTs(iso);
  if (Number.isNaN(ms)) return '—';
  return new Date(ms).toLocaleTimeString(undefined, { hour12: false });
}

function formatDuration(ms?: number | null): string {
  if (ms == null) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

/** Wall-clock duration between two ISO timestamps, in ms (null if either is missing). */
function spanMs(start?: string | null, end?: string | null): number | null {
  const a = parseTs(start);
  const b = parseTs(end);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.max(0, b - a);
}

/** Compact "N ok · M failed · K skipped" tally from a run's step list. */
function stepTally(steps?: { status: string }[]): string {
  if (!steps || steps.length === 0) return '—';
  const counts = { success: 0, failed: 0, skipped: 0, partial: 0, other: 0 };
  for (const s of steps) {
    const key = (s.status || '').toLowerCase();
    if (key === 'success') counts.success += 1;
    else if (key === 'failed' || key === 'failure') counts.failed += 1;
    else if (key === 'skipped') counts.skipped += 1;
    else if (key === 'partial' || key === 'running') counts.partial += 1;
    else counts.other += 1;
  }
  const parts: string[] = [`${counts.success} ok`];
  if (counts.failed) parts.push(`${counts.failed} failed`);
  if (counts.skipped) parts.push(`${counts.skipped} skipped`);
  if (counts.partial) parts.push(`${counts.partial} partial`);
  if (counts.other) parts.push(`${counts.other} other`);
  return parts.join(' · ');
}

/** Collapse a long filesystem path to `head/…/last-two-segments` so it fits on
 *  one line; the full value is surfaced via tooltip in `PathTip`. */
function shortenPath(p: string, maxLen = 44): string {
  if (p.length <= maxLen) return p;
  const parts = p.split('/').filter(Boolean);
  if (parts.length <= 2) return `…${p.slice(-(maxLen - 1))}`;
  const lead = p.startsWith('/') ? '/' : '';
  const tail = parts.slice(-2).join('/');
  const short = `${lead}${parts[0]}/…/${tail}`;
  return short.length <= maxLen ? short : `…/${tail}`;
}

/** A single-line, ellipsized path (monospace). The full path shows on hover, and
 *  clicking copies it to the clipboard (the shortened text isn't selectable). */
const PathTip: React.FC<{ path?: string | null }> = ({ path }) =>
  path ? (
    <CopyButton value={path} timeout={1500}>
      {({ copied, copy }) => (
        <Tooltip label={copied ? 'Copied!' : `${path}  (click to copy)`} withArrow multiline maw={560}>
          <Code
            fz="10px"
            onClick={copy}
            style={{ whiteSpace: 'nowrap', cursor: 'pointer' }}
          >
            {shortenPath(path)}
          </Code>
        </Tooltip>
      )}
    </CopyButton>
  ) : (
    <>—</>
  );

/** One metadatum as a stacked label-over-value cell (uppercase caption above the
 *  value). Used in the ingestion detail field grid so values line up in columns
 *  instead of wrapping into an unreadable run-on. */
const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <Box>
    <Text size="10px" c="dimmed" tt="uppercase" fw={700} lts={0.4}>
      {label}
    </Text>
    <Text size="xs" style={{ lineHeight: 1.35 }}>
      {children}
    </Text>
  </Box>
);

const TimeText: React.FC<{ iso?: string | null }> = ({ iso }) => (
  <Tooltip label={iso || 'n/a'} disabled={!iso} withArrow>
    <Text component="span" size="xs" c="dimmed">
      {relTime(iso)}
    </Text>
  </Tooltip>
);

/** Small uppercase caption used to title each block in an expanded detail panel. */
const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
    {children}
  </Text>
);

/** A titled block: caption above arbitrary content (a CodeHighlight, an Alert…). */
const DetailBlock: React.FC<{ label: string; children: React.ReactNode }> = ({
  label,
  children,
}) => (
  <Stack gap={2}>
    <SectionLabel>{label}</SectionLabel>
    {children}
  </Stack>
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

const IngestionPane: React.FC<{ liveSignal: number }> = ({ liveSignal }) => {
  const [auto, setAuto] = useState(true);
  const [q, setQ] = useState('');
  // Controlled open rows: only the expanded run mounts its field grid + steps
  // table, keeping a large run list light on load and on refresh.
  const [open, setOpen] = useState<string[]>([]);
  const load = useCallback(() => fetchIngestionRuns({ limit: 200 }), []);
  const { data, loading, error, refresh } = usePolling<MonitoringIngestionRun[]>(
    load,
    auto,
    liveSignal,
  );
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
                    <Table withTableBorder withColumnBorders fz="xs">
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Step</Table.Th>
                          <Table.Th>Status</Table.Th>
                          <Table.Th>Detail</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {r.steps.map((s, i) => {
                          const isCurrent = r.status === 'running' && s.name === r.current_step;
                          return (
                            <Table.Tr
                              key={`${r.run_id}-${i}`}
                              bg={isCurrent ? 'var(--mantine-color-yellow-light)' : undefined}
                            >
                              <Table.Td>
                                <Group gap={6} wrap="nowrap">
                                  {isCurrent && <Loader size={10} color="yellow" />}
                                  {s.name}
                                </Group>
                              </Table.Td>
                              <Table.Td>
                                <Badge size="xs" color={statusColor(s.status)} variant="light">
                                  {s.status}
                                </Badge>
                              </Table.Td>
                              <Table.Td>{s.detail || '—'}</Table.Td>
                            </Table.Tr>
                          );
                        })}
                      </Table.Tbody>
                    </Table>
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
