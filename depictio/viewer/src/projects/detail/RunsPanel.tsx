/**
 * The project's runs: one row per run folder, with when the folder and its
 * ingestions happened, and, unfolded, how many files each collection found in
 * it and every scan of it. A collection that found nothing in a run is what
 * this view is for: it shows a run that is incomplete.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Center,
  Collapse,
  CopyButton,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectRuns } from 'depictio-react-core';
import type { ProjectRun } from 'depictio-react-core';

import { DcTypeIcon } from '../dcTypeIcon';
import { formatTimestamp } from './DcViewerParts';

const SEARCH_FROM = 9;

const STATUS: Record<string, { label: string; color: string; hint: string }> = {
  ok: { label: 'Complete', color: 'teal', hint: 'Every collection found files in this run.' },
  incomplete: {
    label: 'Incomplete',
    color: 'orange',
    hint: 'At least one collection found no file in this run.',
  },
  partial: { label: 'Failures', color: 'red', hint: 'Some files of this run could not be read.' },
  no_scan: { label: 'Not scanned', color: 'gray', hint: 'This run was registered but never scanned.' },
};

/** Run times are written with the server's local clock. */
const when = (value: string | null | undefined) => formatTimestamp(value, { utc: false }) ?? '—';

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const s = STATUS[status] ?? { label: status, color: 'gray', hint: '' };
  return (
    <Tooltip label={s.hint} withArrow disabled={!s.hint}>
      <Badge variant="light" color={s.color} radius="sm" tt="none" fw={500}>
        {s.label}
      </Badge>
    </Tooltip>
  );
};

const Label: React.FC<{ icon: string; children: React.ReactNode }> = ({ icon, children }) => (
  <Group gap={6} mb={8} wrap="nowrap">
    <Icon icon={icon} width={14} style={{ opacity: 0.6 }} />
    <Text size="xs" c="dimmed" fw={600} tt="uppercase">
      {children}
    </Text>
  </Group>
);

const RunDetails: React.FC<{
  run: ProjectRun;
  dcIdByTag: Record<string, string>;
  dcTypeByTag: Record<string, string>;
  onOpenDc?: (dcId: string) => void;
}> = ({ run, dcIdByTag, dcTypeByTag, onOpenDc }) => {
  // Missing ones first: they are why the run is incomplete.
  const dcs = Object.entries(run.dc_files).sort(
    ([a, n], [b, m]) => Number(n > 0) - Number(m > 0) || a.localeCompare(b),
  );
  return (
    <Stack gap="md" py="sm" px="xs" data-testid={`run-details-${run.run_tag}`}>
      {run.run_location && (
        <Group gap={6} wrap="nowrap" align="flex-start">
          <Icon icon="mdi:folder-outline" width={16} style={{ opacity: 0.6, flexShrink: 0, marginTop: 2 }} />
          <Text size="sm" ff="monospace" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
            {run.run_location}
          </Text>
          <CopyButton value={run.run_location} timeout={1500}>
            {({ copied, copy }) => (
              <Tooltip label={copied ? 'Copied' : 'Copy the folder path'} withArrow>
                <ActionIcon
                  size="sm"
                  variant="subtle"
                  color="gray"
                  onClick={copy}
                  aria-label="Copy the folder path"
                  data-testid={`run-copy-path-${run.run_tag}`}
                >
                  <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                </ActionIcon>
              </Tooltip>
            )}
          </CopyButton>
        </Group>
      )}
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xl">
        <div>
          <Label icon="mdi:database-outline">Collections in this run</Label>
          <Stack gap={2}>
            {dcs.map(([tag, n]) => {
              const id = dcIdByTag[tag];
              const missing = n === 0;
              const name = (
                <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                  <DcTypeIcon type={dcTypeByTag[tag] ?? 'table'} size={16} withTooltip={false} />
                  <Text size="sm" fw={500} truncate="end">
                    {tag}
                  </Text>
                </Group>
              );
              return (
                <Group
                  key={tag}
                  justify="space-between"
                  wrap="nowrap"
                  gap="sm"
                  px="xs"
                  py={4}
                  style={{
                    borderRadius: 'var(--mantine-radius-sm)',
                    background: missing ? 'var(--mantine-color-orange-light)' : undefined,
                  }}
                >
                  {id && onOpenDc ? (
                    <Tooltip label="Open this collection" withArrow>
                      <UnstyledButton onClick={() => onOpenDc(id)} style={{ minWidth: 0 }}>
                        {name}
                      </UnstyledButton>
                    </Tooltip>
                  ) : (
                    name
                  )}
                  {missing ? (
                    <Text size="xs" fw={600} c="orange" style={{ whiteSpace: 'nowrap' }}>
                      <Icon icon="mdi:alert-outline" width={14} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                      Nothing found
                    </Text>
                  ) : (
                    <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                      {n === 1 ? '1 file' : `${n} files`}
                    </Text>
                  )}
                </Group>
              );
            })}
            {dcs.length === 0 && (
              <Text size="sm" c="dimmed">
                No collection reads files per run.
              </Text>
            )}
          </Stack>
        </div>
        <div>
          <Label icon="mdi:history">Scans</Label>
          {run.scans.length === 0 ? (
            <Text size="sm" c="dimmed">
              Never scanned.
            </Text>
          ) : (
            <Stack gap={0}>
              {[...run.scans].reverse().map((s, i) => (
                <Group
                  key={`${s.scan_time}-${i}`}
                  justify="space-between"
                  wrap="nowrap"
                  gap="sm"
                  py={6}
                  style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}
                >
                  <Group gap={8} wrap="nowrap">
                    <Icon
                      icon={i === 0 ? 'mdi:circle' : 'mdi:circle-outline'}
                      width={10}
                      style={{ opacity: i === 0 ? 0.8 : 0.4 }}
                    />
                    <Text size="sm" style={{ whiteSpace: 'nowrap' }}>
                      {when(s.scan_time)}
                    </Text>
                    {i === 0 && (
                      <Text size="xs" c="dimmed">
                        latest
                      </Text>
                    )}
                  </Group>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" c="dimmed" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {s.files_total === 1 ? '1 file' : `${s.files_total} files`}
                    </Text>
                    {s.files_new > 0 && (
                      <Badge size="sm" variant="light" color="blue" radius="sm" tt="none">
                        +{s.files_new} new
                      </Badge>
                    )}
                    {s.files_updated > 0 && (
                      <Badge size="sm" variant="light" color="orange" radius="sm" tt="none">
                        {s.files_updated} updated
                      </Badge>
                    )}
                    {s.files_failed > 0 && (
                      <Badge size="sm" variant="light" color="red" radius="sm" tt="none">
                        {s.files_failed} failed
                      </Badge>
                    )}
                  </Group>
                </Group>
              ))}
            </Stack>
          )}
        </div>
      </SimpleGrid>
    </Stack>
  );
};

export const RunsPanel: React.FC<{
  projectId: string;
  refreshKey?: number;
  /** Open on this run, found and unfolded (a link from elsewhere on the page). */
  focusRun?: string | null;
  dcIdByTag: Record<string, string>;
  /** Tag → collection type, for each collection's icon. */
  dcTypeByTag: Record<string, string>;
  onOpenDc?: (dcId: string) => void;
}> = ({ projectId, refreshKey = 0, focusRun = null, dcIdByTag, dcTypeByTag, onOpenDc }) => {
  const [runs, setRuns] = useState<ProjectRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState(focusRun ?? '');
  const [open, setOpen] = useState<Set<string>>(new Set(focusRun ? [focusRun] : []));

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchProjectRuns(projectId)
      .then((r) => {
        if (!cancelled) setRuns(r.runs);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message || 'The runs could not be loaded.');
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey]);

  useEffect(() => {
    if (!focusRun) return;
    setQuery(focusRun);
    setOpen(new Set([focusRun]));
  }, [focusRun]);

  const workflows = useMemo(() => new Set((runs ?? []).map((r) => r.workflow).filter(Boolean)), [runs]);
  if (error) {
    return (
      <Alert color="red" variant="light">
        {error}
      </Alert>
    );
  }
  if (!runs) {
    return (
      <Center py="lg">
        <Loader size="sm" />
      </Center>
    );
  }
  if (runs.length === 0) {
    return (
      <Text size="sm" c="dimmed" data-testid="runs-panel-empty">
        This project has no pipeline run yet. Runs come from a run folder, added with “Add data” or
        with the CLI.
      </Text>
    );
  }

  const needle = query.trim().toLowerCase();
  const shown = needle ? runs.filter((r) => r.run_tag.toLowerCase().includes(needle)) : runs;
  const counts = runs.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});
  const toggle = (tag: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  const multiWorkflow = workflows.size > 1;

  return (
    <Stack gap="sm" data-testid="runs-panel">
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Group gap="xs" wrap="wrap">
          <Text size="sm" fw={600}>
            {runs.length === 1 ? '1 run' : `${runs.length} runs`}
          </Text>
          {Object.entries(counts)
            .filter(([status]) => status !== 'ok')
            .map(([status, n]) => (
              <Badge
                key={status}
                variant="light"
                color={STATUS[status]?.color ?? 'gray'}
                radius="sm"
                tt="none"
                fw={500}
              >
                {n} {(STATUS[status]?.label ?? status).toLowerCase()}
              </Badge>
            ))}
        </Group>
        {runs.length >= SEARCH_FROM && (
          <TextInput
            size="xs"
            w={260}
            placeholder="Search runs"
            aria-label="Search runs"
            leftSection={<Icon icon="mdi:magnify" width={14} />}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            data-testid="runs-panel-search"
          />
        )}
      </Group>
      <Table.ScrollContainer minWidth={760}>
        <Table verticalSpacing={8} highlightOnHover layout="auto">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={28} />
              <Table.Th fz="xs" c="dimmed">Run</Table.Th>
              {multiWorkflow && <Table.Th fz="xs" c="dimmed">Pipeline</Table.Th>}
              <Table.Th fz="xs" c="dimmed">Folder modified</Table.Th>
              <Table.Th fz="xs" c="dimmed">First ingested</Table.Th>
              <Table.Th fz="xs" c="dimmed">Last scan</Table.Th>
              <Table.Th fz="xs" c="dimmed" ta="right">Files</Table.Th>
              <Table.Th fz="xs" c="dimmed">Status</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map((run) => {
              const isOpen = open.has(run.run_tag);
              const last = run.scans[run.scans.length - 1];
              return (
                <React.Fragment key={run.run_tag}>
                  <Table.Tr
                    onClick={() => toggle(run.run_tag)}
                    style={{ cursor: 'pointer' }}
                    data-testid={`run-row-${run.run_tag}`}
                  >
                    <Table.Td>
                      <ActionIcon
                        variant="subtle"
                        color="gray"
                        size="sm"
                        aria-label={isOpen ? 'Hide details' : 'Show details'}
                        aria-expanded={isOpen}
                      >
                        <Icon icon={isOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
                      </ActionIcon>
                    </Table.Td>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <Text size="sm" fw={600} ff="monospace">
                        {run.run_tag}
                      </Text>
                    </Table.Td>
                    {multiWorkflow && (
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>
                        <Text size="sm">{run.workflow ?? '—'}</Text>
                      </Table.Td>
                    )}
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <Text size="sm">{when(run.folder_modified)}</Text>
                    </Table.Td>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <Text size="sm">{when(run.registered)}</Text>
                    </Table.Td>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <Text size="sm">{when(last?.scan_time)}</Text>
                    </Table.Td>
                    <Table.Td ta="right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                      <Text size="sm">{run.files}</Text>
                    </Table.Td>
                    <Table.Td>
                      <StatusBadge status={run.status} />
                    </Table.Td>
                  </Table.Tr>
                  <Table.Tr style={{ display: isOpen ? undefined : 'none' }}>
                    <Table.Td />
                    <Table.Td colSpan={multiWorkflow ? 7 : 6} pt={0}>
                      <Collapse in={isOpen}>
                        <RunDetails run={run} dcIdByTag={dcIdByTag} dcTypeByTag={dcTypeByTag} onOpenDc={onOpenDc} />
                      </Collapse>
                    </Table.Td>
                  </Table.Tr>
                </React.Fragment>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {shown.length === 0 && (
        <Text size="sm" c="dimmed">
          No run matches “{query}”.
        </Text>
      )}
    </Stack>
  );
};

export default RunsPanel;
