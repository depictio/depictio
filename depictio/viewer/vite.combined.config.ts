/**
 * The static runtime, built once for every offline output
 * (`src/static-runtime/combined/main.tsx`): a serverless bundle page (composed
 * by `depictio/serverless/bundle_html.py`), a report alone, and the combined
 * report + dashboard file.
 *
 * The whole viewer App (the bundle's runtime) plus the report host, built as
 * one classic script (IIFE, every dynamic import inlined) and one UNSCOPED
 * stylesheet, `dist-static/combined-runtime.{js,css}`. The producer
 * (`depictio/serverless/combined.py`) inlines the script once, where the
 * report's own Plotly copy was, and the stylesheet once, as inert text: the
 * report view scopes it onto the runtime's roots in the page
 * (`combined/scopeStyles.ts`), and the dashboard view of a combined file (an
 * iframe written from that same text) takes it as written.
 *
 * The offline shims (`vite-plugins/static-runtime.ts`) apply to every host.
 * Built into `dist-static/` (`emptyOutDir: false`, the add-ons build writes
 * beside it; `scripts/clean-dist-static.mjs` empties it first), by `pnpm run
 * build:static`.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

import {
  staticRuntimeAliases,
  staticRuntimeDedupe,
  staticRuntimeJbrowseForwarders,
  staticRuntimeShim,
} from './vite-plugins/static-runtime';

export default defineConfig({
  base: './',
  plugins: [react(), staticRuntimeShim(), staticRuntimeJbrowseForwarders()],
  define: {
    // Library mode leaves `process.env.NODE_ENV` for the host to define; a
    // report is no build tool, so React's production build is chosen here.
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    outDir: 'dist-static',
    emptyOutDir: false,
    copyPublicDir: false,
    sourcemap: false,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    lib: {
      entry: path.resolve(__dirname, 'src/static-runtime/combined/main.tsx'),
      name: 'DepictioCombinedRuntime',
      formats: ['iife'],
      fileName: () => 'combined-runtime.js',
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        assetFileNames: (asset) =>
          asset.name && asset.name.endsWith('.css') ? 'combined-runtime.css' : '[name][extname]',
      },
    },
  },
  resolve: {
    alias: staticRuntimeAliases,
    dedupe: staticRuntimeDedupe,
  },
});
