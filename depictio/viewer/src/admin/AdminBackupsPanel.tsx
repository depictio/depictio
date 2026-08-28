import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Center,
  Code,
  Divider,
  FileButton,
  Group,
  Loader,
  NumberInput,
  Paper,
  Popover,
  SegmentedControl,
  SimpleGrid,
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

/** The schedule fields behind the Save button. `enabled` is deliberately not
 *  one of them: the header switch is a single unambiguous action and saves on
 *  the spot, while the numbers need a deliberate commit. */
interface ScheduleDraft {
  interval_hours: number;
  retention_days: number;
  weekly_weeks: number;
  monthly_months: number;
}

/** One row of the status panel: a label on the left, its value on the right. */
const ScheduleFact: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <Group justify="space-between" wrap="nowrap" gap="md" align="baseline">
    <Text size="xs" c="dimmed" tt="uppercase" fw={600} style={{ flexShrink: 0 }}>
      {label}
    </Text>
    <Text size="sm" ta="right" style={{ minWidth: 0 }}>
      {value}
    </Text>
  </Group>
);

/** The one policy "Smart retention" stands for. Fully fixed rather than exposed
 *  as three number inputs: the value of the mode is that an admin picks thinning
 *  without having to design a policy, and a badly chosen set of tiers is worse
 *  than none.
 *
 *  30 days of full fidelity, not the textbook 7, so that switching from the
 *  default fixed policy (also 30 days) can only ever keep *more* history than
 *  before. A mode that silently shortened the window an admin already had would
 *  be the wrong kind of surprise in a backup feature. */
const SMART_RETENTION = {
  retention_days: 30,
  weekly_weeks: 4,
  monthly_months: 12,
} as const;

type RetentionMode = 'simple' | 'smart';

/** Smart mode is simply "some tier is on", so a policy set through the API or an
 *  env var still reads back correctly here. */
const retentionModeOf = (draft: ScheduleDraft): RetentionMode =>
  draft.weekly_weeks > 0 || draft.monthly_months > 0 ? 'smart' : 'simple';

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'}`;

/** Plain-language summary, so an admin can read back what the policy keeps
 *  without doing the arithmetic. */
const describeRetention = (draft: ScheduleDraft): string => {
  if (draft.retention_days <= 0) return 'Every backup is kept forever.';
  const parts = [`every backup for ${plural(draft.retention_days, 'day')}`];
  if (draft.weekly_weeks > 0) parts.push(`then one a week for ${plural(draft.weekly_weeks, 'week')}`);
  if (draft.monthly_months > 0) {
    parts.push(`then one a month for ${plural(draft.monthly_months, 'month')}`);
  }
  return `Keeps ${parts.join(', ')}. Everything older is deleted.`;
};

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
  const [togglingSchedule, setTogglingSchedule] = useState(false);
  /** The admin's own "keep for" value, parked while smart mode overrides it. */
  const fixedTimeDays = useRef<number>(SMART_RETENTION.retention_days);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [restoreTarget, setRestoreTarget] = useState<RestoreTarget | null>(null);

  /** Store the server's answer and reset the editable copy to match it. */
  const applySchedule = useCallback((next: BackupScheduleStatus) => {
    setSchedule(next);
    setDraft({
      interval_hours: next.interval_hours,
      retention_days: next.retention_days,
      weekly_weeks: next.weekly_weeks,
      monthly_months: next.monthly_months,
    });
  }, []);

  const scheduleDirty =
    !!schedule &&
    !!draft &&
    (draft.interval_hours !== schedule.interval_hours ||
      draft.retention_days !== schedule.retention_days ||
      draft.weekly_weeks !== schedule.weekly_weeks ||
      draft.monthly_months !== schedule.monthly_months);

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
          intervalHours: draft.interval_hours,
          retentionDays: draft.retention_days,
          weeklyWeeks: draft.weekly_weeks,
          monthlyMonths: draft.monthly_months,
        }),
      );
      notifications.show({
        color: 'teal',
        title: 'Schedule saved',
        message: `Automatic backup every ${draft.interval_hours} h. ${describeRetention(draft)}`,
        autoClose: 3500,
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

  /** Smart mode forces the whole preset, including the days. Switching back
   *  hands the admin their own number again rather than the preset's, so the
   *  mode switch is not a one-way door for a value they chose. */
  const setRetentionMode = (draft: ScheduleDraft, mode: RetentionMode) => {
    if (mode === 'smart') {
      fixedTimeDays.current = draft.retention_days;
      setDraft({ ...draft, ...SMART_RETENTION });
      return;
    }
    setDraft({
      ...draft,
      retention_days: fixedTimeDays.current,
      weekly_weeks: 0,
      monthly_months: 0,
    });
  };

  /** The header switch commits on the spot rather than waiting for Save: it is
   *  a single unambiguous choice, and an admin who flips it to stop a runaway
   *  backup loop should not have to find a second button to make it stick. */
  const handleToggleSchedule = async (enabled: boolean) => {
    setTogglingSchedule(true);
    try {
      applySchedule(await updateBackupSchedule({ enabled }));
      notifications.show({
        color: enabled ? 'teal' : 'gray',
        title: enabled ? 'Automated backups on' : 'Automated backups off',
        message: enabled
          ? `The server will take a backup every ${schedule?.interval_hours ?? 24} hours.`
          : 'Backups now only exist when an administrator creates one.',
        autoClose: 2500,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Could not change the schedule',
        message: err instanceof Error ? err.message : 'Failed to update the backup schedule',
      });
    } finally {
      setTogglingSchedule(false);
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

  /** Left panel: the policy an admin edits. Interval and the three retention
   *  tiers, committed together by Save. */
  const renderPolicyPanel = (d: ScheduleDraft) => (
    <Paper withBorder radius="sm" p="md">
      <Stack gap="sm">
        <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
          Schedule &amp; retention
        </Text>

        <NumberInput
          label="Interval"
          description="How often the server takes a backup"
          suffix=" hours"
          min={1}
          max={8760}
          clampBehavior="strict"
          allowDecimal={false}
          value={d.interval_hours}
          onChange={(v) =>
            setDraft({ ...d, interval_hours: typeof v === 'number' ? v : d.interval_hours })
          }
          disabled={savingSchedule}
          data-testid="backup-schedule-interval"
        />

        <Divider
          my={4}
          label={
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Retention policy
            </Text>
          }
          labelPosition="left"
        />

        {/* Two modes rather than three tier inputs: an admin either caps by age
            or asks for thinning, and the tier sizes behind "Smart" are not a
            decision worth making per deployment. */}
        <SegmentedControl
          fullWidth
          size="xs"
          value={retentionModeOf(d)}
          onChange={(value) => setRetentionMode(d, value as RetentionMode)}
          disabled={savingSchedule}
          data-testid="backup-retention-mode"
          data={[
            { label: 'Keep for a fixed time', value: 'simple' },
            { label: 'Smart retention', value: 'smart' },
          ]}
        />

        {retentionModeOf(d) === 'smart' ? (
          // Smart mode has nothing to configure, so it shows what it does
          // instead of a disabled input the admin would try to edit.
          <Stack gap={4} data-testid="backup-retention-smart">
            <Text size="sm" fw={500}>
              Keeps, from newest to oldest:
            </Text>
            <Text size="sm" c="dimmed">
              every backup for {plural(SMART_RETENTION.retention_days, 'day')}, then one a week
              for {plural(SMART_RETENTION.weekly_weeks, 'week')}, then one a month for{' '}
              {plural(SMART_RETENTION.monthly_months, 'month')}.
            </Text>
          </Stack>
        ) : (
          <NumberInput
            label="Keep backups for"
            description="0 keeps every backup forever"
            suffix=" days"
            min={0}
            max={3650}
            clampBehavior="strict"
            allowDecimal={false}
            value={d.retention_days}
            onChange={(v) =>
              setDraft({ ...d, retention_days: typeof v === 'number' ? v : d.retention_days })
            }
            disabled={savingSchedule}
            data-testid="backup-schedule-retention"
          />
        )}

        <Text size="xs" c="dimmed" data-testid="backup-retention-summary">
          {retentionModeOf(d) === 'smart'
            ? 'A year of history stays reachable without the backup volume growing forever.'
            : describeRetention(d)}
        </Text>

        <Group justify="flex-end">
          <Button
            onClick={() => void handleSaveSchedule()}
            loading={savingSchedule}
            disabled={!scheduleDirty}
            data-testid="backup-schedule-save"
          >
            Save schedule
          </Button>
        </Group>
      </Stack>
    </Paper>
  );

  /** Right panel: what the schedule is actually doing, read-only. */
  const renderStatusPanel = (s: BackupScheduleStatus, d: ScheduleDraft) => {
    const totalMb = backups.reduce((sum, b) => sum + (b.size_mb ?? 0), 0);
    const automatic = backups.filter((b) => b.is_automatic).length;

    return (
      <Paper withBorder radius="sm" p="md">
        <Stack gap="sm">
          <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
            Status
          </Text>

          <ScheduleFact
            label="Last automatic run"
            value={s.last_run ? formatDateTime(s.last_run) : 'Never'}
          />
          <ScheduleFact
            label="Next automatic run"
            value={
              s.enabled ? (
                s.next_run ? (
                  formatDateTime(s.next_run)
                ) : (
                  'As soon as a worker wakes'
                )
              ) : (
                <Text size="sm" c="dimmed">
                  Not scheduled
                </Text>
              )
            }
          />

          <Divider my={4} />

          <ScheduleFact
            label="Backups on server"
            value={`${backups.length}${automatic ? ` (${automatic} automatic)` : ''}`}
          />
          <ScheduleFact label="Disk used" value={`${totalMb.toFixed(1)} MB`} />
          <ScheduleFact
            label="Policy in force"
            value={
              d.retention_days <= 0
                ? 'Keep forever'
                : [
                    `${d.retention_days}d`,
                    d.weekly_weeks > 0 ? `${d.weekly_weeks}w` : null,
                    d.monthly_months > 0 ? `${d.monthly_months}m` : null,
                  ]
                    .filter(Boolean)
                    .join(' → ')
            }
          />
          <ScheduleFact
            label="Settings source"
            value={s.is_customized ? 'Saved on this page' : 'Deployment environment'}
          />
        </Stack>
      </Paper>
    );
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
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        {renderPolicyPanel(draft)}
        {renderStatusPanel(schedule, draft)}
      </SimpleGrid>
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
      <Table.ScrollContainer minWidth={860}>
        <Table withTableBorder fz="sm" data-testid="backup-list-table">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Backup</Table.Th>
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
                {/* The id is the filename a download lands under, so it is
                    what ties a file on the admin's disk back to a row here. */}
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <Tooltip label={b.filename}>
                      <Code>{b.backup_id}</Code>
                    </Tooltip>
                    {b.restored_at && (
                      <Tooltip
                        label={`This deployment's data was restored from this backup on ${formatDateTime(
                          b.restored_at,
                        )}${b.restored_by ? ` by ${b.restored_by}` : ''}`}
                      >
                        <Badge
                          color="grape"
                          variant="filled"
                          size="xs"
                          data-testid={`backup-restored-${b.backup_id}`}
                        >
                          restored
                        </Badge>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
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
        <Stack gap="md">
          {/* The button must not be a shrinkable flex item: Mantine clips a
              Button's label rather than letting it overflow, so a nowrap Group
              renders "Create backu". Let the description shrink instead, and let
              the button wrap onto its own line once the card gets narrow. */}
          <Group justify="space-between" align="flex-start">
            <Stack gap={4} style={{ flex: '1 1 320px', minWidth: 0 }}>
              <Group gap="xs">
                <Icon icon="mdi:database-export" width={20} color="var(--mantine-color-blue-6)" />
                <Title order={5}>Create database backup</Title>
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

          {/* Naming the boundary here rather than in the docs alone: the page
              is called "Backups", and an admin who reads that as "everything is
              backed up" only finds out otherwise during a restore. */}
          <Alert
            variant="light"
            color="blue"
            icon={<Icon icon="mdi:information-outline" />}
            data-testid="backup-scope-notice"
          >
            <Text size="sm">
              This backs up the <strong>database only</strong>: dashboards, projects and the
              metadata pointing at your data. The data itself (Delta tables in S3 or MinIO) is
              not included and is not restored from here. Back it up separately, with your
              object store&apos;s own replication or with{' '}
              <Code>depictio-cli backup create --include-s3-data</Code>.{' '}
              <Anchor
                href="https://depictio.github.io/depictio-docs/latest/usage/administration/backup/"
                target="_blank"
                rel="noopener noreferrer"
                size="sm"
              >
                Backup &amp; restore documentation
              </Anchor>
              .
            </Text>
          </Alert>
        </Stack>
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
          {/* Title and the master switch sit on one line: the switch is the
              section's on/off, not one setting among the others, so it stays
              out of the panel that needs a Save. */}
          <Group justify="space-between" align="center" wrap="nowrap">
            <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
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
              {schedule && (
                <Popover width={480} position="bottom-start" withArrow shadow="md">
                  <Popover.Target>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      aria-label="Where these settings come from"
                      data-testid="backup-schedule-info"
                    >
                      <Icon icon="mdi:information-outline" width={18} />
                    </ActionIcon>
                  </Popover.Target>
                  <Popover.Dropdown>
                    <Text size="xs">
                      {schedule.is_customized ? 'Saved here, overriding this' : 'Currently taken from this'}{' '}
                      deployment&apos;s <Code>DEPICTIO_BACKUP_AUTO_BACKUP_ENABLED</Code>,{' '}
                      <Code>DEPICTIO_BACKUP_AUTO_BACKUP_INTERVAL_HOURS</Code>,{' '}
                      <Code>DEPICTIO_BACKUP_BACKUP_FILE_RETENTION_DAYS</Code>,{' '}
                      <Code>DEPICTIO_BACKUP_BACKUP_RETENTION_WEEKLY_WEEKS</Code> and{' '}
                      <Code>DEPICTIO_BACKUP_BACKUP_RETENTION_MONTHLY_MONTHS</Code>. Anything saved
                      on this page wins over those defaults from then on, and applies to every API
                      worker within a few minutes — no restart needed.
                    </Text>
                  </Popover.Dropdown>
                </Popover>
              )}
            </Group>
            {schedule && (
              <Switch
                checked={schedule.enabled}
                onChange={(e) => void handleToggleSchedule(e.currentTarget.checked)}
                disabled={togglingSchedule}
                size="md"
                aria-label="Take a backup automatically"
                data-testid="backup-schedule-enabled"
              />
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
