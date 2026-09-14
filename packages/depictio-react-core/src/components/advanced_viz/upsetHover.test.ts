import { describe, expect, it } from 'vitest';

import {
  emphasizeUpsetColumn,
  UPSET_DIMMED_OPACITY as DIM,
  upsetHoverColumn,
  withUpsetHoverTargets,
} from './upsetHover';

// Sets A, B, C at y = 0, 1, 2. Intersections: 0 = A & B, 1 = B, 2 = A & C.
const layout = {
  yaxis: { title: { text: 'Intersection Size' } },
  yaxis2: { ticktext: ['A', 'B', 'C'] },
  yaxis3: { ticktext: ['A', 'B', 'C'], matches: 'y2' },
};

const degreeTwoBars = { type: 'bar', name: '2', x: [0, 2], y: [5, 3], marker: { color: '#123456' } };
const degreeOneBars = { type: 'bar', name: '1', x: [1], y: [4] };
const emptyDots = {
  type: 'scatter',
  mode: 'markers',
  x: [0, 1, 1, 2],
  y: [2, 0, 2, 1],
  hoverinfo: 'skip',
  xaxis: 'x3',
  yaxis: 'y3',
};
const edgeA_B = { type: 'scatter', mode: 'lines', x: [0, 0], y: [0, 1], hoverinfo: 'skip', xaxis: 'x3', yaxis: 'y3' };
const edgeA_C = { type: 'scatter', mode: 'lines', x: [2, 2], y: [0, 2], hoverinfo: 'skip', xaxis: 'x3', yaxis: 'y3' };
const filledDots = {
  type: 'scatter',
  mode: 'markers',
  x: [0, 0, 1, 2, 2],
  y: [0, 1, 1, 0, 2],
  hovertext: ['A & B', 'A & B', 'B', 'A & C', 'A & C'],
  hoverinfo: 'text',
  xaxis: 'x3',
  yaxis: 'y3',
};
const setSizes = { type: 'bar', orientation: 'h', name: 'Set Size', x: [9, 8, 7], y: [0, 1, 2], xaxis: 'x2', yaxis: 'y2' };
const boxTrack = { type: 'box', x: [1, 1, 1], y: [0.1, 0.2, 0.3], xaxis: 'x4', yaxis: 'y4' };
const legendEntry = { type: 'bar', x: [null], y: [null], name: 'category' };

const figure = [degreeTwoBars, degreeOneBars, emptyDots, edgeA_B, edgeA_C, filledDots, setSizes, boxTrack, legendEntry];

const markerOpacity = (t: Record<string, unknown>) => (t.marker as { opacity?: unknown }).opacity;

describe('emphasizeUpsetColumn', () => {
  const out = emphasizeUpsetColumn(figure, layout, 2);
  const [twoBars, oneBars, empty, edgeAB, edgeAC, filled, sizes, box, legend] = out;

  it('keeps the hovered bar and dims the others, whatever trace they sit in', () => {
    expect(markerOpacity(twoBars)).toEqual([DIM, 1]);
    expect(markerOpacity(oneBars)).toEqual([DIM]);
    expect((twoBars.marker as { color: string }).color).toBe('#123456');
  });

  it('keeps the hovered matrix column: its dots and its edge', () => {
    expect(markerOpacity(filled)).toEqual([DIM, DIM, DIM, 1, 1]);
    expect(markerOpacity(empty)).toEqual([DIM, DIM, DIM, 1]);
    expect(edgeAB.opacity).toBe(DIM);
    expect(edgeAC.opacity).toBe(1);
  });

  it('keeps the size bars of the sets the intersection joins', () => {
    expect(markerOpacity(sizes)).toEqual([1, DIM, 1]);
  });

  it('dims one-intersection tracks as a whole and leaves legend entries alone', () => {
    expect(box.opacity).toBe(DIM);
    expect(emphasizeUpsetColumn(figure, layout, 1)[7].opacity).toBe(1);
    expect(legend).toBe(legendEntry);
  });

  it('does not touch the figure it is given', () => {
    expect(degreeOneBars).not.toHaveProperty('marker');
    expect(edgeAB).not.toBe(edgeA_B);
    expect(edgeA_B).not.toHaveProperty('opacity');
  });
});

describe('upsetHoverColumn', () => {
  it('reads the intersection off a bar, a dot or a track', () => {
    expect(upsetHoverColumn({ data: degreeTwoBars, x: 2 })).toBe(2);
    expect(upsetHoverColumn({ data: boxTrack, x: 0.9999 })).toBe(1);
  });

  it('has no intersection for a set-size bar or a missing point', () => {
    expect(upsetHoverColumn({ data: setSizes, x: 9 })).toBeNull();
    expect(upsetHoverColumn(undefined)).toBeNull();
    expect(upsetHoverColumn({ data: degreeTwoBars })).toBeNull();
  });
});

describe('withUpsetHoverTargets', () => {
  it('makes the empty matrix dots hoverable without a label, and nothing else', () => {
    const [, , empty, edge, , filled] = withUpsetHoverTargets(figure, layout);
    expect(empty.hoverinfo).toBe('none');
    expect(edge.hoverinfo).toBe('skip');
    expect(filled.hoverinfo).toBe('text');
  });
});
