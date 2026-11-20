/**
 * The static runtime's `jbrowse` add-on: JBrowse 2 and what it brings (MUI,
 * mobx, the track adapters), built from depictio-react-core's
 * `components/jbrowse/vendorModules.ts` into one IIFE.
 *
 * React is external: the add-on must render with the runtime's own React, so
 * scripts/build-static-addons.mjs wraps the IIFE in a factory
 * (`globalThis.__depictioJBrowseVendor = function (React, ReactDOM, ...)`) that
 * the runtime calls with it (src/static-runtime/jbrowse/vendor.ts). Built to
 * dist-static/jbrowse-addon/, which build-static-addons.mjs turns into
 * dist-static/addons/jbrowse.js.
 */
import { defineConfig } from 'vite';
import path from 'path';

const ENTRY = path.resolve(
  __dirname,
  '../../packages/depictio-react-core/src/components/jbrowse/vendorModules.ts',
);

/** Externals and the factory parameter each one is bound to. */
export const JBROWSE_ADDON_GLOBALS: Record<string, string> = {
  react: '__dpReact',
  'react-dom': '__dpReactDOM',
  'react-dom/client': '__dpReactDOMClient',
  'react/jsx-runtime': '__dpJsxRuntime',
};

export default defineConfig({
  publicDir: false,
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    outDir: 'dist-static/jbrowse-addon',
    emptyOutDir: true,
    sourcemap: false,
    minify: 'esbuild',
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    lib: {
      entry: ENTRY,
      formats: ['iife'],
      name: '__depictioJBrowseAddon',
      fileName: () => 'jbrowse-addon.js',
    },
    rollupOptions: {
      external: Object.keys(JBROWSE_ADDON_GLOBALS),
      output: {
        globals: JBROWSE_ADDON_GLOBALS,
        interop: 'compat',
        inlineDynamicImports: true,
      },
    },
  },
});
