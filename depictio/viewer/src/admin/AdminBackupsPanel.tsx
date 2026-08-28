import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Card,
  Center,
  Code,
  FileButton,
  Group,
  Loader,
  NumberInput,
  Stack,
  Switch,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  createBackup,
  downloadBackup,
  getBackupSchedule,
  listBackups,
  updateBackupSchedule,
  uploadBackup,
} from 'depictio-react-core';
import type { AdminBackupEntry, BackupScheduleStatus } from 'depictio-react-core';

import UnstyledDropZone from '../components/UnstyledDropZone';
import { formatDateTime } from '../lib/datetime';
import RestoreBackupModal from './RestoreBackupModal';
import type { RestoreTarget } from './RestoreBackupModal';

/** The three schedule fields an admin can edit, as held while editing. */
interface ScheduleDraft {
  enabled: boolean;
  interval_hours: number;
  retention_days: number;
}

/** One labelled value in the Automated backups summary row. */
const ScheduleFact: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <Stack gap={0}>
    <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
      {label}
    </Text>
    <Text size="sm">{value}</Text>
  </Stack>
);

/**
 * Admin > Backups tab. One-click server-side backup (create + download),
 * a list of the backups on the server, and a restore flow: pick a listed
 * backup or upload a file → validation → typed-phrase confirmation →
 * destructive restore (see RestoreBackupModal for the safety rails).
 */
const AdminBackupsPanel: React.FC = () => {
  const [backups, setBackups] = useState<AdminBackupEntry[]>([]);
  const [schedule, setSchedule] = useState<BackupScheduleStatus | null>(null);
  /** Editable copy of the schedule; `schedule` stays the server's answer so the
   *  Save button can tell whether anything actually changed. */
  const [draft, setDraft] = useState<ScheduleDraft | null>(null);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<RestoreTarget | null>(null);

  /** Store the server's answer and reset the editable copy to match it. */
  const applySchedule = useCallback((next: BackupScheduleStatus) => {
    setSchedule(next);
    setDraft({
      enabled: next.enabled,
      interval_hours: next.interval_hours,
      retention_days: next.retention_days,
    });
  }, []);

  const scheduleDirty =
    !!schedule &&
    !!draft &&
    (draft.enabled !== schedule.enabled ||
      draft.interval_hours !== schedule.interval_hours ||
      draft.retention_days !== schedule.retention_days);

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

  /** Loaded separately from the backup list, and deliberately not re-read by
   *  refresh(): the last/next run only move when the *scheduler* runs, so
   *  re-reading after a manual backup would discard an in-progress edit for
   *  nothing. A failure here must not blank the list, so it skips loadError. */
  const loadSchedule = useCallback(async () => {
    try {
      applySchedule(await getBackupSchedule());
    } catch {
      setSchedule(null);
      setDraft(null);
    }
  }, [applySchedule]);

  const handleSaveSchedule = async () => {
    if (!draft) return;
    setSavingSchedule(true);
    try {
      applySchedule(
        await updateBackupSchedule({
          enabled: draft.enabled,
          intervalHours: draft.interval_hours,
          retentionDays: draft.retention_days,
        }),
      );
      notifications.show({
        color: 'teal',
        title: 'Schedule saved',
        message: draft.enabled
          ? `Automatic backup every ${draft.interval_hours} h.`
          : 'Automatic backups are off.',
        autoClose: 2500,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not save the schedule',
        message: err instanceof Error ? err.message : 'Failed to update the backup schedule',
      });
    } finally {
      setSavingSchedule(false);
    }
  };

  useEffect(() => {
    void refresh();
    void loadSchedule();
  }, [refresh, loadSchedule]);

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

  const renderSchedule = () => {
    if (!schedule || !draft) {
      return (
        <Text size="sm" c="dimmed">
          Schedule status unavailable.
        </Text>
      );
    }
    return (
      <Stack gap="md">
        <Text size="sm" c="dimmed">
          {schedule.enabled
            ? `The server takes a backup on its own every ${schedule.interval_hours} hours.`
            : 'Nothing is backing this deployment up on a schedule. Backups only exist when an administrator creates one here.'}{' '}
          Old backups are pruned after every backup, scheduled or manual.
        </Text>

        <Switch
          checked={draft.enabled}
          onChange={(e) => setDraft({ ...draft, enabled: e.currentTarget.checked })}
          label="Take a backup automatically"
          description="Applies to every API worker within a few minutes. No restart needed."
          disabled={savingSchedule}
          data-testid="backup-schedule-enabled"
        />

        <Group gap="md" align="flex-start" wrap="wrap">
          <NumberInput
            label="Interval"
            suffix=" hours"
            min={1}
            max={8760}
            clampBehavior="strict"
            allowDecimal={false}
            w={150}
            value={draft.interval_hours}
            onChange={(v) =>
              setDraft({ ...draft, interval_hours: typeof v === 'number' ? v : draft.interval_hours })
            }
            disabled={savingSchedule}
            data-testid="backup-schedule-interval"
          />
          <NumberInput
            label="Keep backups for"
            suffix=" days"
            description="0 keeps them forever"
            min={0}
            max={3650}
            clampBehavior="strict"
            allowDecimal={false}
            w={190}
            value={draft.retention_days}
            onChange={(v) =>
              setDraft({ ...draft, retention_days: typeof v === 'number' ? v : draft.retention_days })
            }
            disabled={savingSchedule}
            data-testid="backup-schedule-retention"
          />
          <Button
            mt={25}
            onClick={() => void handleSaveSchedule()}
            loading={savingSchedule}
            disabled={!scheduleDirty}
            data-testid="backup-schedule-save"
          >
            Save schedule
          </Button>
        </Group>

        <Group gap="lg" wrap="wrap">
          <ScheduleFact
            label="Last automatic run"
            value={schedule.last_run ? formatDateTime(schedule.last_run) : 'Never'}
          />
          <ScheduleFact
            label="Next automatic run"
            value={schedule.next_run ? formatDateTime(schedule.next_run) : 'Not scheduled'}
          />
        </Group>

        <Text size="xs" c="dimmed">
          {schedule.is_customized ? 'Saved here, overriding this' : 'Currently taken from this'}{' '}
          deployment&apos;s <Code>DEPICTIO_BACKUP_AUTO_BACKUP_ENABLED</Code>,{' '}
          <Code>DEPICTIO_BACKUP_AUTO_BACKUP_INTERVAL_HOURS</Code> and{' '}
          <Code>DEPICTIO_BACKUP_BACKUP_FILE_RETENTION_DAYS</Code>. Anything saved on this page wins
          over those defaults from then on.
        </Text>
      </Stack>
    );
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
                    {b.is_automatic && (
                      <Tooltip label="Taken by the backup scheduler">
                        <Badge color="blue" variant="light" size="xs">
                          auto
                        </Badge>
                      </Tooltip>
                    )}
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
                  {/* Both row actions are labelled icon buttons of the same
                      size: an icon-only download next to a text-only restore
                      read as two different kinds of control. Colour escalates
                      with consequence — neutral download, orange restore (it
                      replaces data), red only on the modal's final confirm. */}
                  <Group gap="xs" justify="flex-end" wrap="nowrap">
                    <Button
                      variant="default"
                      size="xs"
                      leftSection={<Icon icon="mdi:download" width={14} />}
                      onClick={() => void handleDownload(b.backup_id)}
                      data-testid={`backup-download-${b.backup_id}`}
                    >
                      Download
                    </Button>
                    <Button
                      color="orange"
                      variant="light"
                      size="xs"
                      leftSection={<Icon icon="mdi:backup-restore" width={14} />}
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
        {/* The button must not be a shrinkable flex item: Mantine clips a
            Button's label rather than letting it overflow, so a nowrap Group
            renders "Create backu". Let the description shrink instead, and let
            the button wrap onto its own line once the card gets narrow. */}
        <Group justify="space-between" align="flex-start">
          <Stack gap={4} style={{ flex: '1 1 320px', minWidth: 0 }}>
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
            style={{ flexShrink: 0 }}
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
          <Group gap="xs">
            <Icon icon="mdi:calendar-clock" width={20} color="var(--mantine-color-blue-6)" />
            <Title order={5}>Automated backups</Title>
            {schedule && (
              <Badge
                color={schedule.enabled ? 'teal' : 'gray'}
                variant="light"
                data-testid="backup-schedule-status"
              >
                {schedule.enabled ? 'Enabled' : 'Disabled'}
              </Badge>
            )}
          </Group>
          {renderSchedule()}
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
