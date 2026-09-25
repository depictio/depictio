import { describe, expect, it } from 'vitest';

import {
  chooseResolution,
  coarsenBins,
  formatResolution,
  shouldRefetchWindow,
} from './contactMapBinning';

describe('coarsenBins', () => {
  it('returns every bin unchanged when under the cap', () => {
    const starts = [0, 10, 20, 30, 40];
    const { buckets, index } = coarsenBins(starts, 10);
    expect(buckets).toEqual(starts);
    starts.forEach((s, i) => expect(index.get(s)).toBe(i));
  });

  it('merges adjacent bins to fit the cap', () => {
    const starts = Array.from({ length: 100 }, (_, i) => i * 10);
    const { buckets, index } = coarsenBins(starts, 20);
    expect(buckets.length).toBeLessThanOrEqual(20);
    // Every original bin still maps to some bucket, and every bucket index
    // stays inside the buckets array.
    for (const s of starts) {
      const b = index.get(s);
      expect(b).toBeDefined();
      expect(b as number).toBeGreaterThanOrEqual(0);
      expect(b as number).toBeLessThan(buckets.length);
    }
  });

  it('is monotonic: adjacent bins never merge with an earlier bucket', () => {
    const starts = Array.from({ length: 57 }, (_, i) => i);
    const { index } = coarsenBins(starts, 10);
    let prev = -1;
    for (const s of starts) {
      const b = index.get(s) as number;
      expect(b).toBeGreaterThanOrEqual(prev);
      prev = b;
    }
  });
});

describe('chooseResolution', () => {
  // The two levels the nf-core/hic megatest really dumps.
  const megatest = [500_000, 1_000_000];
  const derived = [500_000, 1_000_000, 2_000_000, 4_000_000];

  it('opens a whole chromosome on the coarsest level', () => {
    // Mouse chr1 is 195 Mb: 390 bins a side at 500 kb, 76k cells.
    expect(chooseResolution(megatest, 195_000_000, 800)).toBe(1_000_000);
  });

  it('picks the fine level once the reader is down to a few megabases', () => {
    expect(chooseResolution(megatest, 4_000_000, 800)).toBe(500_000);
  });

  it('treats no span as the whole contig', () => {
    expect(chooseResolution(derived, null, 800)).toBe(4_000_000);
  });

  it('gives a wider tile a finer level for the same region', () => {
    const narrow = chooseResolution(derived, 100_000_000, 200) as number;
    const wide = chooseResolution(derived, 100_000_000, 1600) as number;
    expect(wide).toBeLessThan(narrow);
  });

  it('breaks an exact tie towards the coarser level', () => {
    // An ideal of exactly 1 Mb, equidistant in log space from 500 kb and 2 Mb.
    const span = 1_000_000 * 800 * 0.25;
    expect(chooseResolution([500_000, 2_000_000], span, 800)).toBe(2_000_000);
  });

  it('has nothing to choose on a flat collection', () => {
    expect(chooseResolution([], 1_000_000, 800)).toBeNull();
  });

  it('agrees with the server on the same inputs', () => {
    // Pinned against depictio/tests/api/v1/test_advanced_viz_contact_map.py.
    expect(chooseResolution(megatest, 195_000_000, 800)).toBe(1_000_000);
    expect(chooseResolution(megatest, 4_000_000, 800)).toBe(500_000);
  });
});

describe('shouldRefetchWindow', () => {
  const loaded = { start: 10_000_000, end: 20_000_000 };

  it('fetches when nothing is loaded yet', () => {
    expect(shouldRefetchWindow(null, loaded)).toBe(true);
  });

  it('stays put while panning inside the loaded window', () => {
    expect(shouldRefetchWindow(loaded, { start: 12_000_000, end: 18_000_000 })).toBe(false);
  });

  it('fetches once the span doubles', () => {
    expect(shouldRefetchWindow(loaded, { start: 5_000_000, end: 25_000_000 })).toBe(true);
  });

  it('fetches once the span halves', () => {
    expect(shouldRefetchWindow(loaded, { start: 14_000_000, end: 19_000_000 })).toBe(true);
  });

  it('fetches when the window moves past the loaded edge', () => {
    expect(shouldRefetchWindow(loaded, { start: 18_000_000, end: 26_000_000 })).toBe(true);
  });

  it('ignores a window with no finite bounds', () => {
    expect(shouldRefetchWindow(loaded, { start: 0, end: Number.POSITIVE_INFINITY })).toBe(false);
    expect(shouldRefetchWindow(loaded, null)).toBe(false);
  });
});

describe('formatResolution', () => {
  it('names a bin size the way a reader says it', () => {
    expect(formatResolution(500_000)).toBe('500 kb');
    expect(formatResolution(1_000_000)).toBe('1 Mb');
    expect(formatResolution(2_500_000)).toBe('2.5 Mb');
    expect(formatResolution(10)).toBe('10 bp');
    expect(formatResolution(0)).toBe('');
  });
});
