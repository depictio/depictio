import { describe, expect, it } from 'vitest';

import cases from '../../../depictio/models/palettes/assign_cases.json';
import {
  assignColors,
  BAR_CORNER_RADIUS,
  orderWithRemainderLast,
  OVERVIEW_TOP_N,
  reservedKind,
  scatterMarker,
} from './palettes';

type Case = {
  name: string;
  values: (string | null)[];
  pinned: Record<string, string> | null;
  palette: string | string[] | null;
  mode: 'light' | 'dark';
  ranked?: boolean;
  overflow?: 'other' | 'shade';
  expected: Record<string, string>;
};

// Same cases as depictio/tests/unit/test_palettes.py: both languages must agree.
describe('assignColors parity with Python', () => {
  for (const c of (cases as unknown as { cases: Case[] }).cases) {
    it(c.name, () => {
      const got = assignColors(c.values, { pinned: c.pinned, palette: c.palette, scheme: c.mode, ranked: c.ranked, overflow: c.overflow });
      expect(Object.fromEntries(got)).toEqual(c.expected);
    });
  }
});

describe('reserved values', () => {
  it('classifies remainder values', () => {
    expect(reservedKind(' Others ')).toBe('other');
    expect(reservedKind('unknown')).toBe('unclassified');
    expect(reservedKind(null)).toBe('na');
    expect(reservedKind('Soil')).toBeNull();
  });

  it('moves the remainder last', () => {
    expect(orderWithRemainderLast(['NA', 'b', 'Other', 'a', 'Unclassified'])).toEqual([
      'b', 'a', 'Other', 'Unclassified', 'NA',
    ]);
  });
});

describe('overview style constants', () => {
  it('match the shared JSON', () => {
    expect(BAR_CORNER_RADIUS).toBe(4);
    expect(OVERVIEW_TOP_N).toBe(8);
  });

  it('size scatter markers by point count, last bucket open-ended', () => {
    expect(scatterMarker(0).size).toBe(9);
    expect(scatterMarker(50).size).toBe(9);
    expect(scatterMarker(51).size).toBe(7);
    expect(scatterMarker(5000).size).toBe(5);
    expect(scatterMarker(5001).size).toBe(3.5);
    expect(scatterMarker(10_000_000).outline).toBe(false);
  });
});
