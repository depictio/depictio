import { describe, expect, it } from 'vitest';

import { rotateToTriangle } from './contactMapTriangle';

describe('rotateToTriangle', () => {
  it('puts the diagonal on the bottom row and the far corner at the apex', () => {
    const m = [
      [1, 2, 3],
      [2, 4, 5],
      [3, 5, 6],
    ];
    const { z, positionIndex, separations } = rotateToTriangle(m);
    expect(separations).toEqual([0, 1, 2]);
    expect(positionIndex).toEqual([0, 0.5, 1, 1.5, 2]);
    // Separation 0 is the diagonal: (0,0), (1,1), (2,2) at x = 0, 2, 4.
    expect(z[0][0]).toBe(1);
    expect(z[0][2]).toBe(4);
    expect(z[0][4]).toBe(6);
    // Separation 2 is the single most distant pair, (0,2), at x = 2.
    expect(z[2][2]).toBe(3);
  });

  it('fills the odd-parity lattice gaps from their horizontal neighbours', () => {
    const m = [
      [1, 2],
      [2, 3],
    ];
    const { z } = rotateToTriangle(m);
    // Row 0 holds the diagonal at x = 0 and x = 2; x = 1 is a lattice gap.
    expect(z[0][0]).toBe(1);
    expect(z[0][2]).toBe(3);
    expect(z[0][1]).toBe(2);
    expect(z[0].every((v) => v !== null)).toBe(true);
  });

  it('caps the drawn separations, because far contacts are noise', () => {
    const m = [
      [1, 1, 1, 1],
      [1, 1, 1, 1],
      [1, 1, 1, 1],
      [1, 1, 1, 1],
    ];
    expect(rotateToTriangle(m).z).toHaveLength(4);
    expect(rotateToTriangle(m, 2).z).toHaveLength(2);
    expect(rotateToTriangle(m, 99).z).toHaveLength(4);
  });

  it('keeps an absent cell blank rather than drawing it as zero', () => {
    const m = [
      [5, null],
      [null, 7],
    ];
    const { z } = rotateToTriangle(m);
    expect(z[0][0]).toBe(5);
    expect(z[0][2]).toBe(7);
    // Separation 1 has no data at all, so it stays blank.
    expect(z[1].every((v) => v === null)).toBe(true);
  });

  it('reads the mirrored half when only one triangle is populated', () => {
    const m = [
      [1, null],
      [9, 3],
    ];
    const { z } = rotateToTriangle(m);
    expect(z[1][1]).toBe(9);
  });

  it('survives an empty matrix', () => {
    expect(rotateToTriangle([])).toEqual({ z: [], positionIndex: [], separations: [] });
  });
});
