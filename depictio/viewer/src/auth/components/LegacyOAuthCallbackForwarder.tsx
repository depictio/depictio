import { Loader, Stack, Text } from '@mantine/core';
import { useEffect } from 'react';
import { oidcCallbackUrl } from 'depictio-react-core';

import AuthCard from './AuthCard';

/**
 * Renders at the legacy `/auth/google/callback?code=..&state=..` path.
 *
 * Deployments registered that URL with Google before sign-in moved to generic
 * OpenID Connect, and the backend still sends it as the redirect URI for the
 * mapped `google` provider. The API owns the code exchange now, so the browser
 * is handed straight on to its callback with the query string untouched; no
 * token is handled here.
 */
export default function LegacyOAuthCallbackForwarder() {
  useEffect(() => {
    window.location.replace(oidcCallbackUrl('google', window.location.search));
  }, []);

  return (
    <AuthCard heading="Signing you in…">
      <Stack align="center" gap="md">
        <Loader />
        <Text c="dimmed">Completing sign-in…</Text>
      </Stack>
    </AuthCard>
  );
}
