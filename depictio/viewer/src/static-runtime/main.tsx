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
import { loadBundleFromDocument } from './bundle';

const manifest = loadBundleFromDocument();

// App has no /dashboard/<id> route to read on file:// or a static host —
// extractDashboardId() falls back to this global (set before mount).
window.__DEPICTIO_STATIC_DASHBOARD_ID__ = manifest.dashboard.id;

// The badge provider must sit above every LazyMount/Suspense boundary: one of
// the ten chrome call sites (AdvancedVizDispatch) lives in a separately
// lazy-loaded chunk and reads the context after this tree is mounted.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} defaultColorScheme="auto">
      <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
        <Notifications position="bottom-right" />
        <StaticBadgeProvider tiers={manifest.tiers as StaticTierMap}>
          <App />
        </StaticBadgeProvider>
      </DatesProvider>
    </MantineProvider>
  </React.StrictMode>,
);
