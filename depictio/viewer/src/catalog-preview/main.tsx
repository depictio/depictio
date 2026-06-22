/**
 * Entry for the standalone catalog-preview single-file bundle.
 *
 * The payload is embedded by the CLI as a JSON <script id="catalog-payload">.
 * We parse it onto window before mounting so the api shim (mockApi.ts) can read
 * it. Mirrors the main viewer's provider + stylesheet setup so the real
 * ComponentRenderer renders identically.
 *
 * Dev (HMR) fallback: when served by `pnpm dev:catalog-preview` the CLI never
 * runs, so the `__CATALOG_PAYLOAD__` placeholder is still literal — we then fetch
 * the dumped `public/catalog-payload.dev.json` (see dev/dump_catalog_payload.py).
 */
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

import { depictioTheme } from '../theme';
import CatalogApp from './App';
import type { CatalogGlobal } from './shared';
import faviconRaw from '../../public/favicon.svg?raw';

// Depictio favicon — inlined as a data URI so it works both on the dev server
// and in the CLI's self-contained single-file bundle.
(() => {
  const link = document.createElement('link');
  link.rel = 'icon';
  link.type = 'image/svg+xml';
  link.href = `data:image/svg+xml;utf8,${encodeURIComponent(faviconRaw)}`;
  document.head.appendChild(link);
})();

async function resolvePayload(): Promise<Record<string, unknown>> {
  const raw = (document.getElementById('catalog-payload')?.textContent || '').trim();
  // Built bundle served by the CLI: the placeholder is replaced with real JSON.
  if (raw && raw !== '__CATALOG_PAYLOAD__') return JSON.parse(raw);
  // Dev server (HMR): fetch the dumped payload. A missing file makes Vite serve
  // index.html (HTML, not JSON) with a 200, so check the body — not just res.ok —
  // to give a clear message instead of "Unexpected token '<'".
  const hint =
    'To just VIEW the catalog, run:  depictio-cli catalog gallery\n\n' +
    'For the HMR dev server, dump the data first then open /catalog-preview.html:\n' +
    '  python dev/dump_catalog_payload.py';
  const res = await fetch(`${import.meta.env.BASE_URL}catalog-payload.dev.json`);
  const body = await res.text();
  if (!res.ok || body.trimStart().startsWith('<')) {
    throw new Error(`No catalog data (catalog-payload.dev.json not found).\n\n${hint}`);
  }
  return JSON.parse(body);
}

resolvePayload()
  .then((payload) => {
    window.__CATALOG_PREVIEW__ = payload as never;
    const g = payload as unknown as CatalogGlobal;
    const scheme = g.theme === 'dark' ? 'dark' : 'light';
    ReactDOM.createRoot(document.getElementById('root')!).render(
      <React.StrictMode>
        <MantineProvider theme={depictioTheme} forceColorScheme={scheme}>
          <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
            <Notifications position="bottom-right" />
            <CatalogApp g={g} />
          </DatesProvider>
        </MantineProvider>
      </React.StrictMode>,
    );
  })
  .catch((err: Error) => {
    const root = document.getElementById('root');
    if (root) {
      root.innerHTML = `<pre style="padding:24px;white-space:pre-wrap;color:#c92a2a;font:14px/1.5 monospace">${err.message}</pre>`;
    }
  });
