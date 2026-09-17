import { describe, expect, it } from 'vitest';

import { coarsenBins } from './contactMapBinning';

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
