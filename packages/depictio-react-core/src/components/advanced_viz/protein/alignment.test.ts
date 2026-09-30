import { describe, expect, it } from 'vitest';

import {
  chainLayoutLength,
  chainRangeToConcat,
  chainStarts,
  chainToConcat,
  concatRangeToChain,
  concatToChain,
  parseChainLayout,
  columnConservation,
  columnProfiles,
  columnRangeToResidueRange,
  normaliseRows,
  orderMsaRows,
  percentIdentity,
  referenceColumnMap,
  referenceIndexOf,
  residueRangeToColumnRange,
} from './alignment';

describe('referenceColumnMap', () => {
  it('numbers reference residues and skips its gap columns', () => {
    const map = referenceColumnMap('M-KV--L');
    expect(Array.from(map.colToRes)).toEqual([1, -1, 2, 3, -1, -1, 4]);
    expect(Array.from(map.resToCol)).toEqual([0, 2, 3, 6]);
    expect(map.residueCount).toBe(4);
  });

  it('honours a first residue number other than 1', () => {
    const map = referenceColumnMap('AB', 10);
    expect(Array.from(map.colToRes)).toEqual([10, 11]);
  });
});

describe('column <-> residue ranges', () => {
  const map = referenceColumnMap('M-KV--L');

  it('reports a column brush in reference residues, gaps skipped', () => {
    expect(columnRangeToResidueRange(map, 1, 5)).toEqual({ start: 2, end: 3 });
    expect(columnRangeToResidueRange(map, 6, 0)).toEqual({ start: 1, end: 4 });
  });

  it('returns null for a brush over reference gaps only', () => {
    expect(columnRangeToResidueRange(map, 4, 5)).toBeNull();
  });

  it('maps a residue range back to its columns, clamped to the reference', () => {
    expect(residueRangeToColumnRange(map, { start: 2, end: 4 })).toEqual([2, 6]);
    expect(residueRangeToColumnRange(map, { start: 3 })).toEqual([3, 3]);
    expect(residueRangeToColumnRange(map, { start: 0, end: 100 })).toEqual([0, 6]);
    expect(residueRangeToColumnRange(map, { start: 50, end: 60 })).toBeNull();
  });
});

describe('columnProfiles and conservation', () => {
  const seqs = ['AKL', 'AKV', 'ARI', 'A--'];
  const profiles = columnProfiles(seqs);

  it('counts residues and finds the consensus', () => {
    expect(profiles[0]).toMatchObject({ nonGap: 4, consensus: 'A', consensusFraction: 1 });
    expect(profiles[1].consensus).toBe('K');
    expect(profiles[1].consensusFraction).toBeCloseTo(2 / 3);
  });

  it('scores a fully conserved column 1 and a gappy variable one lower', () => {
    expect(columnConservation(profiles[0], seqs.length)).toBeCloseTo(1);
    const variable = columnConservation(profiles[2], seqs.length);
    expect(variable).toBeGreaterThan(0);
    expect(variable).toBeLessThan(columnConservation(profiles[1], seqs.length));
  });

  it('gives an all-gap column no consensus and no conservation', () => {
    const p = columnProfiles(['-', '.'])[0];
    expect(p.consensus).toBeNull();
    expect(columnConservation(p, 2)).toBe(0);
  });
});

describe('percentIdentity', () => {
  it('compares shared residue columns only, case-insensitive', () => {
    expect(percentIdentity('AK-L', 'AKVI')).toBeCloseTo(2 / 3);
    expect(percentIdentity('ak', 'AK')).toBe(1);
    expect(percentIdentity('--', 'AK')).toBeNull();
  });
});

describe('row order', () => {
  const rows = [
    { seqId: 'b', sequence: 'AKLI', rank: 2 },
    { seqId: 'ref', sequence: 'AKVI', rank: 0 },
    { seqId: 'a', sequence: 'AKVL', rank: 1 },
    { seqId: 'c', sequence: 'GGGG', rank: 3, identity: 0.9 },
  ];

  it('finds the rank 0 row as the reference, else the first', () => {
    expect(referenceIndexOf(rows)).toBe(1);
    expect(referenceIndexOf([{ seqId: 'x', sequence: 'A' }])).toBe(0);
  });

  it('keeps the reference first and sorts the others', () => {
    expect(orderMsaRows(rows, 'rank', 10).rows.map((r) => r.seqId)).toEqual(['ref', 'a', 'b', 'c']);
    expect(orderMsaRows(rows, 'input', 10).rows.map((r) => r.seqId)).toEqual(['ref', 'b', 'a', 'c']);
    // Identity from the table wins over the computed one (c says 0.9).
    expect(orderMsaRows(rows, 'identity', 10).rows.map((r) => r.seqId)).toEqual(['ref', 'c', 'b', 'a']);
  });

  it('caps the rows and keeps the reference', () => {
    const out = orderMsaRows(rows, 'rank', 2);
    expect(out.rows.map((r) => r.seqId)).toEqual(['ref', 'a']);
    expect(out.total).toBe(4);
  });

  it('pads ragged rows and says so', () => {
    const out = normaliseRows([
      { seqId: 'x', sequence: 'AK' },
      { seqId: 'y', sequence: 'AKV' },
    ]);
    expect(out.width).toBe(3);
    expect(out.ragged).toBe(true);
    expect(out.rows[0].sequence).toBe('AK-');
  });
});

describe('multi-chain references', () => {
  // ESMFold style: chain B numbered on from chain A.
  const esm = parseChainLayout('A:1-4,B:5-7')!;
  // Per-chain numbering: both chains from 1.
  const own = parseChainLayout('A:4; B:3')!;

  it('parses both layout spellings and rejects junk', () => {
    expect(esm).toEqual([
      { chain: 'A', first: 1, last: 4 },
      { chain: 'B', first: 5, last: 7 },
    ]);
    expect(own[1]).toEqual({ chain: 'B', first: 1, last: 3 });
    expect(chainLayoutLength(own)).toBe(7);
    expect(parseChainLayout('A-4')).toBeNull();
    expect(parseChainLayout('A:5-2')).toBeNull();
    expect(parseChainLayout('')).toBeNull();
  });

  it('maps concatenated residues to chain numbering and back', () => {
    expect(concatToChain(6, own)).toEqual({ chain: 'B', position: 2 });
    expect(concatToChain(6, esm)).toEqual({ chain: 'B', position: 6 });
    expect(concatToChain(9, own)).toBeNull();
    expect(chainToConcat('B', 2, own)).toBe(6);
    expect(chainToConcat(null, 2, own)).toBe(2);
    expect(chainToConcat('B', 9, own)).toBeNull();
  });

  it('clamps a brush across a boundary to the chain holding most of it', () => {
    expect(concatRangeToChain({ start: 3, end: 7 }, own)).toEqual({ chain: 'B', start: 1, end: 3 });
    expect(concatRangeToChain({ start: 2, end: 5 }, esm)).toEqual({ chain: 'A', start: 2, end: 4 });
    expect(concatRangeToChain({ start: 20, end: 30 }, own)).toBeNull();
  });

  it('places a chain range on the concatenated reference', () => {
    expect(chainRangeToConcat('B', { start: 2, end: 9 }, own)).toEqual({ start: 6, end: 7 });
    expect(chainRangeToConcat('B', { start: 6 }, esm)).toEqual({ start: 6, end: 6 });
    expect(chainStarts(own)).toEqual([
      { chain: 'A', offset: 1 },
      { chain: 'B', offset: 5 },
    ]);
  });
});
