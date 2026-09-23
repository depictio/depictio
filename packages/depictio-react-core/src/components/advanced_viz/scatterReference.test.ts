import { describe, expect, it } from 'vitest';

import { highlightPredicate } from './scatterReference';

describe('highlightPredicate', () => {
  it('reads above as the greater value on each kind of line', () => {
    expect(highlightPredicate('horizontal', 2, 'above')?.({ x: 0, y: 3 })).toBe(true);
    expect(highlightPredicate('horizontal', 2, 'above')?.({ x: 0, y: 2 })).toBe(false);
    expect(highlightPredicate('vertical', 2, 'above')?.({ x: 3, y: 0 })).toBe(true);
    expect(highlightPredicate('diagonal', null, 'above')?.({ x: 1, y: 2 })).toBe(true);
    expect(highlightPredicate('diagonal', null, 'above')?.({ x: 2, y: 1 })).toBe(false);
  });

  it('flips for below', () => {
    expect(highlightPredicate('horizontal', 2, 'below')?.({ x: 0, y: 1 })).toBe(true);
    expect(highlightPredicate('horizontal', 2, 'below')?.({ x: 0, y: 3 })).toBe(false);
  });

  it('has nothing to highlight without a placed line or a side', () => {
    expect(highlightPredicate('none', 2, 'above')).toBeNull();
    expect(highlightPredicate('horizontal', null, 'above')).toBeNull();
    expect(highlightPredicate('vertical', undefined, 'below')).toBeNull();
    expect(highlightPredicate('diagonal', null, 'none')).toBeNull();
  });
});
