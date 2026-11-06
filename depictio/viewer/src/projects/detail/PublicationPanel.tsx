import React, { useCallback, useEffect, useState } from 'react';
import { Button, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
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

interface PublicationPanelProps {
  projectId: string;
  projectName?: string | null;
  /** Owners and admins: publishing is theirs alone. */
  canPush: boolean;
  /** The project's editing lock, when it has one. */
  lock?: PublishedLock | null;
}

/**
 * Publishing this project to another Depictio instance, in the project
 * settings: the Publish action, whether editing is locked here, and what was
 * sent already (newest first, as the API lists it). Polls while a push is
 * still moving.
 */
const PublicationPanel: React.FC<PublicationPanelProps> = ({
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
        Publishing to another instance is turned off on this instance.
      </Text>
    );
  }
  if (!canPush) {
    return (
      <Text size="sm" c="dimmed" data-testid="publication-owners-only">
        Only the project owners and administrators can publish this project.
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
      Publish to…
    </Button>
  );

  return (
    <Stack gap="md" data-testid="publication-panel">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Stack gap={4}>
          <Text size="sm">
            Send a copy of this project, its data and its dashboards, to another Depictio
            instance.
          </Text>
          <Group gap="xs">
            <Text size="sm" c="dimmed">
              Editing here
            </Text>
            {lock ? (
              <PublishedLockBadge lock={lock} />
            ) : (
              <Text size="sm" data-testid="publication-unlocked">
                Not locked
              </Text>
            )}
          </Group>
        </Stack>
        {status === 'unavailable' ? (
          <Tooltip label={NO_DESTINATION_REASON} multiline w={280} withinPortal>
            <span data-testid="publication-disabled-reason">{publishButton}</span>
          </Tooltip>
        ) : (
          publishButton
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

export default PublicationPanel;
