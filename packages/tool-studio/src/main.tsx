import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@mantine/code-highlight/styles.css';
// depictio's Paper chrome, from the viewer's own sheets: the dashboards' top
// bar and keys (layout.css), the management pages' shell, cards, fields and
// pills (pages.css), and the component builder's one-column shell, stepper,
// step bar and tiles (builder-glass.css). glass.css (the --gl-* tokens) comes
// in with the chrome style itself, imported by theme.ts.
import 'depictio-chrome/variants/glass/layout.css';
import 'depictio-chrome/variants/glass/pages/pages.css';
import 'depictio-builder/glass/builder-glass.css';
import './styles/app.css';
import './styles/studio.css';

import { studioCssVariablesResolver, studioTheme } from './theme';
import App from './App';
import { notifications } from '@mantine/notifications';
import { applyDraft, catalogLoaded, installAgentApi } from './agentApi';
import { decodeDraftFromUrl } from './catalog/draft';
import { backupCurrentDraft, discardDraftBackup } from './state/draftBackup';

installAgentApi(__STUDIO_VERSION__);

// A `#draft=` link (toolStudio.link(), or "Copy link" in Export) loads that
// draft and then clears the hash, so a reload does not re-apply it over edits.
// Whatever this browser had restored is backed up first, and App offers it
// back ("Restore previous draft"). A link's code-mode figures and recipes are
// untrusted: they are shown, not run, until the author says so.
const hashDraft = new URLSearchParams(location.hash.slice(1)).get('draft');
if (hashDraft) {
  decodeDraftFromUrl(hashDraft)
    .then(async (draft) => {
      // Append-mode drafts re-enter on a catalog output: wait for the snapshot.
      if (draft.appendTo) await catalogLoaded();
      const backedUp = backupCurrentDraft();
      try {
        applyDraft(draft);
      } catch (e) {
        if (backedUp) discardDraftBackup(); // nothing was replaced
        throw e;
      }
      sessionStorage.setItem('tool-studio-loaded-from-link', '1');
    })
    .catch((e) => {
      console.error('[tool-studio] could not load #draft:', e);
      notifications.show({
        color: 'red',
        autoClose: false,
        title: 'Could not open this link',
        message: e instanceof Error ? e.message : String(e),
      });
    })
    .finally(() => history.replaceState(null, '', location.pathname + location.search));
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider
      theme={studioTheme}
      cssVariablesResolver={studioCssVariablesResolver}
      defaultColorScheme="auto"
    >
      {/* Bottom-right, as in depictio (viewer/src/main.tsx). The stack is lifted
          above the step bar in styles/app.css so it never covers Back/Next. */}
      <Notifications position="bottom-right" />
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
