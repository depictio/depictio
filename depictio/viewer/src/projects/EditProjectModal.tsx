import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Modal, Stack, Text, TextInput } from '@mantine/core';

import type { EditProjectInput, ProjectListEntry } from 'depictio-react-core';
import { useBrandAccents } from 'depictio-react-core';

interface EditProjectModalProps {
  opened: boolean;
  project: ProjectListEntry | null;
  onClose: () => void;
  onSubmit: (projectId: string, input: EditProjectInput) => Promise<void>;
}

const EditProjectModal: React.FC<EditProjectModalProps> = ({
  opened,
  project,
  onClose,
  onSubmit,
}) => {
  const accent = useBrandAccents();
  const [name, setName] = useState('');
  const [dmpUrl, setDmpUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened || !project) return;
    setName(project.name || '');
    setDmpUrl(
      typeof project.data_management_platform_project_url === 'string'
        ? project.data_management_platform_project_url
        : '',
    );
    setError(null);
    setSubmitting(false);
  }, [opened, project]);

  const handleSubmit = async () => {
    if (!project) return;
    const id = (project._id ?? project.id) as string;
    if (!name.trim()) {
      setError('Project name is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(id, {
        name: name.trim(),
        data_management_platform_project_url: dmpUrl.trim() || null,
      });
    } catch (err) {
      setError((err as Error).message || 'Failed to update project.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title="Edit project"
      centered
      size="md"
    >
      <Stack gap="md">
        <TextInput
          label="Project name"
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          required
          disabled={submitting}
        />
        <TextInput
          label="Data management platform URL"
          placeholder="https://..."
          value={dmpUrl}
          onChange={(e) => setDmpUrl(e.currentTarget.value)}
          disabled={submitting}
        />
        <Text size="xs" c="dimmed">
          Visibility (public/private) is managed from the project's Permissions
          page — changing it there also updates all of its dashboards.
        </Text>
        {error && (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        )}
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button color={accent.secondary} onClick={handleSubmit} loading={submitting}>
            Save changes
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default EditProjectModal;
