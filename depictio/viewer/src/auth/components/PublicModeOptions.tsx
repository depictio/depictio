import { Group, Loader, Stack, Text, UnstyledButton } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useState } from 'react';
import { createTemporaryUser, persistSession, startGoogleOAuth } from 'depictio-react-core';

interface Props {
  googleEnabled: boolean;
  expiryHours: number;
  expiryMinutes: number;
  /** Called after a temporary-user session is persisted. */
  onSuccess: () => void;
}

const cardStyle: React.CSSProperties = {
  border: '1px solid var(--app-border-color, #ddd)',
  borderRadius: 8,
  width: 200,
  minHeight: 100,
  padding: 16,
  backgroundColor: 'var(--app-surface-color, #fff)',
  cursor: 'pointer',
  transition: 'all 0.2s ease',
};

function formatExpiry(hours: number, minutes: number): string {
  if (hours === 24 && minutes === 0) return '24h session';
  if (hours > 0 && minutes > 0) return `${hours}h ${minutes}m session`;
  if (hours > 0) return `${hours}h session`;
  return `${minutes}m session`;
}

/**
 * Public-mode sign-in options — port of users_management.py:
 * render_public_mode_sign_in_options. Two side-by-side cards (temp user +
 * optional Google) inside the AuthCard.
 */
export default function PublicModeOptions({ googleEnabled, expiryHours, expiryMinutes, onSuccess }: Props) {
  const [submitting, setSubmitting] = useState<'temp' | 'google' | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleTempUser() {
    setSubmitting('temp');
    setError(null);
    try {
      const session = await createTemporaryUser();
      persistSession(session);
      onSuccess();
    } catch (err) {
      console.error(err);
      setError('Failed to create temporary user. Please try again.');
      setSubmitting(null);
    }
  }

  async function handleGoogle() {
    setSubmitting('google');
    setError(null);
    try {
      const { authorization_url } = await startGoogleOAuth();
      window.location.assign(authorization_url);
    } catch (err) {
      console.error(err);
      setError('Failed to start Google sign-in. Please try again.');
      setSubmitting(null);
    }
  }

  return (
    <Stack gap="sm">
      <Text size="xs" c="dimmed" ta="center">
        Choose how you'd like to sign in:
      </Text>
      <Group gap="md" justify="center">
        <UnstyledButton onClick={handleTempUser} style={cardStyle} disabled={submitting !== null}>
          <Stack gap={4} align="center">
            {submitting === 'temp' ? (
              <Loader size="sm" />
            ) : (
              <Icon icon="mdi:clock-outline" width={28} color="var(--mantine-color-blue-6)" />
            )}
            <Text fw={500} size="sm">Temporary User</Text>
            <Text size="xs" c="dimmed">{formatExpiry(expiryHours, expiryMinutes)}</Text>
          </Stack>
        </UnstyledButton>
        {googleEnabled && (
          <UnstyledButton onClick={handleGoogle} style={cardStyle} disabled={submitting !== null}>
            <Stack gap={4} align="center">
              {submitting === 'google' ? (
                <Loader size="sm" />
              ) : (
                <Icon icon="devicon:google" width={28} />
              )}
              <Text fw={500} size="sm">Google</Text>
              <Text size="xs" c="dimmed">Persistent account</Text>
            </Stack>
          </UnstyledButton>
        )}
      </Group>
      {error && <Text c="red" size="sm" ta="center">{error}</Text>}
    </Stack>
  );
}
