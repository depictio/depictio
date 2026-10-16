import { describe, expect, it } from 'vitest';

import {
  columnOfResidue,
  columnResidueMap,
  followerWidth,
  mappedAxis,
  residueAtColumn,
  uniformAxis,
  widthForWindow,
} from './zoomAxis';

describe('uniformAxis', () => {
  it('puts the first residue at x 0 and moves one residue per column', () => {
    const axis = uniformAxis(5, 10);
    expect(axis.xOf(5, 10)).toBe(0);
    expect(axis.xOf(8.5, 10)).toBe(35);
    expect(axis.posAt(35)).toBe(8.5);
  });

  it('round-trips at another width', () => {
    const axis = uniformAxis(1, 4);
    expect(axis.xOf(axis.posAt(123), 4)).toBeCloseTo(123, 10);
  });
});

describe('columnResidueMap', () => {
  // Reference "AC--DE": columns 0, 1, 4, 5 hold residues 1, 2, 3, 4.
  const ref = [1, 2, null, null, 3, 4];
  const map = columnResidueMap(ref.length, (c) => ref[c]);

  it('maps residue columns one to one', () => {
    expect(residueAtColumn(map, 0)).toBe(1);
    expect(residueAtColumn(map, 1.5)).toBe(2.5);
    expect(residueAtColumn(map, 4)).toBe(3);
    expect(columnOfResidue(map, 4.25)).toBe(5.25);
  });

  it('holds the residue still across gap columns', () => {
    expect(residueAtColumn(map, 2)).toBe(3);
    expect(residueAtColumn(map, 3.5)).toBe(3);
  });

  it('extrapolates one column per residue past either end', () => {
    expect(residueAtColumn(map, -2)).toBe(-1);
    expect(residueAtColumn(map, 8)).toBe(7);
    expect(columnOfResidue(map, 7)).toBe(8);
  });

  it('squeezes residues that hold no column (a model skipping inserts)', () => {
    // States 0..2 sit on residues 1, 2 and 6: residues 3..5 are inserts.
    const states = [1, 2, 6];
    const m = columnResidueMap(states.length, (c) => states[c]);
    expect(residueAtColumn(m, 2)).toBe(6);
    expect(columnOfResidue(m, 4)).toBe(2);
    expect(columnOfResidue(m, 6.5)).toBe(2.5);
  });

  it('treats a column whose residue does not ascend as a gap', () => {
    const m = columnResidueMap(3, (c) => [1, 1, 2][c]);
    expect(Array.from(m.cols)).toEqual([0, 1, 2, 3]);
    expect(Array.from(m.res)).toEqual([1, 2, 2, 3]);
    expect(residueAtColumn(m, 1.5)).toBe(2);
  });

  it('is the identity when nothing maps', () => {
    const m = columnResidueMap(3, () => null);
    expect(residueAtColumn(m, 2)).toBe(2);
    expect(columnOfResidue(m, 2)).toBe(2);
  });
});

describe('widthForWindow', () => {
  it('fills the width with the window', () => {
    expect(widthForWindow(uniformAxis(1, 3), 11, 61, 500)).toBe(10);
  });

  it('counts fixed-width pieces between the columns', () => {
    // A 14 px stub between residue 20 and 21, whatever the width.
    const axis = {
      posAt: (x: number) => x,
      xOf: (pos: number, cw: number) => (pos - 1) * cw + (pos > 20 ? 14 : 0),
    };
    // 40 residues and the stub in 414 px: 10 px each.
    expect(widthForWindow(axis, 1, 41, 414)).toBeCloseTo(10, 10);
  });

  it('goes through an alignment map', () => {
    const ref = [1, 2, null, null, 3, 4];
    const axis = mappedAxis(columnResidueMap(ref.length, (c) => ref[c]), 1);
    // Residues 1..5 span columns 0..6: 6 columns in 60 px.
    expect(widthForWindow(axis, 1, 5, 60)).toBeCloseTo(10, 10);
  });

  it('says nothing about an empty window or no room', () => {
    expect(widthForWindow(uniformAxis(1, 3), 5, 5, 100)).toBeNull();
    expect(widthForWindow(uniformAxis(1, 3), 5, 9, 0)).toBeNull();
  });
});

describe('followerWidth', () => {
  const axis = uniformAxis(1, 3);

  it('fits when the window needs no more than the fitted width', () => {
    expect(followerWidth(axis, 1, 201, 400, 2, 24)).toBe(0);
    expect(followerWidth(axis, 1, 201, 400, 1.995, 24)).toBe(0);
  });

  it('rounds to a hundredth of a pixel and clamps to the widest', () => {
    expect(followerWidth(axis, 1, 31, 200, 1, 24)).toBe(6.67);
    expect(followerWidth(axis, 1, 3, 200, 1, 24)).toBe(24);
  });
});
