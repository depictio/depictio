import { Anchor, Loader, Stack, Text } from '@mantine/core';
import { useEffect, useRef, useState } from 'react';
import { handleGoogleCallback, persistSession } from 'depictio-react-core';
import AuthCard from './AuthCard';

const DEFAULT_POST_AUTH_PATH = '/dashboards';

/**
 * Same-origin redirect guard. The backend ultimately decides the
 * post-auth destination, but a compromised / MITMed response could supply
 * an off-origin URL (or a ``javascript:`` URL on older browsers) and turn
 * this into an open-redirect / phishing primitive. Anything that doesn't
 * normalise to a same-origin path is silently replaced with the safe
 * dashboard landing.
 */
function safePostAuthTarget(candidate: string | null | undefined): string {
  if (!candidate) return DEFAULT_POST_AUTH_PATH;
  try {
    const target = new URL(candidate, window.location.origin);
    if (target.origin !== window.location.origin) return DEFAULT_POST_AUTH_PATH;
    // Strip protocol/host so we never accidentally emit a fully-qualified URL.
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return DEFAULT_POST_AUTH_PATH;
  }
}

/**
 * Renders at /auth/google/callback?code=...&state=... after Google redirects
 * back. Calls the backend's /auth/google/callback to finalize the flow,
 * persists the session, then redirects to the post-auth destination.
 */
export default function GoogleOAuthCallback() {
  const [error, setError] = useState<string | null>(null);
  // Run exactly once. React StrictMode invokes effects twice in dev, and both
  // the authorization code and the CSRF state are single-use — a second
  // exchange is guaranteed to fail and would surface as a spurious error on
  // an otherwise successful sign-in.
  const handledRef = useRef(false);

  useEffect(() => {
    if (handledRef.current) return;
    handledRef.current = true;

    const url = new URL(window.location.href);
    const code = url.searchParams.get('code');
    const state = url.searchParams.get('state');
    const oauthError = url.searchParams.get('error');

    if (oauthError) {
      setError(`Google sign-in was cancelled or failed: ${oauthError}`);
      return;
    }
    if (!code || !state) {
      setError('Missing OAuth code or state. Please try signing in again.');
      return;
    }

    (async () => {
      const result = await handleGoogleCallback(code, state);
      if (result.success && result.session) {
        persistSession(result.session);
        window.location.assign(safePostAuthTarget(result.redirect_url));
        return;
      }
      setError(result.message || 'Google sign-in failed.');
    })();
  }, []);

  return (
    <AuthCard heading="Signing you in…">
      <Stack align="center" gap="md">
        {error ? (
          <>
            <Text c="red" ta="center">{error}</Text>
            <Anchor href="/auth">Back to sign-in</Anchor>
          </>
        ) : (
          <>
            <Loader />
            <Text c="dimmed">Completing Google sign-in…</Text>
          </>
        )}
      </Stack>
    </AuthCard>
  );
}
