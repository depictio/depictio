/**
 * Which chrome style a page should draw, read from the URL and this browser's
 * storage only. Shared by the app's registry (`./index.ts`) and the catalog
 * preview bundle, which must not import the app's shells: the preview runs in
 * an iframe of the same origin inside the editor's catalog picker, and reading
 * the same keys is what keeps the tile it draws in the reader's chrome.
 *
 * First match wins:
 *   1. `?chrome=<id>` in the URL, kept for the rest of the browser session;
 *   2. the reader's pick in their profile, kept in this browser;
 *   3. the instance default an admin set in the Branding panel (cached here
 *      from `/utils/public-config`);
 *   4. null: the caller's own default.
 */
export const PREF_KEY = 'depictio-chrome-variant';
export const PREF_EVENT = 'depictio:chrome-variant-pref';
export const SESSION_KEY = 'depictio-chrome-session';
export const INSTANCE_KEY = 'depictio-chrome-instance-default';

/** `?chrome=` of this page, or the last one this browser session saw. */
export function sessionChromeId(known: ReadonlySet<string>): string | null {
  const fromUrl = new URLSearchParams(window.location.search).get('chrome')?.toLowerCase();
  try {
    if (fromUrl && known.has(fromUrl)) {
      sessionStorage.setItem(SESSION_KEY, fromUrl);
      return fromUrl;
    }
    const kept = sessionStorage.getItem(SESSION_KEY);
    return kept && known.has(kept) ? kept : null;
  } catch {
    return fromUrl && known.has(fromUrl) ? fromUrl : null;
  }
}

/** A stored chrome id, when it names a known style. */
export function readStoredChromeId(key: string, known: ReadonlySet<string>): string | null {
  try {
    const id = localStorage.getItem(key);
    return id && known.has(id) ? id : null;
  } catch {
    return null;
  }
}

/** The chrome id this page should draw, or null to use the caller's default. */
export function resolveChromeId(known: ReadonlySet<string>): string | null {
  return (
    sessionChromeId(known) ??
    readStoredChromeId(PREF_KEY, known) ??
    readStoredChromeId(INSTANCE_KEY, known)
  );
}
