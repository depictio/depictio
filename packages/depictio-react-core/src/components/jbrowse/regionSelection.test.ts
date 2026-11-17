import { describe, expect, it } from 'vitest';

import type { JBrowseLocusSource } from '../../api';
import { genomeSelectionRegion } from './locusForAction';
import {
  clearOwnRegion,
  isOwnRegion,
  ownRegionOf,
  regionFiltersFor,
  withoutOwnRegion,
} from './regionSelection';

const source: JBrowseLocusSource = {
  dc_id: 'dc-peaks',
  chrom_column: 'chrom',
  start_column: 'start',
  end_column: 'end',
};

describe('regionFiltersFor', () => {
  it('turns a 0-based half-open region into a chromosome and a 1-based range', () => {
    const [chrom, pos] = regionFiltersFor(source, { index: 'jb' }, {
      refName: 'chr8',
      start: 99,
      end: 200,
    });
    expect(chrom).toMatchObject({
      index: 'jb',
      source: 'genome_selection',
      column_name: 'chrom',
      interactive_component_type: 'MultiSelect',
      value: ['chr8'],
    });
    expect(pos).toMatchObject({
      index: 'jb::pos',
      source: 'genome_selection',
      column_name: 'start',
      interactive_component_type: 'RangeSlider',
      value: [100, 200],
    });
  });

  it('carries the collection of the locus source so followers recognise it', () => {
    const pair = regionFiltersFor(source, { index: 'jb' }, { refName: 'chr1', start: 0, end: 10 });
    for (const f of pair) expect(f.metadata?.dc_id).toBe('dc-peaks');
  });

  it('never starts below position 1 and rounds fractional ends up', () => {
    const [, pos] = regionFiltersFor(source, { index: 'jb' }, {
      refName: 'chr1',
      start: -5,
      end: 10.2,
    });
    expect(pos.value).toEqual([1, 11]);
  });

  it('gives the cleared pair for null or an empty span', () => {
    for (const region of [null, { refName: 'chr1', start: 5, end: 5 }]) {
      const pair = regionFiltersFor(source, { index: 'jb' }, region);
      expect(pair).toHaveLength(2);
      for (const f of pair) expect(f.value).toEqual([]);
    }
  });
});

describe('own region', () => {
  const emitted = regionFiltersFor(source, { index: 'jb' }, {
    refName: 'chr8',
    start: 99,
    end: 200,
  });
  const other = regionFiltersFor(source, { index: 'other' }, {
    refName: 'chr2',
    start: 0,
    end: 50,
  });

  it('is recognised by the tile index, either half', () => {
    expect(isOwnRegion(emitted, 'jb')).toBe(true);
    expect(isOwnRegion(other, 'jb')).toBe(false);
    expect(isOwnRegion([], 'jb')).toBe(false);
  });

  it('is not own once cleared', () => {
    expect(isOwnRegion(regionFiltersFor(source, { index: 'jb' }, null), 'jb')).toBe(false);
  });

  it('is excluded from what the tile follows, and only that', () => {
    const all = [...emitted, ...other];
    expect(withoutOwnRegion(all, 'jb')).toEqual(other);
    // Followed from the filters, the tile's own region would be a navigation.
    expect(genomeSelectionRegion(all)).not.toBeNull();
    expect(genomeSelectionRegion(withoutOwnRegion(emitted, 'jb'))).toBeNull();
  });

  it('is read back as the 0-based band it was drawn from', () => {
    expect(ownRegionOf(emitted, 'jb')).toEqual({ refName: 'chr8', start: 99, end: 200 });
    expect(ownRegionOf(other, 'jb')).toBeNull();
  });

  it('has no band without a range or after a clear', () => {
    expect(ownRegionOf([emitted[0]], 'jb')).toBeNull();
    expect(ownRegionOf(clearOwnRegion(emitted, 'jb'), 'jb')).toBeNull();
  });

  it('clears both halves, and not another tile', () => {
    const cleared = clearOwnRegion([...emitted, ...other], 'jb');
    expect(cleared).toHaveLength(2);
    expect(cleared.map((f) => f.index).sort()).toEqual(['jb', 'jb::pos']);
    for (const f of cleared) expect(f.value).toEqual([]);
  });
});
