import { afterEach, describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../../api';
import { genomePosFilterIndex, ownSelection } from '../../../selection';
import { ownRegionKey } from './defaultRegion';
import {
  defaultRegionKey,
  forgetDefaultRegion,
  rememberDefaultRegion,
  withoutDefaultRegion,
} from './defaultRegionMemo';

const region = (chroms: string[], range: number[]): InteractiveFilter[] => [
  { index: 'gv', value: chroms, source: 'genome_selection' },
  { index: genomePosFilterIndex('gv'), value: range, source: 'genome_selection' },
];
const pick: InteractiveFilter = { index: 'gv', value: ['BRCA1'], source: 'scatter_selection' };

afterEach(() => forgetDefaultRegion('gv'));

describe('default region memo', () => {
  it('remembers a key per component and ignores the empty key', () => {
    rememberDefaultRegion('gv', '');
    expect(defaultRegionKey('gv')).toBeUndefined();
    rememberDefaultRegion('gv', 'k');
    expect(defaultRegionKey('gv')).toBe('k');
  });
});

describe('withoutDefaultRegion', () => {
  const opening = region(['chr7'], [100, 200]);
  const key = ownRegionKey(opening, 'gv');

  it('hides the region the tile opened on', () => {
    const own = withoutDefaultRegion(ownSelection(opening, 'gv'), 'gv', key);
    expect(own).toEqual({ filters: [], count: 0 });
  });

  it('keeps a region the reader moved', () => {
    const moved = region(['chr7'], [150, 250]);
    const own = withoutDefaultRegion(ownSelection(moved, 'gv'), 'gv', key);
    expect(own.filters).toHaveLength(2);
    expect(own.count).toBe(1);
  });

  it('keeps a pick made on top of the opening region', () => {
    const own = withoutDefaultRegion(ownSelection([...opening, pick], 'gv'), 'gv', key);
    expect(own.filters).toEqual([pick]);
    expect(own.count).toBe(1);
  });

  it('changes nothing for a tile with no opening region', () => {
    const sel = ownSelection(opening, 'gv');
    expect(withoutDefaultRegion(sel, 'gv', undefined)).toBe(sel);
  });
});
