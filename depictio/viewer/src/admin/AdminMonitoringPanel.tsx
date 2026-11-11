import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Box,
  Card,
  Code,
  Group,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import '@mantine/code-highlight/styles.css';
import { Icon } from '@iconify/react';

import {
  fetchAppLogs,
  fetchLogCaptureLevel,
  fetchMonitoringHealth,
  setLogCaptureLevel,
  useMonitoringEvents,
  type IngestionFilters,
  type MonitoringAppLog,
  type MonitoringHealth,
  type MonitoringLiveEvent,
  type MonitoringPane,
} from 'depictio-react-core';

import { useCurrentUser } from '../hooks/useCurrentUser';
import { canSeeMonitoring } from './access';
import { formatDateTimeVerbose } from '../lib/datetime';
import { clockTime, matchesQuery, prettyRepr } from '../monitoring/format';
import { usePrettyPrint } from '../monitoring/usePrettyPrint';
import { PaneHeader, SearchInput } from '../monitoring/primitives';
import {
  ACCORDION_CLASSNAMES,
  ACCORDION_STYLES,
  CODE_STYLES,
  LOG_LEVEL_COLORS,
  PANE_SCROLL_H,
} from '../monitoring/tokens';
import { createLiveFeed, usePolling } from '../monitoring/usePolling';
import { routeMonitoringEvent } from '../monitoring/runs';
import { AgentsPane } from '../monitoring/AgentsPane';
import { TasksPane } from '../monitoring/TasksPane';
import { IngestionPane } from '../monitoring/IngestionPane';
import { useTone } from '../monitoring/useTone';

/**
 * Admin > Monitoring ("Log & Task") tab.
 *
 * Five panes (Tasks / Ingestion / Watchers / Logs / Health) over a small-font,
 * collapsible, badge-tagged UI. Data is the durable MongoDB ledger surfaced by
 * `/depictio/api/v1/monitoring/*`. Refreshes on an interval (toggleable), with
 * live push over the events WebSocket when enabled.
 *
 * The shared formatting helpers, visual tokens, primitives and polling hooks
 * live in `../monitoring/` so the project-scoped panels reuse them rather than
 * growing near-copies.
 *
 * Hidden in demo mode and from a public instance's guests (no real admin
 * surface) — the parent AdminApp already gates on `is_admin`, and we
 * additionally bail in those cases here.
 *
 * The open pane and the Ingestion filters are owned by AdminApp, which keeps
 * them in the URL (`/admin/<pane>?status=...`) so a refresh, Back/Forward or a
 * shared link restores the view.
 */

// ── Logs pane ────────────────────────────────────────────────────────────────

const LogsPane: React.FC = () => {
  const tone = useTone();
  const [pretty] = usePrettyPrint();
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
        prettyPrint
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
            classNames={ACCORDION_CLASSNAMES}
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
                        color={tone(LOG_LEVEL_COLORS[l.level] || 'gray')}
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
                    <Tooltip label={formatDateTimeVerbose(l.ts)} withArrow>
                      <Text
                        size="xs"
                        c="dimmed"
                        w={72}
                        style={{ fontFamily: 'monospace', flexShrink: 0 }}
                      >
                        {clockTime(l.ts)}
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
                      code={pretty ? prettyRepr(l.message) : l.message}
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

interface AdminMonitoringPanelProps {
  /** Open pane; AdminApp mirrors it in the path (`/admin/<pane>`). */
  pane: MonitoringPane;
  onPaneChange: (pane: MonitoringPane) => void;
  /** Ingestion pane filters; AdminApp mirrors them in the query string. */
  ingestionFilters: IngestionFilters;
  onIngestionFiltersChange: (filters: IngestionFilters) => void;
  /** Show the pane switch. Off when the page's own navigation lists the panes. */
  showPaneSwitch?: boolean;
}

const AdminMonitoringPanel: React.FC<AdminMonitoringPanelProps> = ({
  pane,
  onPaneChange,
  ingestionFilters,
  onIngestionFiltersChange,
  showPaneSwitch = true,
}) => {
  const { user, isPublicMode, isDemoMode, isSingleUserMode } = useCurrentUser();
  const [taskSignal, setTaskSignal] = useState(0);
  const [watcherSignal, setWatcherSignal] = useState(0);
  const [ingestionFeed] = useState(() => createLiveFeed<MonitoringLiveEvent>());

  // Match AdminApp's gate (see `canSeeMonitoring`).
  const visible = canSeeMonitoring({ user, isPublicMode, isDemoMode, isSingleUserMode });

  // Probe whether real-time events are enabled server-side before opening the
  // socket. When they're disabled the WS handshake is rejected (403) and the
  // client reconnects on a loop, spamming the API access log — so gate on this
  // flag and fall back to the polling baseline instead of connecting.
  const [eventsEnabled, setEventsEnabled] = useState(false);
  useEffect(() => {
    if (!visible) return undefined;
    let cancelled = false;
    fetchMonitoringHealth()
      .then((h) => {
        if (!cancelled) setEventsEnabled(h.events_enabled);
      })
      .catch(() => {
        if (!cancelled) setEventsEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, [visible]);

  // Live push, only connected when events are enabled server-side; otherwise
  // the panes keep working off their polling baseline. Two shapes on purpose:
  // panes that refetch wholesale get a counter, bumped only for the events
  // they show, while the ingestion pane subscribes to the events themselves
  // so it can patch one run in place. Ingestion is the only pane whose event
  // rate scales with the work being done: one event per step.
  const { status: liveStatus } = useMonitoringEvents({
    enabled: visible && eventsEnabled,
    onEvent: useCallback(
      (event: MonitoringLiveEvent) => {
        const route = routeMonitoringEvent(event);
        if (route.tasks) setTaskSignal((n) => n + 1);
        if (route.watchers) setWatcherSignal((n) => n + 1);
        if (route.ingestion) ingestionFeed.publish(event);
      },
      [ingestionFeed],
    ),
  });

  const body = useMemo(() => {
    switch (pane) {
      case 'ingestion':
        return (
          <IngestionPane
            feed={ingestionFeed}
            filters={ingestionFilters}
            onFiltersChange={onIngestionFiltersChange}
          />
        );
      case 'watchers':
        return <AgentsPane liveSignal={watcherSignal} />;
      case 'logs':
        return <LogsPane />;
      case 'health':
        return <HealthPane />;
      default:
        return <TasksPane liveSignal={taskSignal} />;
    }
  }, [pane, taskSignal, watcherSignal, ingestionFeed, ingestionFilters, onIngestionFiltersChange]);

  if (!visible) {
    return (
      <Text size="sm" c="dimmed">
        Monitoring is not available in this deployment mode.
      </Text>
    );
  }

  return (
    <Stack gap="md">
      {(showPaneSwitch || liveStatus === 'connected') && (
        <Group justify={showPaneSwitch ? 'space-between' : 'flex-end'} wrap="nowrap">
          {showPaneSwitch && (
            <SegmentedControl
              size="xs"
              value={pane}
              onChange={(v) => onPaneChange(v as MonitoringPane)}
              data={[
                { value: 'tasks', label: 'Tasks' },
                { value: 'ingestion', label: 'Ingestion' },
                { value: 'watchers', label: 'Watchers' },
                { value: 'logs', label: 'Logs' },
                { value: 'health', label: 'Health' },
              ]}
            />
          )}
          {liveStatus === 'connected' && (
            <Badge size="xs" color="green" variant="dot">
              Live
            </Badge>
          )}
        </Group>
      )}
      <Card withBorder radius="md" p="md">
        {body}
      </Card>
    </Stack>
  );
};

export default AdminMonitoringPanel;
