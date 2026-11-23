import type { SsoProvider } from 'depictio-react-core';

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
  providers: SsoProvider[];
}

interface AdminSignInState extends GuestSignInState {
  /** `public_admin_sign_in` from the server. */
  adminSignIn: boolean;
}

/**
 * Whether a guest should be offered the password form as an "Admin sign-in"
 * link: a public instance (not the demo) with no identity provider, where the
 * deployment kept the link on. Only admins can sign in with a password there,
 * so this is a door for the instance's admins, not an invitation to guests:
 * the prompts aimed at guests (comments, the tour, Account settings) keep
 * following `canGuestSignIn`. With a provider, the ordinary "Sign in" already
 * leads to the same form.
 */
export function canAdminSignIn(s: AdminSignInState): boolean {
  return (
    !s.loading &&
    s.isPublicMode &&
    !s.isDemoMode &&
    s.isGuest &&
    s.adminSignIn &&
    s.providers.length === 0
  );
}

/** The words on a guest's sign-in entry. */
export const ADMIN_SIGN_IN_LABEL = 'Admin sign-in';

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
    s.providers.length > 0
  );
}

/** The page to come back to after signing in: the current one, or the listing
 *  when this is the sign-in page itself. For providers that carry the target
 *  in their own redirect rather than in `sessionStorage`. */
export function returnPathOrDefault(): string {
  return safePostAuthTarget(
    window.location.pathname + window.location.search + window.location.hash,
  );
}
