/**
 * Entry for the standalone catalog-preview single-file bundle.
 *
 * The payload is embedded by the CLI as a JSON <script id="catalog-payload">.
 * We parse it onto window before mounting so the api shim (mockApi.ts) can read
 * it. Mirrors the main viewer's provider + stylesheet setup so the real
 * ComponentRenderer renders identically.
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

const payloadEl = document.getElementById('catalog-payload');
window.__CATALOG_PREVIEW__ = JSON.parse(payloadEl?.textContent || '{}');

const g = window.__CATALOG_PREVIEW__ as unknown as CatalogGlobal;
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
