import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Center, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';

import { listPushes } from 'depictio-react-core';
import type { MigrationPush } from 'depictio-react-core';

import { formatDateTime } from '../lib/datetime';
import {
  PushStatusBadges,
  RetryPushButton,
  isPushActive,
  pushDestinationLabel,
  pushResultLabel,
} from '../projects/pushStatus';

const POLL_MS = 5000;

/** Admin > Migrations > Sent: projects this instance pushed elsewhere. */
const AdminMigrationSentView: React.FC = () => {
  const [pushes, setPushes] = useState<MigrationPush[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPushes(await listPushes());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load sent projects.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = pushes.some(isPushActive);
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [active, load]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={4}>Sent to other instances</Title>
        <Button
          size="xs"
          variant="default"
          onClick={() => void load()}
          leftSection={<Icon icon="mdi:refresh" width={14} />}
        >
          Refresh
        </Button>
      </Group>
      {loading ? (
        <Center mih={120}>
          <Loader />
        </Center>
      ) : error ? (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      ) : pushes.length === 0 ? (
        <Center mih={120}>
          <Text c="dimmed" size="sm" data-testid="sent-empty">
            Nothing sent yet. Use Publish to… on a project.
          </Text>
        </Center>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table withTableBorder fz="sm" data-testid="sent-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Project</Table.Th>
                <Table.Th>Destination</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Updated</Table.Th>
                <Table.Th>Result</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pushes.map((p) => (
                <Table.Tr key={p.id} data-testid="sent-row" data-status={p.status}>
                  <Table.Td>{p.project_name ?? p.project_id}</Table.Td>
                  <Table.Td>
                    <Text size="sm">{pushDestinationLabel(p)}</Text>
                    {p.target_name && p.target_url && (
                      <Text size="xs" c="dimmed">
                        {p.target_url}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <PushStatusBadges push={p} />
                  </Table.Td>
                  <Table.Td>{formatDateTime(p.created_at)}</Table.Td>
                  <Table.Td>{formatDateTime(p.updated_at)}</Table.Td>
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
                  <Table.Td>
                    <RetryPushButton push={p} onRetried={() => void load()} />
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

export default AdminMigrationSentView;
