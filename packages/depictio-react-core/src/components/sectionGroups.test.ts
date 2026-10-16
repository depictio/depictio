import { describe, expect, it } from 'vitest';

import {
  MAX_FIT_ROW_RATIO,
  MIN_FIT_ROW_PX,
  LINKED_VIEW_MIN_PANE_PX,
  effectiveDisplay,
  fitRowPx,
  layoutRows,
  minRowPxForTiles,
  rowFloorPx,
} from './sectionGroups';

const tile = (i: string, x: number, y: number, w: number, h: number) => ({ i, x, y, w, h });

describe('effectiveDisplay', () => {
  it('keeps what the dashboard declares without an override', () => {
    expect(effectiveDisplay({ display: 'linked' }, null)).toBe('linked');
  });

  it('draws a linked view as an ordinary section under classic', () => {
    expect(effectiveDisplay({ display: 'linked' }, 'classic')).toBe('grid');
  });

  it('never touches a section that is not a linked view', () => {
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

  it('stretches no further than twice the normal row', () => {
    expect(MAX_FIT_ROW_RATIO).toBe(2);
    expect(fitRowPx(2, 1200, 4, 100)).toBe(200);
    // A read-only grid counts in half rows (48 px): 96 at most.
    expect(fitRowPx(2, 1200, 4, 48)).toBe(96);
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

  it('never goes under the floor, however little room the screen has', () => {
    // 10 rows would fit a 676 px screen at 64, but the tiles need 90.
    expect(fitRowPx(10, 676, 4, 100, 1, 90)).toBe(90);
    expect(fitRowPx(20, 300, 4, 100, 1, 60)).toBe(60);
  });

  it('lets the floor beat the stretch cap: a tall stack makes a tall linked view', () => {
    expect(fitRowPx(2, 900, 4, 100, 1, 240)).toBe(240);
  });

  it('leaves the fit alone when the floor is below it, or is not a floor', () => {
    expect(fitRowPx(10, 676, 4, 100, 1, 30)).toBe(64);
    expect(fitRowPx(10, 676, 4, 100, 1, 0)).toBe(64);
    expect(fitRowPx(10, 676, 4, 100, 1, Number.NaN)).toBe(64);
    expect(fitRowPx(10, 676, 4, 100, 1, -5)).toBe(64);
  });

  it('keeps the floor when there is nothing to fit', () => {
    expect(fitRowPx(0, 600, 4, 100, 1, 120)).toBe(120);
    expect(fitRowPx(10, 0, 4, 100, 1, 120)).toBe(120);
    expect(fitRowPx(10, 0, 4, 100, 1, 80)).toBe(100);
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

describe('rowFloorPx', () => {
  it('is the row height at which the rows and their gaps reach the wanted height', () => {
    // 9 rows and 8 gaps of 4 must span 848 px: (848 - 32) / 9 = 90.7, rounded up.
    expect(rowFloorPx(848, 9, 4)).toBe(91);
    expect(91 * 9 + 8 * 4).toBeGreaterThanOrEqual(848);
    expect(90 * 9 + 8 * 4).toBeLessThan(848);
  });

  it('is 0 when there is nothing to size', () => {
    expect(rowFloorPx(0, 9, 4)).toBe(0);
    expect(rowFloorPx(848, 0, 4)).toBe(0);
    expect(rowFloorPx(Number.NaN, 9, 4)).toBe(0);
  });

  it('is never negative for a few rows and a lot of gap', () => {
    expect(rowFloorPx(10, 3, 40)).toBe(0);
  });
});

describe('minRowPxForTiles', () => {
  const floor = () => LINKED_VIEW_MIN_PANE_PX;

  it('lets the tightest tile set the row: a tile h rows high spans h * row + (h - 1) * gap', () => {
    // 280 over 3 rows and 2 gaps of 4: (280 - 8) / 3 = 90.7; over 2 rows, 138.
    expect(minRowPxForTiles([tile('a', 0, 0, 8, 3)], floor, 4)).toBe(91);
    expect(minRowPxForTiles([tile('a', 0, 0, 4, 3), tile('b', 4, 0, 4, 2)], floor, 4)).toBe(138);
  });

  it('asks little of a very tall tile', () => {
    expect(minRowPxForTiles([tile('a', 0, 0, 8, 9)], floor, 4)).toBe(Math.ceil((280 - 32) / 9));
  });

  it('skips a tile with no floor, and a layout with none', () => {
    const none = (key: string) => (key === 'card' ? 0 : LINKED_VIEW_MIN_PANE_PX);
    expect(minRowPxForTiles([tile('card', 0, 0, 2, 1), tile('b', 2, 0, 6, 3)], none, 4)).toBe(91);
    expect(minRowPxForTiles([], floor, 4)).toBe(0);
    expect(minRowPxForTiles([tile('x', 0, 0, 8, 0)], floor, 4)).toBe(0);
  });
});
