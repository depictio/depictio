/**
 * Filter-state serialization for shareable URLs.
 *
 * A dashboard view is captured in the `#filters=` fragment of the dashboard's
 * own URL. The recipient's viewer decodes the fragment during state
 * initialization (so the very first fetch is already filtered), applies the
 * entries, and strips the fragment from the address bar — the URL is a
 * hand-off, not live state. The same encoding rides on sidebar tab links so a
 * view survives the full page navigation a tab switch is.
 *
 * Two encodings coexist:
 *
 * - **Compact (v2, preferred)**: `2;<entry>;<entry>` where each entry is
 *   `index:dc_id:component_type:column:value` with percent-encoded fields —
 *   one legible line per component, e.g.
 *   `efebaefa-…:646b0f…:RangeSlider:sepal.length:r~5.272..7.9`.
 *   The dc/type/column ride along because the panel-filter hydration runs
 *   before the dashboard's `stored_metadata` is available, and the backend
 *   silently skips entries missing `column_name`.
 * - **Opaque (v1)**: `base64url({v:1, filters})` — the fallback whenever any
 *   entry carries state the compact grammar can't express (chart/table/map/
 *   image selections, `filter_expr`, `selection_column`). Still decoded for
 *   already-shared links.
 *
 * All five filter levels (left-panel controls, scatter/table/map/image
 * selections) share one `InteractiveFilter[]` array, so encoding that array is
 * the whole view.
 */

import type { InteractiveFilter, InteractiveFilterSource } from './api';

const FILTER_HASH_PARAM = 'filters';
const FILTER_STATE_VERSION = 1;
const COMPACT_PREFIX = '2;';
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

/** Value grammar of a compact entry. The tag only preserves the JS type on
 *  round-trip (RangeSlider needs numbers back, MultiSelect needs an array) —
 *  it carries no component semantics of its own. */
function encodeCompactValue(value: unknown): string | null {
  if (typeof value === 'string') return `s~${encodeURIComponent(value)}`;
  if (typeof value === 'number' && Number.isFinite(value)) return `n~${String(value)}`;
  if (typeof value === 'boolean') return `b~${String(value)}`;
  if (Array.isArray(value)) {
    if (value.length === 2 && value.every((v) => typeof v === 'number' && Number.isFinite(v))) {
      return `r~${String(value[0])}..${String(value[1])}`;
    }
    if (value.every((v) => typeof v === 'string')) {
      return `l~${value.map(encodeURIComponent).join(',')}`;
    }
  }
  try {
    return `j~${encodeURIComponent(JSON.stringify(value))}`;
  } catch {
    return null;
  }
}

function decodeCompactValue(raw: string): { ok: true; value: unknown } | { ok: false } {
  const sep = raw.indexOf('~');
  if (sep < 1) return { ok: false };
  const tag = raw.slice(0, sep);
  const payload = raw.slice(sep + 1);
  switch (tag) {
    case 's':
      return { ok: true, value: decodeURIComponent(payload) };
    case 'n': {
      const n = Number(payload);
      return payload !== '' && Number.isFinite(n) ? { ok: true, value: n } : { ok: false };
    }
    case 'b':
      if (payload === 'true' || payload === 'false') {
        return { ok: true, value: payload === 'true' };
      }
      return { ok: false };
    case 'r': {
      const bounds = payload.split('..');
      if (bounds.length !== 2) return { ok: false };
      const lo = Number(bounds[0]);
      const hi = Number(bounds[1]);
      if (bounds[0] === '' || bounds[1] === '' || !Number.isFinite(lo) || !Number.isFinite(hi)) {
        return { ok: false };
      }
      return { ok: true, value: [lo, hi] };
    }
    case 'l':
      return { ok: true, value: payload === '' ? [] : payload.split(',').map(decodeURIComponent) };
    case 'j':
      try {
        return { ok: true, value: JSON.parse(decodeURIComponent(payload)) };
      } catch {
        return { ok: false };
      }
    default:
      return { ok: false };
  }
}

/** One compact entry, or null when this filter carries state the compact
 *  grammar can't express — which sends the whole array down the v1 path. */
function encodeCompactEntry(f: InteractiveFilter): string | null {
  if (f.source !== undefined || f.filter_expr != null) return null;
  const meta = f.metadata ?? {};
  if (meta.selection_column != null || meta.filter_expr != null) return null;
  const column = f.column_name ?? meta.column_name ?? '';
  const componentType = f.interactive_component_type ?? meta.interactive_component_type ?? '';
  // A single field per concept: if top-level and metadata disagree, the entry
  // can't round-trip losslessly through the compact form.
  if ((meta.column_name ?? column) !== column) return null;
  if ((meta.interactive_component_type ?? componentType) !== componentType) return null;
  const value = encodeCompactValue(f.value);
  if (value === null) return null;
  return [
    encodeURIComponent(f.index),
    encodeURIComponent(meta.dc_id ?? ''),
    encodeURIComponent(componentType),
    encodeURIComponent(column),
    value,
  ].join(':');
}

function decodeCompactEntry(entry: string): InteractiveFilter | null {
  // Own try/catch so a malformed percent-escape (a link truncated mid-entry
  // by a chat app) throws away this entry only, not the whole fragment.
  try {
    const parts = entry.split(':');
    if (parts.length !== 5) return null;
    const index = decodeURIComponent(parts[0]);
    if (!index) return null;
    const decoded = decodeCompactValue(parts[4]);
    if (!decoded.ok) return null;
    const dcId = decodeURIComponent(parts[1]);
    const componentType = decodeURIComponent(parts[2]);
    const column = decodeURIComponent(parts[3]);
    const filter: InteractiveFilter = { index, value: decoded.value };
    if (column) filter.column_name = column;
    if (componentType) filter.interactive_component_type = componentType;
    const metadata: NonNullable<InteractiveFilter['metadata']> = {};
    if (dcId) metadata.dc_id = dcId;
    if (column) metadata.column_name = column;
    if (componentType) metadata.interactive_component_type = componentType;
    if (Object.keys(metadata).length > 0) filter.metadata = metadata;
    return filter;
  } catch {
    return null;
  }
}

/** Encode filters for a share URL fragment. Compact form when every entry
 *  fits its grammar, v1 base64 otherwise. Returns null when the encoded form
 *  would be too long to make a reliable link. */
export function encodeFiltersForHash(filters: InteractiveFilter[]): string | null {
  const compactEntries: string[] = [];
  for (const f of filters) {
    const entry = encodeCompactEntry(f);
    if (entry === null) {
      compactEntries.length = 0;
      break;
    }
    compactEntries.push(entry);
  }
  if (compactEntries.length === filters.length && filters.length > 0) {
    const encoded = COMPACT_PREFIX + compactEntries.join(';');
    return encoded.length > MAX_SHARE_HASH_CHARS ? null : encoded;
  }
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
    // Manual param extraction: URLSearchParams.get() percent-decodes its
    // value, which would corrupt the compact form (whose `:`/`;` delimiters
    // rely on field-level percent-encoding surviving until *our* decode).
    const encoded = rawHash
      .replace(/^#/, '')
      .split('&')
      .find((p) => p.startsWith(`${FILTER_HASH_PARAM}=`))
      ?.slice(FILTER_HASH_PARAM.length + 1);
    if (!encoded) return null;
    if (encoded.startsWith(COMPACT_PREFIX)) {
      // A malformed entry is dropped, not fatal — same degradation the v1
      // path applies per entry via isPlausibleFilter.
      return encoded
        .slice(COMPACT_PREFIX.length)
        .split(';')
        .filter((e) => e !== '')
        .map(decodeCompactEntry)
        .filter((f): f is InteractiveFilter => f !== null);
    }
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

/** Full share URL for the current dashboard: the plain dashboard URL when no
 *  filters are active, or null when the selection is too large to encode as
 *  a link. */
export function buildFilterShareUrl(filters: InteractiveFilter[]): string | null {
  const { origin, pathname } = window.location;
  if (filters.length === 0) return `${origin}${pathname}`;
  const encoded = encodeFiltersForHash(filters);
  if (encoded === null) return null;
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
