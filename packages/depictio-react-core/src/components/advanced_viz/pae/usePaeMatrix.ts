/**
 * The PAE matrix of one object of the companion `pae` collection, fetched and
 * parsed once per object.
 *
 * The download, the gunzip, the per-object cache and the renewal of an
 * expired presigned URL are `molecule/objectText.ts`'s, under the `pae`
 * namespace (its own budget, so PAE matrices and structures never evict each
 * other). The cached value is the parsed matrix, not the text: `parsePae` runs
 * inside the shared promise, so two tiles on the same file, or a refresh that
 * signs a new URL for it, parse it once.
 */

import { useEffect, useRef, useState } from 'react';

import { loadObjectTextRenewing, objectCacheKey } from '../molecule/objectText';
import { parsePae, type PaeMatrix } from './paeParse';

export const PAE_CACHE_NAMESPACE = 'pae';

/** Fetch (or take from the cache) and parse one PAE object. */
export function loadPaeMatrix(
  url: string,
  opts: {
    nameHint?: string | null;
    renew?: (() => Promise<string | null>) | null;
    fetcher?: (url: string) => Promise<Response>;
  } = {},
): Promise<PaeMatrix> {
  return loadObjectTextRenewing<PaeMatrix>(url, {
    cacheNamespace: PAE_CACHE_NAMESPACE,
    nameHint: opts.nameHint ?? null,
    renew: opts.renew ?? null,
    fetcher: opts.fetcher,
    noun: 'PAE',
    parse: (text) => parsePae(text),
  });
}

interface Async<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

/**
 * The matrix behind a presigned URL. A new URL for the same object (the
 * manifest re-read on the refresh tick) keeps the matrix on screen while the
 * cache answers; another object starts blank, so a matrix is never drawn
 * against another entity's residue axis. `renew` is tried once per object on
 * a 403 (an expired URL), as `useStructureText` does.
 */
export function usePaeMatrix(
  url: string | null,
  nameHint: string | null,
  renew?: () => Promise<string | null>,
): Async<PaeMatrix> {
  const [state, setState] = useState<Async<PaeMatrix>>({
    data: null,
    loading: Boolean(url),
    error: null,
  });
  const last = useRef<{ key: string; data: PaeMatrix } | null>(null);
  const renewRef = useRef(renew);
  renewRef.current = renew;
  const renewedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!url) {
      setState({ data: null, loading: false, error: null });
      return undefined;
    }
    let cancelled = false;
    const key = objectCacheKey(url);
    const keep = last.current && last.current.key === key ? last.current.data : null;
    setState({ data: keep, loading: true, error: null });
    const canRenew = Boolean(renewRef.current) && renewedFor.current !== key;
    loadPaeMatrix(url, {
      nameHint,
      renew: canRenew
        ? () => {
            renewedFor.current = key;
            return renewRef.current?.() ?? Promise.resolve(null);
          }
        : null,
    })
      .then((data) => {
        if (renewedFor.current === key) renewedFor.current = null;
        if (cancelled) return;
        last.current = { key, data };
        setState({ data, loading: false, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            data: null,
            loading: false,
            error: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url, nameHint]);
  return state;
}

/**
 * Whether this bundle renders from an embedded payload with no API behind it
 * (the catalog preview, a component embed: `viewer/src/offline/mockApi.ts`).
 * There the manifest and the object store are out of reach, so the tile says
 * so instead of failing a fetch. Promote beside the offline shim if another
 * file-backed tile needs it.
 */
export function isOfflineBundle(): boolean {
  if (typeof window === 'undefined') return false;
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.__CATALOG_PREVIEW__ || w.__DEPICTIO_EMBED__);
}
