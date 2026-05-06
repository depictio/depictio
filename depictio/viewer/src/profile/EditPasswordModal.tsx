import React, { useEffect, useState } from 'react';
import {
  Button,
  Divider,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { editPassword } from 'depictio-react-core';

interface EditPasswordModalProps {
  opened: boolean;
  onClose: () => void;
}

/** Mirrors `layouts_toolbox.py:create_edit_password_modal` — three password
 *  fields, blue Save button, Enter-to-submit, error/success message inline.
 *  Validates client-side before posting; backend re-validates on its side. */
const EditPasswordModal: React.FC<EditPasswordModalProps> = ({ opened, onClose }) => {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState<{ text: string; tone: 'success' | 'error' } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!opened) {
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setMessage(null);
      setSubmitting(false);
    }
  }, [opened]);

  const handleSubmit = async () => {
    if (!oldPassword || !newPassword || !confirmPassword) {
      setMessage({ text: 'Please fill all fields', tone: 'error' });
      return;
    }
    if (newPassword !== confirmPassword) {
      setMessage({ text: 'Passwords do not match', tone: 'error' });
      return;
    }
    if (newPassword === oldPassword) {
      setMessage({ text: 'New password cannot be the same as old password', tone: 'error' });
      return;
    }
    setSubmitting(true);
    try {
      await editPassword(oldPassword, newPassword);
      setMessage({ text: 'Password updated successfully', tone: 'success' });
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (err) {
      const text = err instanceof Error ? err.message : 'Failed to update password';
      setMessage({ text, tone: 'error' });
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
      closeOnEscape
      closeOnClickOutside
      size="lg"
      shadow="xl"
      radius="md"
      overlayProps={{ opacity: 0.55, blur: 3 }}
    >
      <Stack
        gap="md"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !submitting) {
            e.preventDefault();
            void handleSubmit();
          }
        }}
      >
        <Group justify="flex-start" gap="sm">
          <Icon icon="carbon:password" width={28} height={28} color="gray" />
          <Title order={4} c="blue" m={0}>
            Edit Password
          </Title>
        </Group>
        <Divider />
        <PasswordInput
          label="Old Password"
          placeholder="Old Password"
          required
          radius="md"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.currentTarget.value)}
          disabled={submitting}
        />
        <PasswordInput
          label="New Password"
          placeholder="New Password"
          required
          radius="md"
          value={newPassword}
          onChange={(e) => setNewPassword(e.currentTarget.value)}
          disabled={submitting}
        />
        <PasswordInput
          label="Confirm Password"
          placeholder="Confirm Password"
          required
          radius="md"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.currentTarget.value)}
          disabled={submitting}
        />
        {message && (
          <Text size="sm" c={message.tone === 'success' ? 'green' : 'red'}>
            {message.text}
          </Text>
        )}
        <Group justify="flex-end" mt="lg">
          <Button
            color="blue"
            radius="md"
            onClick={handleSubmit}
            loading={submitting}
            leftSection={<Icon icon="mdi:content-save" width={16} />}
          >
            Save
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default EditPasswordModal;
