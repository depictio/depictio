import { describe, expect, it } from 'vitest';

import {
  cardNumberFormat,
  formatAggregate,
  formatCardNumber,
  formatCount,
  formatNumber,
  formatSecondary,
  hexWithAlpha,
} from './format';
import { thresholdCaption } from './Threshold';
import type { ThresholdPayload } from './types';
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
    expect(formatCardNumber(0.000322)).toBe('0.00032');
    expect(formatCardNumber(0.0000123)).toBe('1.23e-5');
    expect(formatCardNumber(Number.NaN)).toBe('—');
  });

  it('is what the stat lists print', () => {
    expect(formatSecondary(1234567)).toBe('1,234,567');
    expect(formatSecondary('abc')).toBe('abc');
    expect(formatSecondary(null)).toBe('—');
  });

  it('prints a stat in the card format when given one', () => {
    expect(formatSecondary(0.41, 'percent')).toBe('41%');
    expect(formatSecondary(7.0831, 'decimals:2')).toBe('7.08');
  });
});

describe('formatNumber', () => {
  it('shows a 0-1 fraction as a percentage, one decimal under 10%', () => {
    expect(formatNumber(0.41, 'percent')).toBe('41%');
    expect(formatNumber(0.047, 'percent')).toBe('4.7%');
    expect(formatNumber(1, 'percent')).toBe('100%');
    expect(formatNumber(0, 'percent')).toBe('0%');
  });

  it('keeps a share under 1% off 0%, at two significant digits', () => {
    expect(formatNumber(0.000322, 'percent')).toBe('0.032%');
    expect(formatNumber(0.0047, 'percent')).toBe('0.47%');
    expect(formatNumber(0.01, 'percent')).toBe('1%');
  });

  it('abbreviates large values with SI suffixes', () => {
    expect(formatNumber(214_000, 'si')).toBe('214k');
    expect(formatNumber(3_712_345, 'si')).toBe('3.7M');
    expect(formatNumber(812, 'si')).toBe('812');
  });

  it('rounds to an integer, or to the decimals asked for', () => {
    expect(formatNumber(12345.6, 'integer')).toBe('12,346');
    expect(formatNumber(7.1, 'decimals:2')).toBe('7.10');
  });

  it('prints like a card without a format, or with one it does not know', () => {
    expect(formatNumber(0.41)).toBe('0.41');
    expect(formatNumber(0.41, 'decimals:9')).toBe('0.41');
    expect(formatNumber(Number.NaN, 'percent')).toBe('—');
  });
});

describe('cardNumberFormat', () => {
  it('takes the card format, else its decimals', () => {
    expect(cardNumberFormat({ format: 'percent' })).toBe('percent');
    expect(cardNumberFormat({ decimals: 2 })).toBe('decimals:2');
    expect(cardNumberFormat({ decimals: 0 })).toBe('decimals:0');
    expect(cardNumberFormat({})).toBeUndefined();
    expect(cardNumberFormat({ format: '  ', decimals: null })).toBeUndefined();
  });

  it('lets the format win when both are set', () => {
    expect(cardNumberFormat({ format: 'si', decimals: 1 })).toBe('si');
  });
});

describe('formatCount', () => {
  it('keeps a count whole, with an SI suffix only under si', () => {
    expect(formatCount(37, 'percent')).toBe('37');
    expect(formatCount(1_234_567, 'si')).toBe('1.2M');
    expect(formatCount(1234, 'percent')).toBe((1234).toLocaleString());
  });
});

describe('formatAggregate', () => {
  it('formats aggregations of the card column like its value', () => {
    expect(formatAggregate('median', 0.41, 'percent')).toBe('41%');
    expect(formatAggregate('max', 0.97, 'percent')).toBe('97%');
    expect(formatAggregate('std_dev', 0.05, 'percent')).toBe('5%');
  });

  it('keeps counts as counts', () => {
    expect(formatAggregate('count', 40, 'percent')).toBe('40');
    expect(formatAggregate('nunique', 3_400_000, 'si')).toBe('3.4M');
  });

  it('leaves the shape statistics and unformatted cards alone', () => {
    expect(formatAggregate('skewness', 0.41, 'percent')).toBe('0.41');
    expect(formatAggregate('median', 0.41)).toBe('0.41');
    expect(formatAggregate('mode', 'paired', 'percent')).toBe('paired');
  });
});

describe('thresholdCaption', () => {
  const payload: ThresholdPayload = {
    column: 'mapped_rate',
    threshold: 0.7,
    warn_threshold: 0.5,
    direction: 'min',
    total: 40,
    measured: 40,
    nulls: 0,
    passing: 37,
    warning: 2,
    failing: 1,
    pass_rate: 0.925,
    min: 0.41,
    max: 0.97,
    median: 0.88,
  };

  it('puts the cut-off in the card format and keeps the counts whole', () => {
    expect(thresholdCaption(payload, 'percent')).toBe('37/40 pass ≥ 70% · 2 warn · 1 fail');
  });

  it('prints the cut-off at axis precision without a format', () => {
    expect(thresholdCaption(payload)).toBe('37/40 pass ≥ 0.70 · 2 warn · 1 fail');
  });

  it('takes SI suffixes on the counts under si', () => {
    const reads = {
      ...payload,
      threshold: 5e6,
      passing: 1_250_000,
      measured: 1_300_000,
      warning: 0,
      failing: 50_000,
    };
    expect(thresholdCaption(reads, 'si')).toBe('1.3M/1.3M pass ≥ 5M · 50k fail');
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

describe('hexWithAlpha', () => {
  it('takes a hex colour, an rgb() colour and a Mantine palette name', () => {
    expect(hexWithAlpha('#ff7f00', 0.5)).toBe('rgba(255,127,0,0.5)');
    expect(hexWithAlpha('FF7F00', 0.5)).toBe('rgba(255,127,0,0.5)');
    expect(hexWithAlpha('rgb(1, 2, 3)', 0.3)).toBe('rgba(1,2,3,0.3)');
    expect(hexWithAlpha('grape', 0.85)).toBe(
      'color-mix(in srgb, var(--mantine-color-grape-filled) 85%, transparent)',
    );
  });

  it('falls back to teal for anything else', () => {
    expect(hexWithAlpha('var(--x)', 1)).toBe('rgba(69,184,172,1)');
    expect(hexWithAlpha(null, 1)).toBe('rgba(69,184,172,1)');
  });
});
