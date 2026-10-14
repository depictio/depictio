/**
 * Files from object storage as text: one download per object, shared by every
 * tile that asks for it.
 *
 * A tile reads a file (a structure, a PAE matrix) through a presigned URL its
 * manifest or the resolver signs. This module is everything that does not
 * depend on what the file is: fetching, gunzipping by magic number, a
 * per-object memory cache keyed on the URL's path, and the renewal of a URL
 * the store refuses as expired. What the text means is the caller's `parse`.
 *
 * The cache is split by `cacheNamespace`, one map and one budget per kind of
 * file, so a dashboard full of PAE matrices does not push the structures its
 * 3D tiles hold out of memory, or the other way round. The budget is a count
 * of objects, so a namespace whose values are big (a parsed PAE matrix is
 * N x N floats: 25 MB at 2500 residues) passes a smaller `maxCachedObjects`.
 */

/** Objects kept per namespace unless the caller passes its own cap; the least
 *  recently used goes first. */
export const MAX_CACHED_OBJECTS = 24;

/** gzip magic number (1f 8b). */
export function isGzip(bytes: Uint8Array): boolean {
  return bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
}

async function gunzipToText(bytes: Uint8Array, noun: string): Promise<string> {
  if (typeof DecompressionStream === 'undefined') {
    throw new Error(`This browser cannot read gzip-compressed ${noun} files`);
  }
  const stream = new Blob([bytes as BlobPart])
    .stream()
    .pipeThrough(new DecompressionStream('gzip'));
  return new Response(stream).text();
}

/** Raw bytes to text, gunzipping when the bytes say so (whatever the name says).
 *  `noun` names the file in the error of a browser that cannot gunzip. */
export async function decodeObjectBytes(bytes: Uint8Array, noun = 'object'): Promise<string> {
  if (isGzip(bytes)) return gunzipToText(bytes, noun);
  return new TextDecoder().decode(bytes);
}

/**
 * The cache key of a URL: the URL without its query string.
 *
 * Presigned URLs change on every manifest or resolver call (new signature, new
 * expiry) while the object behind them does not, so keying on the full URL
 * would miss every time the tile refreshes. The path names the object.
 */
export function objectCacheKey(url: string): string {
  const q = url.indexOf('?');
  return q === -1 ? url : url.slice(0, q);
}

/** A download the object store refused, with its HTTP status. */
export class ObjectFileError extends Error {
  constructor(
    readonly status: number,
    noun = 'object',
  ) {
    super(`${noun.charAt(0).toUpperCase()}${noun.slice(1)} file unavailable (${status})`);
    this.name = 'ObjectFileError';
  }
}

export interface ObjectParseContext {
  /** The cache key of the object (its URL without the query string). */
  key: string;
  nameHint: string | null;
}

export interface ObjectLoadOptions<T = string> {
  /** Cache bucket: one map, one object budget per namespace. A namespace holds
   *  one kind of value, the one its callers' `parse` returns. */
  cacheNamespace: string;
  /**
   * Objects the namespace keeps (the least recently used goes first), for
   * values far heavier than a structure's text. Defaults to
   * `MAX_CACHED_OBJECTS`; every caller of one namespace passes the same value,
   * or the last to load decides the cap. At least 1.
   */
  maxCachedObjects?: number;
  /** A file name, when the caller knows it, for `parse` to sniff the format by. */
  nameHint?: string | null;
  fetcher?: (url: string) => Promise<Response>;
  /**
   * Turn the decoded text into the cached value. It runs once per object,
   * inside the shared promise; a throw fails the load and evicts the entry.
   * Left out, the value is the text itself.
   */
  parse?: (text: string, ctx: ObjectParseContext) => T;
  /** What the file is called in error messages. Defaults to the namespace. */
  noun?: string;
  /** The error to throw for a refused download. Defaults to `ObjectFileError`;
   *  a subclass lets a caller keep its own error type. */
  errorFor?: (status: number) => ObjectFileError;
}

const caches = new Map<string, Map<string, Promise<unknown>>>();

function bucketOf(namespace: string): Map<string, Promise<unknown>> {
  let bucket = caches.get(namespace);
  if (!bucket) {
    bucket = new Map();
    caches.set(namespace, bucket);
  }
  return bucket;
}

/**
 * Fetch an object once and keep it in memory.
 *
 * The promise is cached, not the result, so two tiles asking for the same
 * object at mount share one download. A failed load is evicted so a retry
 * (refresh tick, new presigned URL) fetches again. Insertion order doubles as
 * a cheap LRU: a hit is re-inserted at the end, the oldest entry goes first.
 */
export function loadObjectText<T = string>(url: string, opts: ObjectLoadOptions<T>): Promise<T> {
  const { cacheNamespace, nameHint = null, parse, errorFor } = opts;
  const asked = opts.maxCachedObjects;
  const cap = asked !== undefined && Number.isFinite(asked) ? Math.max(1, Math.floor(asked)) : MAX_CACHED_OBJECTS;
  const noun = opts.noun ?? cacheNamespace;
  const cache = bucketOf(cacheNamespace);
  const key = objectCacheKey(url);
  const hit = cache.get(key);
  if (hit) {
    cache.delete(key);
    cache.set(key, hit);
    return hit as Promise<T>;
  }
  const fetcher = opts.fetcher ?? ((u: string) => fetch(u));
  const pending = (async () => {
    const res = await fetcher(url);
    if (!res.ok) throw errorFor ? errorFor(res.status) : new ObjectFileError(res.status, noun);
    const bytes = new Uint8Array(await res.arrayBuffer());
    const text = await decodeObjectBytes(bytes, noun);
    if (!text.trim()) throw new Error(`Empty ${noun} file`);
    return parse ? parse(text, { key, nameHint }) : (text as unknown as T);
  })();
  cache.set(key, pending);
  pending.catch(() => {
    if (cache.get(key) === pending) cache.delete(key);
  });
  while (cache.size > cap) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
  return pending;
}

/**
 * `loadObjectText`, asking once for a new URL when the object store answers
 * 403: a presigned URL past its expiry (15 minutes) is refused that way, and
 * the manifest it came from signs a fresh one. Any other failure, a renewal
 * that gives nothing or the same URL, or a second refusal is thrown as is.
 */
export async function loadObjectTextRenewing<T = string>(
  url: string,
  opts: ObjectLoadOptions<T> & { renew?: (() => Promise<string | null>) | null },
): Promise<T> {
  const { renew, ...load } = opts;
  try {
    return await loadObjectText(url, load);
  } catch (err) {
    if (!renew || !(err instanceof ObjectFileError) || err.status !== 403) throw err;
    const fresh = await renew();
    if (!fresh || fresh === url) throw err;
    return loadObjectText(fresh, load);
  }
}

/** Test hook: forget the cached objects of one namespace, or of every one. */
export function clearObjectCache(cacheNamespace?: string): void {
  if (cacheNamespace === undefined) caches.clear();
  else caches.delete(cacheNamespace);
}
