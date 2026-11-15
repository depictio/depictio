/**
 * The report runtime: the static runtime, built to be hosted by a Quarto report.
 *
 * Same renderers, same shims (`vite-plugins/static-runtime.ts`), same engine
 * as the serverless bundle (`vite.static.config.ts`) — only the host differs.
 * Where the bundle is a page of its own, this is a guest in somebody else's:
 *
 *   - one classic script (IIFE, every dynamic import inlined) and one
 *     stylesheet, `dist-static/report-runtime.{js,css}`, that the report
 *     producer (`depictio/serverless/report.py`) inlines ONCE at the end of a
 *     report beside the manifest, however many tiles it mounts;
 *   - its CSS scoped to its own roots (`vite-plugins/scope-css.ts`), so
 *     Mantine's and the app's global rules cannot restyle the Quarto page.
 *
 * Built after the bundle into the same `dist-static/` (`emptyOutDir: false`),
 * by `pnpm run build:static`.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

import { scopeCss } from './vite-plugins/scope-css';
import {
  staticRuntimeAliases,
  staticRuntimeDedupe,
  staticRuntimeShim,
} from './vite-plugins/static-runtime';

export default defineConfig({
  base: './',
  plugins: [react(), staticRuntimeShim()],
  define: {
    // Library mode leaves `process.env.NODE_ENV` for the host to define; a
    // report is no build tool, so React's production build is chosen here.
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  css: {
    postcss: {
      plugins: [
        // Virgil is the app's hand-drawn page-title face (app.css); no tile
        // draws in it, and a report has its own titles.
        scopeCss('.depictio-report-root', { dropFontFaces: ['Virgil'] }),
      ],
    },
  },
  build: {
    outDir: 'dist-static',
    emptyOutDir: false,
    // The bundle build already copied public/ next to static.html.
    copyPublicDir: false,
    sourcemap: false,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    lib: {
      entry: path.resolve(__dirname, 'src/static-runtime/report/main.tsx'),
      name: 'DepictioReportRuntime',
      formats: ['iife'],
      fileName: () => 'report-runtime.js',
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        assetFileNames: (asset) =>
          asset.name && asset.name.endsWith('.css') ? 'report-runtime.css' : '[name][extname]',
      },
    },
  },
  resolve: {
    alias: staticRuntimeAliases,
    dedupe: staticRuntimeDedupe,
  },
});
