import { Button, Group, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { loginUser, persistSession, registerUser } from 'depictio-react-core';

import { useGlassPages } from '../../chrome/variants/glass/pages';

const EMAIL_RE = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;

interface Props {
  onSwitchToLogin: () => void;
  /** Called after register + auto-login succeed. */
  onSuccess: () => void;
}

export default function RegisterForm({ onSwitchToLogin, onSuccess }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [feedback, setFeedback] = useState<{ kind: 'error' | 'success'; text: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const glass = useGlassPages();

  const emailValid = EMAIL_RE.test(email);
  const canSubmit =
    emailValid && password.length > 0 && confirm.length > 0 && !submitting;

  async function handleSubmit() {
    if (!canSubmit) return;
    if (password !== confirm) {
      setFeedback({ kind: 'error', text: 'Passwords do not match.' });
      return;
    }
    setSubmitting(true);
    setFeedback(null);
    try {
      const result = await registerUser(email, password);
      if (!result.success) {
        setFeedback({ kind: 'error', text: result.message || 'Registration failed.' });
        return;
      }
      // Auto-login on successful registration so the user lands on /dashboards
      // without bouncing back to the login form.
      try {
        const session = await loginUser(email, password);
        persistSession(session);
        onSuccess();
      } catch {
        setFeedback({ kind: 'success', text: 'Registration successful! Please log in.' });
        onSwitchToLogin();
      }
    } catch (err) {
      console.error(err);
      setFeedback({ kind: 'error', text: 'Registration failed. Please try again.' });
    } finally {
      setSubmitting(false);
    }
  }

  // Glass: one column, the commit full width; the way back to sign in is the
  // card's foot (AuthApp).
  if (glass) {
    return (
      <>
        <TextInput
          label="Email"
          placeholder="name@example.org"
          value={email}
          onChange={(e) => setEmail(e.currentTarget.value)}
          error={email.length > 0 && !emailValid ? 'Enter a valid email address' : null}
          autoComplete="email"
          data-autofocus
          data-testid="register-email"
        />
        <PasswordInput
          label="Password"
          placeholder="Choose a password"
          value={password}
          onChange={(e) => setPassword(e.currentTarget.value)}
          autoComplete="new-password"
          data-testid="register-password"
        />
        <PasswordInput
          label="Confirm password"
          placeholder="Type it again"
          value={confirm}
          onChange={(e) => setConfirm(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
          autoComplete="new-password"
          data-testid="register-confirm-password"
        />
        {feedback && (
          <p
            className={feedback.kind === 'error' ? 'gp-auth-error' : 'gp-auth-ok'}
            role={feedback.kind === 'error' ? 'alert' : 'status'}
            data-testid="user-feedback-message-register"
          >
            {feedback.text}
          </p>
        )}
        <Button
          fullWidth
          mt={4}
          loading={submitting}
          disabled={!canSubmit}
          onClick={handleSubmit}
          data-testid="register-button"
        >
          Create account
        </Button>
      </>
    );
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
        data-testid="register-email"
      />
      <PasswordInput
        label="Password:"
        placeholder="Enter your password"
        value={password}
        onChange={(e) => setPassword(e.currentTarget.value)}
        autoComplete="new-password"
        data-testid="register-password"
      />
      <PasswordInput
        label="Confirm Password:"
        placeholder="Confirm your password"
        value={confirm}
        onChange={(e) => setConfirm(e.currentTarget.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
        autoComplete="new-password"
        data-testid="register-confirm-password"
      />
      {feedback && (
        <Text
          c={feedback.kind === 'error' ? 'red' : 'green'}
          size="sm"
          ta="center"
          data-testid="user-feedback-message-register"
        >
          {feedback.text}
        </Text>
      )}
      <Group justify="center" gap="sm" mt="sm">
        <Button
          radius="md"
          color="blue"
          loading={submitting}
          disabled={!canSubmit}
          onClick={handleSubmit}
          style={{ width: 140 }}
          data-testid="register-button"
        >
          Register
        </Button>
        <Button
          radius="md"
          variant="outline"
          color="blue"
          onClick={onSwitchToLogin}
          style={{ width: 140 }}
          data-testid="open-login-form"
        >
          Back to Login
        </Button>
      </Group>
    </Stack>
  );
}
