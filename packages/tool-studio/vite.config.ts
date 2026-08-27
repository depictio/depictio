/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { readFileSync } from 'node:fs';
import { apiShimPlugin } from '../depictio-react-core/viteApiShim';

// The footer states which build is live. The Studio's own version is bumped by
// hand in this package.json when the app changes; depictio's version comes from the
// repo's bumpversion config, so a release bump carries into the site with
// nothing to remember; the commit comes from the Pages workflow's GITHUB_SHA
// and is simply absent for a local build.
const studioVersion = JSON.parse(
  readFileSync(path.resolve(__dirname, 'package.json'), 'utf8'),
).version as string;

const depictioVersion = (() => {
  try {
    const cfg = readFileSync(path.resolve(__dirname, '..', '..', '.bumpversion.cfg'), 'utf8');
    return cfg.match(/^current_version\s*=\s*(.+)$/m)?.[1].trim() ?? 'dev';
  } catch {
    return 'dev';
  }
})();

// Tool Studio is a static, backend-less SPA served from GitHub Pages at
// https://depictio.github.io/depictio-tool-studio/ — hence base '/depictio-tool-studio/'. It consumes
// the source of the sibling workspace packages directly (no build step in
// those packages), so the resolve.alias + dedupe block below mirrors
// depictio/viewer/vite.config.ts verbatim. Do NOT drop the plotly.js regex
// alias or the dedupe list: without them esbuild walks plotly's unpolyfilled
// `require('buffer/')` shim (optimizeDeps crash) and shared components hit a
// duplicate @mantine/core ("MantineProvider was not found").
export default defineConfig({
  base: '/depictio-tool-studio/',
  // Every depictio-react-core import of the real `api.ts` is served from
  // src/api/studioApi.ts instead, which computes the same payloads from the
  // in-browser fixture. That is what lets depictio's own builders and
  // renderers run here unmodified with no backend — see studioApi.ts.
  plugins: [react(), apiShimPlugin(path.resolve(__dirname, 'src/api/studioApi.ts'))],
  define: {
    __STUDIO_VERSION__: JSON.stringify(studioVersion),
    __DEPICTIO_VERSION__: JSON.stringify(depictioVersion),
    __BUILD_SHA__: JSON.stringify((process.env.GITHUB_SHA ?? '').slice(0, 7)),
  },
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
      // network); tool-studio imports its form components and seeds the
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
    coverage: {
      provider: 'v8',
      // The logic worth covering. Components are exercised by Playwright, the
      // generated card spec is generated, and the two build scripts are covered
      // by the CI round-trip rather than by unit tests.
      include: ['src/catalog/**', 'src/viz/**', 'src/state/**', 'src/builder/columnSpecs.ts'],
      exclude: ['src/catalog/generated/**'],
      reporter: ['text-summary', 'html'],
    },
  },
});
