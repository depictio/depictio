import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Accordion,
  Alert,
  Badge,
  Box,
  Code,
  Group,
  Loader,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tooltip,
  Text,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  EMPTY_INGESTION_FILTERS,
  INGESTION_STATUSES,
  fetchIngestionRuns,
  type IngestionFilters,
  type IngestionStatusFilter,
  type MonitoringIngestionRun,
  type MonitoringLiveEvent,
} from 'depictio-react-core';

import { absTime, formatDuration, matchesQuery, spanMs, stepTally } from './format';
import { DetailBlock, Field, PaneHeader, PathTip, SearchInput, TimeText } from './primitives';
import {
  ACCORDION_CLASSNAMES,
  ACCORDION_STYLES,
  PANE_SCROLL_H,
  statusColor,
} from './tokens';
import { useLivePolling, type LiveFeed } from './usePolling';
import { applyIngestionEvent, runOrigin } from './runs';
import { IngestionStepTimeline } from './IngestionStepTimeline';
import { TriggerBadge } from './TriggerBadge';
import { useQuietTags, useTone } from './useTone';
import { PaneEmptyState, RedactedNote } from './notices';

/** Instances and project names seen in ingestion runs, for the Ingestion
 *  pane's selects. `projects` maps project id to name. */
interface RunFilterOptions {
  instances: string[];
  projects: Record<string, string>;
}

/** What a run's instance badge shows and the instance filter matches: the
 *  configured label, else the CLI's hostname (the label is optional and most
 *  CLI configs leave it unset). */
function runInstance(r: MonitoringIngestionRun): string | null {
  return r.cli_instance_label || r.cli_hostname || null;
}

/** Fold `runs` into `prev`, returning `prev` itself when nothing is new so a
 *  poll that brings no new instance or project doesn't re-render. */
function mergeRunFilterOptions(
  prev: RunFilterOptions,
  runs: MonitoringIngestionRun[],
): RunFilterOptions {
  let { instances, projects } = prev;
  for (const r of runs) {
    const label = runInstance(r);
    if (label && !instances.includes(label)) instances = [...instances, label];
    if (r.project_id) {
      const name = r.project_name || projects[r.project_id] || r.project_id;
      if (projects[r.project_id] !== name) projects = { ...projects, [r.project_id]: name };
    }
  }
  return instances === prev.instances && projects === prev.projects
    ? prev
    : { instances, projects };
}

/** Instance select entries, sorted. The selected value stays listed even when
 *  no fetched run carries it (a shared link to a quiet instance). */
function instanceSelectData(options: RunFilterOptions, selected: string | null): string[] {
  const values = new Set(options.instances);
  if (selected) values.add(selected);
  return [...values].sort((a, b) => a.localeCompare(b));
}

/** Project select entries sorted by name, the id's tail appended when several
 *  projects share a name. The selected id stays listed, as above. */
function projectSelectData(
  options: RunFilterOptions,
  selected: string | null,
): { value: string; label: string }[] {
  const entries = Object.entries(options.projects);
  if (selected && !(selected in options.projects)) entries.push([selected, selected]);
  const counts = new Map<string, number>();
  for (const [, name] of entries) counts.set(name, (counts.get(name) ?? 0) + 1);
  return entries
    .map(([id, name]) => ({
      value: id,
      label: (counts.get(name) ?? 0) > 1 ? `${name} (${id.slice(-6)})` : name,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Ingestion runs. Shared by Admin > Log & Task (every run) and the Activity
 *  page (the runs of the reader's projects, redacted unless they can edit the
 *  project); the API decides what comes back. */
export const IngestionPane: React.FC<{
  feed: LiveFeed<MonitoringLiveEvent>;
  filters: IngestionFilters;
  onFiltersChange: (next: IngestionFilters) => void;
}> = ({ feed, filters, onFiltersChange }) => {
  const tone = useTone();
  const quiet = useQuietTags();
  const { status, instance, projectId, q } = filters;
  const [auto, setAuto] = useState(true);
  // Controlled open rows: only the expanded run mounts its field grid + steps
  // table, keeping a large run list light on load and on refresh.
  const [open, setOpen] = useState<string[]>([]);
  // Status, instance and project filter server-side, so matches older than the
  // 200 newest runs still show; the text search narrows what came back.
  const load = useCallback(
    () =>
      fetchIngestionRuns({
        status: status || undefined,
        instance: instance || undefined,
        projectId: projectId || undefined,
        limit: 200,
      }),
    [status, instance, projectId],
  );
  const serverFiltered = Boolean(status || instance || projectId);

  // With server-side filters on, a run missing from the list may simply be one
  // the filters exclude, and refetching on each of its step events would bring
  // back the per-step full-list reads that patching exists to avoid. Refetch
  // once per (run, status) instead: a status change can bring a run into the
  // filter (running to failed), a step event cannot.
  const missedRuns = useRef(new Map<string, string>());
  useEffect(() => {
    missedRuns.current.clear();
  }, [load]);
  const patchRuns = useCallback(
    (current: MonitoringIngestionRun[] | null, event: MonitoringLiveEvent) => {
      const next = applyIngestionEvent(current, event);
      if (next !== null || !current || !serverFiltered) return next;
      if (event.event_type !== 'ingestion_event') return next;
      const payload = (event.payload ?? {}) as { run_id?: string; status?: string };
      if (!payload.run_id) return next;
      const seenStatus = payload.status ?? '';
      if (missedRuns.current.get(payload.run_id) === seenStatus) return current;
      missedRuns.current.set(payload.run_id, seenStatus);
      return null;
    },
    [serverFiltered],
  );
  // Patch in place rather than refetch: a run emits one event per step, so
  // refetching 200 full runs each time would put this pane under continuous
  // load for the whole of a run, and a watcher never stops producing them.
  const { data, loading, error, refresh } = useLivePolling<
    MonitoringIngestionRun[],
    MonitoringLiveEvent
  >(load, auto, feed, { patch: patchRuns });

  // Select options accumulate over every response, seeded by one unfiltered
  // fetch, so narrowing to one instance doesn't shrink the list to that one.
  const [options, setOptions] = useState<RunFilterOptions>({ instances: [], projects: {} });
  useEffect(() => {
    let cancelled = false;
    fetchIngestionRuns({ limit: 500 })
      .then((all) => {
        if (!cancelled) setOptions((prev) => mergeRunFilterOptions(prev, all));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    if (data) setOptions((prev) => mergeRunFilterOptions(prev, data));
  }, [data]);

  const setFilter = (patch: Partial<IngestionFilters>) =>
    onFiltersChange({ ...filters, ...patch });
  const projectNames = options.projects;
  // The filters in force, as the empty state lists them. They come from the
  // address bar too (`?status=`, `instance`, `project`), so a shared link that
  // matches nothing says why instead of looking like an empty ledger.
  const filterChips = [
    ...(status ? [{ key: 'status', label: `status: ${status}` }] : []),
    ...(instance ? [{ key: 'instance', label: `instance: ${instance}` }] : []),
    ...(projectId
      ? [{ key: 'project', label: `project: ${projectNames[projectId] ?? projectId}` }]
      : []),
    ...(q.trim() ? [{ key: 'q', label: `search: ${q.trim()}` }] : []),
  ];
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
        extra={
          <Group gap="xs" wrap="nowrap">
            <SearchInput value={q} onChange={(v) => setFilter({ q: v })} />
            <Select
              size="xs"
              placeholder="Status"
              clearable
              w={120}
              value={status}
              onChange={(v) => setFilter({ status: v as IngestionStatusFilter | null })}
              data={[...INGESTION_STATUSES]}
            />
            <Select
              size="xs"
              placeholder="Instance"
              clearable
              searchable
              w={150}
              // Hostnames outgrow the input; let the list show them whole.
              comboboxProps={{ width: 280, position: 'bottom-end' }}
              value={instance}
              onChange={(v) => setFilter({ instance: v })}
              data={instanceSelectData(options, instance)}
              nothingFoundMessage="No matching instance"
            />
            <Select
              size="xs"
              placeholder="Project"
              clearable
              searchable
              w={190}
              value={projectId}
              onChange={(v) => setFilter({ projectId: v })}
              data={projectSelectData(options, projectId)}
              nothingFoundMessage="No matching project"
            />
          </Group>
        }
      />
      {error && (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      )}
      {!loading && runs.length === 0 && !error ? (
        <PaneEmptyState
          noun="ingestion runs"
          source="Ingestion runs come from the depictio CLI (ingest and watch), table uploads in the web UI and project imports. Runs for a project show up here once someone ingests its data."
          chips={filterChips}
          onClear={() => onFiltersChange({ ...EMPTY_INGESTION_FILTERS })}
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
            {runs.map((r) => (
            <Accordion.Item key={r.run_id} value={r.run_id}>
              <Accordion.Control>
                <Group gap="sm" wrap="nowrap">
                  {/* Wider than the Tasks column: fits "interrupted". */}
                  <Box w={96} style={{ flexShrink: 0 }}>
                    <Badge
                      size="xs"
                      fullWidth
                      color={tone(statusColor(r.status))}
                      variant="filled"
                      leftSection={
                        r.status === 'running' ? <Loader size={8} color={quiet ? 'yellow' : 'white'} /> : undefined
                      }
                    >
                      {r.status}
                    </Badge>
                  </Box>
                  {/* Fits "upload" and "server"; the full label is in the details. */}
                  <Box w={56} style={{ flexShrink: 0 }}>
                    <Badge size="xs" fullWidth color={tone(runOrigin(r).color)} variant="light">
                      {runOrigin(r).badge}
                    </Badge>
                  </Box>
                  {/* Sized for a typical hostname and not uppercased, which
                      widens it; a longer one truncates and the tooltip has it whole. */}
                  <Box w={190} style={{ flexShrink: 0 }}>
                    <Tooltip label={runInstance(r) ?? 'unknown'} openDelay={400}>
                      <Badge size="xs" fullWidth tt="none" color={tone('blue')} variant="outline">
                        {runInstance(r) ?? 'unknown'}
                      </Badge>
                    </Tooltip>
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
                  {r.redacted && (
                    <RedactedNote what="Commands, local paths, user details and step messages" />
                  )}
                  <SimpleGrid cols={{ base: 2, xs: 3, sm: 4 }} spacing="md" verticalSpacing="xs">
                    <Field label="Project">{r.project_name || '—'}</Field>
                    <Field label="User">{r.email || '—'}</Field>
                    <Field label="Source">{runOrigin(r).label}</Field>
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
