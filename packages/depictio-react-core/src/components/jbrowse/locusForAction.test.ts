import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../api';
import { genomeRegionFilters } from '../../selection';
import {
  genomeSelectionRegion,
  genomeSelectionSource,
  locusForAction,
  pointLocus,
  pointOnAxis,
  readPlotXRange,
  regionNavTarget,
  windowLocus,
  windowOnOneChrom,
} from './locusForAction';

const tile = { index: 'nav', dc_id: 'dc1' } as never;
const region = (chroms: string[], range: [number, number] | null): InteractiveFilter[] =>
  genomeRegionFilters(tile, 'chr', 'pos', { chroms, range });

describe('locusForAction', () => {
  const point = { chrom: 'chr8', pos: 1000 };
  const reg = { chrom: 'chr2', start: 100, end: 900 };
  const win = { chrom: 'chr3', start: 5, end: 50 };

  it('prefers the clicked point, padded on both sides', () => {
    expect(locusForAction({ point, region: reg, window: win })).toBe('chr8:500-1500');
  });
  it('falls back to the selected region, then to the visible window', () => {
    expect(locusForAction({ region: reg, window: win })).toBe('chr2:100-900');
    expect(locusForAction({ window: win })).toBe('chr3:5-50');
  });
  it('is null when no source gives a locus', () => {
    expect(locusForAction({})).toBeNull();
    expect(locusForAction({ point: { chrom: '', pos: 3 }, region: null, window: null })).toBeNull();
  });
  it('clamps a point near the contig start to base 1', () => {
    expect(pointLocus({ chrom: 'chr1', pos: 100 })).toBe('chr1:1-600');
  });
  it('names the contig alone for a region without a range', () => {
    expect(windowLocus({ chrom: 'chr7', start: 0, end: Number.POSITIVE_INFINITY })).toBe('chr7');
    expect(locusForAction({ region: { chrom: 'chr7', start: 0, end: Infinity } })).toBe('chr7');
  });
});

describe('genomeSelectionRegion', () => {
  it('reads the contig and range from the filters themselves', () => {
    expect(genomeSelectionRegion(region(['chr5'], [1000, 2000]))).toEqual({
      chrom: 'chr5',
      start: 1000,
      end: 2000,
    });
  });
  it('is the whole contig when the brush has no range', () => {
    expect(genomeSelectionRegion(region(['chr5'], null))).toEqual({
      chrom: 'chr5',
      start: 0,
      end: Number.POSITIVE_INFINITY,
    });
  });
  it('is the first contig, whole, for a brush across several', () => {
    expect(genomeSelectionRegion(region(['chr5', 'chr6'], null))).toEqual({
      chrom: 'chr5',
      start: 0,
      end: Number.POSITIVE_INFINITY,
    });
  });
  it('is null for no contig or other filter sources', () => {
    expect(genomeSelectionRegion(region([], null))).toBeNull();
    expect(genomeSelectionRegion([])).toBeNull();
    const other: InteractiveFilter = {
      index: 'x',
      value: ['a'],
      source: 'scatter_selection',
      column_name: 'chr',
      interactive_component_type: 'MultiSelect',
    } as InteractiveFilter;
    expect(genomeSelectionRegion([other])).toBeNull();
  });
});

describe('regionNavTarget', () => {
  const canonical = (name: string) => ({ '8': 'chr8', chr8: 'chr8' })[name];
  it('navigates by the assembly name of the contig', () => {
    expect(regionNavTarget({ chrom: '8', start: 10, end: 90 }, canonical)).toBe('chr8:10-90');
    expect(regionNavTarget({ chrom: '8', start: 0, end: Infinity }, canonical)).toBe('chr8');
  });
  it('is null for a contig the assembly does not know', () => {
    expect(regionNavTarget({ chrom: 'chrZ', start: 1, end: 9 }, canonical)).toBeNull();
    expect(regionNavTarget(null, canonical)).toBeNull();
  });
});

describe('cumulative axis helpers', () => {
  const offsets = new Map([
    ['chr1', 0],
    ['chr2', 1000],
    ['chr3', 2000],
  ]);
  it('gives the window when the range covers one contig', () => {
    expect(windowOnOneChrom([1100, 1400], offsets)).toEqual({ chrom: 'chr2', start: 100, end: 400 });
  });
  it('is null on the genome-wide view or an empty range', () => {
    expect(windowOnOneChrom([0, 2500], offsets)).toBeNull();
    expect(windowOnOneChrom([500, 500], offsets)).toBeNull();
    expect(windowOnOneChrom(null, offsets)).toBeNull();
  });
  it('reads a position back from an x', () => {
    expect(pointOnAxis(2150, offsets)).toEqual({ chrom: 'chr3', pos: 150 });
    expect(pointOnAxis(10, offsets)).toEqual({ chrom: 'chr1', pos: 10 });
    expect(pointOnAxis(Number.NaN, offsets)).toBeNull();
  });
  it('reads the visible x range of a graph div', () => {
    expect(readPlotXRange({ _fullLayout: { xaxis: { range: [5, 1] } } })).toEqual([1, 5]);
    expect(readPlotXRange({ layout: { xaxis: { range: [2, 9] } } })).toEqual([2, 9]);
    expect(readPlotXRange(null)).toBeNull();
    expect(readPlotXRange({ layout: { xaxis: {} } })).toBeNull();
  });
});

describe('genomeSelectionSource', () => {
  it('names the tile that selected the region, without the position suffix', () => {
    const filters = region(['chr6'], [100, 200]);
    expect(filters.some((f) => String(f.index).includes('::'))).toBe(true);
    expect(genomeSelectionSource(filters)).toBe('nav');
  });
  it('is null without a region', () => {
    expect(genomeSelectionSource([])).toBeNull();
    expect(genomeSelectionSource(null)).toBeNull();
  });
});
