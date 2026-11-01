import { describe, expect, it } from 'vitest';

import { dataExtentView } from './dataExtent';

const contigs = [
  { name: 'chr1', size: 1_000_000 },
  { name: 'chr2', size: 500_000 },
];
const cols = { chr: 'chrom', pos: 'start', end: 'end' };

describe('dataExtentView', () => {
  it('keeps the whole genome for rows on several chromosomes', () => {
    const rows = [
      { chrom: 'chr1', start: 10, end: 20 },
      { chrom: 'chr2', start: 10, end: 20 },
    ];
    expect(dataExtentView(rows, cols, contigs)).toBeNull();
  });

  it('opens on the chromosome the rows spread over', () => {
    const rows = [
      { chrom: 'chr1', start: 100_000, end: 110_000 },
      { chrom: 'chr1', start: 800_000, end: 820_000 },
    ];
    expect(dataExtentView(rows, cols, contigs)).toEqual({ chrom: 'chr1', start: 0, end: 1_000_000 });
  });

  it('opens on the region of rows packed on a locus, with a margin', () => {
    const rows = [
      { chrom: 'chr1', start: 400_000, end: 410_000 },
      { chrom: 'chr1', start: 450_000, end: 500_000 },
    ];
    expect(dataExtentView(rows, cols, contigs)).toEqual({ chrom: 'chr1', start: 390_000, end: 510_000 });
  });

  it('has nothing to open on without rows', () => {
    expect(dataExtentView([], cols, contigs)).toBeNull();
    expect(dataExtentView(null, cols, contigs)).toBeNull();
  });
});
