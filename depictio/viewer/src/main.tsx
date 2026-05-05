import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { DatesProvider } from '@mantine/dates';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/carousel/styles.css';
// REQUIRED: @mantine/dates ships its own stylesheet. Without it, the
// DatePickerInput renders with broken/partial styling — the calendar
// dropdown is unstyled and the closed input doesn't look like the Mantine
// docs / DMC equivalent. This must come AFTER core/styles.css so the
// dates-package overrides apply.
import '@mantine/dates/styles.css';
import './styles/app.css';

import App from './App';
import EditorApp from './EditorApp';
import AuthApp from './auth/AuthApp';
import DashboardsApp from './dashboards/DashboardsApp';
import ProjectsApp from './projects/ProjectsApp';
import ProjectDetailApp from './projects/detail/ProjectDetailApp';
import PermissionsApp from './projects/detail/PermissionsApp';
import AboutApp from './about/AboutApp';
import AdminApp from './admin/AdminApp';
import ProfileApp from './profile/ProfileApp';
import CliAgentsApp from './cli-agents/CliAgentsApp';
import CreateComponentPage from './builder/CreateComponentPage';
import EditComponentPage from './builder/EditComponentPage';
import { matchEditorRoute } from './builder/routeMatch';
import {
  ErrorBoundary,
  fetchAuthStatus,
  getAnonymousSession,
  persistSession,
  validateSession,
} from 'depictio-react-core';
import { depictioTheme } from './theme';

// Client-side route resolution. FastAPI serves index.html for all paths under
// /dashboard-beta/, /dashboard-beta-edit/, /auth, /dashboards-beta,
// /about-beta, and /admin-beta — we pick the right tree at boot.
function resolveTree(): React.ReactElement {
  if (window.location.pathname.startsWith('/auth')) {
    return <AuthApp />;
  }
  if (window.location.pathname.startsWith('/dashboards-beta')) {
    return <DashboardsApp />;
  }
  if (window.location.pathname.startsWith('/projects-beta')) {
    // /projects-beta                  → list page
    // /projects-beta/{id}             → data-collections detail
    // /projects-beta/{id}/permissions → permissions editor
    if (
      /\/projects-beta\/[^/]+\/permissions(\/|$)/.test(window.location.pathname)
    ) {
      return <PermissionsApp />;
    }
    const detailMatch = window.location.pathname.match(/^\/projects-beta\/[^/]+/);
    return detailMatch ? <ProjectDetailApp /> : <ProjectsApp />;
  }
  if (window.location.pathname.startsWith('/about-beta')) {
    return <AboutApp />;
  }
  if (window.location.pathname.startsWith('/admin-beta')) {
    return <AdminApp />;
  }
  if (window.location.pathname.startsWith('/profile-beta')) {
    return <ProfileApp />;
  }
  if (window.location.pathname.startsWith('/cli-agents-beta')) {
    return <CliAgentsApp />;
  }
  const route = matchEditorRoute(window.location.pathname);
  if (!route) return <App />;
  if (route.kind === 'create') {
    return (
      <CreateComponentPage
        dashboardId={route.dashboardId}
        newComponentId={route.newComponentId}
      />
    );
  }
  if (route.kind === 'edit') {
    return (
      <EditComponentPage
        dashboardId={route.dashboardId}
        componentId={route.componentId}
      />
    );
  }
  return <EditorApp />;
}

// Mirrors depictio/dash/layouts/shared_app_shell.py:create_app_shell MantineProvider config.
// forceColorScheme initial value comes from localStorage — same key as the Dash app writes.
// Defensive parse: stale/invalid stored value must NOT crash the SPA on boot.
function readInitialColorScheme(): 'light' | 'dark' | 'auto' {
  try {
    const raw = localStorage.getItem('theme-store');
    if (!raw) return 'light';
    const parsed = JSON.parse(raw);
    const scheme = parsed?.colorScheme;
    return scheme === 'dark' || scheme === 'auto' ? scheme : 'light';
  } catch {
    return 'light';
  }
}

// Boot-time session bootstrap. Two jobs:
//   1. Refresh the JWT if it's near expiry, so the first network request of
//      the session never carries a stale token.
//   2. In single-user mode, mint+persist an admin session if one isn't in
//      localStorage yet — covers direct navigation to auth-required routes
//      like /cli-agents-beta or /profile-beta without first visiting /auth.
// Public/demo mode is intentionally NOT auto-bootstrapped: those flows
// require the user to pick "Temporary user" or Google on /auth.
async function bootstrapSession(): Promise<void> {
  const valid = await validateSession();
  if (valid) return;
  if (window.location.pathname.startsWith('/auth')) return;
  try {
    const status = await fetchAuthStatus();
    if (status.is_single_user_mode) {
      const session = await getAnonymousSession();
      persistSession(session);
    }
  } catch (err) {
    console.error('Auth bootstrap failed:', err);
  }
}

bootstrapSession().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <MantineProvider theme={depictioTheme} defaultColorScheme={readInitialColorScheme()}>
        {/* DatesProvider is required for @mantine/dates components to pick up
            locale + first-day-of-week settings. Matches what DMC does
            internally for ``dmc.DatePickerInput``. */}
        <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
          <Notifications position="bottom-right" />
          <ErrorBoundary>{resolveTree()}</ErrorBoundary>
        </DatesProvider>
      </MantineProvider>
    </React.StrictMode>,
  );
});
