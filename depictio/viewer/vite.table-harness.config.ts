// Dev-only config for table-harness.html. Not part of any production build.
//
// Built as a static bundle (rather than served by `vite dev`) because the dev
// server's on-demand dep optimizer repeatedly invalidates mid-load here — the
// table views transitively reach the plotly/cytoscape renderers, whose
// CommonJS deps (`buffer/`, es6-iterator's `d`) esbuild can't resolve under
// pnpm's strict layout. `vite build` uses rollup, which handles them fine.
//
//   npx vite build --config vite.table-harness.config.ts
//   python3 -m http.server --directory dist-table-harness 5199
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist-table-harness',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: { input: 'table-harness.html' },
  },
});
