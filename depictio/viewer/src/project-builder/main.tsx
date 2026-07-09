/**
 * Entry for the standalone Depictio Project Builder single-file bundle.
 *
 * Reuses the viewer's `depictioTheme` + Mantine provider stack so the Project Builder
 * looks like the rest of depictio. Service-free: every call goes to the local
 * `/project-builder/*` authoring API (backend.ts). No viz rendering, so no
 * ComponentRenderer / render-data shim here.
 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import 'ag-grid-community/styles/ag-grid.css';
import 'ag-grid-community/styles/ag-theme-alpine.css';
import '../styles/app.css';

import { depictioTheme } from '../theme';
import ProjectBuilderApp from './ProjectBuilderApp';

const scheme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} defaultColorScheme={scheme}>
      <Notifications position="bottom-right" />
      <ProjectBuilderApp />
    </MantineProvider>
  </React.StrictMode>,
);
