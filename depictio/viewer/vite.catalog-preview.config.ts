/**
 * Standalone single-file build for `depictio catalog preview`.
 *
 * Produces ONE self-contained HTML (JS + CSS inlined) that renders the viewer's
 * real `ComponentRenderer` from an embedded payload — no API, fully offline. The
 * shared `apiShimPlugin` (packages/depictio-react-core/viteApiShim.ts) redirects
 * every `depictio-react-core` import of the real `api.ts` to
 * `src/catalog-preview/mockApi.ts` (which itself imports the real api), so the
 * renderers read embedded payloads instead of fetching. Tool Studio uses the
 * same plugin with a shim that computes payloads instead of looking them up.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';
import { apiShimPlugin } from '../../packages/depictio-react-core/viteApiShim';

const SHIM = path.resolve(__dirname, 'src/catalog-preview/mockApi.ts');

export default defineConfig({
  base: './',
  plugins: [react(), apiShimPlugin(SHIM), viteSingleFile()],
  build: {
    outDir: 'dist-catalog-preview',
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: {
      input: path.resolve(__dirname, 'catalog-preview.html'),
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
      // The single-file build inlines every dynamic import, so the real
      // 3Dmol.js would ride along in every catalog page. The stub throws a
      // friendly "3D preview unavailable in the catalog" the molecule_3d
      // renderer shows as its empty state.
      { find: /^3dmol$/, replacement: path.resolve(__dirname, 'src/catalog-preview/threeDmolStub.ts') },
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
