/**
 * Live CLI agents (`depictio watch` processes).
 *
 * A watcher is a daemon that can run for weeks on a login node without anyone
 * watching it. Without this pane the only evidence it is alive is whether new
 * ingestion runs keep appearing — which is indistinguishable from "nothing has
 * changed upstream". This makes the distinction visible.
 *
 * Rows come from a TTL-backed collection, so a listed agent is by construction
 * one that has heartbeated recently; a dead one disappears on its own.
 */

import React, { useCallback, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Loader,
  ScrollArea,
  SimpleGrid,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { fetchCliAgents, triggerCliAgentRun, type MonitoringCliAgent } from 'depictio-react-core';

import { matchesQuery, parseTs, relTime } from './format';
import { Field, IdRow, PaneHeader, PathTip, SearchInput } from './primitives';
import { ACCORDION_CLASSNAMES, ACCORDION_STYLES, PANE_SCROLL_H } from './tokens';
import { usePolling } from './usePolling';

const AGENT_STATUS_COLORS: Record<string, string> = {
  idle: 'gray',
  settling: 'blue',
  scanning: 'cyan',
  ingesting: 'yellow',
  error: 'red',
};

/** Agents heartbeat every 60s. Three missed beats is the point at which the
 *  process is more likely wedged than merely slow — flag it rather than wait
 *  for the TTL to remove the row. */
const STALE_HEARTBEAT_MS = 180_000;

function isStale(agent: MonitoringCliAgent): boolean {
  const beat = parseTs(agent.heartbeat_at);
  if (Number.isNaN(beat)) return true;
  return Date.now() - beat > STALE_HEARTBEAT_MS;
}

const AgentRow: React.FC<{ agent: MonitoringCliAgent; onTriggered: () => void }> = ({
  agent,
  onTriggered,
}) => {
  const [requesting, setRequesting] = useState(false);
  const stale = isStale(agent);
  const active = agent.status === 'scanning' || agent.status === 'ingesting';
  const pending = Boolean(agent.run_requested_at);

  // The button is only meaningful for a watcher that is listening and free. Each
  // case gets its own reason rather than a bare disabled control, because "why
  // can't I press this?" is otherwise unanswerable from the card.
  const blocked = stale
    ? 'No recent heartbeat — this watcher may never pick the request up'
    : active
      ? 'A cycle is already running'
      : pending
        ? 'Already requested — the watcher claims it within a few seconds'
        : null;

  const requestRun = async () => {
    setRequesting(true);
    try {
      await triggerCliAgentRun(agent.agent_id);
      notifications.show({
        color: 'green',
        title: 'Run requested',
        message: 'The watcher starts a cycle at its next check, within a few seconds.',
      });
      onTriggered();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not request a run',
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRequesting(false);
    }
  };

  return (
    <Accordion.Item value={agent.agent_id}>
      <Accordion.Control>
        <Group gap="xs" wrap="nowrap">
          <Badge
            size="xs"
            variant="light"
            color={AGENT_STATUS_COLORS[agent.status] ?? 'gray'}
            leftSection={active ? <Loader size={8} color="yellow" /> : undefined}
          >
            {agent.status}
          </Badge>
          <Text size="xs" fw={500}>
            {agent.instance_label || agent.agent_id.slice(0, 8)}
          </Text>
          <Text size="10px" c="dimmed">
            {agent.hostname || '—'}
          </Text>
          {agent.project_name && (
            <Badge size="xs" variant="outline" color="gray">
              {agent.project_name}
            </Badge>
          )}
          {agent.mode && (
            <Badge size="xs" variant="dot" color={agent.mode === 'full' ? 'orange' : 'blue'}>
              {agent.mode}
            </Badge>
          )}
          {agent.backend && (
            <Tooltip
              label={
                agent.backend === 'polling'
                  ? 'Polling only — filesystem events are not reliable here (network mount)'
                  : `Change detection: ${agent.backend}`
              }
              withArrow
            >
              <Badge size="xs" variant="light" color="grape">
                {agent.backend}
              </Badge>
            </Tooltip>
          )}
          <Group gap={4} ml="auto" wrap="nowrap">
            {agent.runs_total != null && (
              <Text size="10px" c="dimmed">
                {agent.runs_total} runs
              </Text>
            )}
            <Tooltip label={agent.heartbeat_at || 'never'} withArrow>
              <Text size="10px" c={stale ? 'red' : 'dimmed'} fw={stale ? 700 : 400}>
                {relTime(agent.heartbeat_at)}
              </Text>
            </Tooltip>
          </Group>
        </Group>
      </Accordion.Control>
      <Accordion.Panel>
        <Stack gap="xs">
          {stale && (
            <Alert color="red" variant="light" p="xs">
              <Text size="xs">
                No heartbeat for over {Math.round(STALE_HEARTBEAT_MS / 60000)} minutes. The process
                may be wedged, or unable to reach the API.
              </Text>
            </Alert>
          )}
          {agent.last_error && (
            <Alert color="red" variant="light" p="xs" title="Last error">
              <Text size="xs">{agent.last_error}</Text>
            </Alert>
          )}
          <Group justify="space-between" align="center" wrap="nowrap">
            {/* Four short scalars, four columns: they line up and each is
                readable at a glance. The long identifiers live below, where
                they have the full width. */}
            <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs" style={{ flex: 1, minWidth: 0 }}>
              <Field label="PID">{agent.pid ?? '—'}</Field>
              <Field label="CLI version">{agent.cli_version || '—'}</Field>
              <Field label="Started">{relTime(agent.started_at)}</Field>
              <Field label="Last trigger">{relTime(agent.last_trigger_at)}</Field>
            </SimpleGrid>
            <Tooltip label={blocked ?? 'Ingest now, without waiting for a change'} withArrow>
              <Button
                size="compact-xs"
                variant="light"
                loading={requesting}
                disabled={Boolean(blocked)}
                onClick={() => void requestRun()}
                leftSection={<Icon icon={pending ? 'mdi:clock-outline' : 'mdi:play'} width={13} />}
                style={{ flexShrink: 0 }}
              >
                {pending ? 'Requested' : 'Run now'}
              </Button>
            </Tooltip>
          </Group>
          <Stack gap={4}>
            <IdRow label="Agent ID" value={agent.agent_id} />
            <IdRow label="Last run" value={agent.last_run_id} />
          </Stack>
          {agent.watching && agent.watching.length > 0 && (
            <Stack gap={2}>
              <Text size="10px" c="dimmed" tt="uppercase" fw={700} lts={0.4}>
                Watching
              </Text>
              <Stack gap={1}>
                {agent.watching.map((p: string) => (
                  <PathTip key={p} path={p} />
                ))}
              </Stack>
            </Stack>
          )}
        </Stack>
      </Accordion.Panel>
    </Accordion.Item>
  );
};

export const AgentsPane: React.FC<{ liveSignal?: number; projectId?: string }> = ({
  liveSignal = 0,
  projectId,
}) => {
  const [auto, setAuto] = useState(true);
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<string[]>([]);
  const load = useCallback(() => fetchCliAgents({ projectId, limit: 200 }), [projectId]);
  const { data, loading, error, refresh } = usePolling<MonitoringCliAgent[]>(
    load,
    auto,
    liveSignal,
  );

  const agents = (data ?? []).filter((a) =>
    matchesQuery(
      q,
      a.instance_label,
      a.hostname,
      a.project_name,
      a.agent_id,
      a.status,
      a.mode,
      a.backend,
    ),
  );

  return (
    <Stack gap="sm">
      <PaneHeader
        title="CLI agents"
        loading={loading}
        auto={auto}
        onAuto={setAuto}
        onRefresh={() => void refresh()}
        extra={<SearchInput value={q} onChange={setQ} />}
      />
      {error && (
        <Alert color="red" variant="light" p="xs">
          <Text size="xs">{error}</Text>
        </Alert>
      )}
      {!loading && agents.length === 0 && (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
          <Stack gap={4}>
            <Text size="xs">No CLI agents are running.</Text>
            <Text size="xs" c="dimmed">
              Start one to re-ingest automatically when files change:
            </Text>
            <Code block fz="10px">
              depictio watch --CLI-config-path ~/.depictio/CLI.yaml \{'\n'}
              {'  '}--project-config-path ./project.yaml --write-mode replace-runs
            </Code>
          </Stack>
        </Alert>
      )}
      {agents.length > 0 && (
        <ScrollArea.Autosize mah={PANE_SCROLL_H}>
          <Accordion
            multiple
            chevronPosition="left"
            value={open}
            onChange={setOpen}
            styles={ACCORDION_STYLES}
            classNames={ACCORDION_CLASSNAMES}
          >
            {agents.map((agent) => (
              <AgentRow key={agent.agent_id} agent={agent} onTriggered={() => void refresh()} />
            ))}
          </Accordion>
        </ScrollArea.Autosize>
      )}
    </Stack>
  );
};
