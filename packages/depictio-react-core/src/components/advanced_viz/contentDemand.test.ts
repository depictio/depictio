import { describe, expect, it } from 'vitest';

import { GRID_ROW_GAP_PX, GRID_ROW_PX } from '../autofit';
import {
  ADVANCED_VIZ_MAX_ROWS,
  ADVANCED_VIZ_MIN_ROWS,
  demandForItems,
  demandForPx,
  heightForRows,
  rowsForItems,
  rowsForPx,
} from './contentDemand';

describe('rowsForPx', () => {
  it('converts against the grid geometry, not a baked-in row height', () => {
    // One row's worth of content asks for one row, which the floor then
    // raises to the kind's minimum.
    expect(rowsForPx(GRID_ROW_PX, { min: 1 })).toBe(1);
    // A pixel past what one row offers needs a second one.
    expect(rowsForPx(heightForRows(1) + 1, { min: 1 })).toBe(2);
    expect(rowsForPx(heightForRows(5), { min: 1 })).toBe(5);
    // The gaps between rows are room too: five rows offer 4 * GRID_ROW_GAP_PX
    // more than five bare rows would.
    expect(rowsForPx(5 * GRID_ROW_PX + 4 * GRID_ROW_GAP_PX, { min: 1 })).toBe(5);
  });

  it('clamps to the advanced_viz policy by default', () => {
    expect(rowsForPx(10)).toBe(ADVANCED_VIZ_MIN_ROWS);
    expect(rowsForPx(100_000)).toBe(ADVANCED_VIZ_MAX_ROWS);
  });

  it('honours narrower bounds', () => {
    expect(rowsForPx(10_000, { max: 6 })).toBe(6);
    expect(rowsForPx(10, { min: 5 })).toBe(5);
  });

  it('returns integers for any input', () => {
    for (const px of [0, 1, 37.4, 211.9, 1_003.5, Number.NaN, -40]) {
      const rows = rowsForPx(px);
      expect(Number.isInteger(rows)).toBe(true);
      expect(rows).toBeGreaterThanOrEqual(ADVANCED_VIZ_MIN_ROWS);
      expect(rows).toBeLessThanOrEqual(ADVANCED_VIZ_MAX_ROWS);
    }
  });
});

describe('rowsForItems', () => {
  it('grows with the item count and never shrinks', () => {
    const counts = [1, 2, 5, 10, 20, 200];
    const rows = counts.map((n) => rowsForItems(n, 24, 80));
    for (let i = 1; i < rows.length; i += 1) {
      expect(rows[i]).toBeGreaterThanOrEqual(rows[i - 1]);
    }
    expect(rows[rows.length - 1]).toBe(ADVANCED_VIZ_MAX_ROWS);
  });

  it('asks for less than a generous tile when there is little to draw', () => {
    // Two bars and three genes are the cases the policy exists for: they must
    // not come back asking for the ceiling.
    expect(rowsForItems(2, 30, 90)).toBeLessThan(ADVANCED_VIZ_MAX_ROWS);
    expect(rowsForItems(3, 22, 120)).toBeLessThan(ADVANCED_VIZ_MAX_ROWS);
  });

  it('counts a fetch that has not landed as unknown, not as empty', () => {
    expect(rowsForItems(0, 30, 400)).toBe(ADVANCED_VIZ_MIN_ROWS);
    expect(rowsForItems(Number.NaN, 30, 400)).toBe(ADVANCED_VIZ_MIN_ROWS);
  });

  it('adds the chrome once, not per item', () => {
    const withoutChrome = rowsForItems(4, 100, 0, { min: 1, max: 99 });
    const withChrome = rowsForItems(4, 100, 400, { min: 1, max: 99 });
    expect(withChrome - withoutChrome).toBe(4);
  });

  it('is stable for the same data', () => {
    expect(rowsForItems(17, 26, 150)).toBe(rowsForItems(17, 26, 150));
  });
});

describe('demandForItems / demandForPx', () => {
  it('says nothing at all when there is nothing on screen', () => {
    expect(demandForItems(0, 30, 90)).toBeUndefined();
    expect(demandForItems(-3, 30, 90)).toBeUndefined();
    expect(demandForPx(0)).toBeUndefined();
  });

  it('wraps the row count in the shape AdvancedVizFrame takes', () => {
    expect(demandForItems(8, 26, 120)).toEqual({ rows: rowsForItems(8, 26, 120) });
    expect(demandForPx(600)).toEqual({ rows: rowsForPx(600) });
  });
});
