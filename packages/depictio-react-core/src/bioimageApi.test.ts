import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  BioimageHttpError,
  bioimageAuthHeaders,
  bioimageRangeHeader,
  createBioimageSource,
  createBioimageZarrStore,
} from './api';

const SESSION_KEY = 'local-store';

function session(token: string): string {
  // Far from expiry, so no refresh round-trip is attempted.
  const expire = new Date(Date.now() + 3_600_000).toISOString();
  return JSON.stringify({ access_token: token, refresh_token: 'r', expire_datetime: expire });
}

describe('bioimageAuthHeaders', () => {
  let store: Map<string, string>;

  beforeEach(() => {
    store = new Map();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => store.set(k, v),
      removeItem: (k: string) => store.delete(k),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('carries the stored bearer', async () => {
    store.set(SESSION_KEY, session('first'));
    expect({ ...(await bioimageAuthHeaders()) }).toEqual({ Authorization: 'Bearer first' });
  });

  it('reads the token again on every spread, as geotiff does per range request', async () => {
    store.set(SESSION_KEY, session('first'));
    const headers = await bioimageAuthHeaders();
    store.set(SESSION_KEY, session('refreshed'));
    expect({ ...headers, Range: 'bytes=0-65536' }).toEqual({
      Authorization: 'Bearer refreshed',
      Range: 'bytes=0-65536',
    });
  });

  it('is empty for an anonymous session', async () => {
    expect(await bioimageAuthHeaders()).toEqual({});
  });
});

describe('createBioimageSource', () => {
  it('opens OME-TIFF as a single file at an absolute URL', () => {
    const source = createBioimageSource('dc1', { name: 'a b.ome.tif', format: 'ome-tiff' });
    expect(source.kind).toBe('tiff');
    if (source.kind !== 'tiff') return;
    expect(source.tiff.url).toMatch(
      /^https?:\/\/[^/]+\/depictio\/api\/v1\/advanced_viz\/bioimage\/dc1\/a%20b\.ome\.tif$/,
    );
  });

  it('opens OME-Zarr and SpatialData as zarr key trees', () => {
    expect(createBioimageSource('dc1', { name: 's.zarr', format: 'ome-zarr' }).kind).toBe('zarr');
    expect(createBioimageSource('dc1', { name: 's.zarr', format: 'spatialdata' }).kind).toBe('zarr');
  });
});

describe('createBioimageZarrStore.getRange', () => {
  let calls: Array<{ url: string; range: string | null }>;

  function respond(status: number, body: number[]) {
    calls = [];
    vi.stubGlobal('localStorage', {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
    });
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init: RequestInit) => {
        calls.push({ url, range: new Headers(init.headers).get('Range') });
        return new Response(status === 404 ? null : new Uint8Array(body), { status });
      }),
    );
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('spells offset ranges inclusively and suffix ranges as bytes=-n', () => {
    expect(bioimageRangeHeader({ offset: 100, length: 50 })).toBe('bytes=100-149');
    expect(bioimageRangeHeader({ offset: 0, length: 1 })).toBe('bytes=0-0');
    expect(bioimageRangeHeader({ suffixLength: 20 })).toBe('bytes=-20');
  });

  it('sends one Range header for a shard key and returns the 206 body', async () => {
    respond(206, [7, 8, 9]);
    const store = createBioimageZarrStore('dc1', 's.zarr');
    const bytes = await store.getRange('/0/c/0/0/0', { offset: 16, length: 3 });
    expect(Array.from(bytes ?? [])).toEqual([7, 8, 9]);
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toMatch(/\/advanced_viz\/bioimage\/dc1\/s\.zarr\/0\/c\/0\/0\/0$/);
    expect(calls[0].range).toBe('bytes=16-18');
  });

  it('slices a plain 200 from a server that ignored the Range', async () => {
    respond(200, [0, 1, 2, 3, 4, 5]);
    const store = createBioimageZarrStore('dc1', 's.zarr');
    expect(Array.from((await store.getRange('0/c/0', { offset: 2, length: 2 })) ?? [])).toEqual([
      2, 3,
    ]);
    expect(Array.from((await store.getRange('0/c/0', { suffixLength: 2 })) ?? [])).toEqual([4, 5]);
  });

  it('fetches a key once however many readers ask for it', async () => {
    respond(200, [1, 2, 3]);
    const store = createBioimageZarrStore('dc1', 's.zarr');
    const reads = await Promise.all([store.get('0/c/0'), store.get('0/c/0'), store.get('0/c/0')]);
    expect(reads.map((r) => Array.from(r ?? []))).toEqual([[1, 2, 3], [1, 2, 3], [1, 2, 3]]);
    expect(Array.from((await store.get('0/c/0')) ?? [])).toEqual([1, 2, 3]);
    expect(calls).toHaveLength(1);
  });

  it('lets one reader give up without failing the others', async () => {
    respond(200, [4]);
    const store = createBioimageZarrStore('dc1', 's.zarr');
    const abort = new AbortController();
    const gaveUp = store.get('0/c/1', { signal: abort.signal });
    const kept = store.get('0/c/1');
    abort.abort();
    await expect(gaveUp).rejects.toThrow('Aborted');
    expect(Array.from((await kept) ?? [])).toEqual([4]);
  });

  it('reads a missing shard as absent and throws on other failures', async () => {
    respond(404, []);
    const store = createBioimageZarrStore('dc1', 's.zarr');
    expect(await store.getRange('0/c/9', { suffixLength: 20 })).toBeUndefined();
    respond(416, []);
    await expect(store.getRange('0/c/0', { offset: 1e9, length: 4 })).rejects.toBeInstanceOf(
      BioimageHttpError,
    );
  });
});
