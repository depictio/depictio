import { beforeEach, describe, expect, it, vi } from 'vitest';

const search = vi.fn();
vi.mock('../../api', () => ({ searchJBrowseGenes: (...a: unknown[]) => search(...a) }));

import { createViewState } from '@jbrowse/react-linear-genome-view2';

import DepictioGeneSearchPlugin, {
  DepictioGeneSearchAdapter,
  geneSearchAdapterConfigs,
  geneSearchConfigSchema,
  isGeneQuery,
  selectHits,
} from './geneSearch';

const hits = [
  { label: 'BCR', locus: 'chr22:23180509-23318037' },
  { label: 'BCRP1', locus: 'chr22:1-2' },
];

describe('isGeneQuery', () => {
  it('accepts gene names and rejects loci and free text', () => {
    expect(isGeneQuery('BCR')).toBe(true);
    expect(isGeneQuery('HLA-A')).toBe(true);
    expect(isGeneQuery('chr4:1-100')).toBe(false);
    expect(isGeneQuery('a')).toBe(false);
    expect(isGeneQuery('two words')).toBe(false);
    expect(isGeneQuery('x'.repeat(65))).toBe(false);
  });
});

describe('selectHits', () => {
  it('keeps every hit for a prefix search', () => {
    expect(selectHits(hits, 'bc', 'prefix')).toHaveLength(2);
  });
  it('keeps the exact match for an exact search, else all', () => {
    expect(selectHits(hits, 'bcr', 'exact').map((h) => h.label)).toEqual(['BCR']);
    expect(selectHits(hits, 'zzz', 'exact')).toHaveLength(2);
  });
});

describe('DepictioGeneSearchAdapter', () => {
  beforeEach(() => {
    search.mockReset();
  });
  const adapter = () =>
    new DepictioGeneSearchAdapter(
      geneSearchConfigSchema.create(geneSearchAdapterConfigs('hg38')[0]),
    );

  it('answers a gene name with results that carry the locus', async () => {
    search.mockResolvedValue(hits);
    const out = await adapter().searchIndex({ queryString: 'BCR', searchType: 'exact' });
    expect(search).toHaveBeenCalledWith('hg38', 'BCR', 10);
    expect(out).toHaveLength(1);
    expect(out[0].getLocation()).toBe('chr22:23180509-23318037');
    expect(out[0].getLabel()).toBe('BCR');
  });
  it('does not call the backend for something that is not a gene name', async () => {
    expect(await adapter().searchIndex({ queryString: 'chr4:1-100' })).toEqual([]);
    expect(search).not.toHaveBeenCalled();
  });
  it('answers nothing when the lookup fails', async () => {
    search.mockRejectedValue(new Error('offline'));
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(await adapter().searchIndex({ queryString: 'TP53x' })).toEqual([]);
    warn.mockRestore();
  });
});

describe('geneSearchAdapterConfigs', () => {
  it('covers one assembly', () => {
    expect(geneSearchAdapterConfigs('hg19')).toEqual([
      {
        type: 'DepictioGeneSearchAdapter',
        textSearchAdapterId: 'depictio-gene-search-hg19',
        assemblyNames: ['hg19'],
        assemblyName: 'hg19',
      },
    ]);
  });
});

describe('plugin wiring', () => {
  it("is reached by the view's own text search manager (what the locus box calls)", async () => {
    search.mockReset();
    search.mockResolvedValue([{ label: 'BCR', locus: 'chr22:23180509-23318037' }]);
    const sequence = {
      type: 'ReferenceSequenceTrack',
      trackId: 'ref',
      adapter: {
        type: 'FromConfigSequenceAdapter',
        features: [{ refName: 'chr22', uniqueId: 'a', start: 0, end: 10, seq: 'ACGTACGTAC' }],
      },
    };
    const state = createViewState({
      assembly: { name: 'hg38', sequence },
      tracks: [],
      plugins: [DepictioGeneSearchPlugin],
      aggregateTextSearchAdapters: geneSearchAdapterConfigs('hg38'),
    } as never);
    const { textSearchManager } = state as unknown as {
      textSearchManager: {
        search: (
          args: unknown,
          scope: unknown,
          rank: (r: unknown) => unknown,
        ) => Promise<Array<{ getLocation: () => string }>>;
      };
    };
    const found = await textSearchManager.search(
      { queryString: 'BCR', searchType: 'exact' },
      { assemblyName: 'hg38' },
      (r) => r,
    );
    expect(found.map((r) => r.getLocation())).toEqual(['chr22:23180509-23318037']);
  });
});
