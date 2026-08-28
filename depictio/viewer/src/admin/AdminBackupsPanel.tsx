import React, { useCallback, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Center,
  FileButton,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { createBackup, downloadBackup, listBackups, uploadBackup } from 'depictio-react-core';
import type { AdminBackupEntry } from 'depictio-react-core';

import UnstyledDropZone from '../components/UnstyledDropZone';
import { formatDateTime } from '../lib/datetime';
import RestoreBackupModal from './RestoreBackupModal';
import type { RestoreTarget } from './RestoreBackupModal';

/**
 * Admin > Backups tab. One-click server-side backup (create + download),
 * a list of the backups on the server, and a restore flow: pick a listed
 * backup or upload a file → validation → typed-phrase confirmation →
 * destructive restore (see RestoreBackupModal for the safety rails).
 */
const AdminBackupsPanel: React.FC = () => {
  const [backups, setBackups] = useState<AdminBackupEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<RestoreTarget | null>(null);

  const refresh = useCallback(async () => {
    setLoadError(null);
    try {
      const rows = await listBackups();
      setBackups(rows);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to list backups');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const result = await createBackup();
      notifications.show({
        color: 'teal',
        title: 'Backup created',
        message: `${result.backup_id} — ${result.total_documents} documents.`,
        autoClose: 2500,
      });
      await refresh();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Backup failed',
        message: err instanceof Error ? err.message : 'Failed to create backup',
      });
    } finally {
      setCreating(false);
    }
  };

  const handleDownload = async (backupId: string) => {
    try {
      await downloadBackup(backupId);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Download failed',
        message: err instanceof Error ? err.message : 'Failed to download backup',
      });
    }
  };

  const handleUpload = async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadBackup(file);
      await refresh();
      if (result.backup_id) {
        // Open the restore modal directly on the validation results — the
        // upload endpoint already ran validation server-side.
        setRestoreTarget({
          backupId: result.backup_id,
          filename: result.filename ?? file.name,
          hasChecksum: true, // upload always writes a fresh sidecar
          initialValidation: result.validation ?? undefined,
        });
      }
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Upload failed',
        message: err instanceof Error ? err.message : 'Failed to upload backup',
      });
    } finally {
      setUploading(false);
    }
  };

  const renderList = () => {
    if (loading) {
      return (
        <Center mih={120}>
          <Loader />
        </Center>
      );
    }
    if (loadError) {
      return (
        <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
          {loadError}
        </Alert>
      );
    }
    if (backups.length === 0) {
      return (
        <Center mih={120}>
          <Stack align="center" gap="xs">
            <Icon icon="ph:empty-bold" width={40} color="var(--mantine-color-dimmed)" />
            <Text c="dimmed" size="sm">
              No backups on the server yet.
            </Text>
          </Stack>
        </Center>
      );
    }
    return (
      <Table.ScrollContainer minWidth={720}>
        <Table withTableBorder fz="sm" data-testid="backup-list-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Created</Table.Th>
              <Table.Th>Version</Table.Th>
              <Table.Th>Size</Table.Th>
              <Table.Th>Documents</Table.Th>
              <Table.Th>Created by</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {backups.map((b) => (
              <Table.Tr key={b.backup_id} data-testid={`backup-row-${b.backup_id}`}>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <Text size="sm">{formatDateTime(b.created)}</Text>
                    {!b.has_checksum && (
                      <Tooltip label="No integrity checksum — restore proceeds unverified">
                        <Badge color="yellow" variant="light" size="xs">
                          no checksum
                        </Badge>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
                <Table.Td>
                  {b.depictio_version ? (
                    <Text size="sm">{b.depictio_version}</Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      —
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>{b.size_mb} MB</Table.Td>
                <Table.Td>{b.total_documents}</Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {b.created_by}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Group gap="xs" justify="flex-end" wrap="nowrap">
                    <Tooltip label="Download backup file">
                      <ActionIcon
                        variant="subtle"
                        aria-label={`Download backup ${b.backup_id}`}
                        onClick={() => void handleDownload(b.backup_id)}
                        data-testid={`backup-download-${b.backup_id}`}
                      >
                        <Icon icon="mdi:download" width={18} />
                      </ActionIcon>
                    </Tooltip>
                    <Button
                      color="red"
                      variant="light"
                      size="xs"
                      onClick={() =>
                        setRestoreTarget({
                          backupId: b.backup_id,
                          filename: b.filename,
                          hasChecksum: Boolean(b.has_checksum),
                        })
                      }
                      data-testid={`backup-restore-${b.backup_id}`}
                    >
                      Restore
                    </Button>
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    );
  };

  return (
    <Stack gap="lg">
      <Card withBorder radius="md" p="lg">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Stack gap={4}>
            <Group gap="xs">
              <Icon icon="mdi:database-export" width={20} color="var(--mantine-color-blue-6)" />
              <Title order={5}>Create backup</Title>
            </Group>
            <Text size="sm" c="dimmed">
              Snapshots every MongoDB collection (users, projects, dashboards, workflows,
              data collections, files, delta tables, runs, groups). Tokens and temporary
              users are excluded, so sessions survive a later restore.
            </Text>
          </Stack>
          <Button
            leftSection={<Icon icon="mdi:database-plus" width={16} />}
            onClick={() => void handleCreate()}
            loading={creating}
            data-testid="backup-create-button"
          >
            Create backup
          </Button>
        </Group>
      </Card>

      <Card withBorder radius="md" p="lg">
        <Stack gap="md">
          <Group gap="xs">
            <Icon icon="mdi:database-clock" width={20} color="var(--mantine-color-blue-6)" />
            <Title order={5}>Backups on the server</Title>
          </Group>
          {renderList()}
        </Stack>
      </Card>

      <Card withBorder radius="md" p="lg">
        <Stack gap="md">
          <Stack gap={4}>
            <Group gap="xs">
              <Icon icon="mdi:database-import" width={20} color="var(--mantine-color-orange-6)" />
              <Title order={5}>Restore from file</Title>
            </Group>
            <Text size="sm" c="dimmed">
              Upload a previously downloaded backup. It is stored on the server and
              validated against the current data models before any restore is possible.
            </Text>
          </Stack>
          <div data-testid="backup-upload-zone">
            <FileButton onChange={(file) => void handleUpload(file)} accept="application/json">
              {(props) => (
                <UnstyledDropZone {...props} disabled={uploading}>
                  {uploading ? (
                    <Group gap="sm" data-testid="backup-upload-status">
                      <Loader size="sm" />
                      <Text size="sm" c="dimmed">
                        Uploading and validating…
                      </Text>
                    </Group>
                  ) : (
                    <Stack align="center" gap={4}>
                      <Icon icon="mdi:upload" width={28} color="var(--mantine-color-dimmed)" />
                      <Text size="sm">Click to select a backup JSON file</Text>
                    </Stack>
                  )}
                </UnstyledDropZone>
              )}
            </FileButton>
          </div>
        </Stack>
      </Card>

      <RestoreBackupModal
        opened={Boolean(restoreTarget)}
        target={restoreTarget}
        onClose={() => setRestoreTarget(null)}
        onRestored={() => void refresh()}
      />
    </Stack>
  );
};

export default AdminBackupsPanel;
