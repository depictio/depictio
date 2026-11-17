/**
 * Messages for the `/auth?error=<code>` redirects the API issues when an
 * OpenID Connect sign-in fails. Unknown codes fall back to a generic message.
 */
const SSO_ERROR_MESSAGES: Record<string, string> = {
  sso_failed: 'Single sign-on failed. Please try again.',
  sso_cancelled: 'Single sign-on was cancelled.',
  sso_unavailable: 'The single sign-on provider is not available right now. Please try again later.',
  registration_disabled:
    'No account exists for this identity, and self-registration is disabled. Ask an administrator to create one.',
  email_not_verified:
    'The identity provider did not confirm your email address, so you cannot sign in with it.',
};

/** The message for an `error` query value, or null when there is none. */
export function ssoErrorMessage(code: string | null | undefined): string | null {
  if (!code) return null;
  return SSO_ERROR_MESSAGES[code] ?? 'Sign-in failed. Please try again.';
}

/** Read the `error` query parameter, if any. */
export function readSsoErrorCode(): string | null {
  return new URLSearchParams(window.location.search).get('error');
}
