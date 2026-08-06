/**
 * Entry for the standalone component-embed single-file bundle.
 *
 * The payload arrives as a JSON <script id="embed-payload"> injected by
 * services/export/embed.py. We parse it onto window BEFORE mounting so the
 * offline api shim (src/offline/mockApi.ts) can read it on first render.
 *
 * Provider and stylesheet setup mirrors the main viewer's so the real
 * ComponentRenderer renders identically to the dashboard it came from.
 */
// REQUIRED FIRST: registers the bundled Iconify icons. An embed is served with
// `connect-src 'none'` and is also opened straight from disk, so an icon that
// isn't bundled can never resolve — without this every icon renders as an empty
// box. Same contract as src/catalog-preview/main.tsx. See src/icons.ts.
import '../icons';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { DatesProvider } from '@mantine/dates';
import { _api } from '@iconify/react';
import '@mantine/core/styles.css';
import '@mantine/carousel/styles.css';
import '@mantine/dates/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../styles/app.css';

import { depictioTheme } from '../theme';
import EmbedApp from './EmbedApp';
import type { EmbedGlobal } from '../offline/mockApi';

// Iconify lazily fetches icon data from api.iconify.design (and its mirrors) for
// any icon not bundled locally. An embed must make zero network calls — the
// response CSP declares `connect-src 'none'`, so those requests are blocked in
// production anyway, leaving only console noise and failed-request entries on the
// host page (and they DO fire when the file is opened from file://, where no CSP
// applies).
//
// Replacing the fetch implementation is the robust way to stop them: unlike
// `addAPIProvider(..., { resources: [] })` — which Iconify rejects as invalid —
// or per-prefix custom loaders, it cannot be outflanked by a renderer adding an
// icon from a new prefix later.
//
// This is the backstop, not the fix: the `../icons` import above bundles the
// subset the source tree actually uses, so the icons an embed needs resolve
// locally. Only a prefix the generator's scanner missed reaches here, and it
// fails silently rather than firing a request that could not have succeeded.
_api.setFetch(
  (() => Promise.reject(new Error('offline embed: icon API disabled'))) as typeof fetch,
);

const payloadEl = document.getElementById('embed-payload');
window.__DEPICTIO_EMBED__ = JSON.parse(payloadEl?.textContent || '{}') as EmbedGlobal;

const payload = window.__DEPICTIO_EMBED__ as EmbedGlobal;
const scheme = payload.theme === 'dark' ? 'dark' : 'light';

// No <Notifications />: an embed has no user actions that raise one, and the
// portal would sit above the host page's own UI.
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} forceColorScheme={scheme}>
      <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
        <EmbedApp payload={payload} />
      </DatesProvider>
    </MantineProvider>
  </React.StrictMode>,
);
