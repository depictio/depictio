/**
 * Bundle one dev check with esbuild, then run it.
 *
 * Usage:  node dev/run_check.mjs dev/<name>_check.mjs
 *
 * The checks import TypeScript sources straight from `src/` and from
 * `packages/depictio-react-core/src`, so they need a bundling step before Node
 * can execute them. esbuild is not a direct dependency of the viewer: under
 * pnpm's strict layout only vite can see it, and a bare `esbuild` in a script
 * fails with "command not found". Resolving it through vite keeps the checks
 * runnable without adding a dependency, on whatever esbuild vite ships with.
 *
 * React stays external so the bundle shares the viewer's single copy, the same
 * as the app does at runtime.
 */

import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { basename, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const entry = process.argv[2];
if (!entry) {
  console.error('usage: node dev/run_check.mjs <check.mjs>');
  process.exit(2);
}

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');

const cacheDir = resolve('node_modules/.cache');
mkdirSync(cacheDir, { recursive: true });
const outfile = resolve(cacheDir, basename(entry).replace(/\.m?js$/, '.bundle.mjs'));

await esbuild.build({
  entryPoints: [entry],
  bundle: true,
  platform: 'node',
  format: 'esm',
  external: ['react', 'react/jsx-runtime', 'react-dom/server'],
  outfile,
  logLevel: 'error',
});

// The check reports and sets the exit code itself.
await import(pathToFileURL(outfile).href);
