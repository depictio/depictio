import React, { useCallback, useState } from 'react';
import { Alert, Stack, Table, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { listPushes, type MigrationPush } from 'depictio-react-core';

import { formatDateTime } from '../lib/datetime';
import { PaneEmptyState } from '../monitoring/notices';
import { PaneHeader } from '../monitoring/primitives';
import { usePolling } from '../monitoring/usePolling';
import { PushStatusBadges, pushDestinationLabel, pushResultLabel } from '../projects/pushStatus';

/**
 * Projects pushed from this instance to another, newest first. Read-only: a
 * failed push is retried from the project's own settings, not from here.
 *
 * The API scopes the list: an admin sees every push, anyone else their own.
 */
export const SendsPane: React.FC = () => {
  const [auto, setAuto] = useState(true);
  const load = useCallback(() => listPushes(), []);
  const { data, loading, error, refresh } = usePolling<MigrationPush[]>(load, auto);
  const pushes = data ?? [];

  return (
    <Stack gap="sm">
      <PaneHeader
        title="Sends to other instances"
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
      {!loading && pushes.length === 0 && !error ? (
        <PaneEmptyState
          noun="sends"
          source="A send is a project you pushed to another depictio instance, from the project's settings (Send). Your own sends are listed here with their status."
        />
      ) : (
        <Table.ScrollContainer minWidth={760}>
          <Table withTableBorder fz="xs" data-testid="activity-sends-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Project</Table.Th>
                <Table.Th>Destination</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Result</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pushes.map((p) => (
                <Table.Tr key={p.id} data-status={p.status}>
                  <Table.Td>{p.project_name ?? p.project_id}</Table.Td>
                  <Table.Td>{pushDestinationLabel(p)}</Table.Td>
                  <Table.Td>
                    <PushStatusBadges push={p} />
                  </Table.Td>
                  <Table.Td>{formatDateTime(p.created_at)}</Table.Td>
                  <Table.Td>
                    {p.error ? (
                      <Text size="xs" c="red" style={{ wordBreak: 'break-word' }}>
                        {p.error}
                      </Text>
                    ) : (
                      <Text size="xs" c="dimmed">
                        {pushResultLabel(p) ?? '—'}
                      </Text>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
};
