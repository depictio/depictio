import { describe, expect, it } from 'vitest';

import {
  arrowNoteFromClick,
  markedPointsFromSelection,
  rangeFromSelection,
  refLineFromClick,
  regionFromSelection,
} from './capture';
import { MAX_POINT_IDS, MAX_REGION_VERTICES } from './types';

describe('rangeFromSelection', () => {
  it('keeps the x extent of a box and orders the ends', () => {
    expect(rangeFromSelection({ range: { x: [5, 2], y: [0, 9] } }, 'x')).toEqual({
      kind: 'x_range',
      x0: 2,
      x1: 5,
    });
  });
  it('reads date strings', () => {
    expect(rangeFromSelection({ range: { x: ['2024-01-01', '2024-02-01'], y: [0, 1] } }, 'x')).toEqual({
      kind: 'x_range',
      x0: '2024-01-01',
      x1: '2024-02-01',
    });
  });
  it('builds numeric y ranges and ignores the x extent', () => {
    expect(rangeFromSelection({ range: { x: ['a', 'b'], y: [3, 1] } }, 'y')).toEqual({
      kind: 'y_range',
      y0: 1,
      y1: 3,
    });
    expect(rangeFromSelection({ range: { x: [0, 1], y: ['a', 'b'] } }, 'y')).toBeNull();
  });
  it('falls back to the newest rectangle of the main subplot', () => {
    const selections = [
      { type: 'rect', xref: 'x', yref: 'y', x0: 0, x1: 1, y0: 0, y1: 1 },
      { type: 'rect', xref: 'x', yref: 'y', x0: 4, x1: 3, y0: 0, y1: 1 },
    ];
    expect(rangeFromSelection({ selections }, 'x')).toEqual({ kind: 'x_range', x0: 3, x1: 4 });
    expect(
      rangeFromSelection({ selections: [{ type: 'rect', xref: 'x2', x0: 0, x1: 1 }] }, 'x'),
    ).toBeNull();
    expect(rangeFromSelection({ selections: [{ type: 'path', path: 'M0,0L1,1L1,0Z' }] }, 'x')).toBeNull();
  });
  it('ignores lassos, empty boxes and missing events', () => {
    expect(rangeFromSelection({ lassoPoints: { x: [0, 1, 2], y: [0, 1, 0] } }, 'x')).toBeNull();
    expect(rangeFromSelection({ range: { x: [1, 1], y: [0, 1] } }, 'x')).toBeNull();
    expect(rangeFromSelection(null, 'x')).toBeNull();
    expect(rangeFromSelection(undefined, 'y')).toBeNull();
  });
});

describe('click helpers', () => {
  it('builds reference lines on either axis', () => {
    expect(refLineFromClick({ x: 'cat', y: 4 }, 'x')).toEqual({ kind: 'ref_line', axis: 'x', value: 'cat' });
    expect(refLineFromClick({ x: 'cat', y: 4 }, 'y')).toEqual({ kind: 'ref_line', axis: 'y', value: 4 });
    expect(refLineFromClick({ x: null, y: 4 }, 'x')).toBeNull();
  });
  it('builds an arrow note with the default offset', () => {
    expect(arrowNoteFromClick({ x: 1, y: 2 })).toEqual({ kind: 'arrow_note', x: 1, y: 2, ax: -40, ay: -40 });
    expect(arrowNoteFromClick({ x: 1 })).toBeNull();
    expect(arrowNoteFromClick(undefined)).toBeNull();
  });
});

describe('markedPointsFromSelection', () => {
  const points = [
    { x: 1, y: 1, curveNumber: 0, customdata: ['s1', 9] },
    { x: 2, y: 2, curveNumber: 0, customdata: ['s2', 9] },
    { x: 2, y: 2, curveNumber: 1, customdata: ['s2', 9] },
  ];

  it('uses selection ids when a selection column is known, deduped', () => {
    expect(markedPointsFromSelection({ points }, 0, 'sample')).toEqual({
      kind: 'points',
      column: 'sample',
      ids: ['s1', 's2'],
    });
  });

  it('accepts scalar customdata at index 0', () => {
    expect(markedPointsFromSelection({ points: [{ x: 1, y: 1, customdata: 42 }] }, 0, 'id')).toEqual({
      kind: 'points',
      column: 'id',
      ids: [42],
    });
  });

  it('falls back to coords without a selection column, deduped per trace', () => {
    expect(markedPointsFromSelection({ points: [...points, points[0]] })).toEqual({
      kind: 'points',
      coords: [
        { x: 1, y: 1, trace: 0 },
        { x: 2, y: 2, trace: 0 },
        { x: 2, y: 2, trace: 1 },
      ],
    });
  });

  it('falls back to coords when no point carries an id', () => {
    const out = markedPointsFromSelection({ points: [{ x: 'a', y: 3, curveNumber: 0 }] }, 0, 'id');
    expect(out).toEqual({ kind: 'points', coords: [{ x: 'a', y: 3, trace: 0 }] });
  });

  it('returns null for an empty selection', () => {
    expect(markedPointsFromSelection({ points: [] }, 0, 'id')).toBeNull();
    expect(markedPointsFromSelection(undefined)).toBeNull();
  });

  it('caps the number of ids', () => {
    const many = Array.from({ length: MAX_POINT_IDS + 10 }, (_, i) => ({ x: i, y: i, customdata: [`s${i}`] }));
    const out = markedPointsFromSelection({ points: many }, 0, 'id');
    expect(out?.ids).toHaveLength(MAX_POINT_IDS);
  });
});

describe('regionFromSelection', () => {
  const points = [{ x: 1, y: 1, curveNumber: 0 }];

  it('keeps a box selection as an ordered box region', () => {
    const out = markedPointsFromSelection({ points, range: { x: [3, 1], y: [5, 2] } });
    expect(out?.region).toEqual({ shape: 'box', x0: 1, x1: 3, y0: 2, y1: 5 });
  });

  it('keeps a lasso selection alongside selection ids', () => {
    const lassoPoints = { x: [0, 2, 2, 0], y: [0, 0, 2, 2] };
    const out = markedPointsFromSelection(
      { points: [{ x: 1, y: 1, customdata: ['s1'] }], lassoPoints },
      0,
      'id',
    );
    expect(out).toEqual({
      kind: 'points',
      column: 'id',
      ids: ['s1'],
      region: { shape: 'lasso', ...lassoPoints },
    });
  });

  it('thins a long lasso to the vertex cap', () => {
    const n = MAX_REGION_VERTICES * 3 + 7;
    const x = Array.from({ length: n }, (_, i) => Math.cos(i));
    const y = Array.from({ length: n }, (_, i) => Math.sin(i));
    const region = regionFromSelection({ lassoPoints: { x, y } });
    expect(region?.shape).toBe('lasso');
    if (region?.shape !== 'lasso') return;
    expect(region.x).toHaveLength(MAX_REGION_VERTICES);
    expect(region.y).toHaveLength(MAX_REGION_VERTICES);
    expect(region.x[0]).toBe(x[0]);
  });

  it('ignores degenerate lassos and unusable ranges', () => {
    expect(regionFromSelection({ lassoPoints: { x: [0, 1], y: [0, 1] } })).toBeNull();
    expect(regionFromSelection({ lassoPoints: { x: [0, 1, 2], y: [0, 1] } })).toBeNull();
    expect(regionFromSelection({ range: { x: [0], y: [0, 1] } })).toBeNull();
    expect(regionFromSelection({ points })).toBeNull();
    expect(regionFromSelection(null)).toBeNull();
    expect(markedPointsFromSelection({ points })).toEqual({
      kind: 'points',
      coords: [{ x: 1, y: 1, trace: 0 }],
    });
  });

  it('falls back to the newest entry of selections', () => {
    expect(
      regionFromSelection({
        selections: [
          { type: 'rect', x0: 9, x1: 10, y0: 9, y1: 10 },
          { type: 'rect', x0: 2, x1: 0, y0: 'b', y1: 'a' },
        ],
      }),
    ).toEqual({ shape: 'box', x0: 0, x1: 2, y0: 'a', y1: 'b' });
    expect(
      regionFromSelection({ selections: [{ type: 'path', path: 'M0,0L2.5,0L1,-1.5e1Z' }] }),
    ).toEqual({ shape: 'lasso', x: [0, 2.5, 1], y: [0, 0, -15] });
  });
});

describe('box plots on a category axis', () => {
  // A box selection over grouped, jittered box points, as Plotly 2.35 emits it.
  const boxEvent = {
    points: [
      { x: 'Chinstrap', y: 49.3, curveNumber: 0, pointNumber: 101, fullData: { type: 'box' } },
      { x: 'Chinstrap', y: 49.3, curveNumber: 0, pointNumber: 102, fullData: { type: 'box' } },
      { x: 'Chinstrap', y: 58, curveNumber: 1, pointIndex: 7, data: { type: 'box' } },
    ],
    range: { x: [0.5258, 1.1717], y: [49.29, 53.79] },
    selections: [{ type: 'rect', xref: 'x', yref: 'y', x0: 0.5258, x1: 1.1717, y0: 53.79, y1: 49.29 }],
  };

  it('stores the point index of box points, keeping points that share a value', () => {
    expect(markedPointsFromSelection(boxEvent)?.coords).toEqual([
      { x: 'Chinstrap', y: 49.3, trace: 0, index: 101 },
      { x: 'Chinstrap', y: 49.3, trace: 0, index: 102 },
      { x: 'Chinstrap', y: 58, trace: 1, index: 7 },
    ]);
  });

  it('keeps the numeric category positions of the box as the region', () => {
    const region = { shape: 'box', x0: 0.5258, x1: 1.1717, y0: 49.29, y1: 53.79 };
    expect(markedPointsFromSelection(boxEvent)?.region).toEqual(region);
    const { range: _r, ...withoutRange } = boxEvent;
    expect(regionFromSelection(withoutRange)).toEqual(region);
  });

  it('keeps a lasso traced on a category axis', () => {
    expect(
      regionFromSelection({ lassoPoints: { x: [-0.3, 0.4, 0.1], y: [40, 41, 45] } }),
    ).toEqual({ shape: 'lasso', x: [-0.3, 0.4, 0.1], y: [40, 41, 45] });
  });

  it('stores no index for scatter points', () => {
    const geom = markedPointsFromSelection({
      points: [{ x: 1, y: 2, curveNumber: 0, pointNumber: 5, fullData: { type: 'scatter' } }],
    });
    expect(geom?.coords).toEqual([{ x: 1, y: 2, trace: 0 }]);
  });
});
