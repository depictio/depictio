/**
 * Shim for viewer/src/hooks/useCurrentUser.ts in static bundles.
 *
 * The real hook raw-fetches /auth/me/optional (outside api.ts — RFC errata
 * shim target #2). A bundle has no auth backend and no user: return the
 * anonymous-viewer shape, statically, with `loading: false` so nothing
 * flickers. Fourteen modules import this hook (chrome, NotesFooter, App), so
 * the full UseCurrentUserResult surface must be present.
 */
import type { UseCurrentUserResult } from '../hooks/useCurrentUser';

// Types come from the real module — type-only imports are erased at build
// time, so no runtime dependency on the shimmed-out file remains.
export type { AuthMode, CurrentUser, UseCurrentUserResult } from '../hooks/useCurrentUser';

const STATIC_RESULT: UseCurrentUserResult = {
  user: null,
  authMode: 'unauthenticated',
  isPublicMode: true,
  isDemoMode: false,
  isDevMode: false,
  walkthroughDisabled: true,
  isSingleUserMode: false,
  // The real hook falls back to 24h when the backend supplies nothing; a
  // bundle has no temp users, but keep the documented fallback shape.
  temporaryUserExpiryHours: 24,
  temporaryUserExpiryMinutes: 0,
  // The inspector reads live component metadata from the server; a bundle has
  // none, so the info and notes surfaces stay in their popover/drawer form.
  inspectorEnabled: false,
  loading: false,
};

export function useCurrentUser(): UseCurrentUserResult {
  return STATIC_RESULT;
}
