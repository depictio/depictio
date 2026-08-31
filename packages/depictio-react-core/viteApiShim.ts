/**
 * Vite plugin: serve this package's `api.ts` from a shim module instead.
 *
 * Every renderer imports its fetchers directly from `./api`, so redirecting
 * that one module is all it takes to run depictio's real components against
 * something other than FastAPI. The shim is expected to `export *` from the
 * real api and override only the functions it can answer — imports made *by*
 * the shim itself are let through so that re-export resolves.
 *
 * Two backend-less consumers use it, and they must not drift apart:
 *   depictio/viewer/vite.catalog-preview.config.ts → src/offline/mockApi.ts
 *      (looks up payloads Python precomputed into the bundle)
 *   packages/tool-studio/vite.config.ts            → src/api/studioApi.ts
 *      (computes them from the fixture in the browser)
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';

const REAL_API = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  'src',
  'api.ts',
);

export function apiShimPlugin(shimPath: string): Plugin {
  const shim = path.resolve(shimPath);
  return {
    name: 'depictio-api-shim',
    enforce: 'pre',
    async resolveId(source, importer, options) {
      // The shim itself imports the real api — let that through.
      if (!importer || importer === shim) return null;
      const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
      if (resolved && resolved.id.split('?')[0] === REAL_API) return shim;
      return null;
    },
  };
}
