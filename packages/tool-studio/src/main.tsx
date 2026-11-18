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
import { installAgentApi } from './agentApi';
import { decodeDraftFromUrl } from './catalog/draft';
import { useStudioStore } from './state/useStudioStore';

installAgentApi(__STUDIO_VERSION__);

// A `#draft=` link (toolStudio.link(), or "Copy link" in Export) loads that
// draft and then clears the hash, so a reload does not re-apply it over edits.
const hashDraft = new URLSearchParams(location.hash.slice(1)).get('draft');
if (hashDraft) {
  decodeDraftFromUrl(hashDraft)
    .then((draft) => {
      useStudioStore.getState().loadDraft(draft);
      sessionStorage.setItem('tool-studio-loaded-from-link', '1');
    })
    .catch((e) => console.error('[tool-studio] could not load #draft:', e))
    .finally(() => history.replaceState(null, '', location.pathname + location.search));
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={depictioTheme} defaultColorScheme="auto">
      {/* top-right so toasts never overlap the bottom Back/Next footer nav. */}
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
