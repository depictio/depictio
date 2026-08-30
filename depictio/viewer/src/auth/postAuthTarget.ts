/**
 * Where a visitor lands once they are authenticated, and how the page they
 * originally asked for survives the trip through the gate.
 *
 * A shared dashboard link handed to someone without a session bounces to
 * `/auth`. Before this module that bounce forgot where they were going and
 * every sign-in ended on the dashboard listing, so the recipient of a link had
 * to find the dashboard themselves. On a public instance behind a shared access
 * code that is the normal path, not an edge case.
 *
 * The intended target rides in `sessionStorage` rather than a `?next=` query
 * parameter: the Google flow leaves the origin entirely and comes back to
 * `/auth/google/callback`, where a query parameter set on `/auth` is long gone.
 * sessionStorage is also per-tab, which is what we want when someone opens the
 * shared link in a new tab while already reading another dashboard.
 */

export const DEFAULT_POST_AUTH_PATH = '/dashboards';

const RETURN_TO_KEY = 'depictio:return-to';
/** Older than this and the visitor has moved on; land them on the listing. */
const RETURN_TO_MAX_AGE_MS = 30 * 60 * 1000;

/**
 * Reduce a candidate to a same-origin path, or fall back to the listing.
 *
 * The guard is the reason this is centralised: an unchecked redirect target is
 * an open-redirect and phishing primitive, whether it arrives from a crafted
 * `next=` in a magic link, from a MITMed OAuth response, or from our own
 * storage. Anything that does not normalise to a path on this origin is
 * replaced, `javascript:` URLs included.
 */
export function safePostAuthTarget(candidate: string | null | undefined): string {
  if (!candidate) return DEFAULT_POST_AUTH_PATH;
  try {
    const target = new URL(candidate, window.location.origin);
    if (target.origin !== window.location.origin) return DEFAULT_POST_AUTH_PATH;
    const path = `${target.pathname}${target.search}${target.hash}`;
    // Never send someone back into the gate they just cleared: `/auth` would
    // re-run bootstrap and, with a session now in hand, bounce them onwards
    // anyway — a visible flicker at best, a loop at worst.
    if (target.pathname.startsWith('/auth')) return DEFAULT_POST_AUTH_PATH;
    // Strip protocol/host so we never accidentally emit a fully-qualified URL.
    return path;
  } catch {
    return DEFAULT_POST_AUTH_PATH;
  }
}

/**
 * Record where the visitor was heading, called at the moment we bounce them to
 * the gate. Defaults to the current URL, fragment included: a shared dashboard
 * link carries its filter state in the fragment, and dropping it would hand the
 * recipient the right dashboard showing the wrong thing.
 */
export function rememberReturnTo(
  target: string = window.location.pathname + window.location.search + window.location.hash,
): void {
  const safe = safePostAuthTarget(target);
  if (safe === DEFAULT_POST_AUTH_PATH) return;
  try {
    window.sessionStorage.setItem(RETURN_TO_KEY, JSON.stringify({ target: safe, ts: Date.now() }));
  } catch {
    // Storage can be unavailable (private mode, blocked site data). Losing the
    // target costs the visitor a click on the listing; it must not cost them
    // the sign-in.
  }
}

let resolved: string | null | undefined;

/**
 * The remembered target, or null. Reads once per page load: the entry is
 * cleared on first read so a stale target can't hijack a later sign-in, but
 * the answer is cached because React StrictMode invokes effects twice in dev
 * and the second call would otherwise see an empty slot and route to the
 * listing.
 */
export function takeReturnTo(): string | null {
  if (resolved !== undefined) return resolved;
  resolved = null;
  try {
    const raw = window.sessionStorage.getItem(RETURN_TO_KEY);
    if (!raw) return resolved;
    window.sessionStorage.removeItem(RETURN_TO_KEY);
    const parsed = JSON.parse(raw) as { target?: unknown; ts?: unknown };
    if (typeof parsed.target !== 'string' || typeof parsed.ts !== 'number') return resolved;
    if (Date.now() - parsed.ts > RETURN_TO_MAX_AGE_MS) return resolved;
    const safe = safePostAuthTarget(parsed.target);
    resolved = safe === DEFAULT_POST_AUTH_PATH ? null : safe;
  } catch {
    resolved = null;
  }
  return resolved;
}

/** The remembered target when there is one, otherwise `candidate`, otherwise
 *  the listing. Both callbacks resolve their destination through this. */
export function postAuthDestination(candidate?: string | null): string {
  return takeReturnTo() ?? safePostAuthTarget(candidate);
}
