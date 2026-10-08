import { describe, expect, it } from 'vitest';

import { formatCardNumber, formatSecondary } from './format';
import { breakdownHasShares } from './types';

describe('formatCardNumber', () => {
  it('adds thousands separators to integers without rounding them', () => {
    expect(formatCardNumber(879737777)).toBe('879,737,777');
    expect(formatCardNumber(42)).toBe('42');
    expect(formatCardNumber(-1200)).toBe('-1,200');
  });

  it('shrinks decimals as the magnitude grows', () => {
    expect(formatCardNumber(3640.9958)).toBe('3,641');
    expect(formatCardNumber(907.1053)).toBe('907.1');
    expect(formatCardNumber(12.34567)).toBe('12.35');
    expect(formatCardNumber(0.123456789012345)).toBe('0.123');
    expect(formatCardNumber(0.5)).toBe('0.5');
  });

  it('keeps tiny values visible and non-finite values blank', () => {
    expect(formatCardNumber(0.0000123)).toBe('1.23e-5');
    expect(formatCardNumber(Number.NaN)).toBe('—');
  });

  it('is what the stat lists print', () => {
    expect(formatSecondary(1234567)).toBe('1,234,567');
    expect(formatSecondary('abc')).toBe('abc');
    expect(formatSecondary(null)).toBe('—');
  });
});

describe('breakdownHasShares', () => {
  it('holds for count and sum only', () => {
    expect(breakdownHasShares({ column: 'sample', breakdown_kind: 'count' })).toBe(true);
    expect(breakdownHasShares({ column: 'sample', breakdown_kind: 'sum' })).toBe(true);
    expect(breakdownHasShares({ column: 'sample' })).toBe(true);
    expect(breakdownHasShares({ column: 'sample', breakdown_kind: 'max' }, 'reads')).toBe(false);
    expect(breakdownHasShares({ column: 'sample', breakdown_kind: 'nunique' }, 'gene')).toBe(false);
  });

  it('holds when the breakdown is by the hero column (row counts)', () => {
    expect(breakdownHasShares({ column: 'lineage', breakdown_kind: 'nunique' }, 'lineage')).toBe(
      true,
    );
  });
});
