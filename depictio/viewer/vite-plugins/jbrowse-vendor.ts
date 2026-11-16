/**
 * Forwarders for the static runtime's `jbrowse` add-on.
 *
 * The base runtime (vite.static.config.ts) compiles the real JBrowseRenderer
 * but none of JBrowse itself: every import of a specifier the add-on provides
 * (the `from '…'` list of depictio-react-core's
 * `components/jbrowse/vendorModules.ts`, the add-on's entry) resolves to a
 * virtual module that reads that specifier's namespace from the add-on at
 * runtime (`src/static-runtime/jbrowse/vendor.ts`).
 *
 * Named imports go through Rollup's `syntheticNamedExports`: the forwarder
 * exports one object, and `import { observer } from 'mobx-react'` reads
 * `observer` off it, so no list of names has to be kept in step with the
 * imports.
 *
 * Any other `@jbrowse/*`, `@mui/*` or `mobx*` import fails the build: it would
 * compile a second copy of a JBrowse package into the base runtime, outside the
 * budget and as a different module instance from the add-on's.
 */
import fs from 'node:fs';
import type { Plugin } from 'vite';

const PREFIX = '\0jbrowse-vendor:';
const GUARDED = /^(@jbrowse\/|@mui\/|mobx($|[-/]))/;
/** Not in the add-on; their forwarder throws when used (vendor.ts). */
const NOT_BUNDLED = ['@jbrowse/react-circular-genome-view2', '@jbrowse/react-app2'];

export function vendorSpecifiers(vendorModulesPath: string): string[] {
  const src = fs.readFileSync(vendorModulesPath, 'utf8');
  return [...src.matchAll(/^import \* as \w+ from '([^']+)';$/gm)].map((m) => m[1]);
}

export function jbrowseVendorForwarders(vendorModulesPath: string, vendorRuntimePath: string): Plugin {
  const specs = new Set([...vendorSpecifiers(vendorModulesPath), ...NOT_BUNDLED]);
  return {
    name: 'jbrowse-vendor-forwarders',
    enforce: 'pre',
    resolveId(source, importer) {
      if (specs.has(source)) return PREFIX + source;
      if (GUARDED.test(source) && importer && !importer.includes('/node_modules/')) {
        this.error(
          `${source} (imported by ${importer}) is not provided by the jbrowse add-on: ` +
            'add it to depictio-react-core components/jbrowse/vendorModules.ts',
        );
      }
      return null;
    },
    load(id) {
      if (!id.startsWith(PREFIX)) return null;
      const spec = id.slice(PREFIX.length);
      return {
        code:
          `import { vendorModule } from ${JSON.stringify(vendorRuntimePath)};\n` +
          `const ns = vendorModule(${JSON.stringify(spec)});\n` +
          'export const __vendor = ns;\n' +
          'export default ns.default;\n',
        syntheticNamedExports: '__vendor',
      };
    },
  };
}
