import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../../api';
import {
  alwaysSelectedComponents,
  bannerFactColumns,
  bannerFactItems,
  scopeChipColor,
  scopeUnits,
} from './scope';

const select = (index: string, extra: Partial<StoredMetadata> = {}): StoredMetadata => ({
  index,
  component_type: 'interactive',
  interactive_component_type: 'Select',
  always_selected: true,
  ...extra,
});

describe('scopeUnits', () => {
  it('keeps always_selected Selects once each', () => {
    const units = alwaysSelectedComponents([
      select('a'),
      select('a'),
      select('b', { always_selected: false }),
      select('c', { interactive_component_type: 'MultiSelect' }),
      { index: 'd', component_type: 'figure' },
    ]);
    expect(units.map((m) => m.index)).toEqual(['a']);
  });

  it('leaves out a filter that only reaches its own section', () => {
    const scopes = new Map([['b', 'Details']]);
    expect(scopeUnits([select('a'), select('b')], scopes).map((m) => m.index)).toEqual(['a']);
    expect(scopeUnits([select('a'), select('b')], null).map((m) => m.index)).toEqual(['a', 'b']);
  });
});

describe('scopeChipColor', () => {
  it('takes the accent of a single filter, neutral for several', () => {
    expect(scopeChipColor([select('a', { icon_color: 'teal' })])).toBe('teal');
    expect(scopeChipColor([select('a')])).toBeUndefined();
    expect(scopeChipColor([select('a', { icon_color: 'teal' }), select('b')])).toBe('gray');
    expect(scopeChipColor([])).toBe('gray');
  });
});

describe('bannerFactItems', () => {
  const facts = [
    { column: 'size', label: 'Members', format: 'integer' },
    { column: 'kind', label: 'Kind' },
    { column: 'score', label: 'Score', format: 'decimals:2' },
    { column: 'missing', label: 'Missing' },
  ];

  it('formats numbers, keeps text, drops absent or empty values', () => {
    expect(bannerFactItems(facts, { size: 1234.4, kind: ' alpha ', score: null })).toEqual([
      { label: 'Members', text: '1,234' },
      { label: 'Kind', text: 'alpha' },
    ]);
  });

  it('drops non-finite numbers and blank text', () => {
    expect(bannerFactItems(facts, { size: Number.NaN, kind: '  ' })).toEqual([]);
  });

  it('is empty without facts or a row', () => {
    expect(bannerFactItems(undefined, { size: 1 })).toEqual([]);
    expect(bannerFactItems(facts, null)).toEqual([]);
  });

  it('asks for each column once', () => {
    expect(bannerFactColumns([...facts, { column: 'size', label: 'Again' }])).toEqual([
      'size',
      'kind',
      'score',
      'missing',
    ]);
  });
});
