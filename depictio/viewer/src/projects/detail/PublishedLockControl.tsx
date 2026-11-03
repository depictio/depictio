import React, { useState } from 'react';
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { lockProject, unlockProject } from 'depictio-react-core';

/** Admin-only Lock / Unlock action for a project's published read-only state. */
export const PublishedLockControl: React.FC<{
  projectId: string;
  locked: boolean;
  onChanged: () => void;
}> = ({ projectId, locked, onChanged }) => {
  const [opened, setOpened] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    setBusy(true);
    try {
      const r = reason.trim() || undefined;
      if (locked) await unlockProject(projectId, r);
      else await lockProject(projectId, r);
      notifications.show({
        color: 'green',
        message: locked ? 'Project unlocked.' : 'Project published (read-only).',
      });
      setOpened(false);
      setReason('');
      onChanged();
    } catch (err) {
      notifications.show({
        color: 'red',
        title: locked ? 'Unlock failed' : 'Lock failed',
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Group justify="flex-end">
        <Button
          size="xs"
          variant="light"
          color={locked ? 'orange' : 'gray'}
          leftSection={<Icon icon={locked ? 'mdi:lock-open-variant-outline' : 'mdi:lock-outline'} width={14} />}
          onClick={() => setOpened(true)}
        >
          {locked ? 'Unlock project' : 'Publish read-only'}
        </Button>
      </Group>
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title={locked ? 'Unlock project' : 'Publish project read-only'}
        centered
      >
        <Stack gap="sm">
          <Text size="sm">
            {locked
              ? 'Editing of the project and its dashboards will be allowed again.'
              : 'Dashboards and data of this project can no longer be edited until an administrator unlocks it.'}
          </Text>
          <TextInput
            label="Reason (optional)"
            value={reason}
            onChange={(e) => setReason(e.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              Cancel
            </Button>
            <Button color={locked ? 'orange' : 'blue'} loading={busy} onClick={confirm}>
              {locked ? 'Unlock' : 'Lock'}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};
