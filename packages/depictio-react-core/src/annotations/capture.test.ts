import { describe, expect, it } from 'vitest';

import {
  arrowNoteFromClick,
  markedPointsFromSelection,
  rangeFromRelayout,
  refLineFromClick,
} from './capture';
import { MAX_POINT_IDS } from './types';

describe('rangeFromRelayout', () => {
  it('reads indexed keys and orders the ends', () => {
    expect(rangeFromRelayout({ 'xaxis.range[0]': 5, 'xaxis.range[1]': 2 }, 'x')).toEqual({
      kind: 'x_range',
      x0: 2,
      x1: 5,
    });
  });
  it('reads the array form and date strings', () => {
    expect(rangeFromRelayout({ 'xaxis.range': ['2024-01-01', '2024-02-01'] }, 'x')).toEqual({
      kind: 'x_range',
      x0: '2024-01-01',
      x1: '2024-02-01',
    });
  });
  it('builds numeric y ranges', () => {
    expect(rangeFromRelayout({ 'yaxis.range[0]': 3, 'yaxis.range[1]': 1 }, 'y')).toEqual({
      kind: 'y_range',
      y0: 1,
      y1: 3,
    });
    expect(rangeFromRelayout({ 'yaxis.range': ['a', 'b'] }, 'y')).toBeNull();
  });
  it('ignores autorange resets, other axes and empty events', () => {
    expect(rangeFromRelayout({ 'xaxis.autorange': true }, 'x')).toBeNull();
    expect(rangeFromRelayout({ 'yaxis.range[0]': 1, 'yaxis.range[1]': 2 }, 'x')).toBeNull();
    expect(rangeFromRelayout(null, 'x')).toBeNull();
    expect(rangeFromRelayout({ 'xaxis.range[0]': 1, 'xaxis.range[1]': 1 }, 'x')).toBeNull();
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
