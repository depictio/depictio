import { describe, expect, it } from 'vitest';

import { overlayMatrix, overlayPlane } from './overlay';

describe('overlayPlane', () => {
  it('maps a plane of the image to the overlay plane at the same depth', () => {
    // 965 EM planes over 19 overlay planes: both span the same depth.
    expect(overlayPlane(0, 965, 19)).toBe(0);
    expect(overlayPlane(482, 965, 19)).toBe(9);
    expect(overlayPlane(964, 965, 19)).toBe(18);
  });

  it('is the identity for the same depth, and plane 0 for a flat overlay', () => {
    expect(overlayPlane(7, 12, 12)).toBe(7);
    expect(overlayPlane(500, 965, 1)).toBe(0);
  });
});

describe('overlayMatrix', () => {
  it('stretches the overlay to the image in plane', () => {
    const m = overlayMatrix({ width: 5938, height: 7000 }, { width: 371, height: 437 })!;
    expect(m[0]).toBeCloseTo(5938 / 371);
    expect(m[5]).toBeCloseTo(7000 / 437);
    expect([m[10], m[15]]).toEqual([1, 1]);
  });

  it('is null when the overlay already has the image size', () => {
    expect(overlayMatrix({ width: 384, height: 384 }, { width: 384, height: 384 })).toBeNull();
  });
});
