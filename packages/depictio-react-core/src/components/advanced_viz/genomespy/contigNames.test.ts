import { describe, expect, it } from 'vitest';

import { renameToContigs } from './contigNames';

const CONTIGS = ['chr1', 'chr20', 'chrX', 'chrM'];

describe('renameToContigs', () => {
  it('spells Ensembl contigs as the assembly does', () => {
    const rows = [{ chrom: '20', pos: 5 }, { chrom: 'X', pos: 9 }];
    expect(renameToContigs(rows, 'chrom', CONTIGS)).toEqual([
      { chrom: 'chr20', pos: 5 },
      { chrom: 'chrX', pos: 9 },
    ]);
  });

  it('returns the same rows when every name already matches', () => {
    const rows = [{ chrom: 'chr1', pos: 1 }];
    expect(renameToContigs(rows, 'chrom', CONTIGS)).toBe(rows);
  });

  it('leaves out a contig the assembly does not have', () => {
    const rows = [{ chrom: 'KI270728.1', pos: 1 }, { chrom: '1', pos: 2 }];
    expect(renameToContigs(rows, 'chrom', CONTIGS)).toEqual([{ chrom: 'chr1', pos: 2 }]);
  });

  it('does nothing without an assembly', () => {
    const rows = [{ chrom: '20', pos: 1 }];
    expect(renameToContigs(rows, 'chrom', null)).toBe(rows);
  });
});
