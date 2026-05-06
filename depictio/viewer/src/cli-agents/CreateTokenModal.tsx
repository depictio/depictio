import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Group,
  Modal,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { brandColors } from '../profile/colors';

interface CreateTokenModalProps {
  opened: boolean;
  onClose: () => void;
  /** Submit handler — should throw with a user-readable Error message on
   *  failure (e.g. duplicate name). Modal captures and displays the message
   *  via the inline alert. Resolved on success → modal closes via parent. */
  onSubmit: (name: string) => Promise<void>;
  existingNames: string[];
}

/** Mirrors the "Name Your Configuration" modal in `tokens_management.py:284-360`.
 *  Inputs a token name and posts to /auth/me/tokens via the parent's
 *  onSubmit handler. */
const CreateTokenModal: React.FC<CreateTokenModalProps> = ({
  opened,
  onClose,
  onSubmit,
  existingNames,
}) => {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!opened) {
      setName('');
      setError(null);
      setSubmitting(false);
    }
  }, [opened]);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setError('CLI Configuration name is required.');
      return;
    }
    if (existingNames.includes(trimmed)) {
      setError('CLI Configuration name already exists. Please choose a different name.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create configuration.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      withCloseButton={false}
    >
      <Stack
        gap="md"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !submitting) {
            e.preventDefault();
            void handleSave();
          }
        }}
      >
        <Group justify="flex-start" gap="sm" mb="sm">
          <Icon icon="mdi:console-line" width={28} height={28} color={brandColors.green} />
          <Title order={4} c={brandColors.green} m={0}>
            Name Your Configuration
          </Title>
        </Group>

        <TextInput
          label="Configuration Name"
          placeholder="Enter a name for your CLI configuration"
          required
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          disabled={submitting}
        />

        {error && (
          <Alert
            color="red"
            icon={<Icon icon="mdi:alert-circle" width={20} />}
            title="CLI Configuration creation failed"
          >
            {error}
          </Alert>
        )}

        <Group justify="flex-end" mt="xl">
          <Button variant="subtle" color="gray" radius="md" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            radius="md"
            onClick={handleSave}
            loading={submitting}
            styles={{ root: { backgroundColor: brandColors.green } }}
          >
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateTokenModal;
