import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearGeneAnnotationCache,
  decodeGeneAsset,
  geneAssetUrl,
  loadGeneAnnotation,
} from './geneAnnotations';

const payload = {
  assembly: 'hg38',
  source: 'GENCODE 47 basic annotation (Gencode_human), protein-coding genes',
  columns: ['name', 'chrom', 'start', 'end', 'strand'],
  genes: [
    ['OR4F5', 'chr1', 65418, 71585, '+'],
    ['TP53', 'chr17', 7668401, 7687550, '-'],
    ['BROKEN', 'chr1', 'x', 10, '+'],
  ],
};

describe('decodeGeneAsset', () => {
  it('reads the columnar payload by column name, not by position', () => {
    const out = decodeGeneAsset({ ...payload, columns: ['chrom', 'name', 'start', 'end', 'strand'],
      genes: [['chr1', 'OR4F5', 65418, 71585, '+']] })!;
    expect(out.genes[0]).toEqual({
      name: 'OR4F5',
      chrom: 'chr1',
      start: 65418,
      end: 71585,
      strand: '+',
    });
  });

  it('drops rows whose coordinates are not numbers', () => {
    const out = decodeGeneAsset(payload)!;
    expect(out.genes.map((g) => g.name)).toEqual(['OR4F5', 'TP53']);
    expect(out.assembly).toBe('hg38');
    expect(out.source).toContain('GENCODE');
  });

  it('returns null for anything that is not the asset shape', () => {
    expect(decodeGeneAsset(null)).toBeNull();
    expect(decodeGeneAsset({})).toBeNull();
    expect(decodeGeneAsset({ columns: ['name'], genes: [['a']] })).toBeNull();
  });
});

describe('geneAssetUrl', () => {
  it('hangs off the app base so the API serves it from dist/assets', () => {
    expect(geneAssetUrl('mm10')).toMatch(/assets\/genomes\/mm10\.genes\.json$/);
  });
});

describe('loadGeneAnnotation', () => {
  beforeEach(() => {
    clearGeneAnnotationCache();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    clearGeneAnnotationCache();
  });

  it('does not fetch at all for "none"', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    await expect(loadGeneAnnotation('none')).resolves.toBeNull();
    await expect(loadGeneAnnotation(null)).resolves.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('fetches once per assembly and memoises the decoded table', async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => payload }));
    vi.stubGlobal('fetch', fetchMock);
    const [a, b] = await Promise.all([loadGeneAnnotation('hg38'), loadGeneAnnotation('hg38')]);
    expect(a?.genes).toHaveLength(2);
    expect(b).toBe(a);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('resolves to null when the host does not serve the asset', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({}) })));
    await expect(loadGeneAnnotation('hg38')).resolves.toBeNull();
  });

  it('resolves to null when the fetch itself rejects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('offline');
      }),
    );
    await expect(loadGeneAnnotation('mm10')).resolves.toBeNull();
  });
});
