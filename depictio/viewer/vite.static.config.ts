/**
 * Standalone single-file build for the serverless static-bundle runtime.
 *
 * Produces ONE self-contained HTML (JS + CSS inlined) that renders the real
 * viewer App from an embedded bundle manifest — no API, fully offline. The
 * module swaps that keep it offline (api.ts -> tabApiShim.ts -> apiShim.ts,
 * useCurrentUserShim.ts, realtimeShim.ts, serverStatusShim.ts,
 * chromeVariantShim.ts, jbrowseStub.tsx, and `3dmol` -> threeDmolAddon.ts) live
 * in `vite-plugins/static-runtime.ts`, shared with the report runtime
 * (`vite.report.config.ts`): one runtime, two hosts.
 *
 * Producers inject the manifest into dist-static/static.html by replacing the
 * __BUNDLE_MANIFEST__ token (same convention as catalog-preview).
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';

import {
  staticRuntimeAliases,
  staticRuntimeDedupe,
  staticRuntimeShim,
} from './vite-plugins/static-runtime';

export default defineConfig({
  base: './',
  plugins: [react(), staticRuntimeShim(), viteSingleFile()],
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
    alias: staticRuntimeAliases,
    dedupe: staticRuntimeDedupe,
  },
});
