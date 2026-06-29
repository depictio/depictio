import { Anchor, Loader, Stack, Text } from '@mantine/core';
import { useEffect, useRef, useState } from 'react';
import { exchangeMagicToken, persistSession } from 'depictio-react-core';
import AuthCard from './AuthCard';

const DEFAULT_REDIRECT = '/dashboards';

/** Only allow same-origin relative paths as a redirect target, so a crafted
 *  `next=` can't bounce the freshly-authenticated user to an external site. */
function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//')) return DEFAULT_REDIRECT;
  return next;
}

/**
 * Renders at /auth/magic#ticket=...&next=... — the passwordless login link a
 * pipeline hands a user. The single-use ticket rides in the URL fragment (kept
 * out of server/proxy access logs and Referer); we exchange it server-side for
 * a session, persist it, and redirect to the dashboard.
 */
export default function MagicLinkCallback() {
  const [error, setError] = useState<string | null>(null);
  // Run exactly once. React StrictMode invokes effects twice in dev; without
  // this guard the first run strips the fragment (below) and the second run
  // reads an empty hash → a spurious "missing token" error (and a wasted,
  // already-consumed exchange).
  const handledRef = useRef(false);

  useEffect(() => {
    if (handledRef.current) return;
    handledRef.current = true;

    const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const ticket = params.get('ticket');
    const next = safeNext(params.get('next'));

    if (!ticket) {
      setError('This login link is missing its token. Please request a new one.');
      return;
    }

    // Strip the fragment immediately so the ticket doesn't linger in browser
    // history or a shared/bookmarked URL after we've consumed it.
    const { pathname, search } = window.location;
    window.history.replaceState(null, '', pathname + search);

    (async () => {
      try {
        const session = await exchangeMagicToken(ticket);
        persistSession(session);
        window.location.assign(next);
      } catch (err) {
        console.error('[auth] magic-link exchange failed:', err);
        setError(
          'This login link is invalid or has expired. Please request a new one.',
        );
      }
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
            <Text c="dimmed">Completing sign-in…</Text>
          </>
        )}
      </Stack>
    </AuthCard>
  );
}
