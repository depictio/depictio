import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Modal, Stack, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import { SectionHeader } from '../components/settings/SettingsSections';

interface CreateTokenModalProps {
  opened: boolean;
  onClose: () => void;
  /** Submit handler — should throw with a user-readable Error message on
   *  failure (e.g. duplicate name). Modal captures and displays the message
   *  via the inline alert. Resolved on success → modal closes via parent. */
  onSubmit: (name: string) => Promise<void>;
  existingNames: string[];
}

/** Names a new CLI configuration and posts to /auth/me/tokens via the parent's
 *  onSubmit handler. Headed like the Account settings sections it opens from. */
const CreateTokenModal: React.FC<CreateTokenModalProps> = ({
  opened,
  onClose,
  onSubmit,
  existingNames,
}) => {
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!opened) {
      setName('');
      setNameError(null);
      setError(null);
      setSubmitting(false);
    }
  }, [opened]);

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError('Give the configuration a name.');
      return;
    }
    if (existingNames.includes(trimmed)) {
      setNameError('A configuration already has this name.');
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
      title={
        <SectionHeader
          icon="mdi:console-line"
          title="New CLI configuration"
          subtitle="A token and its settings, for the depictio CLI"
        />
      }
    >
      <Stack
        gap="md"
        data-testid="create-cli-token-modal"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !submitting) {
            e.preventDefault();
            void handleSave();
          }
        }}
      >
        <TextInput
          label="Name"
          description="To tell your configurations apart, for example the machine it runs on."
          placeholder="laptop, cluster, CI"
          data-autofocus
          value={name}
          onChange={(e) => {
            setName(e.currentTarget.value);
            setNameError(null);
          }}
          error={nameError}
          disabled={submitting}
          data-testid="cli-config-name-input"
        />

        {error && (
          <Alert color="red" variant="light" icon={<Icon icon="mdi:alert-circle" width={18} />}>
            {error}
          </Alert>
        )}

        <Group justify="flex-end" gap="xs" mt="xs">
          <Button variant="subtle" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSave} loading={submitting} data-testid="save-cli-config-btn">
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateTokenModal;
