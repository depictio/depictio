import { describe, expect, it } from 'vitest';

import {
  BUNDLED_PAGE_SIZE,
  BundledFile,
  JBROWSE_BUNDLE_ORIGIN,
  bundledFileKey,
  parseByteRange,
} from '../src/bundledFiles';

function bytes(n: number, from = 0): Uint8Array {
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = (from + i) % 251;
  return out;
}

describe('parseByteRange', () => {
  it('reads the three spellings and clamps to the file', () => {
    expect(parseByteRange('bytes=0-9', 100)).toEqual({ start: 0, end: 9 });
    expect(parseByteRange('bytes=90-', 100)).toEqual({ start: 90, end: 99 });
    expect(parseByteRange('bytes=-10', 100)).toEqual({ start: 90, end: 99 });
    // JBrowse asks for whole 256 KiB pages past the end of a small file.
    expect(parseByteRange(`bytes=0-${BUNDLED_PAGE_SIZE - 1}`, 100)).toEqual({ start: 0, end: 99 });
    expect(parseByteRange(null, 100)).toBeNull();
    expect(parseByteRange('bytes=100-200', 100)).toBe('unsatisfiable');
    expect(parseByteRange('bytes=0-1,4-5', 100)).toBe('unsatisfiable');
  });
});

describe('BundledFile, shipped whole', () => {
  const data = bytes(1000);
  const file = new BundledFile({ blob: 'jb_x', size: 1000, pages: null }, data);

  it('answers an unranged GET with the whole file', () => {
    const r = file.read(null);
    expect(r.ok && r.status).toBe(200);
    expect(r.ok && r.bytes.length).toBe(1000);
  });

  it('answers a page-sized range with what exists and the size', () => {
    const r = file.read(`bytes=0-${BUNDLED_PAGE_SIZE - 1}`);
    expect(r.ok && r.status).toBe(206);
    expect(r.ok && r.contentRange).toBe('bytes 0-999/1000');
    expect(r.ok && Array.from(r.bytes.subarray(10, 13))).toEqual([10, 11, 12]);
  });

  it('turns a read past the end into 416 (generic-filehandle reads it as EOF)', () => {
    const r = file.read('bytes=1000-2000');
    expect(r.ok).toBe(false);
    expect(!r.ok && r.status).toBe(416);
  });
});

describe('BundledFile, sliced to pages', () => {
  const P = 16;
  const size = 10 * P + 5; // 11 pages, the last one short
  const whole = bytes(size);
  // Pages 0, 3-4 and the short last page 10.
  const runs: [number, number][] = [
    [0, 1],
    [3, 2],
    [10, 1],
  ];
  const shipped = new Uint8Array([
    ...whole.subarray(0, P),
    ...whole.subarray(3 * P, 5 * P),
    ...whole.subarray(10 * P, size),
  ]);
  const file = new BundledFile(
    { blob: 'jb_y', size, pages: runs, page_size: P, label: 'reads (BAM)', region: 'chr1:1-100' },
    shipped,
  );

  it('maps a range inside a run back to the original offsets', () => {
    const r = file.read(`bytes=${3 * P + 2}-${5 * P - 1}`);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(Array.from(r.bytes)).toEqual(Array.from(whole.subarray(3 * P + 2, 5 * P)));
    expect(r.contentRange).toBe(`bytes ${3 * P + 2}-${5 * P - 1}/${size}`);
  });

  it('serves the short last page when asked for a whole one', () => {
    const r = file.read(`bytes=${10 * P}-${11 * P - 1}`);
    expect(r.ok && Array.from(r.bytes)).toEqual(Array.from(whole.subarray(10 * P)));
  });

  it('refuses a range that leaves the shipped pages, naming the region', () => {
    const r = file.read(`bytes=${P}-${2 * P - 1}`);
    expect(r.ok).toBe(false);
    expect(!r.ok && r.message).toMatch(/reads \(BAM\).*outside the region.*chr1:1-100/);
    // Straddling a gap is refused too: the bytes in between were never shipped.
    expect(file.read(`bytes=${P - 1}-${3 * P}`).ok).toBe(false);
  });

  it('refuses an unranged read of a sliced file', () => {
    expect(file.read(null).ok).toBe(false);
  });

  it('rejects a blob whose length does not match its pages', () => {
    expect(
      () => new BundledFile({ blob: 'jb_z', size, pages: runs, page_size: P }, shipped.subarray(1)),
    ).toThrow(/expected/);
  });
});

describe('bundledFileKey', () => {
  it('extracts the key of a rewritten location, and nothing else', () => {
    expect(bundledFileKey(`${JBROWSE_BUNDLE_ORIGIN}jbf_abc`)).toBe('jbf_abc');
    expect(bundledFileKey(`${JBROWSE_BUNDLE_ORIGIN}jbf_abc?x=1`)).toBe('jbf_abc');
    expect(bundledFileKey('https://example.org/jbf_abc')).toBeNull();
    expect(bundledFileKey('/depictio/api/v1/jbrowse/tracks/x/y/data')).toBeNull();
  });
});
