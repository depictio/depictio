/**
 * Standalone single-file build for the component export API (`format=html`).
 *
 * Produces ONE self-contained HTML (JS + CSS inlined) that renders the viewer's
 * real `ComponentRenderer` from an embedded payload — no API, fully offline. The
 * shared `apiShimPlugin` (packages/depictio-react-core/viteApiShim.ts) redirects
 * every `depictio-react-core` import of the real `api.ts` to
 * `src/offline/mockApi.ts` (which itself imports the real api), so the renderers
 * read the embedded payload instead of fetching.
 *
 * Sibling of vite.catalog-preview.config.ts — same plugin, same shim, same
 * aliases, same dedupe list. The two differ only in entry point and output
 * directory. Keep the `dedupe` list in sync between them: a duplicated React or
 * Plotly copy breaks hooks and doubles an already-large bundle.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';
import { apiShimPlugin } from '../../packages/depictio-react-core/viteApiShim';

const SHIM = path.resolve(__dirname, 'src/offline/mockApi.ts');

export default defineConfig({
  base: './',
  plugins: [react(), apiShimPlugin(SHIM), viteSingleFile()],
  build: {
    outDir: 'dist-embed',
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: {
      input: path.resolve(__dirname, 'embed.html'),
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
