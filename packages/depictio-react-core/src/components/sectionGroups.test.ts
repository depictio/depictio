import { describe, expect, it } from 'vitest';

import { MIN_FIT_ROW_PX, effectiveDisplay, fitRowPx, layoutRows } from './sectionGroups';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });

describe('effectiveDisplay', () => {
  it('keeps what the dashboard declares without an override', () => {
    expect(effectiveDisplay({ display: 'workbench' }, null)).toBe('workbench');
  });

  it('draws a workbench as an ordinary section under classic', () => {
    expect(effectiveDisplay({ display: 'workbench' }, 'classic')).toBe('grid');
  });

  it('never touches a section that is not a workbench', () => {
    for (const override of ['classic', null] as const) {
      expect(effectiveDisplay({ display: 'strip' }, override)).toBe('strip');
      expect(effectiveDisplay({ display: 'grid' }, override)).toBe('grid');
      expect(effectiveDisplay({ display: null }, override)).toBeNull();
      expect(effectiveDisplay({}, override)).toBeUndefined();
      expect(effectiveDisplay(undefined, override)).toBeUndefined();
    }
  });
});

describe('fitRowPx', () => {
  it('fills the room: rows plus the gaps between them', () => {
    // 10 rows and 9 gaps of 4 in 676 px: (676 - 36) / 10.
    expect(fitRowPx(10, 676, 4, 100)).toBe(64);
  });

  it('floors, so the section never overshoots by a fraction', () => {
    expect(fitRowPx(7, 500, 4, 100)).toBe(Math.floor((500 - 24) / 7));
  });

  it('squeezes no further than the minimum', () => {
    expect(fitRowPx(20, 300, 4, 100)).toBe(MIN_FIT_ROW_PX);
  });

  it('stretches no further than 1.5 times the normal row', () => {
    expect(fitRowPx(2, 900, 4, 100)).toBe(150);
    // A read-only grid counts in half rows (48 px): 72 at most.
    expect(fitRowPx(2, 900, 4, 48)).toBe(72);
  });

  it('never raises the minimum above a row that is already smaller', () => {
    expect(fitRowPx(50, 100, 4, 20)).toBe(20);
  });

  it('keeps the normal row when there is nothing to fit', () => {
    expect(fitRowPx(0, 600, 4, 100)).toBe(100);
    expect(fitRowPx(10, 0, 4, 100)).toBe(100);
    expect(fitRowPx(10, -20, 4, 100)).toBe(100);
    expect(fitRowPx(10, Number.NaN, 4, 100)).toBe(100);
  });

  it('counts the gaps of each stacked block, not of one tall block', () => {
    // Two stacks of 5 rows: 8 gaps in all, not 9.
    expect(fitRowPx(10, 672, 4, 100, 2)).toBe(64);
    expect(fitRowPx(10, 672, 4, 100, 1)).toBe(63);
  });
});

describe('layoutRows', () => {
  it('is the bottom edge of the lowest tile', () => {
    expect(layoutRows([tile('a', 0, 0, 3, 8), tile('b', 3, 0, 5, 3), tile('c', 3, 3, 5, 6)])).toBe(9);
    expect(layoutRows([])).toBe(0);
  });
});
