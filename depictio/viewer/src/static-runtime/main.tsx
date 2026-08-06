/**
 * Entry for the serverless static-bundle runtime (RFC §3.2).
 *
 * Mounts the *real* viewer App against an embedded bundle manifest instead of
 * the API: the vite.static.config.ts build shims api.ts, useCurrentUser.ts and
 * realtime.ts (see moduleShim), and this entry never imports bootstrapSession,
 * the router, or BootSplash — exactly the catalog-preview precedent.
 */
// REQUIRED FIRST: registers the bundled Iconify icons. The bundle is opened
// straight from disk with no network, so unbundled icons could never resolve.
//
// Registering them is only half of it: Iconify's default entry FETCHES an
// unknown icon name from api.iconify.design, and a dashboard document carries
// author-supplied icon ids the source scanner never saw. vite.static.config.ts
// therefore aliases `@iconify/react` to its `/offline` entry, which has no API
// code at all — see the comment there for the trade-off.
import '../icons';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { DatesProvider } from '@mantine/dates';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/carousel/styles.css';
import '@mantine/dates/styles.css';
import '@mantine/tiptap/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../styles/app.css';

import { StaticBadgeProvider, type StaticTierMap } from 'depictio-react-core';

import { depictioTheme } from '../theme';
import App from '../App';
import { bundledTabs, currentTabId, loadBundleFromDocument, setActiveTab } from './bundle';
import { installBundleNavigation } from './tabNav';

// Also sets window.__DEPICTIO_STATIC_DASHBOARD_ID__ (via setActiveTab below /
// loadBundleFromDocument's seed): App has no /dashboard/<id> route to read on
// file:// or a static host, so extractDashboardId() falls back to that global.
const manifest = loadBundleFromDocument();
setActiveTab(manifest.dashboard.id);

/**
 * Open the tab rail on first run when the bundle has a family to show.
 *
 * `useSidebarOpen()` defaults to COLLAPSED, and on a server that is fine — the
 * viewer is one page of a site you navigated into, and the rail is one click
 * away. A bundle is a file somebody was sent: if it holds three tabs and opens
 * showing one, with no address bar and no other affordance, the other two do
 * not exist. Seeding the same `sidebar-collapsed` key the hook reads keeps this
 * a DEFAULT and not an override — any later toggle is written back over it and
 * survives, and single-tab bundles are left alone.
 */
if (bundledTabs().length > 0) {
  try {
    if (localStorage.getItem('sidebar-collapsed') == null) {
      localStorage.setItem('sidebar-collapsed', 'false');
    }
  } catch {
    /* storage unavailable (file:// with cookies blocked) — rail stays default */
  }
}

/**
 * Owns which tab of the family is on screen.
 *
 * App is REMOUNTED on a switch (`key`), not re-rendered: `extractDashboardId()`
 * reads the global once per render and is not reactive, and every piece of
 * App's state is scoped to one dashboard document anyway. A remount is also
 * exactly what the server does — there, a rail pill is an `<a href>` and
 * switching tab is a full page load — so per-tab state behaves identically in
 * a bundle and on the instance it was exported from: interactive filters reset,
 * while the floating-map selection (persisted to storage) and the panel
 * width/collapse prefs (persisted per dashboard id) survive.
 */
const StaticRuntime: React.FC = () => {
  const [tabId, setTabId] = React.useState(() => currentTabId());
  // `setActiveTab` has already run inside the interceptor by the time this
  // state lands; the effect only wires the listener up (and tears it down for
  // StrictMode's double mount).
  React.useEffect(() => installBundleNavigation(setTabId), []);
  return <App key={tabId} />;
};

// The badge provider must sit above every LazyMount/Suspense boundary: one of
// the ten chrome call sites (AdvancedVizDispatch) lives in a separately
// lazy-loaded chunk and reads the context after this tree is mounted.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} defaultColorScheme="auto">
      <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
        <Notifications position="bottom-right" />
        <StaticBadgeProvider tiers={manifest.tiers as StaticTierMap}>
          <StaticRuntime />
        </StaticBadgeProvider>
      </DatesProvider>
    </MantineProvider>
  </React.StrictMode>,
);
