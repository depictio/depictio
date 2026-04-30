import React, { useEffect, useState } from 'react';
import { Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import { brandColors } from '../profile/colors';

interface DeleteTokenModalProps {
  opened: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}

/** Confirm-by-typing-"delete" gate, mirrors `tokens_management.py:362-416`.
 *  The Confirm Delete button stays disabled until the input matches "delete"
 *  exactly — same behaviour as the Dash callback at line 854-858. */
const DeleteTokenModal: React.FC<DeleteTokenModalProps> = ({ opened, onClose, onConfirm }) => {
  const [confirmInput, setConfirmInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!opened) {
      setConfirmInput('');
      setSubmitting(false);
    }
  }, [opened]);

  const canConfirm = confirmInput.trim().toLowerCase() === 'delete';

  const handleConfirm = async () => {
    if (!canConfirm) return;
    setSubmitting(true);
    try {
      await onConfirm();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      title="Confirm Deletion"
      styles={{ title: { color: brandColors.red, fontWeight: 600 } }}
    >
      <Stack gap="md">
        <Text size="sm" c="gray">
          Are you sure you want to delete this configuration? This action cannot be undone.
        </Text>
        <TextInput
          label='Type "delete" to confirm'
          required
          value={confirmInput}
          onChange={(e) => setConfirmInput(e.currentTarget.value)}
          leftSection={<Icon icon="mdi:delete-alert" width={18} />}
          disabled={submitting}
        />
        <Group justify="flex-end" mt="xl">
          <Button variant="subtle" color="gray" radius="md" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            radius="md"
            disabled={!canConfirm}
            loading={submitting}
            onClick={handleConfirm}
            styles={{ root: { backgroundColor: brandColors.red } }}
          >
            Confirm Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default DeleteTokenModal;
