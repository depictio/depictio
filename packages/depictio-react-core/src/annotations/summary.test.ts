import { describe, expect, it } from 'vitest';

import { annotationHoverText, annotationSummary, formatAxisValue, sameStats } from './summary';
import type { Annotation, Geometry } from './types';

const ann = (geometry: Geometry): Annotation => ({
  kind: geometry.kind === 'points' ? 'points' : 'range',
  geometry,
  label: 'L',
});

describe('annotationSummary', () => {
  it('describes each geometry', () => {
    expect(annotationSummary(ann({ kind: 'x_range', x0: 2.1, x1: 3.5 }), { inRange: 18 })).toBe(
      'x from 2.1 to 3.5 · 18 points',
    );
    expect(annotationSummary(ann({ kind: 'y_range', y0: 0, y1: 1 }))).toBe('y from 0 to 1');
    expect(annotationSummary(ann({ kind: 'x_range', x0: 0, x1: 1 }), { inRange: 1 })).toBe(
      'x from 0 to 1 · 1 point',
    );
    expect(annotationSummary(ann({ kind: 'ref_line', axis: 'y', value: 5 }))).toBe('y = 5');
    expect(annotationSummary(ann({ kind: 'arrow_note', x: 3, y: 4 }))).toBe('Note at (3, 4)');
  });
  it('counts marked points, with the found ones when some are missing', () => {
    const ids = Array.from({ length: 42 }, (_, i) => i);
    expect(annotationSummary(ann({ kind: 'points', column: 'id', ids }))).toBe('42 points');
    expect(annotationSummary(ann({ kind: 'points', column: 'id', ids }), { expected: 42, found: 40 })).toBe(
      '42 points (40 found)',
    );
    expect(annotationSummary(ann({ kind: 'points', coords: [{ x: 1, y: 1 }] }), { expected: 1, found: 1 })).toBe(
      '1 point',
    );
  });
});

describe('annotationHoverText', () => {
  it('lists the facts on separate lines', () => {
    expect(annotationHoverText(ann({ kind: 'x_range', x0: 1, x1: 2 }), { inRange: 3 })).toBe(
      'x from 1 to 2<br>3 points in range',
    );
    expect(annotationHoverText(ann({ kind: 'points', ids: [1, 2] }), { expected: 2, found: 2 })).toBe(
      '2 points marked',
    );
  });
});

describe('formatAxisValue', () => {
  it('keeps integers and strings, rounds long decimals', () => {
    expect(formatAxisValue(42)).toBe('42');
    expect(formatAxisValue('2024-01-01')).toBe('2024-01-01');
    expect(formatAxisValue(2.123456789)).toBe('2.123');
    expect(formatAxisValue(123456.789)).toBe('123457');
    expect(formatAxisValue(0.000123456)).toBe('0.0001235');
  });
});

describe('sameStats', () => {
  it('compares counts per annotation', () => {
    expect(sameStats({ a: { inRange: 1 } }, { a: { inRange: 1 } })).toBe(true);
    expect(sameStats({ a: { inRange: 1 } }, { a: { inRange: 2 } })).toBe(false);
    expect(sameStats({ a: { inRange: 1 } }, { b: { inRange: 1 } })).toBe(false);
    expect(sameStats({}, { a: {} })).toBe(false);
    expect(sameStats(undefined, {})).toBe(false);
  });
});
