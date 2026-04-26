import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import './styles/app.css';

import App from './App';
import EditorApp from './EditorApp';
import { ErrorBoundary } from 'depictio-react-core';
import { depictioTheme } from './theme';

// Client-side routing branch: /dashboard-beta-edit/{id} → editor, else viewer.
// FastAPI serves index.html for both /dashboard-beta/ and /dashboard-beta-edit/;
// we pick the right React tree at boot. Keep this a one-liner — no React Router yet.
const isEditorRoute = /\/dashboard-beta-edit\/[^/?#]+/.test(
  window.location.pathname,
);

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

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} defaultColorScheme={readInitialColorScheme()}>
      <Notifications position="bottom-right" />
      <ErrorBoundary>
        {isEditorRoute ? <EditorApp /> : <App />}
      </ErrorBoundary>
    </MantineProvider>
  </React.StrictMode>,
);
