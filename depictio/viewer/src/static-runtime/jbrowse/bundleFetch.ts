/**
 * The fetch shim the offline genome browser reads its files through.
 *
 * Producer A points every file of a frozen JBrowse session at
 * `JBROWSE_BUNDLE_ORIGIN + key` and ships the bytes in `inline_blobs`
 * (depictio/serverless/jbrowse_bundle.py). JBrowse calls the global `fetch`
 * for each of them at read time (its `checkAuthNeededFetch`), so wrapping
 * `fetch` once answers every one from memory, by byte range, and lets any
 * other URL through untouched. The `.invalid` host never resolves: a file the
 * shim does not know fails here, it does not reach the network.
 */
import {
  BundledFile,
  base64ToBytes,
  bundledFileKey,
  type BundledFileEntry,
} from 'depictio-static-core';

import { rawBundle } from '../bundle';

const entries = new Map<string, BundledFileEntry>();
const files = new Map<string, BundledFile>();
let installed = false;

function fileFor(key: string): BundledFile | null {
  const hit = files.get(key);
  if (hit) return hit;
  const entry = entries.get(key);
  if (!entry) return null;
  const b64 = rawBundle().inline_blobs?.[entry.blob];
  if (b64 === undefined) return null;
  const file = new BundledFile(entry, base64ToBytes(b64));
  files.set(key, file);
  return file;
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

function rangeOf(input: RequestInfo | URL, init?: RequestInit): string | null {
  const fromInit = init?.headers ? new Headers(init.headers).get('range') : null;
  if (fromInit) return fromInit;
  return typeof input === 'object' && 'headers' in input ? input.headers.get('range') : null;
}

/** Answer one bundled-file request (exported for the unit test). */
export function bundledResponse(url: string, range: string | null): Response {
  const key = bundledFileKey(url);
  const file = key ? fileFor(key) : null;
  if (!file) {
    throw new TypeError(`offline bundle: ${url} is not a file this bundle ships`);
  }
  const res = file.read(range);
  if (!res.ok) {
    if (res.status === 416) {
      return new Response(null, {
        status: 416,
        headers: { 'Content-Range': `bytes */${file.entry.size}` },
      });
    }
    // A thrown error reaches the track as its message (generic-filehandle
    // wraps it as "<message> fetching <url>"); an HTTP 404 would only say 404.
    throw new Error(res.message);
  }
  const headers: Record<string, string> = {
    'Content-Type': 'application/octet-stream',
    'Content-Length': String(res.bytes.length),
    'Accept-Ranges': 'bytes',
  };
  if (res.contentRange) headers['Content-Range'] = res.contentRange;
  // Copy: a Response over a subarray view would hand its whole buffer to the
  // reader, and generic-filehandle keeps what it is given.
  return new Response(res.bytes.slice() as BlobPart, { status: res.status, headers });
}

/** Register the files of one frozen session and make sure `fetch` serves them. */
export function registerBundledFiles(map: Record<string, BundledFileEntry> | undefined): void {
  for (const [key, entry] of Object.entries(map ?? {})) entries.set(key, entry);
  if (installed) return;
  installed = true;
  const realFetch = globalThis.fetch.bind(globalThis);
  globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = urlOf(input);
    if (bundledFileKey(url) === null) return realFetch(input, init);
    try {
      return Promise.resolve(bundledResponse(url, rangeOf(input, init)));
    } catch (err) {
      return Promise.reject(err);
    }
  };
}
