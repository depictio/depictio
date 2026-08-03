/**
 * The single URI-resolution point for bundle data references (RFC §3.1).
 *
 * Every read of a `data_refs[].uri` goes through here so base-path bugs have
 * exactly one place to live. Resolution is pure — no I/O: inline blobs are
 * decoded to bytes; everything else resolves to a URL string the engine
 * fetches (with `Range:` per row-group in remote mode).
 */

import type { BundleManifest } from './manifest';

export type ResolvedUri =
  | { kind: 'inline'; bytes: Uint8Array }
  | { kind: 'url'; url: string };

const ABSOLUTE_URL = /^[a-z][a-z0-9+.-]*:\/\//i;

/**
 * @param base Base the bundle is served from, for relative uris. Defaults to
 *   '.' (alongside the page — correct for static-dir's `index.html` + `data/`
 *   layout). Pass `document.baseURI` — or a sub-path — when serving under a
 *   prefix; `base-path.spec.ts` covers that case.
 */
export function resolveUri(manifest: BundleManifest, uri: string, base = '.'): ResolvedUri {
  if (uri.startsWith('inline:')) {
    const key = uri.slice('inline:'.length);
    const blob = manifest.inline_blobs[key];
    if (blob === undefined) {
      throw new Error(`resolveUri: missing inline blob "${key}"`);
    }
    return { kind: 'inline', bytes: base64ToBytes(blob) };
  }
  if (ABSOLUTE_URL.test(uri)) {
    return { kind: 'url', url: uri };
  }
  return { kind: 'url', url: joinBase(base, uri) };
}

function joinBase(base: string, relative: string): string {
  if (ABSOLUTE_URL.test(base)) {
    // URL semantics need a trailing slash for the last segment to be a directory.
    return new URL(relative, base.endsWith('/') ? base : `${base}/`).toString();
  }
  const trimmedBase = base.endsWith('/') ? base.slice(0, -1) : base;
  const trimmedRel = relative.startsWith('./') ? relative.slice(2) : relative;
  return `${trimmedBase}/${trimmedRel}`;
}

export function base64ToBytes(b64: string): Uint8Array {
  if (b64.length === 0) return new Uint8Array(0);
  // atob exists in browsers and Node >= 16; no Buffer dependency needed.
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}
