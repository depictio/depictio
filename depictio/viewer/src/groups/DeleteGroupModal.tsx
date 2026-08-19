import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { GroupSummary } from 'depictio-react-core';

interface DeleteGroupModalProps {
  opened: boolean;
  group: GroupSummary | null;
  onClose: () => void;
  onConfirm: (groupId: string) => Promise<void>;
}

const DeleteGroupModal: React.FC<DeleteGroupModalProps> = ({
  opened,
  group,
  onClose,
  onConfirm,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    setSubmitting(false);
    setErrorMessage(null);
  }, [opened, group]);

  const handleConfirm = async () => {
    if (!group) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      await onConfirm(group.id);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to delete group');
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Delete group"
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
          Delete group &quot;{group?.name || 'this group'}&quot;?
        </Alert>

        <Text size="sm" c="dimmed">
          The group is removed from every project and dashboard it was granted
          access to. Member accounts themselves are not affected.
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
            disabled={!group || submitting}
            data-testid="delete-group-confirm"
          >
            Delete
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default DeleteGroupModal;
