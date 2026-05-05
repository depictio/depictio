import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// Dev-only: serve the SPA's index.html (under base /dashboard-beta/) for any
// request to /auth*, /dashboards-beta*, /projects-beta*, /about-beta*, or
// /admin-beta* so those React routes get HMR. Production has the matching
// FastAPI catch-alls in depictio/api/main.py — this plugin only runs when
// `vite dev` is the server. The browser URL stays untouched, so main.tsx
// still picks the right tree via pathname matching.
const authDevFallback = (): Plugin => ({
  name: 'depictio-spa-dev-fallback',
  apply: 'serve',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (
        req.url &&
        (/^\/auth(\/|$|\?)/.test(req.url) ||
          /^\/dashboards-beta(\/|$|\?)/.test(req.url) ||
          /^\/projects-beta(\/|$|\?)/.test(req.url) ||
          /^\/about-beta(\/|$|\?)/.test(req.url) ||
          /^\/admin-beta(\/|$|\?)/.test(req.url))
      ) {
        req.url = '/dashboard-beta/';
      }
      next();
    });
  },
});

// API proxy target — defaults to the FastAPI port for host-side `pnpm dev`,
// but can be overridden via `VITE_API_TARGET` so the dockerised dev viewer
// proxies to the `depictio-backend` service on the docker network instead
// of trying (and failing) to reach `0.0.0.0:8122` from inside the container.
const API_TARGET = process.env.VITE_API_TARGET || 'http://0.0.0.0:8122';

// HMR client port — what the BROWSER's HMR WebSocket connects back to.
// Must match the host-facing port the user opened. When the dev viewer is
// reached at ``http://localhost:5173/...`` (default) Vite picks this up
// automatically; the override is only needed if the dev server is fronted
// by a different port (e.g. an outer reverse proxy).
const HMR_CLIENT_PORT = process.env.VITE_HMR_CLIENT_PORT
  ? Number(process.env.VITE_HMR_CLIENT_PORT)
  : undefined;

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react(), authDevFallback()],
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
    // Bind 0.0.0.0 so the container's exposed port is reachable from the
    // host (and the FastAPI proxy, if/when wired). Default `localhost`
    // binds only to the container's loopback and refuses outside traffic.
    host: '0.0.0.0',
    proxy: {
      '/depictio/api': {
        target: API_TARGET,
        changeOrigin: true,
        // Required for the realtime WebSocket endpoint
        // (/depictio/api/v1/events/ws). Without it the upgrade fails.
        ws: true,
      },
    },
    hmr: HMR_CLIENT_PORT ? { clientPort: HMR_CLIENT_PORT } : undefined,
  },
  resolve: {
    alias: {
      // Allow importing shared components directly from source (not the built bundle).
      'depictio-components': path.resolve(
        __dirname,
        '../../packages/depictio-components/src/lib',
      ),
      // depictio-react-core is a sibling workspace package — alias straight to
      // its src/index.ts so Vite/HMR sees source changes without a build step.
      'depictio-react-core': path.resolve(
        __dirname,
        '../../packages/depictio-react-core/src',
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
