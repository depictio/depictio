/**
 * Per-data-collection outcome of an ingestion: one row per collection with
 * its status, how many entries it read, and the message that explains a
 * failure or a skip.
 *
 * Shared by every flow that ingests or re-ingests collections and reports
 * back (the manifest tab of the create-project dialog, its post-create
 * review, the project's Data refresh settings, and the run a project created
 * from a run folder starts), so a status reads the same wherever it shows up.
 */
import React from 'react';
import { Badge, Group, Table, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ManifestRefreshStatus } from 'depictio-react-core';

/** Every status a row can carry: the statuses of a polled worker run, which
 *  include those of a one-shot manifest ingestion. `planned` is a dry run;
 *  `dispatched` and `running` only show up while a worker run is being
 *  polled; `skipped` is an optional collection whose source is absent. */
export type IngestionRowStatus = ManifestRefreshStatus;

/** Visual treatment per status: an icon and a label beside the colour, so the
 *  status never rests on colour alone. Colours are Mantine palette names. The
 *  one source for every ingestion status, and the order `summarizeManifestRun`
 *  lists its counts in. */
export const INGESTION_STATUS_META: Record<
  IngestionRowStatus,
  { color: string; icon: string; label: string }
> = {
  ingested: { color: 'green', icon: 'mdi:check-circle', label: 'Ingested' },
  planned: { color: 'blue', icon: 'mdi:clock-outline', label: 'Planned' },
  dispatched: { color: 'blue', icon: 'mdi:tray-arrow-down', label: 'Queued' },
  running: { color: 'blue', icon: 'mdi:progress-clock', label: 'Running' },
  failed: { color: 'red', icon: 'mdi:alert-circle', label: 'Failed' },
  skipped: { color: 'gray', icon: 'mdi:minus-circle-outline', label: 'Skipped' },
};

/** The fields a row needs; the manifest create, refresh and run reports all
 *  carry them. */
export interface IngestionResultRow {
  data_collection_tag: string;
  entries: number;
  status: string;
  message?: string | null;
}

function metaOf(status: string) {
  return (
    INGESTION_STATUS_META[status as IngestionRowStatus] ?? {
      color: 'gray',
      icon: 'mdi:help-circle-outline',
      label: status,
    }
  );
}

/** The status as a badge: icon, label and colour together. */
export const IngestionStatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const meta = metaOf(status);
  return (
    <Badge
      variant="light"
      color={meta.color}
      size="sm"
      leftSection={<Icon icon={meta.icon} width={12} />}
    >
      {meta.label}
    </Badge>
  );
};

interface IngestionResultTableProps {
  rows: ReadonlyArray<IngestionResultRow>;
  /** Shown instead of the table when there is no row. */
  emptyText: string;
  /** Rows get `data-testid="<prefix>-row-<tag>"` and `data-status`. */
  rowTestIdPrefix?: string;
  testId?: string;
}

const IngestionResultTable: React.FC<IngestionResultTableProps> = ({
  rows,
  emptyText,
  rowTestIdPrefix = 'ingestion-result',
  testId,
}) => {
  if (rows.length === 0) {
    return (
      <Group gap="xs" wrap="nowrap" data-testid={testId}>
        <ThemeIcon variant="light" color="gray" size="md" radius="md">
          <Icon icon="mdi:table-off" width={16} />
        </ThemeIcon>
        <Text size="sm" c="dimmed">
          {emptyText}
        </Text>
      </Group>
    );
  }
  return (
    <Table.ScrollContainer minWidth={480} data-testid={testId}>
      <Table verticalSpacing="xs" striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Data collection</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th ta="right">Entries</Table.Th>
            <Table.Th>Details</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row) => (
            <Table.Tr
              key={row.data_collection_tag}
              data-testid={`${rowTestIdPrefix}-row-${row.data_collection_tag}`}
              data-status={row.status}
            >
              <Table.Td>
                <Text size="sm" fw={600}>
                  {row.data_collection_tag}
                </Text>
              </Table.Td>
              <Table.Td>
                <IngestionStatusBadge status={row.status} />
              </Table.Td>
              <Table.Td ta="right">
                <Text size="sm">{row.entries}</Text>
              </Table.Td>
              <Table.Td>
                {row.message && (
                  <Text size="xs" c={row.status === 'failed' ? 'red' : 'dimmed'}>
                    {row.message}
                  </Text>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
};

export default IngestionResultTable;
