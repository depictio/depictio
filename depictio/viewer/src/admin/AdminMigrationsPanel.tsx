import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Drawer,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { listMigrationRequests, retryMigrationRequest } from 'depictio-react-core';
import type { MigrationRequestSummary } from 'depictio-react-core';

import { formatDateTime } from '../lib/datetime';
import AdminMigrationInvitesView from './AdminMigrationInvitesView';
import AdminMigrationSentView from './AdminMigrationSentView';
import { RequestDetail, StatusBadge, formatBytes, modeLabel } from './MigrationRequestDetail';

const STATUS_FILTERS = [
  { value: '', label: 'All statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'importing', label: 'Importing' },
  { value: 'imported', label: 'Imported' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'failed', label: 'Failed' },
  { value: 'superseded', label: 'Superseded' },
];

/**
 * Requests: projects other Depictio instances pushed here. A pairing-key push
 * waits for review: an admin inspects the validation report, then approves (the
 * import runs in the background) or rejects with a reason. An invite-code push
 * imports at once; it shows here too, and a failed one can be retried.
 */
const RequestsView: React.FC = () => {
  const [requests, setRequests] = useState<MigrationRequestSummary[]>([]);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);

  const handleRetry = async (id: string) => {
    setRetrying(id);
    try {
      await retryMigrationRequest(id);
      notifications.show({ message: 'Import started again.' });
      await load();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not retry',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setRetrying(null);
    }
  };

  const load = useCallback(async () => {
    try {
      setRequests(await listMigrationRequests(status || undefined));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load migration requests.');
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={4}>Migration requests</Title>
        <Group gap="xs">
          <Select
            size="xs"
            w={170}
            allowDeselect={false}
            aria-label="Filter by status"
            data={STATUS_FILTERS}
            value={status}
            onChange={(v) => setStatus(v ?? '')}
            data-testid="migrations-status-filter"
          />
          <Button
            size="xs"
            variant="default"
            onClick={() => void load()}
            leftSection={<Icon icon="mdi:refresh" width={14} />}
          >
            Refresh
          </Button>
        </Group>
      </Group>

      {loading ? (
        <Center mih={120}>
          <Loader />
        </Center>
      ) : error ? (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      ) : requests.length === 0 ? (
        <Center mih={120}>
          <Text c="dimmed" size="sm" data-testid="migrations-empty">
            No migration requests.
          </Text>
        </Center>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table withTableBorder highlightOnHover fz="sm" data-testid="migrations-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Status</Table.Th>
                <Table.Th>Source</Table.Th>
                <Table.Th>Requester</Table.Th>
                <Table.Th>Project</Table.Th>
                <Table.Th>Mode</Table.Th>
                <Table.Th>Size</Table.Th>
                <Table.Th>Submitted</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {requests.map((r) => (
                <Table.Tr
                  key={r.id}
                  style={{ cursor: 'pointer' }}
                  onClick={() => setSelected(r.id)}
                  data-testid="migration-row"
                  data-status={r.status}
                >
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <StatusBadge status={r.status} />
                      {r.credential_type === 'invite_code' && (
                        <Badge color="grape" variant="outline" size="xs">
                          invite
                        </Badge>
                      )}
                      {r.error_count > 0 && (
                        <Badge color="red" variant="outline" size="xs">
                          {r.error_count} err
                        </Badge>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>{r.source_name}</Table.Td>
                  <Table.Td>{r.requester?.email ?? r.requester?.name ?? '—'}</Table.Td>
                  <Table.Td>{r.project_name}</Table.Td>
                  <Table.Td>{modeLabel(r.transfer_mode)}</Table.Td>
                  <Table.Td>{formatBytes(r.bundle_bytes)}</Table.Td>
                  <Table.Td>
                    {formatDateTime(r.created_at)}
                    {r.status === 'failed' && r.error && (
                      <Text size="xs" c="red" style={{ wordBreak: 'break-word' }}>
                        {r.error}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td onClick={(e) => e.stopPropagation()}>
                    {r.retryable && (
                      <Button
                        size="compact-xs"
                        variant="light"
                        loading={retrying === r.id}
                        onClick={() => void handleRetry(r.id)}
                        leftSection={<Icon icon="mdi:reload" width={14} />}
                        data-testid="migration-retry"
                      >
                        Retry
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <Drawer
        opened={selected !== null}
        onClose={() => setSelected(null)}
        position="right"
        size="lg"
        title="Migration request"
      >
        {selected && (
          <RequestDetail
            requestId={selected}
            onClose={() => setSelected(null)}
            onChanged={() => void load()}
          />
        )}
      </Drawer>
    </Stack>
  );
};

/**
 * Admin > Migrations: what other instances pushed here (Requests), the codes
 * that let them (Invitations), and what this instance pushed out (Sent).
 */
const AdminMigrationsPanel: React.FC = () => {
  const [tab, setTab] = useState<string>('requests');
  return (
    <Tabs value={tab} onChange={(v) => v && setTab(v)} keepMounted={false}>
      <Tabs.List mb="md">
        <Tabs.Tab value="requests" data-testid="migrations-tab-requests">
          Requests
        </Tabs.Tab>
        <Tabs.Tab value="invitations" data-testid="migrations-tab-invitations">
          Invitations
        </Tabs.Tab>
        <Tabs.Tab value="sent" data-testid="migrations-tab-sent">
          Sent
        </Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="requests">
        <RequestsView />
      </Tabs.Panel>
      <Tabs.Panel value="invitations">
        <AdminMigrationInvitesView />
      </Tabs.Panel>
      <Tabs.Panel value="sent">
        <AdminMigrationSentView />
      </Tabs.Panel>
    </Tabs>
  );
};

export default AdminMigrationsPanel;
