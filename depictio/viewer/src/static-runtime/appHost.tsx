/**
 * The App host of the static runtime: the whole viewer App over a page.
 *
 * Booted by the serverless bundle's entry (`main.tsx`, RFC §3.2) and by the
 * combined runtime (`combined/main.tsx`) inside the dashboard view of a
 * combined report + dashboard file, where the page is a same-origin iframe the
 * report builds on demand.
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
import {
  bundledTabs,
  currentTabId,
  isBundledTab,
  loadBundleFromDocument,
  setActiveTab,
} from './bundle';
import { installBundleNavigation } from './tabNav';
import { installInlineMultiqcLogos } from '../chrome/multiqcLogo';
import { BundleProjectPageContext, type BundleProjectPage } from '../chrome/bundlePage';
import ProjectPage from './ProjectPage';
import type { DashboardController } from 'depictio-static-core';

/** What a host page may ask of a mounted App (the combined file's dashboard
 *  view): which tab is on screen, and to move to another one. */
export type AppController = DashboardController;

export interface BootAppOptions {
  /** The tab to open on instead of the manifest's entry tab. */
  initialTab?: string | null;
  /** Handed the App's controller once, before the first render. */
  onController?: (controller: AppController) => void;
}

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
function seedSidebarOpen(): void {
  if (bundledTabs().length === 0) return;
  try {
    if (localStorage.getItem('sidebar-collapsed') == null) {
      localStorage.setItem('sidebar-collapsed', 'false');
    }
  } catch {
    /* storage unavailable (file:// with cookies blocked) — rail stays default */
  }
}

/** Tab switches requested from outside React (the host page). */
type TabListener = (id: string) => void;

/**
 * Owns which tab of the family is on screen, and whether the project page is
 * laid over it.
 *
 * App is REMOUNTED on a switch (`key`), not re-rendered: `extractDashboardId()`
 * reads the global once per render and is not reactive, and every piece of
 * App's state is scoped to one dashboard document anyway. A remount is also
 * exactly what the server does — there, a rail pill is an `<a href>` and
 * switching tab is a full page load — so per-tab state behaves identically in
 * a bundle and on the instance it was exported from: interactive filters reset,
 * while the floating-map selection (persisted to storage) and the panel
 * width/collapse prefs (persisted per dashboard id) survive.
 *
 * The project page answers every link the live app has to `/projects/<id>`
 * (the Settings drawer, the sidebar's project row): a bundle has no such
 * route, so it opens over the canvas here, and moving to a tab closes it.
 */
const StaticRuntime: React.FC<{
  project: { name: string } | null;
  requests: { listen: (fn: TabListener) => () => void };
  announce: (id: string) => void;
}> = ({ project, requests, announce }) => {
  const [tabId, setTabId] = React.useState(() => currentTabId());
  const [projectOpen, setProjectOpen] = React.useState(false);
  // `setActiveTab` has already run inside the interceptor by the time this
  // state lands; the effect only wires the listener up (and tears it down for
  // StrictMode's double mount).
  React.useEffect(
    () =>
      installBundleNavigation({
        onSwitchTab: (id) => {
          setProjectOpen(false);
          setTabId(id);
        },
        onOpenProject: () => {
          if (!project) return false;
          setProjectOpen(true);
          return true;
        },
      }),
    [project],
  );
  // A switch asked for by the host page (the combined file's cross-links).
  React.useEffect(
    () =>
      requests.listen((id) => {
        setProjectOpen(false);
        setTabId(id);
      }),
    [requests],
  );
  React.useEffect(() => announce(tabId), [tabId, announce]);
  const projectPage = React.useMemo<BundleProjectPage | null>(
    () =>
      project
        ? {
            name: project.name,
            open: projectOpen,
            openPage: () => setProjectOpen(true),
            closePage: () => setProjectOpen(false),
            render: (props) => <ProjectPage {...props} />,
          }
        : null,
    [project, projectOpen],
  );
  return (
    <BundleProjectPageContext.Provider value={projectPage}>
      <App key={tabId} />
    </BundleProjectPageContext.Provider>
  );
};

/**
 * The scheme the bundle opens in: the reader's earlier pick in this browser,
 * else their system's. Resolved here rather than handed to Mantine as `auto`:
 * every theme-aware piece of the viewer reads `colorScheme === 'dark'`, which
 * is false for `auto`, so on a dark system the MultiQC logo, the tab icons and
 * the theme toggle all took their light-page variant (dark ink on a dark
 * rail). The live app never runs on `auto` either (main.tsx starts from the
 * stored scheme, else light).
 */
function initialColorScheme(): 'light' | 'dark' {
  try {
    const stored = localStorage.getItem('mantine-color-scheme-value');
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    /* storage blocked: fall through to the system's preference */
  }
  return typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

/** Mount the viewer App over `#root`, from the manifest in this document. */
export function bootApp(options: BootAppOptions = {}): void {
  // file:// cannot reach `/dashboard/logos/...`: MultiQC tab icons use the
  // inlined copies instead (react-core's themedIconSrc reads this).
  installInlineMultiqcLogos();

  // Also sets window.__DEPICTIO_STATIC_DASHBOARD_ID__ (via setActiveTab below /
  // loadBundleFromDocument's seed): App has no /dashboard/<id> route to read on
  // file:// or a static host, so extractDashboardId() falls back to that global.
  const manifest = loadBundleFromDocument();
  setActiveTab(manifest.dashboard.id);
  if (options.initialTab && isBundledTab(options.initialTab)) setActiveTab(options.initialTab);
  seedSidebarOpen();

  const requestListeners = new Set<TabListener>();
  const changeListeners = new Set<TabListener>();
  let current = currentTabId();
  const requests = {
    listen: (fn: TabListener) => {
      requestListeners.add(fn);
      return () => {
        requestListeners.delete(fn);
      };
    },
  };
  const announce = (id: string) => {
    if (id === current) return;
    current = id;
    for (const fn of Array.from(changeListeners)) fn(id);
  };
  options.onController?.({
    currentTab: () => current,
    switchTab: (id) => {
      if (!isBundledTab(id)) return false;
      if (id === current) return true;
      setActiveTab(id);
      for (const fn of Array.from(requestListeners)) fn(id);
      return true;
    },
    onTabChange: (cb) => {
      changeListeners.add(cb);
      return () => {
        changeListeners.delete(cb);
      };
    },
  });

  const project = manifest.project ? { name: manifest.project.name } : null;
  // The badge provider must sit above every LazyMount/Suspense boundary: one of
  // the ten chrome call sites (AdvancedVizDispatch) lives in a separately
  // lazy-loaded chunk and reads the context after this tree is mounted.
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <MantineProvider theme={depictioTheme} defaultColorScheme={initialColorScheme()}>
        <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
          <Notifications position="bottom-right" />
          <StaticBadgeProvider tiers={manifest.tiers as StaticTierMap}>
            <StaticRuntime project={project} requests={requests} announce={announce} />
          </StaticBadgeProvider>
        </DatesProvider>
      </MantineProvider>
    </React.StrictMode>,
  );
}
