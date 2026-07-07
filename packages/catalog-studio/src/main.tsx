import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/code-highlight/styles.css';
import './styles/app.css';

import { depictioTheme } from './theme';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} defaultColorScheme="light">
      {/* top-right so toasts never overlap the bottom Back/Next footer nav. */}
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
