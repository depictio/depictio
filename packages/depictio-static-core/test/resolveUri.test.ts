import { describe, expect, it } from 'vitest';

import type { BundleManifest } from '../src/manifest';
import { base64ToBytes, resolveUri } from '../src/resolveUri';

function manifestWithBlobs(blobs: Record<string, string>): BundleManifest {
  return {
    manifest_version: 1,
    mode: 'single-file',
    producer: 'B',
    built_at: '2026-08-03T00:00:00Z',
    depictio_version: 'test',
    dashboard: { id: 'a'.repeat(24), title: '', doc: {} },
    data_refs: {},
    tiers: {},
    frozen: {},
    bindings: {},
    prologues: {},
    links: { configs: [], tables: {} },
    allow_network_tiles: false,
    inline_blobs: blobs,
  };
}

describe('resolveUri', () => {
  it('decodes inline blobs to bytes (single-file mode)', () => {
    const m = manifestWithBlobs({ dc_1: btoa('PAR1') });
    const resolved = resolveUri(m, 'inline:dc_1');
    expect(resolved.kind).toBe('inline');
    if (resolved.kind === 'inline') {
      expect(new TextDecoder().decode(resolved.bytes)).toBe('PAR1');
    }
  });

  it('throws on a missing inline blob', () => {
    expect(() => resolveUri(manifestWithBlobs({}), 'inline:dc_missing')).toThrow(
      /missing inline blob/,
    );
  });

  it('passes absolute URLs through untouched (remote mode)', () => {
    const resolved = resolveUri(manifestWithBlobs({}), 'https://bucket.example.com/dc.parquet');
    expect(resolved).toEqual({ kind: 'url', url: 'https://bucket.example.com/dc.parquet' });
  });

  it('joins relative uris against the default base (static-dir mode)', () => {
    expect(resolveUri(manifestWithBlobs({}), 'data/dc.parquet')).toEqual({
      kind: 'url',
      url: './data/dc.parquet',
    });
  });

  it('joins relative uris against an explicit sub-path base', () => {
    expect(resolveUri(manifestWithBlobs({}), 'data/dc.parquet', '/subdir/bundle/')).toEqual({
      kind: 'url',
      url: '/subdir/bundle/data/dc.parquet',
    });
    expect(resolveUri(manifestWithBlobs({}), './data/dc.parquet', '/subdir/bundle')).toEqual({
      kind: 'url',
      url: '/subdir/bundle/data/dc.parquet',
    });
  });

  it('joins against an absolute base with URL semantics', () => {
    expect(
      resolveUri(manifestWithBlobs({}), 'data/dc.parquet', 'https://host.example/pages/dash'),
    ).toEqual({ kind: 'url', url: 'https://host.example/pages/dash/data/dc.parquet' });
  });

  it('base64ToBytes handles empty input', () => {
    expect(base64ToBytes('')).toHaveLength(0);
  });
});
