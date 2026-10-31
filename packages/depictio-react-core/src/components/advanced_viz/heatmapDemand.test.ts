import { describe, expect, it } from 'vitest';

import { heatmapDemandPx, heatmapMatrixPx } from './heatmapDemand';

describe('heatmapMatrixPx', () => {
  it('gives a small matrix a floor, spread over its rows', () => {
    // A 12-run correlation matrix: 144 px at 12 px a row, 320 with the floor.
    expect(heatmapMatrixPx(12)).toBe(320);
    expect(heatmapMatrixPx(20)).toBe(320);
  });

  it('keeps three fat bands from becoming a tall column', () => {
    expect(heatmapMatrixPx(3)).toBe(120);
    expect(heatmapMatrixPx(1)).toBe(40);
  });

  it('leaves a matrix that is tall enough at the shortest readable cell', () => {
    expect(heatmapMatrixPx(85)).toBe(85 * 12);
    expect(heatmapMatrixPx(27)).toBe(27 * 12);
  });

  it('obeys a stated min_cell_px exactly, floor or not', () => {
    expect(heatmapMatrixPx(12, 6)).toBe(72);
    expect(heatmapMatrixPx(85, 4)).toBe(340);
    expect(heatmapMatrixPx(12, 30)).toBe(360);
  });

  it('draws nothing for an empty matrix', () => {
    expect(heatmapMatrixPx(0)).toBe(0);
    expect(heatmapMatrixPx(-3, 12)).toBe(0);
  });
});

describe('heatmapDemandPx', () => {
  it('adds the chrome and bands around the matrix', () => {
    expect(heatmapDemandPx(12, 222)).toBe(542);
    expect(heatmapDemandPx(85, 130, 12)).toBe(85 * 12 + 130);
  });

  it('makes no demand for an empty matrix', () => {
    expect(heatmapDemandPx(0, 222)).toBe(0);
  });
});
