import { Loader, Stack, Text } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import { getAnonymousSession, persistSession } from 'depictio-react-core';

import AuthBackground from './components/AuthBackground';
import AuthCard from './components/AuthCard';
import GoogleOAuthCallback from './components/GoogleOAuthCallback';
import LoginForm from './components/LoginForm';
import PublicModeOptions from './components/PublicModeOptions';
import RegisterForm from './components/RegisterForm';
import { useAuthMode } from './hooks/useAuthMode';
import './styles/auth.css';

const POST_AUTH_REDIRECT = '/dashboards';

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
  const [singleUserError, setSingleUserError] = useState<string | null>(null);

  // Single-user mode: skip the form, fetch the anonymous session and bounce
  // straight to /dashboards. The page never renders any UI in this case.
  useEffect(() => {
    if (view === 'oauth-callback') return;
    if (loading || !status) return;
    if (!status.is_single_user_mode) return;

    let cancelled = false;
    (async () => {
      try {
        const session = await getAnonymousSession();
        if (cancelled) return;
        persistSession(session);
        window.location.assign(POST_AUTH_REDIRECT);
      } catch (err) {
        console.error(err);
        if (!cancelled) {
          setSingleUserError(
            'Failed to start single-user session. Check the backend configuration.',
          );
        }
      }
    })();

    return () => { cancelled = true; };
  }, [loading, status, view]);

  // If the user is already authenticated (token in local-store resolved to a
  // user), bounce to /dashboards rather than re-rendering the login form.
  useEffect(() => {
    if (view === 'oauth-callback') return;
    if (loading || !status) return;
    if (status.user) {
      window.location.assign(POST_AUTH_REDIRECT);
    }
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
        ) : status?.is_single_user_mode ? (
          <AuthCard heading="Welcome to Depictio :">
            <Stack align="center" gap="md">
              {singleUserError ? (
                <Text c="red" ta="center">{singleUserError}</Text>
              ) : (
                <>
                  <Loader />
                  <Text c="dimmed">Starting single-user session…</Text>
                </>
              )}
            </Stack>
          </AuthCard>
        ) : status?.is_public_mode ? (
          <AuthCard heading="Welcome to Depictio">
            <PublicModeOptions
              googleEnabled={status.google_oauth_enabled}
              expiryHours={24}
              expiryMinutes={0}
              onSuccess={handleSuccess}
            />
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
