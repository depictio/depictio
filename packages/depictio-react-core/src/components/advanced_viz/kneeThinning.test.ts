import { describe, expect, it } from 'vitest';

import { logSpacedRankThin } from './kneeThinning';

describe('logSpacedRankThin', () => {
  it('keeps every position when under the cap', () => {
    expect(logSpacedRankThin(10, 100)).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  });

  it('handles n = 0 and cap <= 0', () => {
    expect(logSpacedRankThin(0, 10)).toEqual([]);
    expect(logSpacedRankThin(5, 0)).toEqual([0, 1, 2, 3, 4]);
  });

  it('always keeps the first and last position', () => {
    const idx = logSpacedRankThin(1_000_000, 500);
    expect(idx[0]).toBe(0);
    expect(idx[idx.length - 1]).toBe(999_999);
  });

  it('is sorted, deduplicated and bounded by the cap', () => {
    const idx = logSpacedRankThin(1_000_000, 500);
    expect(idx.length).toBeLessThanOrEqual(500);
    expect(new Set(idx).size).toBe(idx.length);
    for (let i = 1; i < idx.length; i += 1) expect(idx[i]).toBeGreaterThan(idx[i - 1]);
  });

  it('is denser near the start than the end', () => {
    const idx = logSpacedRankThin(1_000_000, 200);
    const firstDecile = idx.filter((i) => i < 100_000).length;
    const lastDecile = idx.filter((i) => i >= 900_000).length;
    expect(firstDecile).toBeGreaterThan(lastDecile);
  });
});
