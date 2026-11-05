import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { listMigrationInvites, revokeMigrationInvite } from 'depictio-react-core';
import type { MigrationInvite, MigrationInviteList } from 'depictio-react-core';

import { formatDateTime } from '../lib/datetime';
import { useTone } from '../monitoring/useTone';
import ReceiveProjectModal from './ReceiveProjectModal';

const STATE_COLOR: Record<string, string> = {
  active: 'green',
  used: 'blue',
  expired: 'gray',
  revoked: 'gray',
};

/** Admin > Migrations > Invitations: codes other instances use to publish here. */
const AdminMigrationInvitesView: React.FC = () => {
  const tone = useTone();
  const [data, setData] = useState<MigrationInviteList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await listMigrationInvites());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load invitations.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleRevoke = async (invite: MigrationInvite) => {
    setRevoking(invite.id);
    try {
      await revokeMigrationInvite(invite.id);
      notifications.show({ message: 'Invitation revoked.' });
      await load();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not revoke',
        message: err instanceof Error ? err.message : 'Unknown error',
      });
    } finally {
      setRevoking(null);
    }
  };

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={4}>Invitations</Title>
        <Group gap="xs">
          <Button
            size="xs"
            variant="default"
            onClick={() => void load()}
            leftSection={<Icon icon="mdi:refresh" width={14} />}
          >
            Refresh
          </Button>
          {data?.inbound_enabled && (
            <Button
              size="xs"
              onClick={() => setCreating(true)}
              leftSection={<Icon icon="mdi:key-plus" width={14} />}
              data-testid="invites-receive"
            >
              Receive a project
            </Button>
          )}
        </Group>
      </Group>

      {data && !data.inbound_enabled && (
        <Alert color="yellow" variant="light" data-testid="invites-disabled">
          This instance does not accept pushed projects, so no invitation can be created. Set
          DEPICTIO_MIGRATION_INBOUND_ENABLED to allow it.
        </Alert>
      )}

      {loading ? (
        <Center mih={120}>
          <Loader />
        </Center>
      ) : error ? (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {error}
        </Alert>
      ) : (data?.invites.length ?? 0) === 0 ? (
        <Center mih={120}>
          <Text c="dimmed" size="sm" data-testid="invites-empty">
            No invitations.
          </Text>
        </Center>
      ) : (
        <Table.ScrollContainer minWidth={900}>
          <Table withTableBorder fz="sm" data-testid="invites-table">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>State</Table.Th>
                <Table.Th>Policy</Table.Th>
                <Table.Th>Code</Table.Th>
                <Table.Th>Expires</Table.Th>
                <Table.Th>Uses</Table.Th>
                <Table.Th>Project</Table.Th>
                <Table.Th>Note</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data?.invites.map((inv) => (
                <Table.Tr key={inv.id} data-testid="invite-row" data-state={inv.state}>
                  <Table.Td>
                    <Badge variant="light" size="sm" color={tone(STATE_COLOR[inv.state] ?? 'gray')}>
                      {inv.state}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {inv.policy === 'single_use' ? 'One push' : 'Push + updates'}
                    <Text size="xs" c="dimmed">
                      {inv.lock_on_import ? 'locks on import' : 'editable'}
                    </Text>
                  </Table.Td>
                  <Table.Td ff="monospace">…{inv.code_hint}</Table.Td>
                  <Table.Td>{inv.expires_at ? formatDateTime(inv.expires_at) : 'Never'}</Table.Td>
                  <Table.Td>{inv.use_count}</Table.Td>
                  <Table.Td>{inv.lineage_project_name ?? '—'}</Table.Td>
                  <Table.Td>{inv.note ?? '—'}</Table.Td>
                  <Table.Td>
                    {inv.state !== 'revoked' && (
                      <Button
                        size="compact-xs"
                        color="red"
                        variant="light"
                        loading={revoking === inv.id}
                        onClick={() => void handleRevoke(inv)}
                        data-testid="invite-revoke"
                      >
                        Revoke
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <ReceiveProjectModal
        opened={creating}
        onClose={() => setCreating(false)}
        onCreated={() => void load()}
      />
    </Stack>
  );
};

export default AdminMigrationInvitesView;
