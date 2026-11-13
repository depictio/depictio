/**
 * The project's runs: one row per run folder, with when the folder and its
 * ingestions happened, and, unfolded, how many files each collection found in
 * it and every scan of it. A collection that found nothing in a run is what
 * this view is for: it shows a run that is incomplete. Unfolded, a run lists
 * its files and what each scan did to them (`RunDetails`).
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Center,
  Collapse,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectRuns } from 'depictio-react-core';
import type { ProjectRun } from 'depictio-react-core';

import { StatusBadge } from '../badges';
import { RunDetails, when } from './RunDetails';

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

const RunStatus: React.FC<{ status: string }> = ({ status }) => {
  const s = STATUS[status] ?? { label: status, color: 'gray', hint: '' };
  return (
    <Tooltip label={s.hint} withArrow disabled={!s.hint}>
      <StatusBadge color={s.color} data-testid="run-status">
        {s.label}
      </StatusBadge>
    </Tooltip>
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
              <StatusBadge key={status} color={STATUS[status]?.color ?? 'gray'}>
                {n} {(STATUS[status]?.label ?? status).toLowerCase()}
              </StatusBadge>
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
                <React.Fragment key={`${run.workflow ?? ''}/${run.run_tag}`}>
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
                      <RunStatus status={run.status} />
                    </Table.Td>
                  </Table.Tr>
                  <Table.Tr style={{ display: isOpen ? undefined : 'none' }}>
                    <Table.Td />
                    <Table.Td colSpan={multiWorkflow ? 7 : 6} pt={0}>
                      <Collapse in={isOpen}>
                        {isOpen && (
                          <RunDetails
                            projectId={projectId}
                            run={run}
                            dcIdByTag={dcIdByTag}
                            dcTypeByTag={dcTypeByTag}
                            onOpenDc={onOpenDc}
                          />
                        )}
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
