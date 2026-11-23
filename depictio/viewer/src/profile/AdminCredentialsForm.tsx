import React, { useState } from 'react';
import { Button, Group, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import { setAdminCredentials } from 'depictio-react-core';

interface AdminCredentialsFormProps {
  /** The default admin's email as it stands. */
  email: string;
  /** Credentials were chosen before: the current password is asked for. */
  claimed: boolean;
  /** Called with the saved email once the server accepted the change. */
  onSaved: (email: string) => void;
}

/** Single-user mode: name the default admin's email and password.
 *
 *  Nobody signs in on a single-user instance, so these credentials are not
 *  used here. They are what the password form accepts if the instance is
 *  switched to public mode, where it is the admin's only way in. The account
 *  is edited in place: everything it owns stays its own. */
const AdminCredentialsForm: React.FC<AdminCredentialsFormProps> = ({ email, claimed, onSaved }) => {
  const [newEmail, setNewEmail] = useState(email);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState<{ text: string; tone: 'success' | 'error' } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!newEmail.trim() || !newPassword || !confirmPassword || (claimed && !currentPassword)) {
      setMessage({ text: 'Please fill all fields', tone: 'error' });
      return;
    }
    if (newPassword.length < 8) {
      setMessage({ text: 'The password needs at least 8 characters', tone: 'error' });
      return;
    }
    if (newPassword !== confirmPassword) {
      setMessage({ text: 'Passwords do not match', tone: 'error' });
      return;
    }
    setSubmitting(true);
    try {
      const saved = await setAdminCredentials(
        newEmail.trim(),
        newPassword,
        claimed ? currentPassword : undefined,
      );
      setMessage({ text: 'Admin email and password saved', tone: 'success' });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setNewEmail(saved.email);
      onSaved(saved.email);
    } catch (err) {
      const text = err instanceof Error ? err.message : 'Could not save the admin credentials';
      setMessage({ text, tone: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      data-testid="admin-credentials-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!submitting) void handleSubmit();
      }}
    >
      <Stack gap="sm" maw={420}>
        <Text size="sm" c="dimmed">
          {claimed
            ? 'This instance signs you in without a password. These are the credentials the sign-in form accepts if it is switched to public mode.'
            : 'This instance signs you in without a password, as an admin account whose password nobody knows. Choose an email and a password for it now: they are what the sign-in form accepts if the instance is switched to public mode.'}
        </Text>
        <TextInput
          label="Admin email"
          type="email"
          required
          autoComplete="username"
          data-testid="admin-credentials-email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.currentTarget.value)}
          disabled={submitting}
        />
        {claimed && (
          <PasswordInput
            label="Current password"
            required
            autoComplete="current-password"
            data-testid="admin-credentials-current"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.currentTarget.value)}
            disabled={submitting}
          />
        )}
        <PasswordInput
          label="New password"
          description="At least 8 characters"
          required
          autoComplete="new-password"
          data-testid="admin-credentials-new"
          value={newPassword}
          onChange={(e) => setNewPassword(e.currentTarget.value)}
          disabled={submitting}
        />
        <PasswordInput
          label="Confirm password"
          required
          autoComplete="new-password"
          data-testid="admin-credentials-confirm"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.currentTarget.value)}
          disabled={submitting}
        />
        {message && (
          <Text
            size="sm"
            c={message.tone === 'success' ? 'green' : 'red'}
            data-testid="admin-credentials-message"
          >
            {message.text}
          </Text>
        )}
        <Group justify="flex-end">
          <Button
            type="submit"
            loading={submitting}
            leftSection={<Icon icon="mdi:content-save" width={16} />}
            data-testid="admin-credentials-save"
          >
            Save
          </Button>
        </Group>
      </Stack>
    </form>
  );
};

export default AdminCredentialsForm;
