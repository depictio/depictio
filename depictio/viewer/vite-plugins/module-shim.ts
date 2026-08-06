/**
 * Shared module-shim Vite plugin.
 *
 * Generalisation of the catalog-preview `apiShim` plugin: redirects every
 * import that resolves to a *real* module onto its shim, by resolved absolute
 * path (not import specifier), so relative imports, workspace aliases and
 * barrel re-exports are all caught uniformly. Each shim may itself import its
 * real module (`export * from` + targeted overrides) — imports whose importer
 * is one of the shim files pass through untouched.
 *
 * Used by vite.catalog-preview.config.ts (api.ts → mockApi.ts) and
 * vite.static.config.ts (api.ts / useCurrentUser.ts / realtime.ts → the
 * static-runtime shims).
 */
import type { Plugin } from 'vite';

/**
 * @param map resolved absolute path of the real module -> absolute path of its shim.
 * @param extraShims further modules to treat as shims, i.e. whose own imports
 *   resolve to the real thing. Needed when shims are CHAINED (A -> B -> real):
 *   only B appears in `map`'s values, so without this A's import of the real
 *   module would be redirected back into the chain.
 */
export function moduleShim(
  name: string,
  map: Record<string, string>,
  extraShims: string[] = [],
): Plugin {
  const shims = new Set([...Object.values(map), ...extraShims]);
  return {
    name,
    enforce: 'pre',
    async resolveId(source, importer, options) {
      // A shim importing (usually its own) real module must get the real one.
      if (!importer || shims.has(importer)) return null;
      const resolved = await this.resolve(source, importer, { ...options, skipSelf: true });
      if (!resolved) return null;
      const real = resolved.id.split('?')[0];
      return map[real] ?? null;
    },
  };
}
