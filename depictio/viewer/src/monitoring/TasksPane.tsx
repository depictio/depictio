import React, { useCallback, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Box,
  Code,
  Group,
  ScrollArea,
  Select,
  Stack,
  Text,
} from '@mantine/core';
import { CodeHighlight } from '@mantine/code-highlight';
import '@mantine/code-highlight/styles.css';
import { Icon } from '@iconify/react';

import { fetchMonitoringTasks, type MonitoringTaskEvent } from 'depictio-react-core';

import { formatDuration, matchesQuery, prettyRepr } from './format';
import { usePrettyPrint } from './usePrettyPrint';
import { DetailBlock, PaneHeader, SearchInput, TimeText } from './primitives';
import {
  ACCORDION_CLASSNAMES,
  ACCORDION_STYLES,
  CODE_STYLES,
  KIND_COLORS,
  PANE_SCROLL_H,
  statusColor,
} from './tokens';
import { usePolling } from './usePolling';
import { useTone } from './useTone';
import { PaneEmptyState, RedactedNote } from './notices';

/** Celery task history. Shared by Admin > Log & Task (every task) and the
 *  Activity page (the tasks of the reader's projects, redacted unless they can
 *  edit the project); the API decides what comes back. */
export const TasksPane: React.FC<{ liveSignal?: number }> = ({ liveSignal = 0 }) => {
  const tone = useTone();
  const [pretty] = usePrettyPrint();
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
    matchesQuery(q, t.task_name, t.task_id, t.kind, t.status, t.worker, t.dashboard_id, t.dc_id, t.project_id, t.error),
  );

  return (
    <Stack gap="sm">
      <PaneHeader
        prettyPrint
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
        <PaneEmptyState
          noun="task events"
          source="Tasks are recorded by the Celery worker (figure renders, screenshots, MultiQC and advanced visualisation computations) and kept for 14 days by default. Open a dashboard to see some appear."
          chips={[
            ...(status ? [{ key: 'status', label: `status: ${status}` }] : []),
            ...(kind ? [{ key: 'kind', label: `kind: ${kind}` }] : []),
            ...(q.trim() ? [{ key: 'q', label: `search: ${q.trim()}` }] : []),
          ]}
          onClear={() => {
            setStatus(null);
            setKind(null);
            setQ('');
          }}
        />
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
            {tasks.map((t) => (
            <Accordion.Item key={t.task_id} value={t.task_id}>
              <Accordion.Control>
                <Group gap="sm" wrap="nowrap">
                  <Box w={84} style={{ flexShrink: 0 }}>
                    <Badge size="xs" fullWidth color={tone(statusColor(t.status))} variant="filled">
                      {t.status}
                    </Badge>
                  </Box>
                  <Box w={88} style={{ flexShrink: 0 }}>
                    <Badge
                      size="xs"
                      fullWidth
                      color={tone(KIND_COLORS[t.kind] || 'gray')}
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
                    {t.project_id && (
                      <Text size="xs" c="dimmed">
                        project: {t.project_id}
                      </Text>
                    )}
                  </Group>
                  {t.redacted && <RedactedNote what="Arguments, results, logs and tracebacks" />}
                  {t.args_repr && (
                    <DetailBlock label="Arguments">
                      <CodeHighlight
                        code={pretty ? prettyRepr(t.args_repr) : t.args_repr}
                        language="python"
                        copyLabel="Copy"
                        styles={CODE_STYLES}
                      />
                    </DetailBlock>
                  )}
                  {t.result_summary && (
                    <DetailBlock label="Result">
                      <CodeHighlight
                        code={pretty ? prettyRepr(t.result_summary) : t.result_summary}
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
