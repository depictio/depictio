import { describe, expect, it } from 'vitest';

import {
  fitViewState,
  niceFloor,
  pointInPolygon,
  pointsInPolygon,
  rectToPolygon,
  scaleBarLength,
  type Polygon,
} from './geometry';

const square: Polygon = [
  [0, 0],
  [10, 0],
  [10, 10],
  [0, 10],
];

// A "C" shape: the notch between x 3..10, y 3..7 is outside.
const cShape: Polygon = [
  [0, 0],
  [10, 0],
  [10, 3],
  [3, 3],
  [3, 7],
  [10, 7],
  [10, 10],
  [0, 10],
];

describe('pointInPolygon', () => {
  it('finds points inside and outside a convex polygon', () => {
    expect(pointInPolygon(5, 5, square)).toBe(true);
    expect(pointInPolygon(11, 5, square)).toBe(false);
    expect(pointInPolygon(5, -1, square)).toBe(false);
  });

  it('respects concavity, which a bounding box would not', () => {
    expect(pointInPolygon(1, 5, cShape)).toBe(true);
    expect(pointInPolygon(6, 5, cShape)).toBe(false);
    expect(pointInPolygon(6, 1, cShape)).toBe(true);
  });

  it('does not depend on the winding direction', () => {
    const reversed = [...cShape].reverse();
    expect(pointInPolygon(1, 5, reversed)).toBe(true);
    expect(pointInPolygon(6, 5, reversed)).toBe(false);
  });
});

describe('pointsInPolygon', () => {
  const cells = [
    { id: 'a', x: 1, y: 5 },
    { id: 'b', x: 6, y: 5 },
    { id: 'c', x: 6, y: 1 },
    { id: 'd', x: 50, y: 50 },
  ];

  it('keeps the enclosed points in input order', () => {
    expect(pointsInPolygon(cells, cShape).map((c) => c.id)).toEqual(['a', 'c']);
  });

  it('encloses nothing with fewer than three vertices', () => {
    expect(pointsInPolygon(cells, [])).toEqual([]);
    expect(
      pointsInPolygon(cells, [
        [0, 0],
        [10, 10],
      ]),
    ).toEqual([]);
  });
});

describe('rectToPolygon', () => {
  it('normalises a drag in any direction', () => {
    const fwd = rectToPolygon([2, 3], [8, 9]);
    const back = rectToPolygon([8, 9], [2, 3]);
    expect(back).toEqual(fwd);
    expect(fwd).toEqual([
      [2, 3],
      [8, 3],
      [8, 9],
      [2, 9],
    ]);
    expect(pointInPolygon(5, 5, fwd)).toBe(true);
    expect(pointInPolygon(1, 5, fwd)).toBe(false);
  });
});

describe('fitViewState', () => {
  it('centres the image and fits its limiting side', () => {
    // 2000x1000 image in a 500x500 view: width limits, 0.25 px per px.
    const v = fitViewState(2000, 1000, 500, 500, 0);
    expect(v.target).toEqual([1000, 500, 0]);
    expect(v.zoom).toBeCloseTo(-2);
  });

  it('leaves the padding clear', () => {
    const v = fitViewState(100, 100, 100, 100, 0.1);
    expect(2 ** v.zoom).toBeCloseTo(0.8);
  });

  it('does not produce a non-finite zoom before layout', () => {
    expect(fitViewState(100, 100, 0, 0).zoom).toBe(0);
  });
});

describe('scale bar', () => {
  it('rounds down to 1, 2 or 5 times a power of ten', () => {
    expect(niceFloor(7.3)).toBe(5);
    expect(niceFloor(0.034)).toBeCloseTo(0.02);
    expect(niceFloor(199)).toBe(100);
    expect(niceFloor(0)).toBe(0);
  });

  it('picks a round physical length that fits the maximum width', () => {
    // 0.5 um per pixel at zoom 0: 120 screen px = 60 um, rounded to 50 um.
    const bar = scaleBarLength(0.5, 0, 120);
    expect(bar?.value).toBe(50);
    expect(bar?.screenPx).toBeCloseTo(100);
  });

  it('shortens the physical length as the view zooms in', () => {
    const out = scaleBarLength(0.5, 0, 120)!;
    const zoomedIn = scaleBarLength(0.5, 2, 120)!;
    expect(zoomedIn.value).toBeLessThan(out.value);
    expect(zoomedIn.screenPx).toBeLessThanOrEqual(120);
  });

  it('has nothing to draw without a physical size', () => {
    expect(scaleBarLength(0, 0)).toBeNull();
    expect(scaleBarLength(Number.NaN, 0)).toBeNull();
  });
});
