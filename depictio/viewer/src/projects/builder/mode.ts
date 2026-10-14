/**
 * Which Project Builder this page load is.
 *
 * - `server`: the `/projects/build` route of the normal, authenticated SPA.
 * - `standalone`: the same bundle served by `depictio project-builder <dir>`,
 *   a thin local server without auth. Its `index.html` carries
 *   `<meta name="depictio-mode" content="project-builder">`; under `vite dev`
 *   the env var `VITE_PROJECT_BUILDER_STANDALONE=1` stands in for it.
 *
 * Kept free of React and heavy imports: `main.tsx` reads it before anything
 * else, to skip the session bootstrap a standalone server cannot answer.
 */

export type BuilderMode = 'server' | 'standalone';

export function isStandaloneBuilder(): boolean {
  if (import.meta.env.VITE_PROJECT_BUILDER_STANDALONE === '1') return true;
  if (typeof document === 'undefined') return false;
  const meta = document.querySelector('meta[name="depictio-mode"]');
  return meta?.getAttribute('content') === 'project-builder';
}

/** The SPA route of the builder in server mode. */
export const PROJECT_BUILDER_ROUTE = '/projects/build';

/** True for `/projects/build` and `/projects/build/`. */
export function isProjectBuilderPath(pathname: string): boolean {
  return /^\/projects\/build\/?$/.test(pathname);
}
