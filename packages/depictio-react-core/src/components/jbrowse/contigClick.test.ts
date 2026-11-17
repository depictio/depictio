import { describe, expect, it } from 'vitest';

import { contigOfClickedMark } from './contigClick';

describe('contigOfClickedMark', () => {
  it('reads the contig off x of a vertical bar', () => {
    expect(contigOfClickedMark({ points: [{ x: 'chr7', y: 31 }] })).toBe('chr7');
  });

  it('reads y of a horizontal bar', () => {
    expect(contigOfClickedMark({ points: [{ x: 31, y: 'chrX' }] }, { orientation: 'h' })).toBe('chrX');
  });

  it('takes the capture-bed twin as its contig', () => {
    expect(contigOfClickedMark({ points: [{ x: 'chr2_region' }] })).toBe('chr2');
  });

  it('opens nothing on the total bar or on an empty click', () => {
    expect(contigOfClickedMark({ points: [{ x: 'total' }] })).toBeNull();
    expect(contigOfClickedMark({ points: [] })).toBeNull();
    expect(contigOfClickedMark(null)).toBeNull();
  });
});
