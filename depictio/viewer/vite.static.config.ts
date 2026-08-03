/**
 * Standalone single-file build for the serverless static-bundle runtime.
 *
 * Produces ONE self-contained HTML (JS + CSS inlined) that renders the real
 * viewer App from an embedded bundle manifest — no API, fully offline. Three
 * modules are swapped by the module-shim plugin (RFC errata #5/#6):
 *
 *   - depictio-react-core api.ts        -> src/static-runtime/apiShim.ts
 *   - viewer hooks/useCurrentUser.ts    -> src/static-runtime/useCurrentUserShim.ts
 *   - depictio-react-core realtime.ts   -> src/static-runtime/realtimeShim.ts
 *   - viewer hooks/useServerStatus.ts   -> src/static-runtime/serverStatusShim.ts
 *
 * Producers inject the manifest into dist-static/static.html by replacing the
 * __BUNDLE_MANIFEST__ token (same convention as catalog-preview).
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';

import { moduleShim } from './vite-plugins/module-shim';

const CORE_SRC = path.resolve(__dirname, '../../packages/depictio-react-core/src');
const RUNTIME = path.resolve(__dirname, 'src/static-runtime');

export default defineConfig({
  base: './',
  plugins: [
    react(),
    moduleShim('static-runtime-shim', {
      [path.join(CORE_SRC, 'api.ts')]: path.join(RUNTIME, 'apiShim.ts'),
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
    }),
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
