/**
 * Multi-file static build of the catalog browser, for GitHub Pages
 * (`depictio catalog export-site`).
 *
 * Same app and same offline api shim as `vite.catalog-preview.config.ts`, but
 * NOT single-file: the bundle is code-split so the first paint (gallery rail +
 * metadata) never pulls plotly / ag-grid / jbrowse / genome-spy, and each
 * output's data is fetched on demand from `data/outputs/<id>.json` (see
 * `src/catalog-preview/lazyOutput.ts`). `base: './'` keeps every URL relative so
 * the site works under any sub-path (e.g. `/depictio-catalog/v1.22.0/`).
 */
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'node:fs';
import path from 'path';
import { apiShimPlugin } from '../../packages/depictio-react-core/viteApiShim';

const SHIM = path.resolve(__dirname, 'src/offline/mockApi.ts');
const OUT_DIR = 'dist-catalog-site';

/** The entry is `catalog-site.html` (so it does not collide with the other HTML
 *  entries in dev); the deployed page must be `index.html`. */
function renameEntryToIndex(): Plugin {
  return {
    name: 'catalog-site-index',
    apply: 'build',
    closeBundle() {
      const dir = path.resolve(__dirname, OUT_DIR);
      const from = path.join(dir, 'catalog-site.html');
      if (fs.existsSync(from)) fs.renameSync(from, path.join(dir, 'index.html'));
    },
  };
}

const CORE_SRC = path.resolve(__dirname, '../../packages/depictio-react-core/src');
const PLOTLY_PATCHES = [
  'plotlyStrictMode',
  'plotlyZoomGate',
  'plotlySkipIdenticalUpdate',
  'plotlySkipIdleResize',
];

/** `depictio-react-core`'s barrel imports four react-plotly prototype patches for
 *  their side effects, which drags plotly.js (~4.7 MB) onto the boot path even
 *  though the gallery shell renders no figure. Drop them from the barrel and
 *  attach them instead to every core module that actually imports react-plotly,
 *  so they still run before any Plot mounts (and load with the plotly chunk). */
function plotlyPatchesWithPlotly(): Plugin {
  const barrel = path.join(CORE_SRC, 'index.ts');
  return {
    name: 'catalog-site-plotly-patches-lazy',
    enforce: 'pre',
    transform(code, id) {
      const file = id.split('?')[0];
      if (file === barrel) {
        return code.replace(/^import '\.\/plotly(StrictMode|ZoomGate|SkipIdenticalUpdate|SkipIdleResize)';\n/gm, '');
      }
      if (!file.startsWith(CORE_SRC) || /\/plotly[A-Z][^/]*$/.test(file)) return null;
      if (!/from 'react-plotly\.js'/.test(code)) return null;
      const pre = PLOTLY_PATCHES.map((n) => `import '${path.join(CORE_SRC, n)}';\n`).join('');
      return pre + code;
    },
  };
}

// Heavy libraries get their own chunks so they are only fetched when an output
// that needs them is opened. Order matters: the first match wins.
const CHUNK_RULES: [RegExp, string][] = [
  [/node_modules\/(\.pnpm\/[^/]+\/node_modules\/)?(plotly\.js|plotly\.js-[^/]+|react-plotly\.js)\//, 'vendor-plotly'],
  [/node_modules\/(\.pnpm\/[^/]+\/node_modules\/)?ag-(grid-community|grid-react)\//, 'vendor-aggrid'],
  [/node_modules\/(\.pnpm\/[^/]+\/node_modules\/)?@jbrowse\//, 'vendor-jbrowse'],
  [/node_modules\/(\.pnpm\/[^/]+\/node_modules\/)?@genome-spy\//, 'vendor-genomespy'],
  [/node_modules\/(\.pnpm\/[^/]+\/node_modules\/)?(cytoscape[^/]*)\//, 'vendor-graph'],
];

// Shared runtime every chunk needs. Pinned to its own chunk, otherwise Rollup
// parks react & the commonjs helpers inside whichever heavy vendor chunk happens
// to use them first (plotly / jbrowse) and the entry then statically imports
// that multi-MB chunk just to get `react`.
const BASE_RE =
  /(\0commonjsHelpers|\0vite\/|commonjs-dynamic-modules|\/node_modules\/(\.pnpm\/[^/]+\/node_modules\/)?(react|react-dom|scheduler|react-is|prop-types|object-assign|@mantine\/[^/]+|@emotion\/[^/]+|@iconify\/[^/]+|dayjs|clsx|use-sync-external-store)\/)/;

function manualChunks(id: string): string | undefined {
  // Stylesheets stay with their importer (the entry): `ag-grid.css` must not
  // drag the ag-grid JS chunk onto the boot path.
  if (/\.css(\?|$)/.test(id)) return undefined;
  for (const [re, name] of CHUNK_RULES) if (re.test(id)) return name;
  if (BASE_RE.test(id)) return 'vendor-base';
  return undefined;
}

export default defineConfig({
  base: './',
  plugins: [react(), apiShimPlugin(SHIM), plotlyPatchesWithPlotly(), renameEntryToIndex()],
  build: {
    outDir: OUT_DIR,
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 6000,
    rollupOptions: {
      input: path.resolve(__dirname, 'catalog-site.html'),
      output: { manualChunks },
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
      // plotly.js-dist-min / a partial bundle is not a dependency of this
      // workspace, so the full bundle stays (it is isolated in `vendor-plotly`
      // and only fetched when a figure is shown).
      { find: /^plotly\.js$/, replacement: 'plotly.js/dist/plotly' },
      // The real 3Dmol.js is large; the stub makes the molecule_3d renderer
      // show its "unavailable in the catalog" empty state.
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
