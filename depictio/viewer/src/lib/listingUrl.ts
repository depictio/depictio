/**
 * The browser half of a shareable listing view — everything in here touches
 * `window.location`. The codec it builds on is pure and tested in
 * `depictio-react-core/src/listingUrlState.ts`.
 *
 * Both listings keep the address bar in step with their filters, so the URL a
 * user copies out of it is always the view they are looking at. Writes go
 * through `replaceState`: narrowing a filter is not a navigation, and pushing
 * a history entry per keystroke would bury the page the visitor arrived from
 * under a pile of Back presses.
 */
import { decodeListingParams, encodeListingParams } from 'depictio-react-core';
import type { ListingParams } from 'depictio-react-core';

export type ListingParamValues = Record<
  string,
  string[] | string | boolean | null | undefined
>;

/** The params the current URL carries. Safe to call during render — it only
 *  reads. */
export function readListingParams(): ListingParams {
  if (typeof window === 'undefined') return {};
  return decodeListingParams(window.location.search);
}

/** Point the address bar at `params`, keeping the path and hash. A no-op when
 *  the query string already says exactly this, so the effect that calls it on
 *  every prefs change doesn't churn history state. */
export function replaceListingParams(params: ListingParamValues): void {
  if (typeof window === 'undefined') return;
  const query = encodeListingParams(params);
  const next = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  window.history.replaceState(window.history.state, '', next);
}

/** Build a link to another listing carrying the same scope — the banner's
 *  "see the matching projects" hop. Returns a root-relative URL. */
export function listingUrl(path: string, params: ListingParamValues): string {
  const query = encodeListingParams(params);
  return query ? `${path}?${query}` : path;
}

/** Did this page load with a filter in its URL? Captured once at module scope
 *  rather than read later, because the page immediately starts rewriting its
 *  own query string and the answer would stop being about how the visitor
 *  arrived. */
const ARRIVAL_PARAMS = readListingParams();

export function arrivedWithParams(keys: readonly string[]): boolean {
  return keys.some((key) => (ARRIVAL_PARAMS[key]?.length ?? 0) > 0);
}

/** Copy `text` to the clipboard, falling back to a hidden textarea for the
 *  browsers (and insecure origins) where `navigator.clipboard` is missing.
 *  Resolves false rather than throwing so callers can show a plain failure
 *  notice. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the textarea path */
  }
  try {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
