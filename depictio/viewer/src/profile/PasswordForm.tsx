import React, { useState } from 'react';
import { Button, Group, PasswordInput, Stack, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import { editPassword } from 'depictio-react-core';

interface PasswordFormProps {
  /** Why the form is unavailable, shown as a tooltip on Save. Null = enabled. */
  disabledReason: string | null;
}

/** Change-password form, the inline successor of the old `EditPasswordModal`:
 *  same three fields, same client-side checks (the backend re-validates),
 *  Enter-to-submit, result message inline. In single-user, public and demo
 *  mode it stays visible but disabled, with the reason on the Save button. */
const PasswordForm: React.FC<PasswordFormProps> = ({ disabledReason }) => {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState<{ text: string; tone: 'success' | 'error' } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const locked = disabledReason !== null;

  const handleSubmit = async () => {
    if (locked) return;
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
    <form
      data-testid="password-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!submitting) void handleSubmit();
      }}
    >
      <Stack gap="sm" maw={420}>
        <PasswordInput
          label="Old password"
          placeholder="Old password"
          required
          autoComplete="current-password"
          data-testid="old-password"
          value={oldPassword}
          onChange={(e) => setOldPassword(e.currentTarget.value)}
          disabled={locked || submitting}
        />
        <PasswordInput
          label="New password"
          placeholder="New password"
          required
          autoComplete="new-password"
          data-testid="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.currentTarget.value)}
          disabled={locked || submitting}
        />
        <PasswordInput
          label="Confirm password"
          placeholder="Confirm password"
          required
          autoComplete="new-password"
          data-testid="confirm-new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.currentTarget.value)}
          disabled={locked || submitting}
        />
        {message && (
          <Text
            size="sm"
            c={message.tone === 'success' ? 'green' : 'red'}
            data-testid="password-message"
          >
            {message.text}
          </Text>
        )}
        <Group justify="flex-end">
          <Tooltip label={disabledReason} withArrow disabled={!locked}>
            {/* A disabled button swallows pointer events; the span carries the tooltip. */}
            <span>
              <Button
                type="submit"
                disabled={locked}
                loading={submitting}
                leftSection={<Icon icon="mdi:content-save" width={16} />}
                data-testid="save-password-btn"
              >
                Save
              </Button>
            </span>
          </Tooltip>
        </Group>
      </Stack>
    </form>
  );
};

export default PasswordForm;
