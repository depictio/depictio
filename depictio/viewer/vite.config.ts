import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // SPA is mounted at /dashboard-beta/ by FastAPI in depictio/api/main.py.
  // The leading slash + trailing slash matter for bundle asset resolution.
  base: '/dashboard-beta/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    port: 5173,
    proxy: {
      // When running `vite dev`, forward API calls to FastAPI backend.
      '/depictio/api': {
        target: 'http://0.0.0.0:8122',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      // Allow importing shared components directly from source (not the built bundle).
      'depictio-components': path.resolve(
        __dirname,
        '../../packages/depictio-components/src/lib',
      ),
    },
    // Force a single instance of these packages across the whole graph.
    // Without this, depictio-components' own node_modules contributes a
    // duplicate copy of @mantine/core, causing "MantineProvider was not
    // found" errors when shared components look up their own context.
    dedupe: [
      'react',
      'react-dom',
      '@mantine/core',
      '@mantine/hooks',
      '@iconify/react',
    ],
  },
});
