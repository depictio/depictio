import { describe, expect, it } from 'vitest';

import { clipContactCells, inferContactWindow } from './contactMapWindow';

// Rows a region link narrowed on the first bin only (65-85 Mb), while the
// second bin still runs far past the region.
const MB = 1_000_000;
const cells = [
  { a: 65 * MB, b: 66 * MB, count: 10 },
  { a: 70 * MB, b: 84 * MB, count: 4 },
  { a: 75 * MB, b: 180 * MB, count: 1 },
  { a: 84 * MB, b: 84 * MB, count: 30 },
];

describe('inferContactWindow', () => {
  it('reads the window off the first-bin coordinates', () => {
    expect(inferContactWindow(cells, MB)).toEqual({ start: 65 * MB, end: 85 * MB });
  });

  it('is null without cells', () => {
    expect(inferContactWindow([], MB)).toBeNull();
  });
});

describe('clipContactCells', () => {
  it('drops pairs whose second bin leaves the window', () => {
    const out = clipContactCells(cells, { start: 65 * MB, end: 85 * MB }, MB);
    expect(out.map((c) => c.b)).toEqual([66 * MB, 84 * MB, 84 * MB]);
    expect(Math.max(...out.map((c) => c.b - c.a))).toBe(14 * MB);
  });

  it('keeps a bin that overlaps the window edge', () => {
    const out = clipContactCells([{ a: 64.5 * MB, b: 65.2 * MB, count: 1 }], { start: 65 * MB, end: 85 * MB }, MB);
    expect(out).toHaveLength(1);
  });

  it('is a copy when there is no window', () => {
    const out = clipContactCells(cells, null);
    expect(out).toEqual(cells);
    expect(out).not.toBe(cells);
  });
});
