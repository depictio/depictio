/**
 * Ingestion-run history for one project.
 *
 * The admin monitoring tab already shows every run on the server; this shows
 * the runs for *this* project to the people who own it, who are usually not
 * admins. Same components as the admin pane (see `src/monitoring/`) so the two
 * views stay consistent.
 *
 * Non-admins have no access to the admin events channel, so this polls rather
 * than subscribing — adaptively: 3s while a run is in flight, 30s otherwise. A
 * project page left open all afternoon should not poll every three seconds for
 * the whole of it.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Box,
  Code,
  Group,
  SimpleGrid,
  Stack,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import {
  fetchProjectIngestionRuns,
  type MonitoringIngestionRun,
} from 'depictio-react-core';

import { absTime, formatDuration, matchesQuery, spanMs, stepTally } from '../../monitoring/format';
import { Field, PaneHeader, SearchInput, TimeText } from '../../monitoring/primitives';
import { ACCORDION_STYLES, statusColor } from '../../monitoring/tokens';
import { usePolling } from '../../monitoring/usePolling';
import { IngestionStepTimeline } from '../../monitoring/IngestionStepTimeline';
import { TriggerBadge } from '../../monitoring/TriggerBadge';

const ACTIVE_POLL_MS = 3000;
const IDLE_POLL_MS = 30000;

const ProjectIngestionHistoryPanel: React.FC<{ projectId: string }> = ({ projectId }) => {
  const [auto, setAuto] = useState(true);
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<string[]>([]);

  const load = useCallback(
    () => fetchProjectIngestionRuns(projectId, { limit: 50 }),
    [projectId],
  );
  // Interval is derived from the data rather than held in state: usePolling
  // re-arms its timer whenever intervalMs changes, so the cadence tightens on
  // the render after a run appears and relaxes on the render after the last one
  // ends. Keeping it in state would mean a setState during render for no gain.
  const [intervalMs, setIntervalMs] = useState(IDLE_POLL_MS);
  const { data, loading, error, refresh } = usePolling(load, auto, 0, intervalMs);

  const runs = useMemo(() => data?.runs ?? [], [data]);
  const redacted = data?.redacted ?? false;

  const anyRunning = runs.some((r) => r.status === 'running');
  useEffect(() => {
    setIntervalMs(anyRunning ? ACTIVE_POLL_MS : IDLE_POLL_MS);
  }, [anyRunning]);

  const filtered = runs.filter((r: MonitoringIngestionRun) =>
    matchesQuery(q, r.command, r.cli_instance_label, r.status, r.run_id, r.trigger),
  );

  return (
    <Stack gap="sm">
      <PaneHeader
        title="Ingestion history"
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

      {redacted && (
        <Text size="xs" c="dimmed">
          <Icon icon="mdi:eye-off-outline" width={12} style={{ verticalAlign: -2 }} /> Local paths
          and host details are hidden — they describe the machine that ran the ingestion, not this
          project.
        </Text>
      )}

      {!loading && filtered.length === 0 && (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
          <Stack gap={4}>
            <Text size="xs">No ingestion runs recorded for this project yet.</Text>
            <Code block fz="10px">
              depictio run --CLI-config-path ~/.depictio/CLI.yaml \{'\n'}
              {'  '}--project-config-path ./project.yaml
            </Code>
            <Text size="xs" c="dimmed">
              To keep it up to date automatically as new files land:
            </Text>
            <Code block fz="10px">
              depictio data watch --CLI-config-path ~/.depictio/CLI.yaml \{'\n'}
              {'  '}--project-config-path ./project.yaml --write-mode replace-runs
            </Code>
          </Stack>
        </Alert>
      )}

      {filtered.length > 0 && (
        <Accordion
          multiple
          chevronPosition="left"
          value={open}
          onChange={setOpen}
          styles={ACCORDION_STYLES}
        >
          {filtered.map((r) => (
            <Accordion.Item key={r.run_id} value={r.run_id}>
              <Accordion.Control>
                <Group gap="sm" wrap="nowrap">
                  <Box w={72} style={{ flexShrink: 0 }}>
                    <Badge size="xs" fullWidth color={statusColor(r.status)} variant="filled">
                      {r.status}
                    </Badge>
                  </Box>
                  <TriggerBadge trigger={r.trigger} reason={r.trigger_reason} />
                  <Text size="xs" fw={500} truncate style={{ flex: 1, minWidth: 0 }}>
                    {r.command || '—'}
                  </Text>
                  <Text size="xs" c="dimmed" w={70} ta="right" style={{ flexShrink: 0 }}>
                    {formatDuration(spanMs(r.started_at, r.finished_at))}
                  </Text>
                  <Box w={68} style={{ flexShrink: 0, textAlign: 'right' }}>
                    <TimeText iso={r.started_at} />
                  </Box>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                {open.includes(r.run_id) && (
                  <Stack gap="sm">
                    <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md" verticalSpacing="xs">
                      <Field label="Instance">{r.cli_instance_label || '—'}</Field>
                      <Field label="CLI version">{r.cli_version ? `v${r.cli_version}` : '—'}</Field>
                      <Field label="Started">{absTime(r.started_at)}</Field>
                      <Field label="Steps">{stepTally(r.steps)}</Field>
                    </SimpleGrid>
                    {r.steps && r.steps.length > 0 && (
                      <IngestionStepTimeline
                        steps={r.steps}
                        currentStep={r.status === 'running' ? r.current_step : null}
                      />
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
      )}
    </Stack>
  );
};

export default ProjectIngestionHistoryPanel;
