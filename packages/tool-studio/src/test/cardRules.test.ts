import { describe, it, expect } from 'vitest';
import { LAYOUT_REQUIRES, missingCardField, cardLayoutProblem } from '../catalog/cardRules';
import { SECONDARY_LAYOUTS } from '../catalog/generated/cardSpec';
import type { CardRender } from '../types';

const card = (extra: Partial<CardRender> = {}): CardRender => ({
  uid: 'c',
  component: 'card',
  column: 'cov',
  aggregation: 'average',
  ...extra,
});

describe('cardRules', () => {
  // The Record is typed exhaustively, so this mostly guards against someone
  // "fixing" a compile error by widening the type instead of adding the layout.
  it('covers every layout the schema declares', () => {
    for (const layout of SECONDARY_LAYOUTS) {
      expect(LAYOUT_REQUIRES).toHaveProperty(layout);
    }
    expect(Object.keys(LAYOUT_REQUIRES).sort()).toEqual([...SECONDARY_LAYOUTS].sort());
  });

  it('a plain card needs nothing', () => {
    expect(missingCardField(card())).toBeNull();
    expect(missingCardField(card({ secondary_layout: 'vertical' }))).toBeNull();
  });

  it('flags the missing companion field per layout', () => {
    expect(missingCardField(card({ secondary_layout: 'donut' }))).toBe('breakdown_col');
    expect(missingCardField(card({ secondary_layout: 'gauge' }))).toBe('coverage_max');
    expect(missingCardField(card({ secondary_layout: 'threshold' }))).toBe('threshold_value');
    expect(missingCardField(card({ secondary_layout: 'attrition' }))).toBe('attrition_cols');
    expect(missingCardField(card({ secondary_layout: 'trend' }))).toBe('trend_col');
  });

  it('accepts the card once the companion field is set', () => {
    expect(missingCardField(card({ secondary_layout: 'donut', breakdown_col: 's' }))).toBeNull();
    expect(missingCardField(card({ secondary_layout: 'gauge', coverage_max: 200 }))).toBeNull();
    expect(missingCardField(card({ secondary_layout: 'threshold', threshold_value: 0 }))).toBeNull();
    expect(
      missingCardField(card({ secondary_layout: 'attrition', attrition_cols: ['a'] })),
    ).toBeNull();
  });

  it('treats an empty attrition list as unset', () => {
    expect(missingCardField(card({ secondary_layout: 'attrition', attrition_cols: [] }))).toBe(
      'attrition_cols',
    );
  });

  it('explains the problem in a sentence', () => {
    expect(cardLayoutProblem(card({ secondary_layout: 'trend' }))).toMatch(/trend_col/);
    expect(cardLayoutProblem(card())).toBeNull();
  });
});
