/**
 * The query-string half of a shareable listing view.
 *
 * `/dashboards` and `/projects` keep their filter state in the URL so a view
 * can be pasted to someone else — "here is every dashboard built from
 * nf-core/rnaseq" — and land on their screen already narrowed. This module is
 * only the codec; reading and writing `window.location` lives in the viewer
 * (`src/lib/listingUrl.ts`), which is what keeps this testable.
 */

/** Raw params, exactly as the query string spelled them: one entry per
 *  occurrence, unsplit. `asList` / `asScalar` interpret them. */
export type ListingParams = Record<string, string[]>;

/** Split a query string into its raw repeated values. Never throws — a
 *  malformed fragment yields an empty map rather than breaking a page load. */
export function decodeListingParams(search: string): ListingParams {
  const out: ListingParams = {};
  let params: URLSearchParams;
  try {
    params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  } catch {
    return out;
  }
  for (const [key, value] of params.entries()) {
    (out[key] ??= []).push(value);
  }
  return out;
}

/** A multi-value filter. Both spellings mean the same thing — `?owner=a&owner=b`
 *  and `?owner=a,b` — because people hand-write these links and both are
 *  natural. Blanks are dropped and duplicates collapse, so `?template=,rnaseq,`
 *  is just `['rnaseq']`. */
export function asList(values: string[] | undefined): string[] {
  if (!values) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values) {
    for (const part of raw.split(',')) {
      const value = part.trim();
      if (!value || seen.has(value)) continue;
      seen.add(value);
      out.push(value);
    }
  }
  return out;
}

/** A single-value param — free text, or a one-of setting like `view=table`.
 *  Taken verbatim (no comma splitting) so a search for "rnaseq, salmon"
 *  survives the round trip. Later occurrences lose to the first. */
export function asScalar(values: string[] | undefined): string | undefined {
  const first = values?.[0]?.trim();
  return first || undefined;
}

/** One of a fixed set of values, or undefined when the URL said something
 *  this build doesn't know — an unrecognised `view=grid` should fall back to
 *  the stored preference, not blank the page. */
export function asEnum<T extends string>(
  values: string[] | undefined,
  allowed: readonly T[],
): T | undefined {
  const value = asScalar(values);
  return value != null && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

/** Serialize back to a query string, without the leading `?`.
 *
 *  Empty values are omitted entirely, so clearing a filter leaves no trace in
 *  the address bar, and key order follows the object's own order so the same
 *  view always produces a byte-identical link. */
export function encodeListingParams(
  params: Record<string, string[] | string | boolean | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === false || value === '') continue;
    if (value === true) {
      search.set(key, '1');
      continue;
    }
    if (Array.isArray(value)) {
      const joined = value.map((v) => v.trim()).filter(Boolean).join(',');
      if (joined) search.set(key, joined);
      continue;
    }
    search.set(key, value);
  }
  return search.toString();
}
