import React, { useState } from 'react';
import { Alert, Button, Group, Modal, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ProjectListEntry } from 'depictio-react-core';

interface DeleteProjectModalProps {
  opened: boolean;
  project: ProjectListEntry | null;
  onClose: () => void;
  onConfirm: (projectId: string) => Promise<void>;
}

const DeleteProjectModal: React.FC<DeleteProjectModalProps> = ({
  opened,
  project,
  onClose,
  onConfirm,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    if (!project) return;
    const id = (project._id ?? project.id) as string;
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm(id);
    } catch (err) {
      setError((err as Error).message || 'Failed to delete project.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Delete project"
      centered
      size="md"
    >
      <Stack gap="md">
        <Text>
          Permanently delete <strong>{project?.name || 'this project'}</strong>?
        </Text>
        <Alert
          color="red"
          icon={<Icon icon="mdi:alert" width={18} />}
          variant="light"
        >
          This will also delete every dashboard, data collection, and stored
          file linked to this project. This action cannot be undone.
        </Alert>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button color="red" onClick={handleConfirm} loading={submitting}>
            Delete project
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default DeleteProjectModal;
