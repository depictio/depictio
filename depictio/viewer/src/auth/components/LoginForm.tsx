import { Anchor, Button, Divider, Group, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { loginUser, persistSession, startGoogleOAuth } from 'depictio-react-core';

const EMAIL_RE = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;

interface Props {
  googleEnabled: boolean;
  onSwitchToRegister: () => void;
  /** Called after a successful login — drives the redirect. */
  onSuccess: () => void;
}

export default function LoginForm({ googleEnabled, onSwitchToRegister, onSuccess }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const emailValid = EMAIL_RE.test(email);
  const canSubmit = emailValid && password.length > 0 && !submitting;

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const session = await loginUser(email, password);
      persistSession(session);
      onSuccess();
    } catch (err) {
      const msg = err instanceof Error && err.message === 'invalid_credentials'
        ? 'Invalid email or password.'
        : 'Login failed. Please try again.';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogleClick() {
    try {
      const { authorization_url } = await startGoogleOAuth();
      window.location.assign(authorization_url);
    } catch (err) {
      setError('Failed to start Google sign-in.');
      console.error(err);
    }
  }

  return (
    <Stack gap="md">
      <TextInput
        label="Email:"
        placeholder="Enter your email"
        value={email}
        onChange={(e) => setEmail(e.currentTarget.value)}
        error={email.length > 0 && !emailValid ? 'Invalid email' : null}
        autoComplete="email"
        data-autofocus
      />
      <PasswordInput
        label="Password:"
        placeholder="Enter your password"
        value={password}
        onChange={(e) => setPassword(e.currentTarget.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleSubmit();
        }}
        autoComplete="current-password"
      />
      {error && <Text c="red" size="sm" ta="center">{error}</Text>}
      <Group justify="center" gap="sm" mt="sm">
        <Button
          radius="md"
          color="blue"
          loading={submitting}
          disabled={!canSubmit}
          onClick={handleSubmit}
          style={{ width: 120 }}
        >
          Login
        </Button>
        <Anchor
          component="button"
          type="button"
          onClick={onSwitchToRegister}
          underline="never"
        >
          <Button radius="md" variant="outline" color="blue" style={{ width: 120 }}>
            Register
          </Button>
        </Anchor>
      </Group>
      {googleEnabled && (
        <Stack gap="xs">
          <Divider label="Or" labelPosition="center" />
          <Button
            id="google-oauth-button"
            variant="outline"
            radius="md"
            fullWidth
            onClick={handleGoogleClick}
            leftSection={
              <img
                src="https://www.google.com/favicon.ico"
                alt=""
                width={18}
                height={18}
                style={{ display: 'block' }}
              />
            }
          >
            Sign in with Google
          </Button>
        </Stack>
      )}
    </Stack>
  );
}
