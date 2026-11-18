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
 *  attach them instead to every core module that imports react-plotly.js or
 *  plotly.js at runtime (type-only imports excluded), so they still run before
 *  any Plot mounts (and load with the plotly chunk).
 *
 *  Fails the build if the barrel no longer has exactly 4 such imports: a format
 *  change would otherwise leave the replacement silently inoperative. */
function plotlyPatchesWithPlotly(): Plugin {
  const barrel = path.join(CORE_SRC, 'index.ts');
  const barrelRe = /^import '\.\/plotly(StrictMode|ZoomGate|SkipIdenticalUpdate|SkipIdleResize)';[ \t]*\r?\n/gm;
  // Runtime (non `import type`) static imports, and dynamic imports.
  const runtimeImportRe =
    /^\s*import\s+(?!type\b)[^;'"]*?from\s+['"](?:react-plotly\.js|plotly\.js)['"]|\bimport\(\s*['"](?:react-plotly\.js|plotly\.js)['"]\s*\)/m;
  return {
    name: 'catalog-site-plotly-patches-lazy',
    enforce: 'pre',
    transform(code, id) {
      const file = id.split('?')[0];
      if (file === barrel) {
        const found = code.match(barrelRe)?.length ?? 0;
        if (found !== PLOTLY_PATCHES.length) {
          this.error(
            `[catalog-site-plotly-patches-lazy] expected exactly ${PLOTLY_PATCHES.length} plotly patch imports ` +
              `in ${barrel}, found ${found}. The barrel format changed: update PLOTLY_PATCHES / the ` +
              `regex in vite.catalog-site.config.ts, otherwise plotly.js lands on the boot path.`,
          );
        }
        return code.replace(barrelRe, '');
      }
      if (!file.startsWith(CORE_SRC) || /\/plotly[A-Z][^/]*$/.test(file)) return null;
      if (!runtimeImportRe.test(code)) return null;
      const pre = PLOTLY_PATCHES.map((n) => `import '${path.join(CORE_SRC, n)}';\n`).join('');
      return pre + code;
    },
  };
}

/** Boot-path guard: the entry chunk and `vendor-base` must never statically
 *  import (directly or transitively) the heavy vendor chunks, which would void
 *  the first-paint savings of this build. Walks Rollup's `chunk.imports` graph. */
const FORBIDDEN_BOOT_CHUNKS = ['vendor-plotly', 'vendor-jbrowse', 'vendor-aggrid'];
function bootPathGuard(): Plugin {
  return {
    name: 'catalog-site-boot-path-guard',
    apply: 'build',
    generateBundle(_opts, bundle) {
      const chunks = Object.values(bundle).filter((c) => c.type === 'chunk');
      const byFile = new Map(chunks.map((c) => [c.fileName, c]));
      const isForbidden = (c: { name: string }) => FORBIDDEN_BOOT_CHUNKS.includes(c.name);
      const roots = chunks.filter((c) => c.isEntry || c.name === 'vendor-base');
      if (!roots.some((c) => c.isEntry)) this.error('[boot-path-guard] no entry chunk found in the bundle');
      for (const root of roots) {
        const seen = new Set<string>([root.fileName]);
        const stack: string[][] = [[root.fileName]];
        while (stack.length) {
          const trail = stack.pop()!;
          const cur = byFile.get(trail[trail.length - 1]);
          if (!cur) continue;
          for (const dep of cur.imports) {
            if (seen.has(dep)) continue;
            seen.add(dep);
            const depChunk = byFile.get(dep);
            if (depChunk && isForbidden(depChunk)) {
              this.error(
                `[boot-path-guard] ${root.name} statically imports ${depChunk.name}: ` +
                  [...trail, dep].join(' -> ') +
                  `. Heavy vendors must stay behind dynamic import().`,
              );
            }
            stack.push([...trail, dep]);
          }
        }
      }
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
  plugins: [react(), apiShimPlugin(SHIM), plotlyPatchesWithPlotly(), bootPathGuard(), renameEntryToIndex()],
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
