/**
 * Filter-state serialization for shareable URLs.
 *
 * A dashboard view is captured as `#filters=<base64url({v:1, filters})>` on the
 * dashboard's own URL. The recipient's viewer decodes the fragment during state
 * initialization (so the very first fetch is already filtered), applies the
 * entries, and strips the fragment from the address bar — the URL is a
 * hand-off, not live state. The same encoding rides on sidebar tab links so a
 * view survives the full page navigation a tab switch is.
 *
 * All five filter levels (left-panel controls, scatter/table/map/image
 * selections) share one `InteractiveFilter[]` array, so encoding that array is
 * the whole view.
 */

import type { InteractiveFilter, InteractiveFilterSource } from './api';

const FILTER_HASH_PARAM = 'filters';
const FILTER_STATE_VERSION = 1;
/** Above this the link risks truncation by chat apps, proxies and browsers.
 *  Hit only by very large image/table selections. */
const MAX_SHARE_HASH_CHARS = 8000;

const SOURCES: ReadonlySet<string> = new Set<InteractiveFilterSource>([
  'scatter_selection',
  'table_selection',
  'map_selection',
  'image_selection',
]);

/** UTF-8-safe base64url (mirror of the `#auth=` hand-off decode in main.tsx). */
function toBase64Url(json: string): string {
  return window
    .btoa(unescape(encodeURIComponent(json)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function fromBase64Url(encoded: string): string {
  const b64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
  return decodeURIComponent(escape(window.atob(b64)));
}

/** Encode filters for a share URL fragment. Returns null when the encoded
 *  form would be too long to make a reliable link. */
export function encodeFiltersForHash(filters: InteractiveFilter[]): string | null {
  try {
    const encoded = toBase64Url(
      JSON.stringify({ v: FILTER_STATE_VERSION, filters }),
    );
    return encoded.length > MAX_SHARE_HASH_CHARS ? null : encoded;
  } catch {
    return null;
  }
}

function isPlausibleFilter(entry: unknown): entry is InteractiveFilter {
  if (!entry || typeof entry !== 'object') return false;
  const f = entry as Record<string, unknown>;
  if (typeof f.index !== 'string' || !('value' in f)) return false;
  if (f.source !== undefined && !SOURCES.has(f.source as string)) return false;
  return true;
}

/** Decode a `#filters=` fragment (with or without the leading `#`).
 *  Null on anything malformed — a bad link degrades to the normal view. */
export function decodeFiltersFromHash(rawHash: string): InteractiveFilter[] | null {
  try {
    const params = new URLSearchParams(rawHash.replace(/^#/, ''));
    const encoded = params.get(FILTER_HASH_PARAM);
    if (!encoded) return null;
    const parsed = JSON.parse(fromBase64Url(encoded)) as {
      v?: unknown;
      filters?: unknown;
    };
    if (parsed?.v !== FILTER_STATE_VERSION || !Array.isArray(parsed.filters)) return null;
    return parsed.filters.filter(isPlausibleFilter);
  } catch {
    return null;
  }
}

export function readFiltersFromLocation(): InteractiveFilter[] | null {
  return decodeFiltersFromHash(window.location.hash);
}

/** Remove a consumed `#filters=` fragment from the address bar without
 *  touching other fragments (e.g. `#ingestion`). */
export function stripFilterHashFromLocation(): void {
  try {
    if (!window.location.hash.includes(`${FILTER_HASH_PARAM}=`)) return;
    const { pathname, search } = window.location;
    window.history.replaceState(null, '', pathname + search);
  } catch {
    // A stale fragment in the address bar is cosmetic only.
  }
}

/** Full share URL for the current dashboard, or null when the selection is
 *  too large to encode as a link. */
export function buildFilterShareUrl(filters: InteractiveFilter[]): string | null {
  const encoded = encodeFiltersForHash(filters);
  if (encoded === null) return null;
  const { origin, pathname } = window.location;
  return `${origin}${pathname}#${FILTER_HASH_PARAM}=${encoded}`;
}

/** Drop restored entries that don't correspond to a component on this
 *  dashboard (stale storage, or a tab-propagated hash from a sibling tab).
 *  `map_selection` entries are exempt: floating maps live outside this tab's
 *  stored_metadata and are validated by the floating-component pass instead. */
export function sanitizeRestoredFilters(
  filters: InteractiveFilter[],
  knownIndices: Set<string>,
): InteractiveFilter[] {
  return filters.filter(
    (f) => f.source === 'map_selection' || knownIndices.has(f.index),
  );
}
