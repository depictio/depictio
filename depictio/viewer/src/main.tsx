// REQUIRED FIRST: registers the bundled Iconify icons. Without it every
// <Icon/> tries to fetch its data from the public Iconify API, which the
// deployed CSP blocks, and all icons render empty. See src/icons.ts.
import './icons';

import React, { Suspense } from 'react';
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
// REQUIRED: @mantine/tiptap ships its own stylesheet for the RichTextEditor.
// Without it, the toolbar's ControlsGroup/Bold/Italic/etc. controls render
// as un-styled invisible boxes and the editor surface has no border or
// padding, producing a large empty gap inside the NotesFooter drawer.
import '@mantine/tiptap/styles.css';
import './styles/app.css';

// Each route tree is its own async chunk. Only one tree renders per page load
// (resolveTree picks it by pathname), so eagerly importing all thirteen forced
// the entry bundle to carry every route's dependencies — including the
// plotly/tiptap/ag-grid the builder and project-detail previews pull in — onto
// the dashboard viewer's boot path. Lazy imports keep the viewer route from
// downloading the editor/builder stack (and vice-versa); Vite fetches the
// chosen tree's chunk on demand behind the Suspense boundary below.
const App = React.lazy(() => import('./App'));
const EditorApp = React.lazy(() => import('./EditorApp'));
import { rememberReturnTo } from './auth/postAuthTarget';
const AuthApp = React.lazy(() => import('./auth/AuthApp'));
const DashboardsApp = React.lazy(() => import('./dashboards/DashboardsApp'));
const ProjectsApp = React.lazy(() => import('./projects/ProjectsApp'));
const ProjectDetailApp = React.lazy(() => import('./projects/detail/ProjectDetailApp'));
const PermissionsApp = React.lazy(() => import('./projects/detail/PermissionsApp'));
const AboutApp = React.lazy(() => import('./about/AboutApp'));
const AdminApp = React.lazy(() => import('./admin/AdminApp'));
const ProfileApp = React.lazy(() => import('./profile/ProfileApp'));
const CliAgentsApp = React.lazy(() => import('./cli-agents/CliAgentsApp'));
const EmbedApp = React.lazy(() => import('./embed/EmbedApp'));
const CreateComponentPage = React.lazy(() => import('./builder/CreateComponentPage'));
const EditComponentPage = React.lazy(() => import('./builder/EditComponentPage'));
import { matchEditorRoute } from './builder/routeMatch';
import {
  ErrorBoundary,
  clearSession,
  createTemporaryUser,
  fetchAuthStatus,
  fetchPublicConfig,
  getAnonymousSession,
  persistSession,
  startSessionKeepAlive,
  validateSession,
} from 'depictio-react-core';
import { UiScaleContext } from 'depictio-react-core';
import BootSplash from './components/BootSplash';
import { brandCssVariablesResolver, buildDepictioTheme } from './theme';
import { readStoredScheme } from './hooks/useColorScheme';
import { useUiScalePref } from './hooks/useUiScalePref';
import { BrandingContext, getBranding, setBranding, subscribeBranding } from './branding';
import { initGoogleAnalytics } from './googleAnalytics';
import { WalkthroughHost } from './walkthrough';

// Client-side route resolution. FastAPI serves index.html for all paths under
// /dashboard/, /dashboard-edit/, /auth, /dashboards,
// /about, and /admin — we pick the right tree at boot.
function resolveTree(): React.ReactElement {
  if (window.location.pathname.startsWith('/auth')) {
    return <AuthApp />;
  }
  if (window.location.pathname.startsWith('/dashboards')) {
    return <DashboardsApp />;
  }
  if (window.location.pathname.startsWith('/projects')) {
    // /projects                  → list page
    // /projects/{id}             → data-collections detail
    // /projects/{id}/permissions → permissions editor
    if (
      /\/projects\/[^/]+\/permissions(\/|$)/.test(window.location.pathname)
    ) {
      return <PermissionsApp />;
    }
    const detailMatch = window.location.pathname.match(/^\/projects\/[^/]+/);
    return detailMatch ? <ProjectDetailApp /> : <ProjectsApp />;
  }
  if (window.location.pathname.startsWith('/about')) {
    return <AboutApp />;
  }
  if (window.location.pathname.startsWith('/admin')) {
    return <AdminApp />;
  }
  if (window.location.pathname.startsWith('/profile')) {
    return <ProfileApp />;
  }
  if (window.location.pathname.startsWith('/cli-agents')) {
    return <CliAgentsApp />;
  }
  if (window.location.pathname.startsWith('/embed/')) {
    // One component, standalone — for headless figure extraction and notebook embeds.
    return <EmbedApp />;
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
// Initial value comes from localStorage — same key/parser as useColorScheme, so
// the boot-time read and the hook's hydration can never disagree.
function readInitialColorScheme(): 'light' | 'dark' {
  return readStoredScheme() ?? 'light';
}

/**
 * Theme + UI-scale + branding root. Rebuilds the Mantine theme whenever the
 * instance brand theme resolves (cached in localStorage for a flash-free first
 * paint on return visits; the /utils/public-config fetch updates it
 * in-flight). The font-size preference deliberately does NOT touch the theme:
 * it scales dashboard content only (see useContentScaleStyle), never the app
 * chrome. The numeric scale reaches the non-Mantine content surfaces (Plotly
 * fonts, AG Grid row metrics) via UiScaleContext; the branding reaches
 * logo/title consumers via BrandingContext.
 *
 * Surfaces (page/nav/section backgrounds, heading color) travel as CSS
 * variables rather than theme fields: a brand needs a light *and* a dark value
 * for each, which is exactly what `cssVariablesResolver` is for.
 */
function ThemeRoot({ children }: { children: React.ReactNode }) {
  const { scale } = useUiScalePref();
  const branding = React.useSyncExternalStore(subscribeBranding, getBranding);
  const theme = React.useMemo(() => buildDepictioTheme({ brand: branding }), [branding]);
  const cssVariablesResolver = React.useMemo(
    () => brandCssVariablesResolver(branding),
    [branding],
  );

  return (
    <UiScaleContext.Provider value={scale}>
      <BrandingContext.Provider value={branding}>
        <MantineProvider
          theme={theme}
          cssVariablesResolver={cssVariablesResolver}
          defaultColorScheme={readInitialColorScheme()}
        >
          {/* DatesProvider is required for @mantine/dates components to pick up
              locale + first-day-of-week settings. Matches what DMC does
              internally for ``dmc.DatePickerInput``. */}
          <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
            <Notifications position="bottom-right" />
            <ErrorBoundary>
              <Suspense fallback={<BootSplash />}>{children}</Suspense>
            </ErrorBoundary>
            <WalkthroughHost />
          </DatesProvider>
        </MantineProvider>
      </BrandingContext.Provider>
    </UiScaleContext.Provider>
  );
}

// Boot-time session bootstrap. Four jobs:
//   1. Refresh the JWT if it's near expiry, so the first network request of
//      the session never carries a stale token.
//   2. Mint+persist a session if one isn't in localStorage yet:
//      - Single-user mode: anonymous-but-admin session.
//      - Public/demo mode: a fresh temporary user (no anonymous intermediate).
//      Covers direct navigation to auth-required routes without first
//      visiting /auth.
//   3. Verify the locally-stored token actually authenticates against the
//      backend — ``validateSession`` only checks the access_token isn't
//      expired locally, so a token revoked server-side (e.g. JWT secret
//      rotated by a docker rebuild) would otherwise pass. We confirm by
//      asking ``/auth/me/optional`` and re-mint or redirect when the
//      backend doesn't recognize the user.
//   4. Standard mode without a valid session — redirect to /auth so the
//      user lands on the login form instead of a broken /dashboards
//      where every API call 401s.
/** Cross-origin hand-off: the Dash app's beta-switcher pill links here
 *  with a `#auth=<base64-utf8 JSON>` fragment carrying the session it
 *  has in its own localStorage (different origin, so we can't read it
 *  directly). Decode, persist into THIS origin's localStorage, then
 *  strip the fragment from the URL so it doesn't leak via history
 *  share-links or appear in the address bar. Errors are swallowed —
 *  malformed fragments just fall through to the normal bootstrap path,
 *  which will redirect to /auth if no valid session is reachable. */
function consumeCrossOriginSessionHandoff(): void {
  if (!window.location.hash || !window.location.hash.includes('auth=')) return;
  try {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const encoded = params.get('auth');
    if (!encoded) return;
    const decoded = decodeURIComponent(escape(window.atob(encoded)));
    const session = JSON.parse(decoded);
    // Permissive cast: the Dash app's stored shape is a SessionPayload
    // superset, but TS doesn't know that statically. Validate the
    // required `access_token` so a malformed payload doesn't blow up
    // the bootstrap.
    if (
      session &&
      typeof session === 'object' &&
      typeof session.access_token === 'string'
    ) {
      persistSession(session as unknown as Parameters<typeof persistSession>[0]);
    }
  } catch (err) {
    console.warn('[auth] cross-origin session hand-off failed:', err);
  } finally {
    // Always strip the fragment so the URL bar / shareable link don't
    // carry the token after consumption — even on parse failure.
    const { pathname, search } = window.location;
    window.history.replaceState(null, '', pathname + search);
  }
}

/** Bounce to the gate, remembering the page that was asked for so the visitor
 *  lands there rather than on the listing once they are through. */
function redirectToAuth(): void {
  rememberReturnTo();
  window.location.replace('/auth');
}

async function bootstrapSession(): Promise<void> {
  if (window.location.pathname.startsWith('/auth')) return;

  // Run BEFORE validateSession so a freshly-handed-off token is the one
  // we check against the backend.
  consumeCrossOriginSessionHandoff();

  const localValid = await validateSession();
  let status;
  try {
    status = await fetchAuthStatus();
  } catch (err) {
    console.error('Auth bootstrap: failed to read /auth/me/optional', err);
    redirectToAuth();
    return;
  }

  // Has a local token AND backend resolved a user → session is good.
  if (localValid && status.user) return;

  // Either no local token, or local token is stale/revoked. Drop it before
  // re-establishing so the next call doesn't reuse the bad token.
  if (!status.user) {
    try { clearSession(); } catch { /* ignore */ }
  }

  try {
    if (status.is_single_user_mode) {
      const session = await getAnonymousSession();
      persistSession(session);
      return;
    }
    if (status.is_public_mode) {
      // A protected public instance has no session to hand out until the
      // visitor has passed the shared code, so go to the gate rather than
      // spend a round-trip on a mint the backend is going to refuse.
      if (status.public_access_code_required) {
        redirectToAuth();
        return;
      }
      const session = await createTemporaryUser();
      persistSession(session);
      return;
    }
    // Standard mode, no valid session — send to login.
    redirectToAuth();
  } catch (err) {
    console.error('Auth bootstrap failed:', err);
    // Fail safe: when bootstrap can't recover, route to /auth so the user
    // sees an actionable login form rather than a silently broken SPA.
    redirectToAuth();
  }
}

/** Load per-deployment frontend config and act on it. Never blocks the render.
 *
 * Fire-and-forget on purpose: analytics is not worth a millisecond of time to
 * first paint, and a backend that doesn't serve `/utils/public-config` (an older
 * version) must leave the app entirely unaffected. */
function bootstrapPublicConfig(): void {
  void fetchPublicConfig()
    .then((config) => {
      const ga = config.google_analytics;
      if (ga?.enabled && ga.tracking_id) {
        initGoogleAnalytics(ga.tracking_id);
      }
      // Instance brand theme: push into the theme root's store + localStorage
      // cache. `undefined` means an older backend without the field — leave
      // whatever the cache holds rather than un-branding a live UI.
      if (config.branding !== undefined) {
        setBranding(config.branding);
      }
    })
    .catch(() => undefined);
}

// Bare SPA root → dashboards list. Vite/FastAPI mount the SPA at
// `/dashboard/` so asset URLs resolve correctly, but that path on its
// own has no dashboard id to render. Bounce unparameterized hits (`/`,
// `/dashboard`, `/dashboard/`) to the list page; if the visitor
// isn't logged in, `bootstrapSession` on the next load routes them through
// `/auth`, and `AuthApp.POST_AUTH_REDIRECT` brings them back here.
const isBareRoot = /^\/(dashboard\/?)?$/.test(window.location.pathname);
if (isBareRoot) {
  window.location.replace('/dashboards');
} else {
  bootstrapPublicConfig();
  bootstrapSession().finally(() => {
    // Keep the access token fresh for the whole page session. Without this a
    // long-open view (dashboard filters, admin monitoring) outlives the 1h
    // token and every subsequent request 401s with "Invalid token".
    startSessionKeepAlive();
    ReactDOM.createRoot(document.getElementById('root')!).render(
      <React.StrictMode>
        <ThemeRoot>{resolveTree()}</ThemeRoot>
      </React.StrictMode>,
    );
  });
}
