import { describe, expect, it } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import { genomeRegionFilters, regionFromFilters } from '../../../selection';
import {
  defaultRegionFilters,
  ownRegionKey,
  ownRegionZoom,
  regionFilterInForce,
} from './defaultRegion';

const meta = {
  index: 'gv-1',
  component_type: 'advanced_viz',
  dc_id: 'dc-1',
} as StoredMetadata;

const CONTIGS = ['chr1', 'chr2', 'chr7', 'chrX'];

function input(overrides: Partial<Parameters<typeof defaultRegionFilters>[0]> = {}) {
  return {
    metadata: meta,
    chrColumn: 'chr',
    posColumn: 'pos',
    defaultRegion: 'chr1:10,000,000-12,000,000',
    enabled: true,
    contigs: CONTIGS,
    genes: null,
    filters: [] as InteractiveFilter[],
    ...overrides,
  };
}

describe('defaultRegionFilters', () => {
  it('emits the same pair the locus field emits for the same text', () => {
    const emitted = defaultRegionFilters(input());
    expect(emitted).toEqual(
      genomeRegionFilters(meta, 'chr', 'pos', {
        chroms: ['chr1'],
        range: [10_000_000, 12_000_000],
      }),
    );
    // Which is to say: it reads back as the region it names.
    expect(regionFromFilters(emitted!, 'chr', 'pos')).toEqual({
      chrom: 'chr1',
      start: 10_000_000,
      end: 12_000_000,
    });
  });

  it('takes the whole grammar the address bar takes', () => {
    const asRegion = (text: string) => {
      const emitted = defaultRegionFilters(input({ defaultRegion: text }));
      return emitted ? regionFromFilters(emitted, 'chr', 'pos') : null;
    };
    expect(asRegion('chr7:55.0Mb-56Mb')).toEqual({ chrom: 'chr7', start: 55e6, end: 56e6 });
    expect(asRegion('chr7:55000000..56000000')).toEqual({
      chrom: 'chr7',
      start: 55e6,
      end: 56e6,
    });
    // One coordinate opens a window around it.
    expect(asRegion('chr7:55000000')).toEqual({ chrom: 'chr7', start: 54_995_000, end: 55_005_000 });
    // A bare contig is the whole contig, which is still somewhere to go.
    expect(asRegion('chr2')).toEqual({ chrom: 'chr2', start: 0, end: Number.POSITIVE_INFINITY });
  });

  it('matches the contig spelling the data carries, not the one the author typed', () => {
    const emitted = defaultRegionFilters(
      input({ defaultRegion: '7:1-1000', contigs: ['1', '7', 'X'] }),
    );
    expect(emitted?.[0].value).toEqual(['7']);
    const chrPrefixed = defaultRegionFilters(input({ defaultRegion: '7:1-1000' }));
    expect(chrPrefixed?.[0].value).toEqual(['chr7']);
  });

  it('emits nothing when there is nothing to emit or nobody to emit to', () => {
    expect(defaultRegionFilters(input({ defaultRegion: null }))).toBeNull();
    expect(defaultRegionFilters(input({ defaultRegion: '   ' }))).toBeNull();
    // region_filter_enabled is off, or the host is read-only.
    expect(defaultRegionFilters(input({ enabled: false }))).toBeNull();
  });

  it('waits for the contig list rather than guessing at the spelling', () => {
    expect(defaultRegionFilters(input({ contigs: [] }))).toBeNull();
    expect(defaultRegionFilters(input({ contigs: null }))).toBeNull();
  });

  it('gives up on a contig the collection does not carry', () => {
    expect(defaultRegionFilters(input({ defaultRegion: 'chr22:1-1000' }))).toBeNull();
  });

  it('never moves a reader who is already somewhere', () => {
    const elsewhere = genomeRegionFilters(
      { ...meta, index: 'gv-2' } as StoredMetadata,
      'chr',
      'pos',
      { chroms: ['chrX'], range: [1, 2000] },
    );
    expect(defaultRegionFilters(input({ filters: elsewhere }))).toBeNull();

    // A plain chromosome select in the left panel counts too: it names the
    // same column, so it is the same region.
    const sidebar: InteractiveFilter[] = [
      {
        index: 'chr-select',
        value: ['chr2'],
        column_name: 'chr',
        interactive_component_type: 'Select',
      } as InteractiveFilter,
    ];
    expect(defaultRegionFilters(input({ filters: sidebar }))).toBeNull();
  });

  it('treats a cleared region as no region, so the default still opens', () => {
    const cleared = genomeRegionFilters(meta, 'chr', 'pos', null);
    expect(regionFilterInForce(cleared, 'chr', 'pos')).toBe(false);
    expect(defaultRegionFilters(input({ filters: cleared }))).not.toBeNull();
  });

  it('ignores filters on other columns', () => {
    const other: InteractiveFilter[] = [
      {
        index: 'sample',
        value: ['S1'],
        column_name: 'sample',
        interactive_component_type: 'MultiSelect',
      } as InteractiveFilter,
    ];
    expect(regionFilterInForce(other, 'chr', 'pos')).toBe(false);
    expect(defaultRegionFilters(input({ filters: other }))).not.toBeNull();
  });
});

describe('ownRegionZoom', () => {
  const pair = (text: [string, [number, number] | null] | null) =>
    genomeRegionFilters(
      meta,
      'chr',
      'pos',
      text ? { chroms: [text[0]], range: text[1] } : null,
    );
  const base = {
    componentIndex: 'gv-1',
    chrColumn: 'chr',
    posColumn: 'pos',
    previousKey: '',
    brushedKey: null as string | null,
    zoomedByCode: false,
  };

  it('zooms the emitting tile to the region its locus field published', () => {
    const filters = pair(['chr7', [55_000_000, 56_000_000]]);
    const { decision, key } = ownRegionZoom({ ...base, filters });
    expect(decision).toEqual({
      action: 'zoom',
      region: { chrom: 'chr7', start: 55_000_000, end: 56_000_000 },
    });
    expect(key).toBe(ownRegionKey(filters, 'gv-1'));
  });

  it('zooms to a whole contig when only the chromosome was picked', () => {
    const { decision } = ownRegionZoom({ ...base, filters: pair(['chr2', null]) });
    expect(decision).toEqual({
      action: 'zoom',
      region: { chrom: 'chr2', start: 0, end: Number.POSITIVE_INFINITY },
    });
  });

  it('does nothing when the region has not changed', () => {
    const filters = pair(['chr7', [1, 2]]);
    const key = ownRegionKey(filters, 'gv-1');
    expect(ownRegionZoom({ ...base, filters, previousKey: key }).decision).toEqual({
      action: 'none',
    });
  });

  it('leaves a region the tile brushed itself to the brush rectangle', () => {
    const filters = pair(['chr7', [1, 2]]);
    const brushedKey = ownRegionKey(filters, 'gv-1');
    expect(ownRegionZoom({ ...base, filters, brushedKey }).decision).toEqual({ action: 'none' });
  });

  it('ignores other tiles regions (those belong to follow_region_filter)', () => {
    const other = genomeRegionFilters(
      { ...meta, index: 'gv-2' } as StoredMetadata,
      'chr',
      'pos',
      { chroms: ['chr1'], range: [10, 20] },
    );
    const { decision, key } = ownRegionZoom({ ...base, filters: other });
    expect(key).toBe('');
    expect(decision).toEqual({ action: 'none' });
  });

  it('zooms back to the whole genome when the region is cleared after a zoom from code', () => {
    const before = ownRegionKey(pair(['chr7', [1, 2]]), 'gv-1');
    const { decision } = ownRegionZoom({
      ...base,
      filters: pair(null),
      previousKey: before,
      zoomedByCode: true,
    });
    expect(decision).toEqual({ action: 'reset' });
  });

  it('falls back to the followed region rather than the whole genome on clear', () => {
    const before = ownRegionKey(pair(['chr7', [1, 2]]), 'gv-1');
    const followedRegion = { chrom: 'chr1', start: 5, end: 9 };
    const { decision } = ownRegionZoom({
      ...base,
      filters: [],
      previousKey: before,
      zoomedByCode: true,
      followedRegion,
    });
    expect(decision).toEqual({ action: 'zoom', region: followedRegion });
  });

  it('does not reset when the view was never zoomed from code', () => {
    const before = ownRegionKey(pair(['chr7', [1, 2]]), 'gv-1');
    expect(
      ownRegionZoom({ ...base, filters: pair(null), previousKey: before }).decision,
    ).toEqual({ action: 'none' });
  });

  it('does not zoom to a region spanning several contigs', () => {
    const filters = genomeRegionFilters(meta, 'chr', 'pos', { chroms: ['chr1', 'chr2'], range: null });
    expect(ownRegionZoom({ ...base, filters }).decision).toEqual({ action: 'none' });
  });
});
