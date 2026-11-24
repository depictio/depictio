import { describe, expect, it } from 'vitest';

import { restrictToChromosomes } from './coverageTrackRows';

const data = {
  rows: { chrom: ['chr1', 'chr2', 'chr1'], start: [0, 0, 10], v: [1, 2, 3] },
  columns: { chromosome: 'chrom' },
};

describe('restrictToChromosomes', () => {
  it('keeps only the rows on the chromosomes shown', () => {
    expect(restrictToChromosomes(data, ['chr1']).rows).toEqual({
      chrom: ['chr1', 'chr1'],
      start: [0, 10],
      v: [1, 3],
    });
  });
  it('returns the same object when nothing is dropped or nothing is chosen', () => {
    expect(restrictToChromosomes(data, [])).toBe(data);
    expect(restrictToChromosomes(data, ['chr1', 'chr2'])).toBe(data);
  });
});
