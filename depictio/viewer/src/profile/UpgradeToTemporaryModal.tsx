import React, { useState } from 'react';
import {
  Alert,
  Button,
  Group,
  List,
  Modal,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { upgradeToTemporaryUser, persistSession } from 'depictio-react-core';

interface UpgradeToTemporaryModalProps {
  opened: boolean;
  onClose: () => void;
  /** Hours until the temporary session expires; defaults to 24 if unset.
   *  Passed straight to the backend, mirrors the Dash modal copy. */
  expiryHours?: number;
  expiryMinutes?: number;
}

/** Mirrors the upgrade-confirmation modal in `profile.py:251-318`. On
 *  confirm, calls `/auth/upgrade_to_temporary_user`, persists the new
 *  session payload, and reloads to /profile-beta so the rest of the SPA
 *  picks up the new token. */
const UpgradeToTemporaryModal: React.FC<UpgradeToTemporaryModalProps> = ({
  opened,
  onClose,
  expiryHours = 24,
  expiryMinutes = 0,
}) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const session = await upgradeToTemporaryUser(expiryHours);
      if (!session) {
        setError('You are already a temporary user.');
        return;
      }
      persistSession(session);
      window.location.assign('/profile-beta');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upgrade failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      size="lg"
      title="Login as a temporary user"
    >
      <Stack gap="md">
        <Group gap="lg">
          <Icon icon="mdi:account-arrow-up" width={30} color="var(--mantine-color-blue-6)" />
          <Title order={3} c="blue">
            Login as a temporary user?
          </Title>
        </Group>
        <Text size="sm" c="gray">
          This will create a temporary account that expires in {expiryHours} hours, allowing
          you to duplicate and modify dashboards.
        </Text>
        <Alert
          color="blue"
          variant="light"
          icon={<Icon icon="mdi:information" width={20} />}
          title="What you'll get:"
        >
          <List size="sm">
            <List.Item>Ability to duplicate and modify dashboards</List.Item>
            <List.Item>Your own isolated workspace</List.Item>
            <List.Item>All changes auto-save to your session</List.Item>
            <List.Item>
              Session expires automatically in {expiryHours}:
              {String(expiryMinutes).padStart(2, '0')} hours:minutes
            </List.Item>
          </List>
        </Alert>
        {error && (
          <Text size="sm" c="red">
            {error}
          </Text>
        )}
        <Group justify="flex-end" mt="md">
          <Button variant="outline" color="gray" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color="blue"
            variant="filled"
            onClick={handleConfirm}
            loading={submitting}
            rightSection={<Icon icon="mdi:arrow-right" width={16} />}
          >
            Login as a temporary user
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default UpgradeToTemporaryModal;
