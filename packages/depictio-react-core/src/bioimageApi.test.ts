import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { bioimageAuthHeaders, createBioimageSource } from './api';

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
