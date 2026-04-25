import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import './styles/app.css';

import App from './App';
import ErrorBoundary from './components/ErrorBoundary';
import { depictioTheme } from './theme';

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
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </MantineProvider>
  </React.StrictMode>,
);
