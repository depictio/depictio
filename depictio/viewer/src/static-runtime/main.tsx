/**
 * Entry for the serverless static-bundle runtime (RFC §3.2).
 *
 * Mounts the *real* viewer App against an embedded bundle manifest instead of
 * the API: the vite.static.config.ts build shims api.ts, useCurrentUser.ts and
 * realtime.ts (see moduleShim), and this entry never imports bootstrapSession,
 * the router, or BootSplash — exactly the catalog-preview precedent. The App
 * host itself (`appHost.tsx`) is shared with the combined report + dashboard
 * runtime (`combined/main.tsx`).
 */
import { bootApp } from './appHost';

bootApp();
