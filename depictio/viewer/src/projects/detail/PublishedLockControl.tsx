import React, { useState } from 'react';
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { lockProject, unlockProject } from 'depictio-react-core';

/** Confirmation for the admin-only Lock / Unlock of a project's published
 *  read-only state. Opened from the page head's Publish menu. */
export const PublishedLockModal: React.FC<{
  opened: boolean;
  onClose: () => void;
  projectId: string;
  locked: boolean;
  onChanged: () => void;
}> = ({ opened, onClose, projectId, locked, onChanged }) => {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const close = () => {
    setReason('');
    onClose();
  };

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
      close();
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
    <Modal
      opened={opened}
      onClose={close}
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
          <Button variant="default" onClick={close}>
            Cancel
          </Button>
          <Button color={locked ? 'orange' : 'blue'} loading={busy} onClick={confirm}>
            {locked ? 'Unlock' : 'Publish read-only'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};
