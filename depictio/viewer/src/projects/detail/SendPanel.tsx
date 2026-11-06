import React, { useCallback, useEffect, useState } from 'react';
import { Button, Group, Paper, Stack, Switch, Table, Text, ThemeIcon, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { Send } from 'lucide-react';

import { listPushes } from 'depictio-react-core';
import type { MigrationPush, PublishedLock } from 'depictio-react-core';

import { useMigrationUi } from '../../hooks/useMigrationUi';
import { formatDateTime } from '../../lib/datetime';
import MigrateProjectModal from '../MigrateProjectModal';
import {
  PushStatusBadges,
  RetryPushButton,
  isPushActive,
  pushDestinationLabel,
  pushResultLabel,
} from '../pushStatus';
import { NO_DESTINATION_REASON, usePublishStatus } from '../usePushTargets';
import { PublishedLockModal } from './PublishedLockControl';

const POLL_MS = 5000;

interface SendPanelProps {
  projectId: string;
  projectName?: string | null;
  /** Owners and admins: publishing is theirs alone. */
  canPush: boolean;
  /** The project's editing lock, when it has one. */
  lock?: PublishedLock | null;
  /** Administrators alone can lock or unlock editing. */
  isAdmin?: boolean;
  /** Reload the project once its editing lock changed. */
  onLockChanged?: () => void;
}

/**
 * Sending this project to another Depictio instance, in the project
 * settings: the Send action, whether editing is locked here, and what was
 * sent already (newest first, as the API lists it). Polls while a push is
 * still moving.
 */
const SendPanel: React.FC<SendPanelProps> = ({
  projectId,
  projectName,
  canPush,
  lock,
  isAdmin = false,
  onLockChanged,
}) => {
  const migrationUi = useMigrationUi();
  const enabled = migrationUi && canPush;
  const status = usePublishStatus(enabled);
  const [pushes, setPushes] = useState<MigrationPush[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [lockOpen, setLockOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      setPushes(await listPushes(projectId));
    } catch {
      // Not allowed, or an older backend: nothing was sent that we can show.
      setPushes([]);
    } finally {
      setLoaded(true);
    }
  }, [projectId]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  const active = pushes.some(isPushActive);
  useEffect(() => {
    if (!enabled || !active) return undefined;
    const t = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(t);
  }, [enabled, active, load]);

  // Reload the list once the modal closes: a push may have just started.
  const close = () => {
    setOpen(false);
    void load();
  };

  if (!migrationUi) {
    return (
      <Text size="sm" c="dimmed" data-testid="publication-hidden">
        Sending projects to another instance is turned off on this instance.
      </Text>
    );
  }
  if (!canPush) {
    return (
      <Text size="sm" c="dimmed" data-testid="publication-owners-only">
        Only the project owners and administrators can send this project.
      </Text>
    );
  }

  const publishButton = (
    <Button
      size="sm"
      leftSection={<Send size={16} strokeWidth={1.8} aria-hidden />}
      disabled={status !== 'available'}
      loading={status === 'loading'}
      onClick={() => setOpen(true)}
      data-testid="publication-publish-button"
    >
      Send to another instance
    </Button>
  );

  const locked = !!lock;
  const lockSwitch = (
    <Switch
      size="md"
      label="Lock editing"
      styles={{ label: { whiteSpace: 'nowrap' }, root: { flexShrink: 0 } }}
      checked={locked}
      onChange={() => setLockOpen(true)}
      disabled={!isAdmin}
      data-testid="project-editing-switch"
    />
  );

  return (
    <Stack gap="lg" data-testid="publication-panel">
      <Text size="sm" c="dimmed">
        Send a copy of this project, its data and its dashboards, to another Depictio
        instance.
      </Text>
      <Group>
        {status === 'unavailable' ? (
          <Tooltip label={NO_DESTINATION_REASON} multiline w={280} withinPortal>
            <span data-testid="publication-disabled-reason">{publishButton}</span>
          </Tooltip>
        ) : (
          publishButton
        )}
      </Group>

      <Paper
        withBorder
        p="md"
        radius="md"
        data-testid={locked ? 'publication-locked' : 'publication-unlocked'}
      >
        <Group justify="space-between" wrap="nowrap" align="center">
          <Group gap="sm" wrap="nowrap" align="flex-start" style={{ minWidth: 0 }}>
            <ThemeIcon variant="light" color={locked ? 'orange' : 'gray'} size={40} radius="md">
              <Icon
                icon={locked ? 'mdi:lock-outline' : 'mdi:pencil-outline'}
                width={22}
                height={22}
              />
            </ThemeIcon>
            <Stack gap={2} style={{ minWidth: 0 }}>
              <Text size="md" fw={600}>
                {locked ? 'Editing locked' : 'Editable'}
              </Text>
              <Text size="sm" c="dimmed">
                {locked
                  ? 'Read-only: nobody can change the dashboards or data, owners included.'
                  : 'Owners and editors can change the dashboards and data on this instance.'}
              </Text>
              {!isAdmin && (
                <Text size="sm" c="dimmed">
                  Only an administrator can lock or unlock editing.
                </Text>
              )}
            </Stack>
          </Group>
          {lockSwitch}
        </Group>
      </Paper>
      {isAdmin && (
        <PublishedLockModal
          opened={lockOpen}
          onClose={() => setLockOpen(false)}
          projectId={projectId}
          locked={locked}
          onChanged={() => onLockChanged?.()}
        />
      )}

      <Stack gap="xs">
        <Text fw={500} size="sm">
          Sent
        </Text>
        {loaded && pushes.length === 0 ? (
          <Text size="sm" c="dimmed" data-testid="publication-empty">
            Nothing was sent from this instance yet.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={520}>
            <Table fz="sm" verticalSpacing={4} data-testid="project-publications">
              <Table.Tbody>
                {pushes.map((p) => (
                  <Table.Tr key={p.id} data-testid="publication-row" data-status={p.status}>
                    <Table.Td>{pushDestinationLabel(p)}</Table.Td>
                    <Table.Td>
                      <PushStatusBadges push={p} />
                    </Table.Td>
                    <Table.Td>{formatDateTime(p.created_at)}</Table.Td>
                    <Table.Td>
                      {p.error ? (
                        <Text size="xs" c="red">
                          {p.error}
                        </Text>
                      ) : (
                        <Text size="xs" c="dimmed">
                          {pushResultLabel(p) ?? ''}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Group justify="flex-end">
                        <RetryPushButton push={p} onRetried={() => void load()} />
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>

      <MigrateProjectModal
        opened={open}
        onClose={close}
        projectId={projectId}
        projectName={projectName ?? undefined}
      />
    </Stack>
  );
};

export default SendPanel;
