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

import React, { useCallback, useEffect, useState } from 'react';
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
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectIngestionRuns } from 'depictio-react-core';
import type { MonitoringIngestionRun, MonitoringIngestionStep } from 'depictio-react-core';
import { INGESTION_STATUS_META } from '../IngestionResultTable';

import { absTime, formatDuration, matchesQuery, spanMs, stepTally } from '../../monitoring/format';
import { Field, PaneHeader, SearchInput, TimeText } from '../../monitoring/primitives';
import { ACCORDION_CLASSNAMES, ACCORDION_STYLES, statusColor } from '../../monitoring/tokens';
import { usePolling } from '../../monitoring/usePolling';
import { IngestionStepTimeline } from '../../monitoring/IngestionStepTimeline';
import { TriggerBadge } from '../../monitoring/TriggerBadge';

const ACTIVE_POLL_MS = 3000;
const IDLE_POLL_MS = 30000;

/** A step's outcome in the words and marks of an ingestion row. */
const STEP_STATUS: Record<string, string> = {
  success: 'ingested',
  ok: 'ingested',
  failed: 'failed',
  failure: 'failed',
  skipped: 'skipped',
  running: 'running',
  pending: 'planned',
};
const ORDER: Record<string, number> = { failed: 0, running: 1, planned: 2, skipped: 3, ingested: 4 };

/**
 * One collection per line: its outcome, its name and, for anything but a
 * clean ingest, the reason. Collections are ingested independently, so they
 * read as a list (failures first), not as a sequence of steps.
 */
const CollectionOutcomes: React.FC<{ steps: MonitoringIngestionStep[] }> = ({ steps }) => {
  const rows = steps
    .map((st) => ({
      tag: st.data_collection_tag || st.name,
      status: STEP_STATUS[st.status] ?? st.status,
      message: st.error || st.detail || null,
    }))
    .sort((a, b) => (ORDER[a.status] ?? 5) - (ORDER[b.status] ?? 5) || a.tag.localeCompare(b.tag));
  return (
    <Stack gap={6} data-testid="run-collection-outcomes">
      {rows.map((r) => {
        const meta = INGESTION_STATUS_META[r.status as keyof typeof INGESTION_STATUS_META] ?? {
          color: 'gray',
          icon: 'mdi:help-circle-outline',
          label: r.status,
        };
        return (
          <Group key={r.tag} gap="xs" wrap="nowrap" align="flex-start" data-status={r.status}>
            <Tooltip label={meta.label} withArrow openDelay={300}>
              <Box component="span" mt={2} style={{ flexShrink: 0, lineHeight: 0 }}>
                <Icon icon={meta.icon} width={16} color={`var(--mantine-color-${meta.color}-6)`} aria-label={meta.label} />
              </Box>
            </Tooltip>
            <Stack gap={0} style={{ minWidth: 0 }}>
              <Text size="sm" fw={500} ff="monospace">
                {r.tag}
              </Text>
              {r.message && r.status !== 'ingested' && (
                <Text size="xs" c={r.status === 'failed' ? 'red' : 'dimmed'} style={{ overflowWrap: 'anywhere' }}>
                  {r.message}
                </Text>
              )}
            </Stack>
          </Group>
        );
      })}
    </Stack>
  );
};

/** One ingestion run in full: where it ran, what happened to each collection
 *  and, for a run with real stages (scan, write, ...), those in order. Shared
 *  with the Activity timeline, which lists the same runs. */
export const IngestionRunDetails: React.FC<{ run: MonitoringIngestionRun }> = ({ run: r }) => {
  const tags = new Set((r.data_collections ?? []).map((d) => d.tag));
  const steps = r.steps ?? [];
  // A step names a collection (the UI's Add data writes one per collection)
  // or a stage of the run; only stages have an order worth drawing.
  const perCollection = steps.filter((st) => st.data_collection_tag || tags.has(st.name));
  const stages = steps.filter((st) => !(st.data_collection_tag || tags.has(st.name)));
  return (
    <Stack gap="sm">
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md" verticalSpacing="xs">
        <Field label="Instance">{r.cli_instance_label || '—'}</Field>
        <Field label="CLI version">{r.cli_version ? `v${r.cli_version}` : '—'}</Field>
        <Field label="Started">{absTime(r.started_at)}</Field>
        <Field label="Steps">{stepTally(r.steps)}</Field>
      </SimpleGrid>
      {stages.length > 0 && (
        <IngestionStepTimeline steps={stages} currentStep={r.status === 'running' ? r.current_step : null} />
      )}
      {perCollection.length > 0 && <CollectionOutcomes steps={perCollection} />}
      {r.error && !perCollection.some((st) => (st.error || st.detail) === r.error) && (
        <Alert color="red" variant="light" p="xs">
          <Text size="xs">{r.error}</Text>
        </Alert>
      )}
    </Stack>
  );
};

const ProjectIngestionHistoryPanel: React.FC<{
  projectId: string;
  /** Bumped by the parent to force a refresh — e.g. when a browser-triggered
   *  ingestion finishes, which the idle 30s cadence would otherwise take half a
   *  minute to notice. */
  refreshSignal?: number;
}> = ({ projectId, refreshSignal = 0 }) => {
  const [auto, setAuto] = useState(true);
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<string[]>([]);

  const load = useCallback(
    () => fetchProjectIngestionRuns(projectId, { limit: 50 }),
    [projectId],
  );
  // The cadence follows the data, but it has to be held in state: usePolling
  // takes the interval before it returns the runs the interval depends on.
  // usePolling re-arms its timer whenever intervalMs changes, so the cadence
  // tightens on the render after a run appears and relaxes on the render after
  // the last one ends.
  const [intervalMs, setIntervalMs] = useState(IDLE_POLL_MS);
  const { data, loading, error, refresh } = usePolling(load, auto, refreshSignal, intervalMs);

  const runs = data?.runs ?? [];
  const redacted = data?.redacted ?? false;

  const anyRunning = runs.some((r) => r.status === 'running');
  useEffect(() => {
    setIntervalMs(anyRunning ? ACTIVE_POLL_MS : IDLE_POLL_MS);
  }, [anyRunning]);

  const filtered = runs.filter((r) =>
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
          and host details are hidden: they describe the machine that ran the ingestion, not this
          project.
        </Text>
      )}

      {!loading && !error && runs.length > 0 && filtered.length === 0 && (
        <Text size="xs" c="dimmed">
          No ingestion runs match this search.
        </Text>
      )}

      {!loading && !error && runs.length === 0 && (
        <Alert color="blue" variant="light" icon={<Icon icon="mdi:information-outline" />}>
          <Stack gap={4}>
            <Text size="xs">No ingestion runs recorded for this project yet.</Text>
            <Code block fz="10px">
              depictio ingest results/ --server ~/.depictio/CLI.yaml
            </Code>
            <Text size="xs" c="dimmed">
              To keep it up to date automatically as new files land:
            </Text>
            <Code block fz="10px">
              depictio watch results/ --server ~/.depictio/CLI.yaml \{'\n'}
              {'  '}--write-mode replace-runs
            </Code>
            <Text size="xs" c="dimmed">
              A project defined by its own YAML rather than a template is selected with
              --project-config-path ./project.yaml.
            </Text>
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
          classNames={ACCORDION_CLASSNAMES}
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
                {open.includes(r.run_id) && <IngestionRunDetails run={r} />}
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  );
};

export default ProjectIngestionHistoryPanel;
