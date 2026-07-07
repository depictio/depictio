/**
 * Entry for the standalone Depictio Studio single-file bundle.
 *
 * Mirrors catalog-preview's provider + stylesheet setup so the viewer's real
 * `ComponentRenderer` (used by LivePreview) renders identically. The render-data
 * shim (mockApi.ts) reads `window.__CATALOG_PREVIEW__`, which LivePreview keeps
 * updated after each `/studio/render` call.
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
import StudioApp from './StudioApp';

// Seed the shim global so an early ComponentRenderer read never throws before the
// first /studio/render populates it.
window.__CATALOG_PREVIEW__ = {
  theme: 'light',
  initialOutputId: null,
  tools: [],
  data: {
    figures: {}, tables: {}, maps: {}, images: {}, multiqc: {}, multiqcGeneralStats: {},
    cards: { values: {}, secondary: {}, aggregations: {} },
    unique: {}, ranges: {}, specs: {}, advancedVizData: {}, compute: {},
  },
} as unknown as typeof window.__CATALOG_PREVIEW__;

const scheme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} forceColorScheme={scheme}>
      <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
        <Notifications position="bottom-right" />
        <StudioApp theme={scheme} />
      </DatesProvider>
    </MantineProvider>
  </React.StrictMode>,
);
