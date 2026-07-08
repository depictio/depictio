/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// Catalog Studio is a static, backend-less SPA served from GitHub Pages at
// https://depictio.github.io/depictio/ — hence base '/depictio/'. It consumes
// the source of the sibling workspace packages directly (no build step in
// those packages), so the resolve.alias + dedupe block below mirrors
// depictio/viewer/vite.config.ts verbatim. Do NOT drop the plotly.js regex
// alias or the dedupe list: without them esbuild walks plotly's unpolyfilled
// `require('buffer/')` shim (optimizeDeps crash) and shared components hit a
// duplicate @mantine/core ("MantineProvider was not found").
export default defineConfig({
  base: '/depictio/',
  plugins: [react()],
  resolve: {
    alias: [
      {
        find: 'depictio-components',
        replacement: path.resolve(__dirname, '../depictio-components/src/lib'),
      },
      {
        find: 'depictio-react-core',
        replacement: path.resolve(__dirname, '../depictio-react-core/src'),
      },
      // Reuse depictio's real component-creation builder in place. The viewer
      // builder is store-driven (reads columns from a Zustand store, not the
      // network); catalog-studio imports its form components and seeds the
      // store from the in-memory fixture. Relative escapes inside the builder
      // (`../../hooks/*`) resolve into viewer/src through this alias.
      {
        find: 'depictio-builder',
        replacement: path.resolve(__dirname, '../../depictio/viewer/src/builder'),
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
      'zustand',
      'plotly.js',
      'react-plotly.js',
      'ag-grid-community',
      'ag-grid-react',
    ],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
