import { describe, expect, it } from 'vitest';

import {
  selectedUpsetIntersection,
  upsetColumnOf,
  upsetIntersectionKey,
  upsetIntersectionMembers,
} from './upsetSelection';

// The matrix column-wise, as the data endpoint returns it: one row per taxon,
// a 0/1 column per site, and the column the other tiles share.
const rows = {
  Athens: [1, 0, 1, 1, 0, 0, null],
  Barcelona: [1, 1, 0, 1, 0, 1, 1],
  Naples: [1, 0, 0, 1, 1, 0, 0],
  Phylum: ['Bacteroidota', 'Ciliophora', 'Fungi', 'Metazoa', 'Gyrista', null, 'Ciliophora'],
};
const SETS = ['Athens', 'Barcelona', 'Naples'];
const key = upsetIntersectionKey;

describe('upsetIntersectionKey', () => {
  it('is the same whatever order the sets come in', () => {
    expect(key(['Naples', 'Athens'])).toBe(key(['Athens', 'Naples']));
    expect(key(['Athens'])).not.toBe(key(['Athens', 'Naples']));
  });
});

describe('upsetIntersectionMembers', () => {
  const members = upsetIntersectionMembers(rows, SETS, 'Phylum');

  it('puts each row in the intersection of exactly the sets it is in', () => {
    expect(members.get(key(SETS))).toEqual(['Bacteroidota', 'Metazoa']);
    expect(members.get(key(['Athens']))).toEqual(['Fungi']);
    expect(members.get(key(['Naples']))).toEqual(['Gyrista']);
  });

  it('dedupes the values, reads a null membership as absent, and skips a row with no value', () => {
    // Rows 1 and 6 share a Phylum; row 6's null Athens is not a membership;
    // row 5 has no Phylum to emit.
    expect(members.get(key(['Barcelona']))).toEqual(['Ciliophora']);
  });

  it('only counts the sets drawn, as the worker does when a filter narrows them', () => {
    const narrowed = upsetIntersectionMembers(rows, ['Athens', 'Naples'], 'Phylum');
    expect(narrowed.get(key(['Athens', 'Naples']))).toEqual(['Bacteroidota', 'Metazoa']);
    expect(narrowed.get(key(['Athens']))).toEqual(['Fungi']);
    // In neither drawn set: dropped, like the worker's all-zero rows.
    expect([...narrowed.values()].flat()).not.toContain('Ciliophora');
  });

  it('accepts booleans as membership', () => {
    const out = upsetIntersectionMembers({ A: [true, false], id: ['x', 'y'] }, ['A'], 'id');
    expect(out).toEqual(new Map([[key(['A']), ['x']]]));
  });
});

describe('selectedUpsetIntersection', () => {
  const members = upsetIntersectionMembers(rows, SETS, 'Phylum');

  it('is nothing while no selection stands, whatever was clicked before', () => {
    expect(selectedUpsetIntersection(key(['Athens']), null, members)).toBeNull();
    expect(selectedUpsetIntersection(key(['Athens']), [], members)).toBeNull();
  });

  it('is the intersection clicked while its selection stands, even if its rows changed since', () => {
    expect(selectedUpsetIntersection(key(['Athens']), ['Fungi', 'Other'], members)).toBe(key(['Athens']));
  });

  it('is recognised by its values when the click was not seen here', () => {
    expect(selectedUpsetIntersection(null, ['Metazoa', 'Bacteroidota'], members)).toBe(key(SETS));
    expect(selectedUpsetIntersection(null, ['Unknown'], members)).toBeNull();
    expect(selectedUpsetIntersection(null, ['Fungi'], null)).toBeNull();
  });
});

describe('upsetColumnOf', () => {
  const columns = new Map([
    [0, ['Athens', 'Barcelona', 'Naples']],
    [1, ['Barcelona']],
  ]);

  it('finds the bar an intersection is drawn at', () => {
    expect(upsetColumnOf(columns, key(['Barcelona']))).toBe(1);
    expect(upsetColumnOf(columns, key(['Naples', 'Barcelona', 'Athens']))).toBe(0);
  });

  it('is null for an intersection not drawn (hidden by min size) or none', () => {
    expect(upsetColumnOf(columns, key(['Naples']))).toBeNull();
    expect(upsetColumnOf(columns, null)).toBeNull();
  });
});
