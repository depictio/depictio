import { Loader, Stack, Text } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { createTemporaryUser, getAnonymousSession, persistSession } from 'depictio-react-core';

import AuthBackground from './components/AuthBackground';
import AuthCard from './components/AuthCard';
import GoogleOAuthCallback from './components/GoogleOAuthCallback';
import LoginForm from './components/LoginForm';
import RegisterForm from './components/RegisterForm';
import { useAuthMode } from './hooks/useAuthMode';
import './styles/auth.css';

const POST_AUTH_REDIRECT = '/dashboards-beta';

type View = 'login' | 'register' | 'oauth-callback';

function detectView(pathname: string): View {
  if (pathname.startsWith('/auth/google/callback')) return 'oauth-callback';
  if (pathname.startsWith('/auth/register')) return 'register';
  return 'login';
}

export default function AuthApp() {
  const initialView = useMemo<View>(() => detectView(window.location.pathname), []);
  const [view, setView] = useState<View>(initialView);
  const { loading, status, error } = useAuthMode();
  const [autoSessionError, setAutoSessionError] = useState<string | null>(null);

  // Auto-redirect on /auth load. Three cases:
  // 1. Single-user mode — always fetch a fresh admin session and persist it
  //    before navigating. /auth/me/optional resolves the admin via fallback
  //    so `status.user` is truthy here, but we MUST persist the token first
  //    so /dashboards' API calls carry `Authorization: Bearer <admin>`.
  //    Without this, save_dashboard's get_user_or_anonymous falls back to
  //    the anonymous user and dashboards land in "Accessed" with the wrong
  //    owner.
  // 2. Public/demo mode — mint a fresh temporary user (no anonymous
  //    intermediate) and persist before navigating. Mirrors single-user
  //    behavior so visitors land directly in /dashboards.
  // 3. Standard mode with an already-resolved session — bounce straight
  //    through without touching localStorage.
  useEffect(() => {
    if (view === 'oauth-callback') return;
    if (loading || !status) return;

    let cancelled = false;
    (async () => {
      try {
        if (status.is_single_user_mode) {
          const session = await getAnonymousSession();
          if (cancelled) return;
          persistSession(session);
        } else if (status.is_public_mode) {
          const session = await createTemporaryUser();
          if (cancelled) return;
          persistSession(session);
        } else if (!status.user) {
          return; // let the login form render
        }
        window.location.assign(POST_AUTH_REDIRECT);
      } catch (err) {
        console.error(err);
        if (!cancelled) {
          setAutoSessionError(
            'Failed to start session. Check the backend configuration.',
          );
        }
      }
    })();

    return () => { cancelled = true; };
  }, [loading, status, view]);

  const handleSuccess = () => window.location.assign(POST_AUTH_REDIRECT);

  return (
    <>
      <AuthBackground />
      <div className="auth-page-content">
        {view === 'oauth-callback' ? (
          <GoogleOAuthCallback />
        ) : loading ? (
          <AuthCard heading="Welcome to Depictio :">
            <Stack align="center" gap="md">
              <Loader />
              <Text c="dimmed">Loading…</Text>
            </Stack>
          </AuthCard>
        ) : error ? (
          <AuthCard heading="Welcome to Depictio :">
            <Text c="red" ta="center">{error}</Text>
          </AuthCard>
        ) : status?.is_single_user_mode || status?.is_public_mode ? (
          <AuthCard heading="Welcome to Depictio :">
            <Stack align="center" gap="md">
              {autoSessionError ? (
                <Text c="red" ta="center">{autoSessionError}</Text>
              ) : (
                <>
                  <Loader />
                  <Text c="dimmed">
                    {status.is_single_user_mode
                      ? 'Starting single-user session…'
                      : 'Starting temporary session…'}
                  </Text>
                </>
              )}
            </Stack>
          </AuthCard>
        ) : view === 'register' ? (
          <AuthCard heading="Please register :">
            <RegisterForm
              onSwitchToLogin={() => setView('login')}
              onSuccess={handleSuccess}
            />
          </AuthCard>
        ) : (
          <AuthCard heading="Welcome to Depictio :">
            <LoginForm
              googleEnabled={status?.google_oauth_enabled ?? false}
              onSwitchToRegister={() => setView('register')}
              onSuccess={handleSuccess}
            />
          </AuthCard>
        )}
      </div>
    </>
  );
}
