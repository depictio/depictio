import { describe, expect, it } from 'vitest';

import {
  findRenderedPoint,
  renderedPointsFromGraph,
  renderedPointsSignature,
} from './renderedPoints';
import type { GraphLike } from './renderedPoints';

const CATS = ['Adelie', 'Chinstrap', 'Gentoo'];
// A category axis as Plotly sets it up: c2d rounds to the nearest category,
// c2r keeps the serial number.
const categoryAxis = {
  type: 'category',
  c2d: (v: number) => CATS[Math.round(v)],
  c2r: (v: number) => v,
};
const linearAxis = { type: 'linear', c2d: (v: number) => v, c2r: (v: number) => v };

/** Two grouped vertical box traces (male / female), points drawn left of each box. */
function boxGraph(): GraphLike {
  return {
    _fullData: [
      { type: 'box', visible: true, orientation: 'v', xaxis: 'x', yaxis: 'y' },
      { type: 'box', visible: true, orientation: 'v', xaxis: 'x', yaxis: 'y' },
      { type: 'scatter', visible: true, xaxis: 'x', yaxis: 'y' },
    ],
    calcdata: [
      [
        { pos: 1, pts: [{ v: 55.8, i: 101, x: 0.62, y: 55.8 }, { v: 49.3, i: 73, x: 0.66, y: 49.3 }] },
        { pos: 2, pts: [{ v: 49.3, i: 150, x: 1.64, y: 49.3 }] },
      ],
      [{ pos: 1, pts: [{ v: 58, i: 7, x: 0.86, y: 58 }] }],
      [{ x: 1, y: 2 }],
    ],
    _fullLayout: { xaxis: categoryAxis, yaxis: linearAxis },
  };
}

describe('renderedPointsFromGraph', () => {
  it('reads the jittered, group-offset position of box points', () => {
    const rendered = renderedPointsFromGraph(boxGraph());
    expect(rendered).not.toBeNull();
    expect([...rendered!.keys()]).toEqual([0, 1]);
    expect(rendered!.get(0)!.byIndex.get(101)).toEqual({ x: 0.62, y: 55.8, pos: 'Chinstrap', value: 55.8 });
    expect(rendered!.get(1)!.points).toHaveLength(1);
  });

  it('skips box points a trace does not draw, hidden traces and other subplots', () => {
    const gd = boxGraph();
    (gd.calcdata as Array<Array<{ pts: unknown[] }>>)[0][0].pts = [{ v: 55.8, i: 101 }];
    (gd._fullData as Array<Record<string, unknown>>)[1].visible = 'legendonly';
    const rendered = renderedPointsFromGraph(gd)!;
    expect(rendered.get(0)!.points).toHaveLength(1);
    expect(rendered.has(1)).toBe(false);
    (gd._fullData as Array<Record<string, unknown>>)[0].xaxis = 'x2';
    expect(renderedPointsFromGraph(gd)).toBeNull();
  });

  it('reads horizontal boxes with the position on y', () => {
    const gd: GraphLike = {
      _fullData: [{ type: 'violin', visible: true, orientation: 'h' }],
      calcdata: [[{ pos: 0, pts: [{ v: 3, i: 2, x: 3, y: -0.2 }] }]],
      _fullLayout: { xaxis: linearAxis, yaxis: categoryAxis },
    };
    const trace = renderedPointsFromGraph(gd)!.get(0)!;
    expect(trace.posLetter).toBe('y');
    expect(trace.byIndex.get(2)).toEqual({ x: 3, y: -0.2, pos: 'Adelie', value: 3 });
  });

  it('reads the offset centre and top of grouped or stacked bars', () => {
    const gd: GraphLike = {
      _fullData: [{ type: 'bar', visible: true, orientation: 'v' }],
      calcdata: [[{ p: 0, x: -0.2, y: 12, s: 12 }, { p: 1, x: 0.8, y: 30, s: 5 }, { p: 2 }]],
      _fullLayout: { xaxis: categoryAxis, yaxis: linearAxis },
    };
    const trace = renderedPointsFromGraph(gd)!.get(0)!;
    expect(trace.byIndex.get(1)).toEqual({ x: 0.8, y: 30, pos: 'Chinstrap', value: 30 });
    expect(trace.byIndex.has(2)).toBe(false);
  });

  it('reads scatter traces only when grouped', () => {
    const gd: GraphLike = {
      _fullData: [{ type: 'scatter', visible: true, orientation: 'v' }],
      calcdata: [[{ x: 0.15, y: 4 }]],
      _fullLayout: { xaxis: categoryAxis, yaxis: linearAxis },
    };
    expect(renderedPointsFromGraph(gd)).toBeNull();
    gd._fullLayout!.scattermode = 'group';
    expect(renderedPointsFromGraph(gd)!.get(0)!.byIndex.get(0)).toMatchObject({ x: 0.15, y: 4 });
  });

  it('is null before Plotly has plotted', () => {
    expect(renderedPointsFromGraph(null)).toBeNull();
    expect(renderedPointsFromGraph({})).toBeNull();
  });

  it('converts calcdata to range coords through the axes (log value axis)', () => {
    const gd: GraphLike = {
      _fullData: [{ type: 'box', visible: true }],
      calcdata: [[{ pos: 0, pts: [{ v: 100, i: 0, x: -0.1, y: 100 }] }]],
      _fullLayout: {
        xaxis: categoryAxis,
        yaxis: { type: 'log', c2d: (v: number) => v, c2r: (v: number) => Math.log10(v) },
      },
    };
    expect(renderedPointsFromGraph(gd)!.get(0)!.byIndex.get(0)).toMatchObject({ x: -0.1, y: 2 });
  });
});

describe('renderedPointsSignature', () => {
  it('is stable for the same positions and changes when they move', () => {
    const a = renderedPointsSignature(renderedPointsFromGraph(boxGraph()));
    expect(renderedPointsSignature(renderedPointsFromGraph(boxGraph()))).toBe(a);
    const moved = boxGraph();
    (moved.calcdata as Array<Array<{ pts: Array<{ x: number }> }>>)[0][0].pts[0].x = 0.7;
    expect(renderedPointsSignature(renderedPointsFromGraph(moved))).not.toBe(a);
    expect(renderedPointsSignature(null)).toBe('');
  });
});

describe('findRenderedPoint', () => {
  const rendered = renderedPointsFromGraph(boxGraph());

  it('finds a point by its stored index', () => {
    expect(findRenderedPoint(rendered, { x: 'Chinstrap', y: 55.8, trace: 0, index: 101 })).toMatchObject({
      x: 0.62,
      y: 55.8,
    });
  });

  it('falls back to category and value when the index moved (filters, re-ingest)', () => {
    expect(findRenderedPoint(rendered, { x: 'Chinstrap', y: 55.8, trace: 0, index: 73 })).toMatchObject({
      x: 0.62,
    });
    expect(findRenderedPoint(rendered, { x: 'Chinstrap', y: 58, trace: 1 })).toMatchObject({ x: 0.86 });
  });

  it('gives each of two identical points its own mark', () => {
    const used = new Set<ReturnType<typeof findRenderedPoint> & object>();
    const a = findRenderedPoint(rendered, { x: 'Gentoo', y: 49.3, trace: 0 }, used);
    expect(a).toMatchObject({ x: 1.64 });
    used.add(a!);
    expect(findRenderedPoint(rendered, { x: 'Gentoo', y: 49.3, trace: 0 }, used)).toBeNull();
  });

  it('is null for a missing point and undefined for traces drawn at their data coords', () => {
    expect(findRenderedPoint(rendered, { x: 'Adelie', y: 1, trace: 0 })).toBeNull();
    expect(findRenderedPoint(rendered, { x: 1, y: 2, trace: 2 })).toBeUndefined();
    expect(findRenderedPoint(rendered, { x: 'Chinstrap', y: 55.8 })).toBeUndefined();
    expect(findRenderedPoint(null, { x: 'Chinstrap', y: 55.8, trace: 0 })).toBeUndefined();
  });
});
