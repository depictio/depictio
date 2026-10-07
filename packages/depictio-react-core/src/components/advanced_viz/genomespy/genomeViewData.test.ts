import { describe, expect, it, vi } from 'vitest';

import type { InteractiveFilter, StoredMetadata } from '../../../api';
import {
  genomePosFilterIndex,
  genomeRegionFilters,
  mergeFiltersBySource,
  regionFromFilters,
} from '../../../selection';
import { buildGenomeSpySpec, regionFromInterval } from './genomeSpySpec';
import type { GenomeViewConfig } from './genomeSpySpec';
import {
  filtersForGenomeViewFetch,
  loadGenomeViewRows,
  navigatorWindow,
  navigatorWindowFilters,
  ownRegion,
} from './genomeViewData';

const metadata = {
  index: 'gv-depth',
  wf_id: 'wf1',
  dc_id: 'dc1',
} as unknown as StoredMetadata;

const config: GenomeViewConfig = {
  chr_col: 'chrom',
  pos_col: 'start',
  score_col: 'coverage',
  end_col: 'end',
  sample_col: 'sample',
};

const serverRows = {
  chrom: ['chr1', 'chr1', 'chr2'],
  start: [0, 200, 0],
  end: [200, 400, 200],
  coverage: [10, 20, 5],
  sample: ['S1', 'S1', 'S2'],
};

function mockFetcher(rows = serverRows, degraded = false) {
  return vi.fn(async () => ({ rows, sampling: { degraded } }));
}

describe('filtersForGenomeViewFetch', () => {
  const others: InteractiveFilter[] = [
    { index: 'sidebar', value: ['S1'], column_name: 'sample' },
    { index: 'other-tile', value: ['chr1'], source: 'genome_selection', column_name: 'chrom' },
  ];

  it('strips this tile’s own pick and both halves of its own region', () => {
    const own = genomeRegionFilters(metadata, 'chrom', 'start', {
      chroms: ['chr1'],
      range: [0, 500],
    });
    const mine: InteractiveFilter[] = [
      ...own,
      { index: metadata.index, value: ['x'], source: 'scatter_selection', column_name: 'feature' },
    ];
    const out = filtersForGenomeViewFetch([...others, ...mine], metadata.index);
    expect(out).toEqual(others);
  });

  it('keeps another tile’s region, which is the whole point of the source', () => {
    const out = filtersForGenomeViewFetch(others, metadata.index);
    expect(out).toHaveLength(2);
  });
});

describe('loadGenomeViewRows', () => {
  it('asks for exactly the bound columns, in role order', async () => {
    const fetcher = mockFetcher();
    await loadGenomeViewRows(fetcher, { metadata, config, filters: [] });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const req = (fetcher.mock.calls as unknown as any[][])[0][0];
    expect(req.columns).toEqual(['chrom', 'start', 'coverage', 'end', 'sample']);
    expect(req.vizKind).toBe('genome_view');
    expect(req.roles).toEqual({ chr: 'chrom', pos: 'start', score: 'coverage' });
    expect(req.tail).toBeUndefined();
  });

  it('adds the selection column and the tail cut when the tile has them', async () => {
    const fetcher = mockFetcher();
    await loadGenomeViewRows(fetcher, {
      metadata,
      config: { ...config, score_threshold: 30 },
      filters: [],
      selectionColumn: 'peak_id',
    });
    const req = (fetcher.mock.calls as unknown as any[][])[0][0];
    expect(req.columns).toContain('peak_id');
    expect(req.tail).toEqual({ column: 'coverage', direction: 'high', threshold: 30 });
  });

  it('reports the server’s sampling flag', async () => {
    const res = await loadGenomeViewRows(mockFetcher(serverRows, true), {
      metadata,
      config,
      filters: [],
    });
    expect(res.estimated).toBe(true);
    expect(res.rows).toBe(serverRows);
  });

  it('refuses to fetch an unbound tile', async () => {
    const fetcher = mockFetcher();
    await expect(
      loadGenomeViewRows(fetcher, {
        metadata: { ...metadata, dc_id: undefined } as unknown as StoredMetadata,
        config,
        filters: [],
      }),
    ).rejects.toThrow(/missing data binding/);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('brush to dashboard filter, end to end', () => {
  it('turns a brushed interval into a chromosome value and a position range', async () => {
    const fetcher = mockFetcher();
    const { rows } = await loadGenomeViewRows(fetcher, { metadata, config, filters: [] });
    const built = buildGenomeSpySpec({
      rows,
      config,
      colors: { textColor: 't', gridColor: 'g', ruleColor: 'r', palette: ['c0', 'c1'] },
    });

    // chr1 is sized past its last interval end, so a brush inside it stays on
    // one contig.
    const chr1 = built.contigs[0];
    expect(chr1.name).toBe('chr1');
    const region = regionFromInterval(built.contigs, [50, 150])!;
    expect(region).toEqual({ chroms: ['chr1'], range: [50, 150] });

    const emitted = genomeRegionFilters(metadata, config.chr_col, config.pos_col, region);
    expect(emitted).toHaveLength(2);
    expect(emitted[0]).toMatchObject({
      index: 'gv-depth',
      source: 'genome_selection',
      column_name: 'chrom',
      interactive_component_type: 'MultiSelect',
      value: ['chr1'],
    });
    expect(emitted[1]).toMatchObject({
      index: genomePosFilterIndex('gv-depth'),
      source: 'genome_selection',
      column_name: 'start',
      interactive_component_type: 'RangeSlider',
      value: [50, 150],
    });
    // Both carry the emitting tile's collection, so the server's link resolver
    // can map them onto a second tile's collection.
    expect(emitted[0].metadata?.dc_id).toBe('dc1');
    expect(emitted[1].metadata?.dc_id).toBe('dc1');
  });

  it('coexists in the filter list and clears as a pair', () => {
    const region = { chroms: ['chr2'], range: [10, 90] as [number, number] };
    let filters: InteractiveFilter[] = [];
    for (const f of genomeRegionFilters(metadata, 'chrom', 'start', region)) {
      filters = mergeFiltersBySource(filters, f);
    }
    expect(filters).toHaveLength(2);

    // A second brush replaces both halves rather than stacking.
    for (const f of genomeRegionFilters(metadata, 'chrom', 'start', {
      chroms: ['chr1'],
      range: [0, 5],
    })) {
      filters = mergeFiltersBySource(filters, f);
    }
    expect(filters).toHaveLength(2);
    expect(filters.find((f) => f.column_name === 'chrom')?.value).toEqual(['chr1']);

    // Clearing the brush drops both.
    for (const f of genomeRegionFilters(metadata, 'chrom', 'start', null)) {
      filters = mergeFiltersBySource(filters, f);
    }
    expect(filters).toEqual([]);
  });

  it('drops the range for a multi-chromosome brush, keeping only the chromosomes', () => {
    const emitted = genomeRegionFilters(metadata, 'chrom', 'start', {
      chroms: ['chr1', 'chr2'],
      range: null,
    });
    expect(emitted[0].value).toEqual(['chr1', 'chr2']);
    expect(emitted[1].value).toEqual([]);
  });
});

describe('regionFromFilters (the following tile)', () => {
  it('reads back a region a sibling tile published', () => {
    const emitted = genomeRegionFilters(metadata, 'chrom', 'start', {
      chroms: ['chr7'],
      range: [1000, 2000],
    });
    expect(regionFromFilters(emitted, 'chrom', 'start')).toEqual({
      chrom: 'chr7',
      start: 1000,
      end: 2000,
    });
  });

  it('follows a plain sidebar multi-select on the same column, with no range', () => {
    const sidebar: InteractiveFilter[] = [
      { index: 'gv-f-chrom', value: ['chr7'], column_name: 'chrom' },
    ];
    expect(regionFromFilters(sidebar, 'chrom', 'start')).toEqual({
      chrom: 'chr7',
      start: 0,
      end: Number.POSITIVE_INFINITY,
    });
  });

  it('is null when the filters name several chromosomes or none', () => {
    expect(
      regionFromFilters(
        [{ index: 'a', value: ['chr1', 'chr2'], column_name: 'chrom' }],
        'chrom',
        'start',
      ),
    ).toBeNull();
    expect(regionFromFilters([], 'chrom', 'start')).toBeNull();
  });

  it('ignores a range on a column this tile does not use', () => {
    const filters: InteractiveFilter[] = [
      { index: 'a', value: ['chr1'], column_name: 'chrom' },
      { index: 'b', value: [5, 50], column_name: 'coverage' },
    ];
    expect(regionFromFilters(filters, 'chrom', 'start')).toEqual({
      chrom: 'chr1',
      start: 0,
      end: Number.POSITIVE_INFINITY,
    });
  });
});

describe('navigator window', () => {
  it('reads only the tile’s own region', () => {
    const own = genomeRegionFilters(metadata, 'chrom', 'start', {
      chroms: ['chr7'],
      range: [1_000_000, 1_400_000],
    });
    const foreign: InteractiveFilter[] = [
      { index: 'other', value: ['chr1'], source: 'genome_selection', column_name: 'chrom' },
    ];
    expect(ownRegion([...foreign, ...own], metadata.index, 'chrom', 'start')).toEqual({
      chrom: 'chr7',
      start: 1_000_000,
      end: 1_400_000,
    });
    expect(ownRegion(foreign, metadata.index, 'chrom', 'start')).toBeNull();
  });

  it('fetches the region’s whole chromosome', () => {
    expect(navigatorWindow({ chrom: 'chr7', start: 1_000_000, end: 1_400_000 })).toEqual({
      chroms: ['chr7'],
      range: null,
    });
    expect(navigatorWindow({ chrom: 'chr7', start: 0, end: Infinity })).toEqual({
      chroms: ['chr7'],
      range: null,
    });
    expect(navigatorWindow(null)).toBeNull();
  });

  it('rides the fetch on a private index, never the published one', async () => {
    const extra = navigatorWindowFilters(metadata, 'chrom', 'start', {
      chroms: ['chr1'],
      range: [0, 100],
    });
    expect(extra.map((f) => f.index)).toEqual([
      `${metadata.index}::window`,
      `${metadata.index}::window::pos`,
    ]);
    const fetcher = mockFetcher();
    await loadGenomeViewRows(fetcher, { metadata, config, filters: [], windowFilters: extra });
    const sent = (fetcher.mock.calls[0] as unknown as [{ filters: InteractiveFilter[] }])[0].filters;
    expect(sent).toEqual(extra);
    // The fetch-side strip of the tile's own region leaves the window alone.
    expect(filtersForGenomeViewFetch(extra, metadata.index)).toEqual(extra);
  });

  it('drops the empty position half of a chromosome-only window', () => {
    const extra = navigatorWindowFilters(metadata, 'chrom', 'start', { chroms: ['chr1'], range: null });
    expect(extra).toHaveLength(1);
  });
});
