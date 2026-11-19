/**
 * Entry for the multi-file catalog site (GitHub Pages).
 *
 * Unlike `main.tsx` (single-file, payload embedded in the HTML), this fetches the
 * light `data/index.json` first, installs it as `window.__CATALOG_PREVIEW__`
 * (with `lazyOutputs` set so each output's data is fetched when first shown) and
 * mounts the same `CatalogApp`, in the same chrome (`chrome.ts`, Paper by default).
 * Theme: `?theme=light|dark`, else the reader's last choice, else the OS setting.
 */
// REQUIRED FIRST: registers the bundled Iconify icons (see src/icons.ts).
import '../icons';

import React from 'react';
import ReactDOM from 'react-dom/client';
import { Alert, Center, Loader, MantineProvider, Stack, Text } from '@mantine/core';
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
import { applyCatalogChrome } from './chrome';
import type { CatalogGlobal } from './shared';
import { resolveCatalogTheme } from './siteTheme';

const DATA_BASE = 'data/';


const Shell: React.FC<{ scheme: 'light' | 'dark'; children: React.ReactNode }> = ({
  scheme,
  children,
}) => (
  <MantineProvider theme={depictioTheme} forceColorScheme={scheme}>
    <DatesProvider settings={{ locale: 'en', firstDayOfWeek: 1 }}>
      <Notifications position="bottom-right" />
      {children}
    </DatesProvider>
  </MantineProvider>
);

const Boot: React.FC<{ scheme: 'light' | 'dark' }> = ({ scheme }) => {
  const [g, setG] = React.useState<CatalogGlobal | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetch(`${DATA_BASE}index.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status} while loading ${DATA_BASE}index.json`);
        return r.json();
      })
      .then((idx) => {
        const global = {
          ...idx,
          theme: scheme,
          lazyOutputs: true,
          dataBase: DATA_BASE,
        } as CatalogGlobal;
        window.__CATALOG_PREVIEW__ = global as unknown as typeof window.__CATALOG_PREVIEW__;
        setG(global);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [scheme]);

  if (error) {
    return (
      <Center h="100vh" p="md">
        <Alert color="red" variant="light" title="Could not load the catalog">
          {error}
        </Alert>
      </Center>
    );
  }
  if (!g) {
    return (
      <Center h="100vh">
        <Stack align="center" gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            Loading catalog…
          </Text>
        </Stack>
      </Center>
    );
  }
  return <CatalogApp g={g} />;
};

const scheme = resolveCatalogTheme();
// The same chrome as the single-file bundle (Paper unless `#chrome=base`),
// applied before the first render so no frame paints in another style.
applyCatalogChrome();
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Shell scheme={scheme}>
      <Boot scheme={scheme} />
    </Shell>
  </React.StrictMode>,
);
