import React, { useCallback, useEffect, useState } from 'react';
import { Group, Paper, Stack, Table, Text } from '@mantine/core';

import { listPushes } from 'depictio-react-core';
import type { MigrationPush } from 'depictio-react-core';

import { useMigrationUi } from '../../hooks/useMigrationUi';
import { formatDateTime } from '../../lib/datetime';
import {
  PushStatusBadges,
  RetryPushButton,
  isPushActive,
  pushDestinationLabel,
  pushResultLabel,
} from '../pushStatus';

const POLL_MS = 5000;

/** Where this project was published: one row per push, newest first as the API
 *  lists them. Absent when migration is hidden or nothing was ever pushed. */
export const ProjectPublications: React.FC<{ projectId: string; canPush: boolean }> = ({
  projectId,
  canPush,
}) => {
  const migrationUi = useMigrationUi();
  const enabled = migrationUi && canPush;
  const [pushes, setPushes] = useState<MigrationPush[]>([]);

  const load = useCallback(async () => {
    try {
      setPushes(await listPushes(projectId));
    } catch {
      // Not allowed, or an older backend: no section.
      setPushes([]);
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

  if (!enabled || pushes.length === 0) return null;

  return (
    <Paper withBorder radius="md" p="md" data-testid="project-publications">
      <Stack gap="xs">
        <Text fw={600}>Publications</Text>
        <Table.ScrollContainer minWidth={560}>
          <Table fz="sm" verticalSpacing={4}>
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
      </Stack>
    </Paper>
  );
};
