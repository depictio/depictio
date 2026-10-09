import { Loader, Stack, Text } from '@mantine/core';
import React, { useEffect, useMemo, useState } from 'react';
import { createTemporaryUser, getAnonymousSession, persistSession } from 'depictio-react-core';

import AuthBackground from './components/AuthBackground';
import AuthCard from './components/AuthCard';
import GoogleOAuthCallback from './components/GoogleOAuthCallback';
import MagicLinkCallback from './components/MagicLinkCallback';
import LoginForm from './components/LoginForm';
import PublicAccessGate from './components/PublicAccessGate';
import RegisterForm from './components/RegisterForm';
import { useAuthMode } from './hooks/useAuthMode';
import './styles/auth.css';

import { postAuthDestination } from './postAuthTarget';
import { useGlassPages } from '../chrome/variants/glass/pages';
import {
  AuthThemeKey,
  GlassAuthBackground,
  GlassAuthCard,
  GlassAuthWait,
} from '../chrome/variants/glass/pages/GlassAuth';
import { useBranding } from '../branding';


type View = 'login' | 'register' | 'oauth-callback' | 'magic-callback';

function detectView(pathname: string): View {
  if (pathname.startsWith('/auth/google/callback')) return 'oauth-callback';
  if (pathname.startsWith('/auth/magic')) return 'magic-callback';
  if (pathname.startsWith('/auth/register')) return 'register';
  return 'login';
}

export default function AuthApp() {
  const initialView = useMemo<View>(() => detectView(window.location.pathname), []);
  const [view, setView] = useState<View>(initialView);
  const { loading, status, error } = useAuthMode();
  const [autoSessionError, setAutoSessionError] = useState<string | null>(null);
  const glass = useGlassPages();
  const branding = useBranding();

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
  //    behavior so visitors land directly in /dashboards. Unless the
  //    deployment sets a shared access code, in which case nothing is minted
  //    here and PublicAccessGate asks for it first.
  // 3. Standard mode with an already-resolved session — bounce straight
  //    through without touching localStorage.
  useEffect(() => {
    if (view === 'oauth-callback' || view === 'magic-callback') return;
    if (loading || !status) return;

    let cancelled = false;
    (async () => {
      try {
        if (status.is_single_user_mode) {
          const session = await getAnonymousSession();
          if (cancelled) return;
          persistSession(session);
        } else if (status.is_public_mode) {
          // A protected public deployment asks for its shared code first, so
          // the session is minted by the gate rather than on page load.
          if (status.public_access_code_required) return;
          const session = await createTemporaryUser();
          if (cancelled) return;
          persistSession(session);
        } else if (!status.user) {
          return; // let the login form render
        }
        window.location.assign(postAuthDestination());
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

  const handleSuccess = () => window.location.assign(postAuthDestination());

  if (glass) {
    const appName = branding?.app_name || 'depictio';
    const showCredentials = !(status?.password_login_disabled ?? false) || !(status?.google_oauth_enabled ?? false);
    let card: React.ReactNode;
    if (view === 'oauth-callback') card = <GoogleOAuthCallback />;
    else if (view === 'magic-callback') card = <MagicLinkCallback />;
    else if (loading) {
      card = (
        <GlassAuthCard title={`Opening ${appName}`}>
          <GlassAuthWait text="Checking how this instance signs people in." />
        </GlassAuthCard>
      );
    } else if (error) {
      card = (
        <GlassAuthCard title={`${appName} could not start`} lede="The server did not answer the sign-in check.">
          <p className="gp-auth-error" role="alert">{error}</p>
        </GlassAuthCard>
      );
    } else if (status?.is_public_mode && status?.public_access_code_required) {
      card = (
        <GlassAuthCard
          title="Enter the access code"
          lede="This instance is open to anyone with its access code. You continue as a guest, no account needed."
        >
          <PublicAccessGate onSuccess={handleSuccess} />
        </GlassAuthCard>
      );
    } else if (status?.is_single_user_mode || status?.is_public_mode) {
      card = (
        <GlassAuthCard title={status.is_single_user_mode ? 'Starting your session' : 'Starting a guest session'}>
          {autoSessionError ? (
            <p className="gp-auth-error" role="alert">{autoSessionError}</p>
          ) : (
            <GlassAuthWait
              text={status.is_single_user_mode ? 'Signing you in to this single-user instance.' : 'Creating a temporary guest account.'}
            />
          )}
        </GlassAuthCard>
      );
    } else if (view === 'register' && !status?.registration_disabled) {
      card = (
        <GlassAuthCard
          title="Create your account"
          lede={`An account keeps your dashboards and projects on ${appName}.`}
          foot={
            <>
              <span>Already have an account?</span>
              <button type="button" className="gp-auth-link" onClick={() => setView('login')} data-testid="open-login-form">
                Sign in
              </button>
            </>
          }
        >
          <RegisterForm onSwitchToLogin={() => setView('login')} onSuccess={handleSuccess} />
        </GlassAuthCard>
      );
    } else {
      card = (
        <GlassAuthCard
          title={`Sign in to ${appName}`}
          lede="Open your dashboards and the projects behind them."
          foot={
            !status?.registration_disabled && showCredentials ? (
              <>
                <span>New here?</span>
                <button type="button" className="gp-auth-link" onClick={() => setView('register')} data-testid="open-register-form">
                  Create an account
                </button>
              </>
            ) : undefined
          }
        >
          <LoginForm
            googleEnabled={status?.google_oauth_enabled ?? false}
            passwordLoginDisabled={status?.password_login_disabled ?? false}
            onSuccess={handleSuccess}
          />
        </GlassAuthCard>
      );
    }
    return (
      <>
        <GlassAuthBackground />
        <AuthThemeKey />
        <div className="auth-page-content">{card}</div>
      </>
    );
  }

  return (
    <>
      <AuthBackground />
      <div className="auth-page-content">
        {view === 'oauth-callback' ? (
          <GoogleOAuthCallback />
        ) : view === 'magic-callback' ? (
          <MagicLinkCallback />
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
        ) : status?.is_public_mode && status?.public_access_code_required ? (
          <AuthCard heading="Welcome to Depictio :">
            <PublicAccessGate onSuccess={handleSuccess} />
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
        ) : view === 'register' && !status?.registration_disabled ? (
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
              passwordLoginDisabled={status?.password_login_disabled ?? false}
              onSwitchToRegister={
                status?.registration_disabled ? undefined : () => setView('register')
              }
              onSuccess={handleSuccess}
            />
          </AuthCard>
        )}
      </div>
    </>
  );
}
