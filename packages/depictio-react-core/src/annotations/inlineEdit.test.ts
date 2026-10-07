import { describe, expect, it } from 'vitest';

import { annotationPatch, effectiveStyle } from './edit';
import {
  anchorOffset,
  applyAnnotationPatch,
  clientPointFromEvent,
  itemsWithEditDraft,
  nextEditDraft,
  withEditDraft,
} from './inlineEdit';
import type { Annotation, RenderableAnnotation } from './types';

const region = { shape: 'box' as const, x0: 0, x1: 1, y0: 0, y1: 1 };
const line: Annotation = {
  kind: 'line',
  geometry: { kind: 'ref_line', axis: 'x', value: 3 },
  label: 'Cutoff',
  color: 'red',
  style: { dash: 'dash', width: 2 },
};
const points: Annotation = {
  kind: 'points',
  geometry: { kind: 'points', coords: [{ x: 0, y: 0 }], region },
  label: 'Outliers',
};
const item = (id: string, annotation: Annotation): RenderableAnnotation => ({ id, number: 1, annotation });

describe('applyAnnotationPatch', () => {
  it('overrides label, colour, style and geometry', () => {
    const geometry = { kind: 'ref_line' as const, axis: 'x' as const, value: 3 };
    expect(
      applyAnnotationPatch(line, { label: 'New', color: 'blue', style: { dash: 'dot' }, geometry }),
    ).toEqual({ ...line, label: 'New', color: 'blue', style: { dash: 'dot' }, geometry });
  });
  it('keeps the saved label while the field is empty', () => {
    expect(applyAnnotationPatch(line, { label: '' }).label).toBe('Cutoff');
  });
  it('leaves the annotation untouched for an empty patch', () => {
    expect(applyAnnotationPatch(line, {})).toEqual(line);
  });
  it('draws what the editor would save (region dropped, style changed)', () => {
    const patch = annotationPatch(points, {
      label: 'Outliers',
      color: 'yellow',
      style: { ...effectiveStyle(points), width: 4 },
      keepRegion: false,
    });
    const drawn = applyAnnotationPatch(points, patch);
    expect(drawn.style?.width).toBe(4);
    expect(drawn.geometry).toEqual({ kind: 'points', coords: [{ x: 0, y: 0 }] });
  });
});

describe('nextEditDraft', () => {
  it('sets, replaces and clears a thread draft', () => {
    const a = nextEditDraft(null, 't1', { label: 'x' });
    expect(a).toEqual({ threadId: 't1', patch: { label: 'x' } });
    expect(nextEditDraft(a, 't1', { color: 'red' })).toEqual({ threadId: 't1', patch: { color: 'red' } });
    expect(nextEditDraft(a, 't1', {})).toBeNull();
    expect(nextEditDraft(a, 't1', null)).toBeNull();
  });
  it('never clears another thread draft', () => {
    const a = nextEditDraft(null, 't1', { label: 'x' });
    expect(nextEditDraft(a, 't2', {})).toBe(a);
    expect(nextEditDraft(null, 't2', {})).toBeNull();
  });
});

describe('withEditDraft / itemsWithEditDraft', () => {
  const items = [item('t1', line), item('t2', points)];
  it('draws the draft over its thread only', () => {
    const next = withEditDraft(items, { threadId: 't2', patch: { color: 'teal' } });
    expect(next).not.toBe(items);
    expect(next[0]).toBe(items[0]);
    expect(next[1].annotation.color).toBe('teal');
    expect(items[1].annotation.color).toBeUndefined();
  });
  it('keeps the same array when nothing applies', () => {
    expect(withEditDraft(items, null)).toBe(items);
    expect(withEditDraft(items, { threadId: 't1', patch: {} })).toBe(items);
    expect(withEditDraft(items, { threadId: 'other', patch: { label: 'y' } })).toBe(items);
  });
  it('replaces only the component holding the thread', () => {
    const other = [item('t9', line)];
    const byComponent = { a: items, b: other };
    const next = itemsWithEditDraft(byComponent, { threadId: 't1', patch: { label: 'Edited' } });
    expect(next.b).toBe(other);
    expect(next.a[0].annotation.label).toBe('Edited');
    expect(itemsWithEditDraft(byComponent, { threadId: 'nope', patch: { label: 'y' } })).toBe(byComponent);
    expect(itemsWithEditDraft(byComponent, null)).toBe(byComponent);
  });
});

describe('clientPointFromEvent', () => {
  it('reads a DOM event or a Plotly event wrapping one', () => {
    expect(clientPointFromEvent({ clientX: 4, clientY: 5 })).toEqual({ x: 4, y: 5 });
    expect(clientPointFromEvent({ points: [], event: { clientX: 1, clientY: 2 } })).toEqual({ x: 1, y: 2 });
  });
  it('returns null without coordinates', () => {
    expect(clientPointFromEvent(null)).toBeNull();
    expect(clientPointFromEvent({ annotation: {} })).toBeNull();
  });
});

describe('anchorOffset', () => {
  const frame = { left: 100, top: 50, width: 200, height: 100 };
  it('places the anchor relative to the frame, clamped inside it', () => {
    expect(anchorOffset({ x: 150, y: 70 }, frame)).toEqual({ left: 50, top: 20 });
    expect(anchorOffset({ x: 0, y: 500 }, frame)).toEqual({ left: 0, top: 100 });
  });
  it('centres the anchor without a click position', () => {
    expect(anchorOffset(null, frame)).toEqual({ left: 100, top: 50 });
  });
});
