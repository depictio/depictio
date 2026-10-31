import { describe, expect, it } from 'vitest';

import { approxSameWindow, windowFromDomain } from './viewWindowPublish';

const contigs = [
  { name: 'chr1', size: 1000 },
  { name: 'chr2', size: 500 },
];
const dom = (a: [string, number], b: [string, number]) => [
  { chrom: a[0], pos: a[1] },
  { chrom: b[0], pos: b[1] },
];

describe('windowFromDomain', () => {
  it('is the window on one contig, rounded outwards, 1-based and inclusive', () => {
    expect(windowFromDomain(dom(['chr1', 99.4], ['chr1', 200.2]), contigs)).toEqual({
      entity: 'chr1',
      start: 99,
      end: 201,
      entityAliases: ['1'],
    });
  });
  it('never starts below 1 or ends past the contig', () => {
    expect(windowFromDomain(dom(['chr2', 0], ['chr2', 800]), contigs)).toMatchObject({ start: 1, end: 500 });
    expect(windowFromDomain(dom(['chr2', 0], ['chr2', 800]), null)).toMatchObject({ end: 800 });
  });
  it('offers the chr-less contig name as an alias, and the prefixed one for a bare name', () => {
    expect(windowFromDomain(dom(['7', 1], ['7', 90]))?.entityAliases).toEqual(['chr7']);
  });
  it('is null across contigs (a genome-wide view), without extent, or unreadable', () => {
    expect(windowFromDomain(dom(['chr1', 10], ['chr2', 20]), contigs)).toBeNull();
    expect(windowFromDomain(dom(['chr1', 10], ['chr1', 10]), contigs)).toBeNull();
    expect(windowFromDomain(null)).toBeNull();
    expect(windowFromDomain([{ chrom: 'chr1', pos: 'x' }, { chrom: 'chr1', pos: 5 }])).toBeNull();
    expect(windowFromDomain([])).toBeNull();
  });
});

describe('approxSameWindow', () => {
  const w = { entity: 'chr1', start: 1000, end: 5000 };
  it('holds within a base or two, or 0.2% of the span', () => {
    expect(approxSameWindow(w, { entity: 'chr1', start: 1001, end: 4999 })).toBe(true);
    expect(approxSameWindow(w, { entity: 'chr1', start: 1008, end: 5000 })).toBe(true);
  });
  it('fails for a real move, another contig or a missing window', () => {
    expect(approxSameWindow(w, { entity: 'chr1', start: 1100, end: 5000 })).toBe(false);
    expect(approxSameWindow(w, { entity: 'chr2', start: 1000, end: 5000 })).toBe(false);
    expect(approxSameWindow(w, null)).toBe(false);
  });
});
