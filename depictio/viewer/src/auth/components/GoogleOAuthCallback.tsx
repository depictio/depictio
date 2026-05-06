import { Anchor, Loader, Stack, Text } from '@mantine/core';
import { useEffect, useState } from 'react';
import { handleGoogleCallback, persistSession } from 'depictio-react-core';
import AuthCard from './AuthCard';

/**
 * Renders at /auth/google/callback?code=...&state=... after Google redirects
 * back. Calls the backend's /auth/google/callback to finalize the flow,
 * persists the session, then redirects to the post-auth destination.
 */
export default function GoogleOAuthCallback() {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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

    let cancelled = false;
    (async () => {
      const result = await handleGoogleCallback(code, state);
      if (cancelled) return;
      if (result.success && result.session) {
        persistSession(result.session);
        window.location.assign(result.redirect_url || '/dashboards');
        return;
      }
      setError(result.message || 'Google sign-in failed.');
    })();

    return () => { cancelled = true; };
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
