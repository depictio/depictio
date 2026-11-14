import { describe, expect, it } from 'vitest';

import {
  onPlane,
  fitBoundsViewState,
  fitViewState,
  boxDisplay,
  footprintBounds,
  padBounds,
  pointAt,
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

describe('onPlane', () => {
  it('keeps a point on its nearest plane without a tolerance', () => {
    expect(onPlane(3.4, 3)).toBe(true);
    expect(onPlane(3.6, 3)).toBe(false);
  });

  it('keeps it on every plane within the tolerance', () => {
    expect(onPlane(400, 460, 60)).toBe(true);
    expect(onPlane(400, 461, 60)).toBe(false);
    expect(onPlane(Number.NaN, 0, 60)).toBe(false);
  });
});

describe('footprintBounds', () => {
  it('counts a box by its whole extent and a dot by its centre', () => {
    expect(footprintBounds([])).toBeNull();
    expect(
      footprintBounds([
        { x: 10, y: 10, w: 4, h: 2 },
        { x: 30, y: 5 },
      ]),
    ).toEqual({ minX: 8, minY: 5, maxX: 30, maxY: 11 });
  });
});

describe('fitBoundsViewState', () => {
  it('centres the bounds and fits their larger relative side', () => {
    const v = fitBoundsViewState({ minX: 100, minY: 0, maxX: 300, maxY: 100 }, 400, 400, 0);
    expect(v.target).toEqual([200, 50, 0]);
    expect(v.zoom).toBeCloseTo(1);
  });

  it('matches fitViewState on the whole image', () => {
    expect(fitBoundsViewState({ minX: 0, minY: 0, maxX: 800, maxY: 600 }, 400, 300)).toEqual(
      fitViewState(800, 600, 400, 300),
    );
  });
});

describe('pointAt', () => {
  const boxes = [
    { id: 'big', x: 50, y: 50, w: 100, h: 100 },
    { id: 'small', x: 20, y: 20, w: 10, h: 10 },
  ];

  it('picks the smallest box under the click', () => {
    expect(pointAt(boxes, 21, 19, 0)?.id).toBe('small');
    expect(pointAt(boxes, 80, 80, 0)?.id).toBe('big');
    expect(pointAt(boxes, 200, 200, 5)).toBeNull();
  });

  it('picks the nearest dot within the slack', () => {
    const dots = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 6, y: 0 },
    ];
    expect(pointAt(dots, 4, 0, 3)?.id).toBe('b');
    expect(pointAt(dots, 3, 9, 3)).toBeNull();
  });

  it('prefers a box to a dot', () => {
    expect(pointAt([{ id: 'dot', x: 21, y: 20 }, ...boxes], 21, 20, 5)?.id).toBe('small');
  });
});

describe('padBounds', () => {
  it('grows a small extent about its centre and leaves a large one alone', () => {
    expect(padBounds(null, 10)).toBeNull();
    expect(padBounds({ minX: 5, minY: 0, maxX: 5, maxY: 100 }, 10)).toEqual({
      minX: 0,
      minY: 0,
      maxX: 10,
      maxY: 100,
    });
  });
});

describe('boxDisplay', () => {
  const box = { x: 0, y: 0, w: 100, h: 50 };
  it('is a dot when smaller than one, filled while small, outlined when large', () => {
    expect(boxDisplay(box, 0.03)).toBe('dot');
    expect(boxDisplay(box, 0.3)).toBe('filled');
    expect(boxDisplay(box, 2)).toBe('outline');
  });
});
