/**
 * Standalone single-file build for the serverless static-bundle runtime.
 *
 * Produces ONE self-contained HTML (JS + CSS inlined) that renders the real
 * viewer App from an embedded bundle manifest — no API, fully offline. Three
 * modules are swapped by the module-shim plugin (RFC errata #5/#6):
 *
 *   - depictio-react-core api.ts        -> src/static-runtime/tabApiShim.ts
 *                                          -> src/static-runtime/apiShim.ts
 *   - viewer hooks/useCurrentUser.ts    -> src/static-runtime/useCurrentUserShim.ts
 *   - depictio-react-core realtime.ts   -> src/static-runtime/realtimeShim.ts
 *   - viewer hooks/useServerStatus.ts   -> src/static-runtime/serverStatusShim.ts
 *   - viewer chrome/variants/index.ts   -> src/static-runtime/chromeVariantShim.ts
 *   - depictio-react-core JBrowseRenderer -> src/static-runtime/jbrowseStub.tsx
 *                                          (which mounts the real one when the
 *                                          bundle ships the session's files)
 *   - the project page's server-only parts -> src/static-runtime/projectServerStubs.tsx
 *                                          (listed in projectServerParts.json)
 *
 * JBrowse itself (and MUI, mobx) is never compiled in: every import of it
 * resolves to a forwarder over the conditional `jbrowse` add-on
 * (vite-plugins/jbrowse-vendor.ts, vite.static-jbrowse.config.ts). And `3dmol` is aliased to `src/static-runtime/threeDmolAddon.ts`, which forwards
 * to the conditional 3Dmol.js add-on (scripts/build-static-addons.mjs).
 *
 * Producers inject the manifest into dist-static/static.html by replacing the
 * __BUNDLE_MANIFEST__ token (same convention as catalog-preview).
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';

import { moduleShim } from './vite-plugins/module-shim';
import projectServerParts from './src/static-runtime/projectServerParts.json';
import { jbrowseVendorForwarders } from './vite-plugins/jbrowse-vendor';

const CORE_SRC = path.resolve(__dirname, '../../packages/depictio-react-core/src');
const RUNTIME = path.resolve(__dirname, 'src/static-runtime');

/** The live project page's server-only parts, each swapped for an empty
 *  stand-in (projectServerStubs.tsx): the bundle mounts the real page, hides
 *  those parts, and compiles none of them in. */
const PROJECT_SERVER_STUBS = Object.fromEntries(
  projectServerParts.modules.map((m) => [
    path.resolve(__dirname, m),
    path.join(RUNTIME, 'projectServerStubs.tsx'),
  ]),
);

export default defineConfig({
  base: './',
  plugins: [
    react(),
    moduleShim(
      'static-runtime-shim',
      {
        // Chained: tabApiShim (tab family) -> apiShim (offline data path) ->
        // the real api.ts.
        [path.join(CORE_SRC, 'api.ts')]: path.join(RUNTIME, 'tabApiShim.ts'),
        [path.join(CORE_SRC, 'realtime.ts')]: path.join(RUNTIME, 'realtimeShim.ts'),
        [path.resolve(__dirname, 'src/hooks/useCurrentUser.ts')]: path.join(
          RUNTIME,
          'useCurrentUserShim.ts',
        ),
        // 4th raw-fetch module, missed by the RFC's shim census: polls
        // /utils/status every 30s from the sidebar badge.
        [path.resolve(__dirname, 'src/hooks/useServerStatus.ts')]: path.join(
          RUNTIME,
          'serverStatusShim.ts',
        ),
        // Bundles draw Paper (the app's default), gated for a read-only
        // file; `?chrome=base` opts into Classic (see the shim).
        [path.resolve(__dirname, 'src/chrome/variants/index.ts')]: path.join(
          RUNTIME,
          'chromeVariantShim.ts',
        ),
        // The stub decides: the real renderer over the bundled session files
        // (JBrowse from the add-on), or the session table when nothing fits.
        [path.join(CORE_SRC, 'components', 'JBrowseRenderer.tsx')]: path.join(
          RUNTIME,
          'jbrowseStub.tsx',
        ),
        ...PROJECT_SERVER_STUBS,
      },
      // Middle link of the api chain: apiShim's own `export * from api.ts`
      // must reach the real module, not bounce back through tabApiShim.
      [path.join(RUNTIME, 'apiShim.ts')],
    ),
    // JBrowse, MUI and mobx come from the `jbrowse` add-on at runtime: the
    // base runtime would otherwise grow by ~1.1 MB gzip for every bundle.
    jbrowseVendorForwarders(
      path.join(CORE_SRC, 'components', 'jbrowse', 'vendorModules.ts'),
      path.join(RUNTIME, 'jbrowse', 'vendor.ts'),
    ),
    viteSingleFile(),
  ],
  build: {
    outDir: 'dist-static',
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: {
      input: path.resolve(__dirname, 'static.html'),
    },
  },
  resolve: {
    alias: [
      // Iconify's default entry keeps an API loader: an icon name that is not
      // in the source-scanned subset is fetched from api.iconify.design (with
      // api.simplesvg.com / api.unisvg.com as fallbacks). Dashboard documents
      // carry AUTHORED icon names, so a bundle can always contain ids the
      // scanner never saw — and it would then phone home, which is the one
      // thing a bundle must never do. The `/offline` entry is the same
      // component with the API code removed: unknown ids render blank instead.
      //
      // That is the accepted trade-off, and it is not new: a served deployment
      // ships `connect-src 'self'`, so those lookups are blocked there too and
      // the same ids render blank (see scripts/generate-icon-subset.mjs). The
      // fix for a missing icon is to add it to the scanned subset, in both
      // cases. Exact-match regex so `@iconify/react/offline` is left alone.
      { find: /^@iconify\/react$/, replacement: '@iconify/react/offline' },
      {
        find: 'depictio-components',
        replacement: path.resolve(__dirname, '../../packages/depictio-components/src/lib'),
      },
      {
        find: 'depictio-react-core',
        replacement: path.resolve(__dirname, '../../packages/depictio-react-core/src'),
      },
      {
        find: 'depictio-static-core',
        replacement: path.resolve(__dirname, '../../packages/depictio-static-core/src'),
      },
      { find: /^plotly\.js$/, replacement: 'plotly.js/dist/plotly' },
      // 3Dmol.js is a CONDITIONAL add-on: never compiled into the base
      // runtime (budget), appended by the producer only to bundles holding a
      // molecule_3d tile (scripts/build-static-addons.mjs builds it next to
      // static.html). This module forwards to the global the add-on defines,
      // and behaves as the catalog stub without it.
      {
        find: /^3dmol$/,
        replacement: path.resolve(__dirname, 'src/static-runtime/threeDmolAddon.ts'),
      },
    ],
    dedupe: [
      'react',
      'react-dom',
      '@mantine/core',
      '@mantine/hooks',
      '@mantine/dates',
      '@iconify/react',
      'dayjs',
      'plotly.js',
      'react-plotly.js',
      'ag-grid-community',
      'ag-grid-react',
      'react-grid-layout',
      'cytoscape',
    ],
  },
});
