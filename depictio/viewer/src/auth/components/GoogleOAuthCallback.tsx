import { Anchor, Loader, Stack, Text } from '@mantine/core';
import { useEffect, useRef, useState } from 'react';
import { handleGoogleCallback, persistSession } from 'depictio-react-core';
import AuthCard from './AuthCard';
import { postAuthDestination } from '../postAuthTarget';

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
        window.location.assign(postAuthDestination(result.redirect_url));
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
