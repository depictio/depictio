import { Button, PasswordInput, Stack, Text } from '@mantine/core';
import { useState } from 'react';
import { createTemporaryUser, persistSession } from 'depictio-react-core';

interface Props {
  /** Called after the code is accepted and the session is persisted. */
  onSuccess: () => void;
}

/**
 * Access-code gate for a protected public deployment
 * (`DEPICTIO_AUTH_PUBLIC_ACCESS_CODE`).
 *
 * Public mode's whole point is that a visitor needs no account: they get a
 * throwaway user and land on the dashboards. That also means an open
 * deployment hands a session to anyone who loads the page. The code turns it
 * into "shareable with the people who have the link and the code" without
 * reintroducing accounts — everyone who passes still gets their own temporary
 * user, and the code is one shared secret rather than a credential per person.
 *
 * The gate is a courtesy, not the enforcement: `/auth/public/create_temporary_user`
 * refuses a wrong or missing code on its own, so skipping this form buys
 * nothing.
 */
export default function PublicAccessGate({ onSuccess }: Props) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!code || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      persistSession(await createTemporaryUser(code));
      onSuccess();
    } catch {
      // The server answers 403 for a wrong code and never says more than
      // that; there is no account here to enumerate, so one message covers it.
      setError('That access code was not accepted.');
      setSubmitting(false);
    }
  }

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed" ta="center">
        This instance is open to anyone with the access code. Enter it to
        continue as a guest — no account needed.
      </Text>
      <PasswordInput
        label="Access code:"
        placeholder="Enter the access code"
        value={code}
        onChange={(e) => setCode(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleSubmit();
        }}
        autoComplete="one-time-code"
        data-autofocus
        data-testid="public-access-code"
      />
      {error && (
        <Text c="red" size="sm" ta="center" data-testid="public-access-error">
          {error}
        </Text>
      )}
      <Button
        radius="md"
        loading={submitting}
        disabled={!code || submitting}
        onClick={handleSubmit}
        data-testid="public-access-submit"
      >
        Continue
      </Button>
    </Stack>
  );
}
