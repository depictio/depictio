import { describe, expect, it } from 'vitest';

import { spanSelection } from './viewer';
import { clampFraction, MAX_FRACTION, MIN_FRACTION, splitOrientation } from './SplitView';

describe('split layout', () => {
  it('goes side by side only in a clearly wide tile', () => {
    expect(splitOrientation(900, 400)).toBe('row');
    expect(splitOrientation(500, 450)).toBe('column');
    expect(splitOrientation(0, 0)).toBe('column');
  });

  it('keeps both panes usable', () => {
    expect(clampFraction(0)).toBe(MIN_FRACTION);
    expect(clampFraction(1)).toBe(MAX_FRACTION);
    expect(clampFraction(Number.NaN)).toBe(0.6);
  });
});

describe('3Dmol selections', () => {
  it('names a residue span, leaving a blank chain out', () => {
    expect(spanSelection({ chain: 'B', start: 3, end: 9 })).toEqual({ resi: '3-9', chain: 'B' });
    expect(spanSelection({ chain: '', start: 5, end: 5 })).toEqual({ resi: '5-5' });
  });
});
