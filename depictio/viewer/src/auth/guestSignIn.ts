import { rememberReturnTo, safePostAuthTarget } from './postAuthTarget';

/**
 * Where a public-mode guest signs in.
 *
 * A public instance hands every visitor a temporary account and skips the
 * login form, so `/auth` alone never shows it. `/auth/login` is the explicit
 * request to sign in: `AuthApp` shows the form there instead of minting a guest
 * session. Every "Sign in" a guest sees goes through here, so the page they
 * were reading is remembered and they land back on it afterwards.
 */
export const SIGN_IN_PATH = '/auth/login';

/** Remember the current page, then open the sign-in form. */
export function openSignIn(): void {
  rememberReturnTo();
  window.location.assign(SIGN_IN_PATH);
}

/** `onClick` for an `<a href={SIGN_IN_PATH}>`: remember the page and let the
 *  link navigate. Wrapped so the click event is not taken for a target. */
export function rememberHere(): void {
  rememberReturnTo();
}

interface GuestSignInState {
  loading: boolean;
  isPublicMode: boolean;
  isDemoMode: boolean;
  isGuest: boolean;
  googleOAuthEnabled: boolean;
  samlEnabled: boolean;
}

/**
 * Whether a guest should be offered a way to sign in: a public instance (not
 * the read-only demo) that has an identity provider to sign in with. A public
 * instance with only passwords keeps its current behaviour.
 */
export function canGuestSignIn(s: GuestSignInState): boolean {
  return (
    !s.loading &&
    s.isPublicMode &&
    !s.isDemoMode &&
    s.isGuest &&
    (s.googleOAuthEnabled || s.samlEnabled)
  );
}

/** The page to come back to after signing in: the current one, or the listing
 *  when this is the sign-in page itself. For providers that carry the target
 *  in their own redirect (SAML) rather than in `sessionStorage`. */
export function returnPathOrDefault(): string {
  return safePostAuthTarget(
    window.location.pathname + window.location.search + window.location.hash,
  );
}
