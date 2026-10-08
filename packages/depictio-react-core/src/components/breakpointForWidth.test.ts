import { describe, expect, it } from 'vitest';

import { breakpointForWidth, GRID_BREAKPOINTS } from '../gridConfig';

describe('breakpointForWidth', () => {
  it('picks the widest breakpoint whose threshold the width exceeds', () => {
    expect(breakpointForWidth(1200)).toBe('lg');
    expect(breakpointForWidth(GRID_BREAKPOINTS.lg + 1)).toBe('lg');
    expect(breakpointForWidth(800)).toBe('md');
    expect(breakpointForWidth(600)).toBe('sm');
    expect(breakpointForWidth(358)).toBe('xs');
  });

  it('needs the width to exceed a threshold, as react-grid-layout does', () => {
    expect(breakpointForWidth(GRID_BREAKPOINTS.lg)).toBe('md');
    expect(breakpointForWidth(GRID_BREAKPOINTS.sm)).toBe('xs');
  });

  it('treats an unmeasured grid as the narrowest, which is never saved', () => {
    expect(breakpointForWidth(0)).toBe('xs');
  });
});
