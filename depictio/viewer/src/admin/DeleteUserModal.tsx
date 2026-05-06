import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { AdminUser } from 'depictio-react-core';

interface DeleteUserModalProps {
  opened: boolean;
  user: AdminUser | null;
  onClose: () => void;
  onConfirm: (userId: string) => Promise<void>;
}

const DeleteUserModal: React.FC<DeleteUserModalProps> = ({
  opened,
  user,
  onClose,
  onConfirm,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    setSubmitting(false);
    setErrorMessage(null);
  }, [opened, user]);

  const handleConfirm = async () => {
    const userId = user?.id ?? user?._id;
    if (!userId) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await onConfirm(String(userId));
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to delete user');
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Delete user"
      size="md"
      centered
      closeOnClickOutside={false}
    >
      <Stack gap="sm">
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert" />}
          title="This cannot be undone."
        >
          Delete user &quot;{user?.email || 'this user'}&quot;?
        </Alert>

        <Text size="sm" c="dimmed">
          The user&apos;s account, sessions, and personal data will be removed.
          Dashboards and projects they own remain in the system.
        </Text>

        {errorMessage && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" />}>
            {errorMessage}
          </Alert>
        )}

        <Group justify="flex-end" gap="xs" mt="sm">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color="red"
            leftSection={<Icon icon="tabler:trash" width={14} />}
            onClick={handleConfirm}
            loading={submitting}
            disabled={!user || submitting}
          >
            Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default DeleteUserModal;
