import { describe, expect, it } from 'vitest';

import {
  contigSpellings,
  genomicFromRecord,
  genomicFromRowByName,
  locusOfInterval,
  hoverInterval,
  nearestGenomicPoint,
  pixelsToBp,
  recordMatches,
  rowMatcher,
  sameContig,
  valuesEqual,
} from './genomicHover';

describe('sameContig', () => {
  it('ignores case and the chr prefix', () => {
    expect(sameContig('chr8', '8')).toBe(true);
    expect(sameContig('Chr8', 'chr8')).toBe(true);
    expect(sameContig('chr8', 'chr9')).toBe(false);
  });
  it('honours the aliases of the first name', () => {
    expect(sameContig('NC_000008.11', 'chr8', ['chr8', '8'])).toBe(true);
    expect(sameContig('NC_000008.11', 'chr9', ['chr8'])).toBe(false);
  });
  it('is false for an empty name', () => {
    expect(sameContig('', 'chr1')).toBe(false);
    expect(sameContig('chr1', null)).toBe(false);
  });
});

describe('valuesEqual', () => {
  it('treats a number and its string as one value', () => {
    expect(valuesEqual(100, '100')).toBe(true);
    expect(valuesEqual('100', 100)).toBe(true);
    expect(valuesEqual(1.5, ' 1.5 ')).toBe(true);
    expect(valuesEqual(100, '101')).toBe(false);
  });
  it('keeps strings case-sensitive and non-numeric strings apart', () => {
    expect(valuesEqual('A', 'a')).toBe(false);
    expect(valuesEqual('rs1', 'rs1')).toBe(true);
    expect(valuesEqual('abc', 5)).toBe(false);
  });
  it('lets empty values equal nothing, themselves included', () => {
    expect(valuesEqual(null, null)).toBe(false);
    expect(valuesEqual('', '')).toBe(false);
    expect(valuesEqual(undefined, 0)).toBe(false);
  });
});

describe('recordMatches', () => {
  const row = { chrom: 'chr1', start: 100, name: 'peak1', score: 7 };

  it('matches on every shared column, coercing numbers', () => {
    expect(recordMatches({ chrom: 'chr1', start: '100' }, row)).toBe(true);
    expect(recordMatches({ chrom: 'chr1', start: 101 }, row)).toBe(false);
  });
  it('ignores columns the row lacks and needs at least one shared column', () => {
    expect(recordMatches({ chrom: 'chr1', extra: 'x' }, row)).toBe(true);
    expect(recordMatches({ extra: 'x' }, row)).toBe(false);
    expect(recordMatches({}, row)).toBe(false);
  });
  it('skips columns the record leaves empty', () => {
    expect(recordMatches({ chrom: 'chr1', name: null, score: '' }, row)).toBe(true);
    expect(recordMatches({ name: null }, row)).toBe(false);
  });
  it('restricts to the allowed columns when given', () => {
    expect(recordMatches({ chrom: 'chr1', start: 5 }, row, ['chrom'])).toBe(true);
    expect(recordMatches({ start: 5 }, row, ['chrom'])).toBe(false);
  });
  it('matches contig columns across spellings and aliases', () => {
    expect(recordMatches({ chrom: '1', start: 100 }, row)).toBe(true);
    expect(recordMatches({ chrom: 'NC_000001.11', start: 100 }, row, undefined, ['chr1'])).toBe(true);
    expect(recordMatches({ chrom: 'chr2', start: 100 }, row)).toBe(false);
    // Only contig columns get the tolerance.
    expect(recordMatches({ name: 'PEAK1' }, row)).toBe(false);
  });
});

describe('genomicFromRecord / hoverInterval', () => {
  it('reads the interval through the caller\'s own columns', () => {
    expect(genomicFromRecord({ c: 'chr2', p: '40' }, 'c', 'p')).toEqual({
      refName: 'chr2',
      start: 40,
      end: 40,
    });
    expect(genomicFromRecord({ c: 'chr2', p: 40, e: 90 }, 'c', 'p', 'e')).toEqual({
      refName: 'chr2',
      start: 40,
      end: 90,
    });
  });
  it('is null without a contig, a numeric position or the columns', () => {
    expect(genomicFromRecord({ p: 40 }, 'c', 'p')).toBeNull();
    expect(genomicFromRecord({ c: 'chr1', p: 'x' }, 'c', 'p')).toBeNull();
    expect(genomicFromRecord({ c: 'chr1', p: 1 }, null, 'p')).toBeNull();
    expect(genomicFromRecord(null, 'c', 'p')).toBeNull();
  });
  it('prefers the event\'s genomic interval over its record', () => {
    const ev = {
      sourceIndex: 'jb',
      start: 5,
      genomic: { refName: 'chr3', start: 9, end: 5 },
      record: { c: 'chr1', p: 1 },
    };
    expect(hoverInterval(ev, 'c', 'p')).toEqual({ refName: 'chr3', start: 5, end: 9 });
    expect(hoverInterval({ ...ev, genomic: undefined }, 'c', 'p')).toEqual({
      refName: 'chr1',
      start: 1,
      end: 1,
    });
    expect(hoverInterval({ sourceIndex: 'x', start: 1 }, 'c', 'p')).toBeNull();
  });
});

describe('pixelsToBp', () => {
  it('scales the pixel tolerance by the visible range', () => {
    expect(pixelsToBp(6, [0, 1000], 500)).toBe(12);
    expect(pixelsToBp(6, [1000, 0], 500)).toBe(12);
  });
  it('is zero when the range or width is unknown', () => {
    expect(pixelsToBp(6, null, 500)).toBe(0);
    expect(pixelsToBp(6, [0, 100], 0)).toBe(0);
    expect(pixelsToBp(6, [0, 100], undefined)).toBe(0);
  });
});

describe('nearestGenomicPoint', () => {
  const points = {
    chroms: ['chr1', 'chr1', 'chr1', 'chr2', 'chr2'],
    positions: [100, 200, 205, 200, 900],
    keys: ['a', 'b', 'c', 'd', 'e'],
  };

  it('finds the point inside the interval on the same contig', () => {
    expect(nearestGenomicPoint(points, { refName: 'chr1', start: 195, end: 210 })).toBe(1);
  });
  it('takes the one nearest the midpoint among several inside', () => {
    expect(nearestGenomicPoint(points, { refName: 'chr1', start: 195, end: 215 })).toBe(2);
  });
  it('widens the interval by the tolerance and no further', () => {
    const target = { refName: 'chr1', start: 210, end: 210 };
    expect(nearestGenomicPoint(points, target, { toleranceBp: 4 })).toBe(-1);
    expect(nearestGenomicPoint(points, target, { toleranceBp: 5 })).toBe(2);
  });
  it('only considers the target contig, aliases and prefix tolerated', () => {
    expect(nearestGenomicPoint(points, { refName: '2', start: 200, end: 200 })).toBe(3);
    expect(
      nearestGenomicPoint(points, { refName: 'NC_2', start: 900, end: 900, aliases: ['chr2'] }),
    ).toBe(4);
    expect(nearestGenomicPoint(points, { refName: 'chr3', start: 200, end: 200 })).toBe(-1);
  });
  it('lets a matching row key win over position, on the target contig', () => {
    const target = { refName: 'chr1', start: 100, end: 100 };
    expect(nearestGenomicPoint(points, target, { rowKeys: ['c'] })).toBe(2);
    // A key on another contig does not pull the ring there.
    expect(nearestGenomicPoint(points, target, { rowKeys: ['d'] })).toBe(0);
  });
  it('uses row keys alone when there is no interval', () => {
    expect(nearestGenomicPoint(points, null, { rowKeys: ['e'] })).toBe(4);
    expect(nearestGenomicPoint(points, null, { rowKeys: ['zzz'] })).toBe(-1);
    expect(nearestGenomicPoint(points, null)).toBe(-1);
  });
  it('is -1 when nothing is within reach', () => {
    expect(nearestGenomicPoint(points, { refName: 'chr1', start: 5000, end: 5000 })).toBe(-1);
  });
});

describe('rowMatcher', () => {
  it('is null for an event a table cannot compare', () => {
    expect(rowMatcher(null, 'id')).toBeNull();
    expect(rowMatcher({ sourceIndex: 'p', start: 4 }, 'id')).toBeNull();
    expect(rowMatcher({ sourceIndex: 'p', start: 4, rowKeys: ['x'] }, undefined)).toBeNull();
  });
  it('matches the selection column against the row keys', () => {
    const m = rowMatcher({ sourceIndex: 'p', start: 0, rowKeys: ['v2', 'v9'] }, 'id');
    expect(m?.({ id: 'v2' })).toBe(true);
    expect(m?.({ id: 'v3' })).toBe(false);
    expect(m?.({ other: 'v2' })).toBe(false);
  });
  it('matches a numeric selection value against a string key', () => {
    const m = rowMatcher({ sourceIndex: 'p', start: 0, rowKeys: ['12'] }, 'id');
    expect(m?.({ id: 12 })).toBe(true);
  });
  it('matches the record on shared columns, with the event\'s aliases', () => {
    const m = rowMatcher(
      {
        sourceIndex: 'jb',
        start: 100,
        genomic: { refName: 'NC_1', start: 100, end: 100, aliases: ['chr1'] },
        record: { chrom: 'NC_1', start: 100 },
      },
      undefined,
    );
    expect(m?.({ chrom: 'chr1', start: '100', name: 'x' })).toBe(true);
    expect(m?.({ chrom: 'chr1', start: 101 })).toBe(false);
    // A table without the record's columns ignores the event.
    expect(m?.({ sample: 's1' })).toBe(false);
  });
});

describe('contigSpellings', () => {
  it('gives the spelling with the other chr prefix', () => {
    expect(contigSpellings('chr8')).toEqual(['8']);
    expect(contigSpellings('8')).toEqual(['chr8']);
    expect(contigSpellings('')).toBeUndefined();
    expect(contigSpellings(null)).toBeUndefined();
  });
});

describe('genomicFromRowByName', () => {
  it('reads a contig, a position and an optional end by the usual column names', () => {
    expect(genomicFromRowByName({ gene: 'TP53', chrom: 'chr17', pos: '7675000' })).toEqual({
      refName: 'chr17',
      start: 7675000,
      end: 7675000,
    });
    expect(genomicFromRowByName({ Chromosome: '2', Start: 10, End: 50 })).toEqual({
      refName: '2',
      start: 10,
      end: 50,
    });
  });
  it('falls back to feature-prefixed bounds, pairing the end by prefix', () => {
    expect(
      genomicFromRowByName({ chrom: '10', orf_start: 100, cds_end: 900, orf_end: 400 }),
    ).toEqual({ refName: '10', start: 100, end: 400 });
  });
  it('prefers a plain position over a prefixed one', () => {
    expect(genomicFromRowByName({ chrom: '1', peak_start: 5, start: 10, end: 20 })).toEqual({
      refName: '1',
      start: 10,
      end: 20,
    });
  });
  it('is null without a contig and a numeric position', () => {
    expect(genomicFromRowByName({ gene: 'TP53', score: 3 })).toBeNull();
    expect(genomicFromRowByName({ chrom: 'chr1', pos: 'n/a' })).toBeNull();
    expect(genomicFromRowByName({ chrom: '', pos: 5 })).toBeNull();
    expect(genomicFromRowByName(null)).toBeNull();
  });
});

describe('locusOfInterval', () => {
  it('pads a single position on both sides and never goes below 1', () => {
    expect(locusOfInterval({ refName: 'chr8', start: 1000, end: 1000 })).toBe('chr8:500-1500');
    expect(locusOfInterval({ refName: 'chr8', start: 100, end: 100 })).toBe('chr8:1-600');
  });
  it('gives a span a margin of a tenth of its length, at least the pad', () => {
    expect(locusOfInterval({ refName: 'chr8', start: 10_000, end: 20_000 })).toBe('chr8:9000-21000');
    expect(locusOfInterval({ refName: 'chr8', start: 10_000, end: 10_100 })).toBe('chr8:9500-10600');
  });
  it('is null for a missing contig or a non finite bound', () => {
    expect(locusOfInterval(null)).toBeNull();
    expect(locusOfInterval({ refName: '', start: 1, end: 2 })).toBeNull();
    expect(locusOfInterval({ refName: 'c', start: Number.NaN, end: 2 })).toBeNull();
  });
});
