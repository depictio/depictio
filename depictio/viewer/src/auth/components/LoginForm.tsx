import { Anchor, Button, Divider, Group, PasswordInput, Stack, Text, TextInput } from '@mantine/core';
import { useState } from 'react';
import { loginUser, persistSession, startGoogleOAuth } from 'depictio-react-core';

import { useGlassPages } from '../../chrome/variants/glass/pages';
import SignInProviders from './SignInProviders';

const EMAIL_RE = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;

interface Props {
  googleEnabled: boolean;
  /** SAML SSO login enabled (e.g. EMBL Keycloak). */
  samlEnabled?: boolean;
  /** Label for the SAML button, e.g. "Sign in with EMBL". */
  samlLabel?: string;
  /** Email + password sign-in is disabled on this instance, leaving Google as
   *  the only door in. The credentials form is hidden rather than shown and
   *  rejected, since /auth/login answers 403 to every attempt. */
  passwordLoginDisabled?: boolean;
  /** Switch to the register view. Omit to hide the Register button entirely
   *  (e.g. when registration is disabled on this instance). */
  onSwitchToRegister?: () => void;
  /** Called after a successful login — drives the redirect. */
  onSuccess: () => void;
}

export default function LoginForm({
  googleEnabled,
  samlEnabled = false,
  samlLabel,
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
  // Mirrors the server-side guard: hiding the credentials form is only safe
  // while there is another way in, so a deployment that sets the flag without
  // configuring OAuth keeps its password form instead of a dead card.
  const showCredentials = !passwordLoginDisabled || !(googleEnabled || samlEnabled);

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

  const googleButton = (label: string, variant: 'outline' | 'default') => (
    <Button
      id="google-oauth-button"
      variant={variant}
      radius="md"
      fullWidth
      onClick={handleGoogleClick}
      leftSection={
        <img
          src={`${import.meta.env.BASE_URL}logos/google_g.svg`}
          alt=""
          width={18}
          height={18}
          style={{ display: 'block' }}
        />
      }
    >
      {label}
    </Button>
  );

  // Glass: one column. The identity providers lead (an institution's SSO
  // first, then Google), the email form follows under an "or", and the
  // register switch sits in the card's foot (AuthApp).
  if (glass) {
    const providers = samlEnabled || googleEnabled;
    return (
      <>
        {providers && (
          <div className="gp-auth-providers">
            <SignInProviders
              googleEnabled={googleEnabled}
              samlEnabled={samlEnabled}
              samlLabel={samlLabel}
              onError={setError}
            />
          </div>
        )}
        {providers && showCredentials && <div className="gp-auth-or">or with your email</div>}
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
      {googleEnabled && (
        <Stack gap="xs">
          {/* The divider separates two alternatives. With the credentials form
              hidden there is only one, so it would divide nothing. */}
          {showCredentials ? (
            <Divider label="Or" labelPosition="center" />
          ) : (
            <Text size="sm" c="dimmed" ta="center">
              This instance signs in with Google.
            </Text>
          )}
          <Button
            id="google-oauth-button"
            variant="outline"
            radius="md"
            fullWidth
            onClick={handleGoogleClick}
            leftSection={
              <img
                src={`${import.meta.env.BASE_URL}logos/google_g.svg`}
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
