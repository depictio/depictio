import { describe, expect, it } from 'vitest';

import { annotationPatch, effectiveStyle, hasRegion, withoutRegion } from './edit';
import type { AnnotationEdits } from './edit';
import { DEFAULT_LINE_WIDTH, DEFAULT_POINT_RING_WIDTH, DEFAULT_RANGE_OPACITY } from './toPlotly';
import type { Annotation, MarkedPoints } from './types';

const region = { shape: 'box' as const, x0: 0, x1: 1, y0: 0, y1: 1 };
const points: MarkedPoints = { kind: 'points', coords: [{ x: 0, y: 0 }], region };

const unchanged = (a: Annotation): AnnotationEdits => ({
  label: a.label,
  color: a.color ?? 'yellow',
  style: effectiveStyle(a),
  keepRegion: true,
});

describe('region helpers', () => {
  it('detects and drops a marked-points region', () => {
    expect(hasRegion(points)).toBe(true);
    expect(withoutRegion(points)).toEqual({ kind: 'points', coords: [{ x: 0, y: 0 }] });
    expect('region' in withoutRegion(points)).toBe(false);
    const line = { kind: 'ref_line' as const, axis: 'x' as const, value: 1 };
    expect(hasRegion(line)).toBe(false);
    expect(withoutRegion(line)).toBe(line);
  });
});

describe('effectiveStyle', () => {
  it('fills in the drawing defaults per kind', () => {
    const range: Annotation = { kind: 'range', geometry: { kind: 'x_range', x0: 0, x1: 1 }, label: 'r' };
    expect(effectiveStyle(range).opacity).toBe(DEFAULT_RANGE_OPACITY);
    const line: Annotation = { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 0 }, label: 'l' };
    expect(effectiveStyle(line)).toMatchObject({ opacity: 1, dash: 'dash', width: DEFAULT_LINE_WIDTH });
    const pts: Annotation = { kind: 'points', geometry: points, label: 'p', style: { fill_opacity: 0.3 } };
    expect(effectiveStyle(pts)).toMatchObject({ width: DEFAULT_POINT_RING_WIDTH, fillOpacity: 0.3 });
  });
});

describe('annotationPatch', () => {
  it('is empty when nothing changed', () => {
    const a: Annotation = { kind: 'points', geometry: points, label: 'p', color: 'teal' };
    expect(annotationPatch(a, unchanged(a))).toEqual({});
  });

  it('sends a trimmed label and a new colour only when they differ', () => {
    const a: Annotation = { kind: 'note', geometry: { kind: 'arrow_note', x: 0, y: 0 }, label: 'n' };
    expect(annotationPatch(a, { ...unchanged(a), label: '  n  ' })).toEqual({});
    expect(annotationPatch(a, { ...unchanged(a), label: 'new', color: 'red' })).toEqual({
      label: 'new',
      color: 'red',
    });
  });

  it('sends the whole style, keeping stored fields, when a line control changes', () => {
    const a: Annotation = {
      kind: 'line',
      geometry: { kind: 'ref_line', axis: 'x', value: 1 },
      label: 'l',
      style: { opacity: 0.8 },
    };
    const edits = unchanged(a);
    expect(annotationPatch(a, { ...edits, style: { ...edits.style, dash: 'dot', width: 3 } })).toEqual({
      style: { opacity: 0.8, dash: 'dot', width: 3 },
    });
  });

  it('ignores style controls that do not apply to the kind', () => {
    const a: Annotation = { kind: 'range', geometry: { kind: 'x_range', x0: 0, x1: 1 }, label: 'r' };
    const edits = unchanged(a);
    expect(annotationPatch(a, { ...edits, style: { ...edits.style, dash: 'dot', width: 4 } })).toEqual({});
    expect(annotationPatch(a, { ...edits, style: { ...edits.style, opacity: 0.4 } })).toEqual({
      style: { opacity: 0.4 },
    });
  });

  it('edits the region opacity, or drops the region through the geometry', () => {
    const a: Annotation = { kind: 'points', geometry: points, label: 'p', style: { width: 3 } };
    const edits = unchanged(a);
    expect(annotationPatch(a, { ...edits, style: { ...edits.style, fillOpacity: 0.5 } })).toEqual({
      style: { width: 3, fill_opacity: 0.5 },
    });
    expect(
      annotationPatch(a, { ...edits, keepRegion: false, style: { ...edits.style, fillOpacity: 0.5 } }),
    ).toEqual({ geometry: { kind: 'points', coords: [{ x: 0, y: 0 }] } });
  });
});
