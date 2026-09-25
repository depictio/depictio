import { describe, expect, it } from 'vitest';

import type { GeneRow } from './genomeSpySpec';
import {
  POINT_WINDOW_BP,
  findGenes,
  formatLocus,
  geneWindow,
  parseCoordinate,
  parseLocusText,
  resolveContig,
  resolveLocus,
} from './locusParse';

const CONTIGS = ['chr1', 'chr7', 'chrX'];
const PLAIN_CONTIGS = ['1', '7', 'X'];
const GENES: GeneRow[] = [
  { name: 'TP53', chrom: 'chr17', start: 7_668_402, end: 7_687_550, strand: '-' },
  { name: 'TP53BP1', chrom: 'chr15', start: 43_403_057, end: 43_500_000, strand: '-' },
  { name: 'BRCA1', chrom: 'chr17', start: 43_044_295, end: 43_170_245, strand: '-' },
];

describe('parseCoordinate', () => {
  it('ignores the separators a reader pastes in', () => {
    expect(parseCoordinate('55,000,000')).toBe(55_000_000);
    expect(parseCoordinate('55 000 000')).toBe(55_000_000);
    expect(parseCoordinate('55_000_000')).toBe(55_000_000);
  });

  it('takes the units a locus is usually quoted in', () => {
    expect(parseCoordinate('55Mb')).toBe(55_000_000);
    expect(parseCoordinate('55.5mb')).toBe(55_500_000);
    expect(parseCoordinate('120kb')).toBe(120_000);
    expect(parseCoordinate('2k')).toBe(2_000);
  });

  it('is null for anything that is not a coordinate', () => {
    expect(parseCoordinate('TP53')).toBeNull();
    expect(parseCoordinate('')).toBeNull();
    expect(parseCoordinate('1e6')).toBeNull();
  });
});

describe('parseLocusText', () => {
  it('reads the canonical forms', () => {
    expect(parseLocusText('chr7:55,000,000-56,000,000')).toEqual({
      chrom: 'chr7',
      start: 55_000_000,
      end: 56_000_000,
    });
    expect(parseLocusText('chr7:55000000-56000000')).toEqual({
      chrom: 'chr7',
      start: 55_000_000,
      end: 56_000_000,
    });
    expect(parseLocusText('chr7:55000000..56000000')?.end).toBe(56_000_000);
  });

  it('opens a window around a single coordinate', () => {
    const parsed = parseLocusText('chr7:55,000,000');
    expect(parsed?.end! - parsed?.start!).toBe(POINT_WINDOW_BP);
    expect((parsed!.start! + parsed!.end!) / 2).toBe(55_000_000);
  });

  it('reads a bare contig as the whole contig', () => {
    expect(parseLocusText('chr7')).toEqual({ chrom: 'chr7', start: null, end: null });
    expect(parseLocusText('chr7:')).toEqual({ chrom: 'chr7', start: null, end: null });
  });

  it('orders a reversed interval', () => {
    expect(parseLocusText('chr7:56000000-55000000')).toEqual({
      chrom: 'chr7',
      start: 55_000_000,
      end: 56_000_000,
    });
  });

  it('is null for text that is not a locus', () => {
    expect(parseLocusText('chr7:not-a-number')).toBeNull();
    expect(parseLocusText('   ')).toBeNull();
  });
});

describe('resolveContig', () => {
  it('matches the data spelling, with or without the chr prefix', () => {
    expect(resolveContig('chr7', CONTIGS)).toBe('chr7');
    expect(resolveContig('7', CONTIGS)).toBe('chr7');
    expect(resolveContig('CHR7', CONTIGS)).toBe('chr7');
    expect(resolveContig('chr7', PLAIN_CONTIGS)).toBe('7');
    expect(resolveContig('chr9', CONTIGS)).toBeNull();
  });
});

describe('findGenes', () => {
  it('puts the exact match first, then prefixes', () => {
    expect(findGenes(GENES, 'TP53').map((g) => g.name)).toEqual(['TP53', 'TP53BP1']);
    expect(findGenes(GENES, 'tp53b').map((g) => g.name)).toEqual(['TP53BP1']);
  });

  it('is empty without a gene table or a query', () => {
    expect(findGenes(null, 'TP53')).toEqual([]);
    expect(findGenes(GENES, '')).toEqual([]);
  });
});

describe('geneWindow', () => {
  it('pads the gene span so its flanks stay visible', () => {
    const w = geneWindow(GENES[0]);
    expect(w.chrom).toBe('chr17');
    expect(w.start).toBeLessThan(GENES[0].start);
    expect(w.end).toBeGreaterThan(GENES[0].end);
  });
});

describe('resolveLocus', () => {
  it('resolves a locus onto the data own contig names', () => {
    expect(resolveLocus('7:1-2', CONTIGS, null)).toEqual({
      chrom: 'chr7',
      start: 1,
      end: 2,
      via: 'locus',
    });
  });

  it('falls back to a gene symbol, which names its own contig', () => {
    const out = resolveLocus('BRCA1', CONTIGS, GENES);
    expect(out?.via).toBe('gene');
    expect(out?.chrom).toBe('chr17');
    expect(out?.start).toBeLessThan(43_044_295);
  });

  it('is null when neither a contig nor a gene matches', () => {
    expect(resolveLocus('chr99:1-2', CONTIGS, GENES)).toBeNull();
    expect(resolveLocus('NOTAGENE', CONTIGS, GENES)).toBeNull();
  });
});

describe('formatLocus', () => {
  it('writes the region back the way it is typed', () => {
    expect(formatLocus('chr7', 55_000_000, 56_000_000)).toBe('chr7:55,000,000-56,000,000');
    expect(formatLocus('chr7', 0, Number.POSITIVE_INFINITY)).toBe('chr7');
    expect(formatLocus('chr7', null, null)).toBe('chr7');
  });
});
