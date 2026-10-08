import { describe, expect, it } from 'vitest';

import type { InteractiveFilter } from '../../api';
import { genomeRegionFilters, regionFromFilters } from '../../selection';
import {
  followedRegion,
  genomicRoleBindings,
  genomicRoles,
  isGenomicKind,
  regionXRange,
} from './genomicAxis';

const meta = { index: 'gv-1', component_type: 'advanced_viz', dc_id: 'dc-1' } as any;

/** The pair a genome_view brush publishes, as the dashboard stores it. */
function brush(chrom: string, start: number, end: number, chrCol = 'chr', posCol = 'pos') {
  return genomeRegionFilters(meta, chrCol, posCol, { chroms: [chrom], range: [start, end] } as any);
}

describe('genomicRoles', () => {
  it('maps each kind onto its own column names', () => {
    expect(genomicRoles('manhattan', {})).toEqual({ chrom: 'chr', start: 'pos' });
    expect(genomicRoles('coverage_track', {})).toEqual({
      chrom: 'chromosome',
      start: 'position',
    });
    expect(genomicRoles('cnv_profile', {})).toEqual({
      chrom: 'chrom',
      start: 'start',
      end: 'end',
    });
    expect(genomicRoles('transcript_structure', {})).toEqual({
      chrom: 'chrom',
      start: 'start',
      end: 'end',
    });
    // A metagenomic contig is the chromosome role.
    expect(genomicRoles('gene_arrow_track', {})).toEqual({
      chrom: 'contig',
      start: 'start',
      end: 'end',
    });
    expect(genomicRoles('contact_map', {})).toEqual({ chrom: 'chrom1', start: 'start1' });
  });

  it('prefers the bound columns over the model defaults', () => {
    expect(
      genomicRoles('coverage_track', {
        chromosome_col: 'contig_name',
        position_col: 'bin_start',
        end_col: 'bin_end',
      }),
    ).toEqual({ chrom: 'contig_name', start: 'bin_start', end: 'bin_end' });
  });

  it('leaves an optional end role unbound when the author did not set it', () => {
    expect(genomicRoles('genome_view', { chr_col: 'chr', pos_col: 'pos' })).toEqual({
      chrom: 'chr',
      start: 'pos',
    });
    expect(genomicRoles('genome_view', { end_col: 'stop' })).toEqual({
      chrom: 'chr',
      start: 'pos',
      end: 'stop',
    });
  });

  it('returns null for a kind that is not coordinate bound', () => {
    expect(genomicRoles('volcano', { chr_col: 'chr' })).toBeNull();
    expect(genomicRoles(undefined, {})).toBeNull();
    expect(isGenomicKind('volcano')).toBe(false);
    expect(isGenomicKind('sashimi')).toBe(true);
  });

  it('gives sashimi both of its bindings, junctions first', () => {
    expect(genomicRoleBindings('sashimi', { coverage_dc_id: 'dc-2' })).toEqual([
      { chrom: 'chr', start: 'start', end: 'end' },
      { chrom: 'chromosome', start: 'position' },
    ]);
    expect(genomicRoleBindings('manhattan', {})).toHaveLength(1);
    expect(genomicRoleBindings('volcano', {})).toEqual([]);
  });
});

describe('regionFromFilters with a role map', () => {
  it('reads the brush pair through the role map', () => {
    const region = regionFromFilters(brush('chr7', 55_000_000, 56_000_000), {
      chrom: 'chr',
      start: 'pos',
    });
    expect(region).toEqual({ chrom: 'chr7', start: 55_000_000, end: 56_000_000 });
  });

  it('keeps the historical two-column call shape', () => {
    const region = regionFromFilters(brush('chr7', 1, 2), 'chr', 'pos');
    expect(region).toEqual({ chrom: 'chr7', start: 1, end: 2 });
  });

  it('unions a range on the start column with one on the end column', () => {
    const filters: InteractiveFilter[] = [
      { index: 'a', value: ['chr1'], source: 'genome_selection', column_name: 'chrom' },
      { index: 'b', value: [100, 200], source: 'genome_selection', column_name: 'start' },
      { index: 'c', value: [150, 400], source: 'genome_selection', column_name: 'end' },
    ] as any;
    expect(regionFromFilters(filters, { chrom: 'chrom', start: 'start', end: 'end' })).toEqual({
      chrom: 'chr1',
      start: 100,
      end: 400,
    });
  });

  it('is the whole contig when a chromosome is picked with no range', () => {
    const filters: InteractiveFilter[] = [
      { index: 'a', value: ['chr1'], source: 'genome_selection', column_name: 'chromosome' },
    ] as any;
    const region = regionFromFilters(filters, { chrom: 'chromosome', start: 'position' });
    expect(region?.chrom).toBe('chr1');
    expect(region?.end).toBe(Number.POSITIVE_INFINITY);
    expect(regionXRange(region)).toBeNull();
  });

  it('refuses to zoom on several chromosomes at once', () => {
    const filters: InteractiveFilter[] = [
      { index: 'a', value: ['chr1', 'chr7'], source: 'genome_selection', column_name: 'chrom' },
    ] as any;
    expect(regionFromFilters(filters, { chrom: 'chrom', start: 'start' })).toBeNull();
  });
});

describe('followedRegion', () => {
  it('reaches a coverage_track whose own columns the region names', () => {
    const filters = brush('chr7', 100, 900, 'chromosome', 'position');
    expect(followedRegion('coverage_track', 'cov-1', {}, filters)).toEqual({
      chrom: 'chr7',
      start: 100,
      end: 900,
    });
  });

  it('ignores a region published on some other collection columns', () => {
    const filters = brush('chr7', 100, 900, 'chr', 'pos');
    expect(followedRegion('coverage_track', 'cov-1', {}, filters)).toBeNull();
  });

  it('never follows the region the tile emitted itself', () => {
    const filters = brush('chr7', 100, 900);
    // `meta.index` is 'gv-1', so this is the emitter reading its own brush.
    expect(followedRegion('genome_view', 'gv-1', {}, filters)).toBeNull();
    // Any other tile on the same columns does follow it.
    expect(followedRegion('genome_view', 'gv-2', {}, filters)).toEqual({
      chrom: 'chr7',
      start: 100,
      end: 900,
    });
  });

  it('is null without filters and for a non-genomic kind', () => {
    expect(followedRegion('coverage_track', 'cov-1', {}, [])).toBeNull();
    expect(followedRegion('volcano', 'v-1', {}, brush('chr7', 1, 2))).toBeNull();
  });
});

describe('regionXRange', () => {
  it('is the finite window a renderer can clamp to', () => {
    expect(regionXRange({ chrom: 'chr7', start: 10, end: 20 })).toEqual([10, 20]);
    expect(regionXRange(null)).toBeNull();
    expect(regionXRange({ chrom: 'chr7', start: 20, end: 20 })).toBeNull();
  });
});
