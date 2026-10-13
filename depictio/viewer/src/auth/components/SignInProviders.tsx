import { Button } from '@mantine/core';
import { KeyRound } from 'lucide-react';
import { samlLoginUrl, startGoogleOAuth } from 'depictio-react-core';

import { returnPathOrDefault } from '../guestSignIn';
import { rememberReturnTo } from '../postAuthTarget';

interface Props {
  googleEnabled: boolean;
  /** SAML SSO login enabled (e.g. EMBL Keycloak). */
  samlEnabled?: boolean;
  /** Label for the SAML button, e.g. "Sign in with EMBL". */
  samlLabel?: string;
  /** Called with a message when a provider could not be started. */
  onError?: (message: string) => void;
}

/**
 * The identity-provider buttons, one place for them: an institution's SSO
 * first, then Google. The sign-in form, the guest prompts and the profile page
 * all render these, so a new provider or a restyle reaches every door at once.
 *
 * Starting a provider remembers the page the visitor is on, so they come back
 * to it afterwards (a no-op on `/auth`, which is never a destination).
 */
export default function SignInProviders({
  googleEnabled,
  samlEnabled = false,
  samlLabel,
  onError,
}: Props) {
  async function handleGoogleClick() {
    try {
      rememberReturnTo();
      const { authorization_url } = await startGoogleOAuth();
      window.location.assign(authorization_url);
    } catch (err) {
      onError?.('Failed to start Google sign-in.');
      console.error(err);
    }
  }

  return (
    <>
      {samlEnabled && (
        <Button
          id="saml-login-button"
          data-testid="saml-login-button"
          variant="default"
          fullWidth
          leftSection={<KeyRound size={18} strokeWidth={1.8} aria-hidden />}
          onClick={() => window.location.assign(samlLoginUrl(returnPathOrDefault()))}
        >
          {samlLabel || 'Sign in with SSO'}
        </Button>
      )}
      {googleEnabled && (
        <Button
          id="google-oauth-button"
          variant="default"
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
      )}
    </>
  );
}
