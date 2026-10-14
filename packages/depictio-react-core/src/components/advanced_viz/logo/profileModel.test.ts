import { describe, expect, it } from 'vitest';

import { CLUSTAL_COLOURS } from '../protein/residueColours';
import { AMINO_ORDER, BACKGROUND_AMINO } from './heights';
import {
  emissionColumnProfile,
  letterColours,
  profileFromMsa,
  profileFromRows,
  residueRangeOfStates,
  sortLetters,
  stateColumnLookup,
  stateSpanOfRange,
  topLetters,
  type ProfileColumns,
} from './profileModel';

const COLS: ProfileColumns = {
  entity: 'entity',
  position: 'position',
  model: 'hmm_name',
  state: 'hmm_position',
  letter: 'hmm_letter',
  emission: 'emission',
  insertProb: 'insert_prob',
  insertLength: 'insert_length',
  occupancy: 'occupancy',
  consensus: 'consensus',
  rf: 'rf',
  cs: 'cs',
};

/** A long table as `profile_frame` writes it: one row per (state, letter). */
function longTable(
  models: { name: string; entity: string; letters: string; states: number[][]; positions: (number | null)[] }[],
): Record<string, unknown[]> {
  const out: Record<string, unknown[]> = {};
  for (const key of Object.values(COLS)) if (key) out[key] = [];
  for (const m of models) {
    m.states.forEach((row, i) => {
      m.letters.split('').forEach((letter, a) => {
        out.entity.push(m.entity);
        out.position.push(m.positions[i]);
        out.hmm_name.push(m.name);
        out.hmm_position.push(i + 1);
        out.hmm_letter.push(letter);
        out.emission.push(row[a]);
        out.insert_prob.push(i === m.states.length - 1 ? 0 : 0.1 * (i + 1));
        out.insert_length.push(i === m.states.length - 1 ? 0 : 1.5);
        out.occupancy.push(1 - 0.05 * i);
        out.consensus.push('A');
        out.rf.push(null);
        out.cs.push(null);
      });
    });
  }
  return out;
}

describe('profileFromRows (hmm mode)', () => {
  const frame = longTable([
    {
      name: 'FAM1',
      entity: 'P1',
      letters: 'ACGT',
      states: [
        [0.7, 0.1, 0.1, 0.1],
        [0.25, 0.25, 0.25, 0.25],
        [0, 0, 1, 0],
      ],
      positions: [11, null, 12],
    },
    {
      name: 'FAM2',
      entity: 'P2',
      letters: 'ACGT',
      states: [[1, 0, 0, 0]],
      positions: [5],
    },
  ]);

  it('reads one model: states, letters, emissions and per-state lanes', () => {
    const p = profileFromRows(frame, COLS, 'FAM1')!;
    expect(p.source).toBe('hmm');
    expect(p.model).toBe('FAM1');
    expect(p.entity).toBe('P1');
    expect(p.alphabet).toBe('nucleic');
    expect(p.letters).toEqual(['A', 'C', 'G', 'T']);
    expect(p.background).toEqual([0.25, 0.25, 0.25, 0.25]);
    expect(p.states).toEqual([1, 2, 3]);
    expect(p.positions).toEqual([11, null, 12]);
    expect(Array.from(p.emissions.subarray(8, 12))).toEqual([0, 0, 1, 0]);
    expect(p.insertProb).toEqual([0.1, 0.2, 0]);
    expect(p.insertLength).toEqual([1.5, 1.5, 0]);
    expect(p.occupancy?.[2]).toBeCloseTo(0.9);
    expect(p.consensus).toEqual(['A', 'A', 'A']);
    // All-null annotation columns are no lane at all.
    expect(p.rf).toBeNull();
    expect(p.cs).toBeNull();
  });

  it('keeps every row when the frame has no model column', () => {
    const { hmm_name: _drop, ...rest } = frame;
    const p = profileFromRows(rest, COLS, 'FAM2')!;
    // Both models' rows, merged by state number: 3 states.
    expect(p.states).toEqual([1, 2, 3]);
  });

  it('reads the model name from the rows when none is given', () => {
    const scoped = profileFromRows(frame, { ...COLS }, null)!;
    expect(scoped.model).toBe('FAM1');
  });

  it('orders amino letters the HMMER way, whatever the row order', () => {
    const letters = 'YWVTSRQPNMLKIHGFEDCA';
    const amino = longTable([
      { name: 'M', entity: 'E', letters, states: [letters.split('').map(() => 0.05)], positions: [1] },
    ]);
    const p = profileFromRows(amino, COLS, 'M')!;
    expect(p.alphabet).toBe('amino');
    expect(p.letters.join('')).toBe(AMINO_ORDER);
    expect(p.background[0]).toBe(BACKGROUND_AMINO.A);
  });

  it('is null without usable rows', () => {
    expect(profileFromRows(null, COLS, null)).toBeNull();
    expect(profileFromRows({}, COLS, null)).toBeNull();
    expect(profileFromRows(frame, COLS, 'NOPE')).toBeNull();
  });

  it('treats a missing optional column as no lane', () => {
    const p = profileFromRows(frame, { ...COLS, insertProb: null, occupancy: 'absent' }, 'FAM1')!;
    expect(p.insertProb).toBeNull();
    expect(p.occupancy).toBeNull();
  });
});

describe('profileFromMsa (msa mode)', () => {
  // Reference (rank 0) has a gap at column 3 (0-based): an insert column.
  //   col:  0 1 2 3 4
  //   ref:  A C D - E      match states 1..4 at columns 0,1,2,4
  //   s1:   A C D K E      inserts one residue after state 3
  //   s2:   A - D - E      deletes state 2
  //   s3:   G C E k Q      inserts (lower case) after state 3
  const rows = [
    { seqId: 's1', sequence: 'ACDKE', rank: 1 },
    { seqId: 'ref', sequence: 'ACD-E', rank: 0 },
    { seqId: 's2', sequence: 'A-D-E', rank: 2 },
    { seqId: 's3', sequence: 'GCEkQ', rank: 3 },
  ];

  it('makes one state per reference residue, numbered in the reference', () => {
    const p = profileFromMsa(rows, { entity: 'fam' })!;
    expect(p.source).toBe('msa');
    expect(p.entity).toBe('fam');
    expect(p.model).toBe('fam');
    expect(p.alphabet).toBe('amino');
    expect(p.letters.join('')).toBe(AMINO_ORDER);
    expect(p.states).toEqual([1, 2, 3, 4]);
    expect(p.positions).toEqual([1, 2, 3, 4]);
    expect(p.sequences).toBe(4);
    expect(p.rf).toEqual(['A', 'C', 'D', 'E']);
    expect(p.cs).toBeNull();
  });

  it('counts emissions over the residues of each match column', () => {
    const p = profileFromMsa(rows, { entity: 'fam' })!;
    const k = p.letters.length;
    const at = (i: number, l: string) => p.emissions[i * k + p.letters.indexOf(l)];
    expect(at(0, 'A')).toBeCloseTo(0.75);
    expect(at(0, 'G')).toBeCloseTo(0.25);
    // State 2: three residues (s2 deletes it), all C.
    expect(at(1, 'C')).toBe(1);
    expect(at(2, 'D')).toBeCloseTo(0.75);
    expect(at(3, 'Q')).toBeCloseTo(0.25);
    expect(p.consensus).toEqual(['A', 'C', 'D', 'E']);
  });

  it('derives occupancy, insert probability and insert length from the gaps', () => {
    const p = profileFromMsa(rows, { entity: 'fam' })!;
    expect(p.occupancy).toEqual([1, 0.75, 1, 1]);
    // After state 3, 2 of the 4 rows that hold it insert one residue.
    expect(p.insertProb).toEqual([0, 0, 0.5, 0]);
    expect(p.insertLength).toEqual([null, null, 1, 0]);
  });

  it('lower-cases a consensus below one half', () => {
    const p = profileFromMsa(
      [
        { seqId: 'r', sequence: 'A', rank: 0 },
        { seqId: 'a', sequence: 'C' },
        { seqId: 'b', sequence: 'D' },
      ],
      { entity: 'x' },
    )!;
    expect(p.consensus).toEqual(['a']);
  });

  it('reads a nucleic alignment with a uniform background', () => {
    const p = profileFromMsa(
      [
        { seqId: 'r', sequence: 'ACGU', rank: 0 },
        { seqId: 'b', sequence: 'ACGU' },
      ],
      { entity: 'rna', model: 'RF1' },
    )!;
    expect(p.alphabet).toBe('nucleic');
    expect(p.letters).toEqual(['A', 'C', 'G', 'U']);
    expect(p.background).toEqual([0.25, 0.25, 0.25, 0.25]);
    expect(p.model).toBe('RF1');
  });

  it('is null for an empty alignment or an all-gap reference', () => {
    expect(profileFromMsa([], { entity: 'x' })).toBeNull();
    expect(profileFromMsa([{ seqId: 'r', sequence: '---', rank: 0 }], { entity: 'x' })).toBeNull();
  });
});

describe('residue and state spans', () => {
  const positions = [10, 11, null, 12, null, 13];

  it('takes min..max of the non-null positions a brush covers', () => {
    expect(residueRangeOfStates(positions, 1, 3)).toEqual({ start: 11, end: 12 });
    expect(residueRangeOfStates(positions, 5, 0)).toEqual({ start: 10, end: 13 });
    expect(residueRangeOfStates(positions, 2, 2)).toBeNull();
    expect(residueRangeOfStates(positions, 4, 4)).toBeNull();
  });

  it('finds the states of a residue range', () => {
    expect(stateSpanOfRange(positions, { start: 11, end: 12 })).toEqual([1, 3]);
    expect(stateSpanOfRange(positions, { start: 13 })).toEqual([5, 5]);
    expect(stateSpanOfRange(positions, { start: 50, end: 60 })).toBeNull();
    expect(stateSpanOfRange(positions, null)).toBeNull();
  });

  it('maps a state number to its column, holes and edges included', () => {
    const contiguous = stateColumnLookup([1, 2, 3, 4]);
    expect([contiguous(1), contiguous(4), contiguous(0), contiguous(9)]).toEqual([0, 3, 0, 3]);
    const holes = stateColumnLookup([1, 2, 6, 7]);
    expect([holes(2), holes(4), holes(6), holes(9), holes(-1)]).toEqual([1, 1, 2, 3, 0]);
    expect(stateColumnLookup([])(5)).toBe(0);
  });
});

describe('colours and tooltip helpers', () => {
  it('turns emissions into the column summary the schemes read', () => {
    const col = emissionColumnProfile([0.6, 0.4, 0], ['G', 'P', 'A']);
    expect(col.consensus).toBe('G');
    expect(col.consensusFraction).toBeCloseTo(0.6);
    expect(col.nonGap).toBeCloseTo(1);
    expect(col.counts).toEqual({ G: 0.6, P: 0.4 });
  });

  it('colours a letter the way the msa tile colours a cell', () => {
    // Hydrophobic mass 0.8: L and I take the Clustal X hydrophobic colour.
    const p = profileFromMsa(
      [
        { seqId: 'r', sequence: 'L', rank: 0 },
        { seqId: 'a', sequence: 'L' },
        { seqId: 'b', sequence: 'I' },
        { seqId: 'c', sequence: 'I' },
        { seqId: 'd', sequence: 'K' },
      ],
      { entity: 'x' },
    )!;
    const colours = letterColours(p, 'clustal');
    const k = p.letters.length;
    expect(colours[p.letters.indexOf('L')]).toEqual(CLUSTAL_COLOURS.hydrophobic);
    // K is a minority class in that column: uncoloured.
    expect(colours[p.letters.indexOf('K')]).toBeNull();
    expect(colours).toHaveLength(k);
    expect(letterColours(p, 'none').every((c) => c === null)).toBe(true);
  });

  it('lists the likeliest letters first', () => {
    const p = profileFromMsa(
      [
        { seqId: 'r', sequence: 'W', rank: 0 },
        { seqId: 'a', sequence: 'W' },
        { seqId: 'b', sequence: 'F' },
      ],
      { entity: 'x' },
    )!;
    expect(topLetters(p, 0)).toEqual([
      { letter: 'W', p: 2 / 3 },
      { letter: 'F', p: 1 / 3 },
    ]);
  });

  it('sorts letters in HMMER order, strays last', () => {
    expect(sortLetters(['Y', 'x', 'A', 'B'], 'amino')).toEqual(['A', 'Y', 'B', 'X']);
    expect(sortLetters(['T', 'a', 'G', 'C'], 'nucleic')).toEqual(['A', 'C', 'G', 'T']);
  });
});
