import { describe, expect, it } from 'vitest';

import type { StoredMetadata } from '../../api';
import {
  alwaysSelectedComponents,
  bannerFactColumns,
  bannerFactIcon,
  bannerFactItems,
  scopeUnits,
  unitSteps,
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

describe('bannerFactItems', () => {
  const facts = [
    { column: 'size', label: 'Members', format: 'integer' },
    { column: 'kind', label: 'Kind' },
    { column: 'score', label: 'Score', format: 'decimals:2' },
    { column: 'missing', label: 'Missing' },
  ];

  it('formats numbers, keeps text, drops absent or empty values', () => {
    expect(bannerFactItems(facts, { size: 1234.4, kind: ' alpha ', score: null })).toEqual([
      { label: 'Members', text: '1,234', icon: 'tabler:hash' },
      { label: 'Kind', text: 'alpha', icon: 'tabler:tag' },
    ]);
  });

  it('draws a fact with its own icon, else one for the kind of value', () => {
    expect(bannerFactIcon({ column: 'n', label: 'N', icon: 'tabler:users-group' }, 3)).toBe(
      'tabler:users-group',
    );
    expect(bannerFactIcon({ column: 'n', label: 'N', format: 'percent' }, 0.4)).toBe(
      'tabler:percentage',
    );
    expect(bannerFactIcon({ column: 'n', label: 'N' }, 3)).toBe('tabler:hash');
    expect(bannerFactIcon({ column: 'n', label: 'N' }, 'x')).toBe('tabler:tag');
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

describe('unitSteps', () => {
  const opts = [
    { value: 'a' },
    { value: 'b', disabled: true },
    { value: 'c' },
    { value: 'd' },
  ];

  it('ranks the held value among the offered ones and skips ruled-out neighbours', () => {
    expect(unitSteps(opts, 'c')).toEqual({ position: 2, total: 3, prev: 'a', next: 'd' });
  });

  it('stops at both ends', () => {
    expect(unitSteps(opts, 'a')).toMatchObject({ position: 1, prev: null, next: 'c' });
    expect(unitSteps(opts, 'd')).toMatchObject({ position: 3, prev: 'c', next: null });
  });

  it('steps forward to the first offered value when the held one is not offered', () => {
    expect(unitSteps(opts, 'b')).toEqual({ position: 0, total: 3, prev: null, next: 'a' });
    expect(unitSteps(opts, undefined)).toEqual({ position: 0, total: 3, prev: null, next: 'a' });
    expect(unitSteps([], 'x')).toEqual({ position: 0, total: 0, prev: null, next: null });
  });
});
