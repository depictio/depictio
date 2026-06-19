/**
 * Standalone single-file build for `depictio catalog preview`.
 *
 * Produces ONE self-contained HTML (JS + CSS inlined) that renders the viewer's
 * real `ComponentRenderer` from an embedded payload — no API, fully offline. The
 * `catalog-api-shim` plugin redirects every `depictio-react-core` import of the
 * real `api.ts` to `src/catalog-preview/mockApi.ts` (which itself imports the
 * real api), so the renderers read embedded payloads instead of fetching.
 */
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';
import path from 'path';

const REAL_API = path.resolve(__dirname, '../../packages/depictio-react-core/src/api.ts');
const SHIM = path.resolve(__dirname, 'src/catalog-preview/mockApi.ts');

const apiShim = (): Plugin => ({
  name: 'catalog-api-shim',
  enforce: 'pre',
  async resolveId(source, importer, options) {
    // The shim itself imports the real api — let that through.
    if (!importer || importer === SHIM) return null;
    const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
    if (resolved && resolved.id.split('?')[0] === REAL_API) return SHIM;
    return null;
  },
});

export default defineConfig({
  base: './',
  plugins: [react(), apiShim(), viteSingleFile()],
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
