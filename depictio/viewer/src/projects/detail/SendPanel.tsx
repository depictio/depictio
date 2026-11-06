import React, { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
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
import { PublishedLockBadge } from './PublishedLockBadge';

const POLL_MS = 5000;

interface SendPanelProps {
  projectId: string;
  projectName?: string | null;
  /** Owners and admins: publishing is theirs alone. */
  canPush: boolean;
  /** The project's editing lock, when it has one. */
  lock?: PublishedLock | null;
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
}) => {
  const migrationUi = useMigrationUi();
  const enabled = migrationUi && canPush;
  const status = usePublishStatus(enabled);
  const [pushes, setPushes] = useState<MigrationPush[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);

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
      leftSection={<Send size={16} strokeWidth={1.8} aria-hidden />}
      disabled={status !== 'available'}
      loading={status === 'loading'}
      onClick={() => setOpen(true)}
      data-testid="publication-publish-button"
    >
      Send to another instance…
    </Button>
  );

  return (
    <Stack gap="md" data-testid="publication-panel">
      <Stack gap="sm" align="flex-start">
        <Text size="sm">
          Send a copy of this project, its data and its dashboards, to another Depictio
          instance.
        </Text>
        {status === 'unavailable' ? (
          <Tooltip label={NO_DESTINATION_REASON} multiline w={280} withinPortal>
            <span data-testid="publication-disabled-reason">{publishButton}</span>
          </Tooltip>
        ) : (
          publishButton
        )}
      </Stack>

      <Group
        justify="space-between"
        wrap="nowrap"
        px="sm"
        py={8}
        style={{
          border: '1px solid var(--mantine-color-default-border)',
          borderRadius: 'var(--mantine-radius-sm)',
        }}
        data-testid={lock ? 'publication-locked' : 'publication-unlocked'}
      >
        <Stack gap={0}>
          <Text size="sm" fw={500}>
            Editing on this instance
          </Text>
          <Text size="xs" c="dimmed">
            {lock
              ? 'Read-only: nobody can change the dashboards or data here.'
              : 'Owners and editors can change the dashboards and data here.'}
          </Text>
        </Stack>
        {lock ? (
          <PublishedLockBadge lock={lock} />
        ) : (
          <Badge
            variant="light"
            color="gray"
            leftSection={<Icon icon="mdi:lock-open-variant-outline" width={12} />}
          >
            Editable
          </Badge>
        )}
      </Group>

      <Stack gap="xs">
        <Text fw={600} size="sm">
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
