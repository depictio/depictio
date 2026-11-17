import { Alert, Anchor, Button, Divider, Group, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { loginUser, persistSession } from 'depictio-react-core';
import type { SsoProvider } from 'depictio-react-core';

import { useGlassPages } from '../../chrome/variants/glass/pages';
import SignInProviders from './SignInProviders';

const EMAIL_RE = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;

interface Props {
  /** Enabled OpenID Connect providers, one button each. */
  providers: SsoProvider[];
  /** Message for a failed single sign-on, from `/auth?error=<code>`. */
  ssoError?: string | null;
  /** Email + password sign-in is disabled on this instance, leaving single
   *  sign-on as the only door in. The credentials form is hidden rather than shown and
   *  rejected, since /auth/login answers 403 to every attempt. */
  passwordLoginDisabled?: boolean;
  /** Switch to the register view. Omit to hide the Register button entirely
   *  (e.g. when registration is disabled on this instance). */
  onSwitchToRegister?: () => void;
  /** Called after a successful login — drives the redirect. */
  onSuccess: () => void;
}

export default function LoginForm({
  providers,
  ssoError = null,
  passwordLoginDisabled = false,
  onSwitchToRegister,
  onSuccess,
}: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const glass = useGlassPages();

  const emailValid = EMAIL_RE.test(email);
  const canSubmit = emailValid && password.length > 0 && !submitting;
  const hasProviders = providers.length > 0;
  // Mirrors the server-side guard: hiding the credentials form is only safe
  // while there is another way in, so a deployment that sets the flag without
  // configuring a provider keeps its password form instead of a dead card.
  const showCredentials = !passwordLoginDisabled || !hasProviders;
  const ssoAlert = ssoError ? (
    <Alert color="red" variant="light" data-testid="sso-error-alert" role="alert">
      {ssoError}
    </Alert>
  ) : null;

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

  // Glass: one column. The identity providers lead, the email form follows under an "or", and the
  // register switch sits in the card's foot (AuthApp).
  if (glass) {
    return (
      <>
        {ssoAlert}
        {hasProviders && (
          <div className="gp-auth-providers">
            <SignInProviders providers={providers} />
          </div>
        )}
        {hasProviders && showCredentials && <div className="gp-auth-or">or with your email</div>}
        {showCredentials && (
          <>
            <TextInput
              label="Email"
              placeholder="name@example.org"
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              error={email.length > 0 && !emailValid ? 'Enter a valid email address' : null}
              autoComplete="email"
              data-autofocus
              data-testid="login-email"
            />
            <PasswordInput
              label="Password"
              placeholder="Your password"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
              autoComplete="current-password"
              data-testid="login-password"
            />
          </>
        )}
        {error && (
          <p className="gp-auth-error" role="alert" data-testid="user-feedback-message-login">
            {error}
          </p>
        )}
        {showCredentials && (
          <Button
            fullWidth
            mt={4}
            loading={submitting}
            disabled={!canSubmit}
            onClick={handleSubmit}
            data-testid="login-button"
          >
            Sign in
          </Button>
        )}
      </>
    );
  }

  return (
    <Stack gap="md">
      {ssoAlert}
      {showCredentials && (
        <>
          <TextInput
            label="Email:"
            placeholder="Enter your email"
            value={email}
            onChange={(e) => setEmail(e.currentTarget.value)}
            error={email.length > 0 && !emailValid ? 'Invalid email' : null}
            autoComplete="email"
            data-autofocus
            data-testid="login-email"
          />
          <PasswordInput
            label="Password:"
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
            autoComplete="current-password"
            data-testid="login-password"
          />
        </>
      )}
      {error && (
        <Text c="red" size="sm" ta="center" data-testid="user-feedback-message-login">
          {error}
        </Text>
      )}
      {showCredentials && (
        <Group justify="center" gap="sm" mt="sm">
          <Button
            radius="md"
            color="blue"
            loading={submitting}
            disabled={!canSubmit}
            onClick={handleSubmit}
            style={{ width: 120 }}
            data-testid="login-button"
          >
            Login
          </Button>
          {onSwitchToRegister && (
            <Anchor
              component="button"
              type="button"
              onClick={onSwitchToRegister}
              underline="never"
              data-testid="open-register-form"
            >
              <Button radius="md" variant="outline" color="blue" style={{ width: 120 }}>
                Register
              </Button>
            </Anchor>
          )}
        </Group>
      )}
      {hasProviders && (
        <Stack gap="xs">
          {/* The divider separates two alternatives. With the credentials form
              hidden there is only one, so it would divide nothing. */}
          {showCredentials ? (
            <Divider label="Or" labelPosition="center" />
          ) : (
            <Text size="sm" c="dimmed" ta="center">
              This instance signs in with single sign-on.
            </Text>
          )}
          <SignInProviders providers={providers} />
        </Stack>
      )}
    </Stack>
  );
}
