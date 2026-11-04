import React, { useState } from 'react';
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { lockProject, unlockProject } from 'depictio-react-core';

/** Confirmation for the admin-only Lock / Unlock of a project's editing.
 *  Opened from the Editing row of the Permissions page. */
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
        message: locked ? 'Editing unlocked.' : 'Editing locked: the project is read-only.',
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
      title={locked ? 'Unlock editing' : 'Lock editing'}
      centered
    >
      <Stack gap="sm">
        <Text size="sm">
          {locked
            ? 'Owners and editors will be able to change the dashboards and data again.'
            : 'Nobody, owners included, can change the dashboards or data until an administrator unlocks editing. Who can view the project does not change.'}
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
            {locked ? 'Unlock editing' : 'Lock editing'}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};
