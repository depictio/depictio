import { describe, expect, it } from 'vitest';

import {
  annotateHint,
  annotateInteraction,
  customdataRow,
  DEFAULT_ANNOTATE_OPTIONS,
  isOverlayTraceName,
  kindForGeometry,
  normalizeTraces,
  pixelToData,
  pointMisses,
  publishedToRenderable,
  stripOverlayPoints,
  supportsAnnotation,
  threadsToRenderable,
  validateLabel,
} from './layer';
import type { ThreadLike } from './layer';
import { annotationsToPlotly, OVERLAY_TRACE_PREFIX } from './toPlotly';
import type { Annotation } from './types';

describe('annotateInteraction', () => {
  it('captures ranges from a box selection, on either axis', () => {
    for (const rangeAxis of ['x', 'y'] as const) {
      expect(annotateInteraction('range', { ...DEFAULT_ANNOTATE_OPTIONS, rangeAxis })).toEqual({
        dragmode: 'select',
        capture: 'selected',
      });
    }
  });
  it('captures points from the chosen selection gesture', () => {
    expect(annotateInteraction('points', { ...DEFAULT_ANNOTATE_OPTIONS, selectMode: 'select' })).toEqual({
      dragmode: 'select',
      capture: 'selected',
    });
    expect(annotateInteraction('points').dragmode).toBe('lasso');
  });
  it('captures lines and notes from clicks, with no drag gesture', () => {
    for (const tool of ['line', 'note'] as const) {
      expect(annotateInteraction(tool)).toEqual({ dragmode: false, capture: 'click' });
    }
  });
});

describe('annotateHint', () => {
  it('names the line direction and the axis its value is read on', () => {
    expect(annotateHint('line', { ...DEFAULT_ANNOTATE_OPTIONS, lineAxis: 'x' })).toBe(
      'Click to place a vertical line at an x value',
    );
    expect(annotateHint('line', { ...DEFAULT_ANNOTATE_OPTIONS, lineAxis: 'y' })).toBe(
      'Click to place a horizontal line at a y value',
    );
  });
  it('explains that only the tool axis of a range box counts', () => {
    expect(annotateHint('range', { ...DEFAULT_ANNOTATE_OPTIONS, rangeAxis: 'y' })).toBe(
      'Drag a box: its y extent becomes the range',
    );
  });
});

describe('kindForGeometry / validateLabel', () => {
  it('maps geometries to kinds', () => {
    expect(kindForGeometry({ kind: 'x_range', x0: 1, x1: 2 })).toBe('range');
    expect(kindForGeometry({ kind: 'y_range', y0: 1, y1: 2 })).toBe('range');
    expect(kindForGeometry({ kind: 'ref_line', axis: 'x', value: 1 })).toBe('line');
    expect(kindForGeometry({ kind: 'points', ids: [1] })).toBe('points');
    expect(kindForGeometry({ kind: 'arrow_note', x: 1, y: 2 })).toBe('note');
  });
  it('requires a short non-blank label', () => {
    expect(validateLabel('  ')).not.toBeNull();
    expect(validateLabel('x'.repeat(121))).not.toBeNull();
    expect(validateLabel(' Peak ')).toBeNull();
  });
});

describe('overlay filtering', () => {
  it('recognises overlay trace names', () => {
    expect(isOverlayTraceName(`${OVERLAY_TRACE_PREFIX}abc`)).toBe(true);
    expect(isOverlayTraceName('__depictio_new_items')).toBe(true);
    expect(isOverlayTraceName('setosa')).toBe(false);
    expect(isOverlayTraceName(undefined)).toBe(false);
  });
  it('drops overlay points and normalises customdata rows', () => {
    const ev = {
      points: [
        { x: 1, y: 2, customdata: { 0: 'a', 1: 'b' }, data: { name: 'real' } },
        { x: 3, y: 4, data: { name: `${OVERLAY_TRACE_PREFIX}t1` } },
        { x: 5, y: 6, customdata: new Float64Array([7, 8]), fullData: { name: 'real' } },
      ],
    };
    const out = stripOverlayPoints(ev);
    expect(out.points).toHaveLength(2);
    expect(out.points[0].customdata).toEqual(['a', 'b']);
    expect(out.points[1].customdata).toEqual([7, 8]);
    expect(stripOverlayPoints(null).points).toEqual([]);
  });
  it('leaves scalars alone in customdataRow', () => {
    expect(customdataRow('id-1')).toBe('id-1');
    expect(customdataRow(['a'])).toEqual(['a']);
  });
});

describe('normalizeTraces', () => {
  it('picks the selection column, keeps indices aligned and skips overlays', () => {
    const traces = normalizeTraces(
      [
        { x: [1, 2, 3], y: [4, 5, 6], customdata: [['a', 0], null, ['c', 2]] },
        { name: `${OVERLAY_TRACE_PREFIX}x`, x: [1], y: [1] },
      ],
      0,
    );
    expect(traces).toHaveLength(1);
    expect(traces[0].customdata).toEqual(['a', null, 'c']);
  });
  it('decodes the typed-array transport', () => {
    // float64 [10, 20]
    const bdata = Buffer.from(new Float64Array([10, 20]).buffer).toString('base64');
    const ids = Buffer.from(new Float64Array([1, 9, 2, 8]).buffer).toString('base64');
    const [t] = normalizeTraces(
      [
        {
          x: { dtype: 'f8', bdata },
          y: [1, 2],
          customdata: { dtype: 'f8', bdata: ids, shape: '2, 2' },
        },
      ],
      1,
    );
    expect(t.x).toEqual([10, 20]);
    expect(t.customdata).toEqual(['9', '8']);
  });
  it('lets annotationsToPlotly resolve marked points by id', () => {
    const traces = normalizeTraces([{ x: [1, 2, 3], y: [4, 5, 6], customdata: [['a'], ['b'], ['c']] }], 0);
    const res = annotationsToPlotly(
      [
        {
          id: 't1',
          number: 1,
          annotation: { kind: 'points', label: 'P', geometry: { kind: 'points', column: 'id', ids: ['a', 'c', 'z'] } },
        },
      ],
      { resolveColor: () => 'currentColor', traces, selectionColumnIndex: 0 },
    );
    expect(res.stats.t1).toEqual({ expected: 3, found: 2 });
  });
});

describe('supportsAnnotation', () => {
  it('accepts cartesian figures only', () => {
    expect(supportsAnnotation({ component_type: 'figure', visu_type: 'scatter' })).toBe(true);
    expect(supportsAnnotation({ component_type: 'figure' })).toBe(true);
    expect(supportsAnnotation({ component_type: 'figure', visu_type: 'pie' })).toBe(false);
    expect(supportsAnnotation({ component_type: 'figure', visu_type: 'scatter_3d' })).toBe(false);
    expect(supportsAnnotation({ component_type: 'table' })).toBe(false);
  });
});

const ann = (over: Partial<Annotation> = {}): Annotation => ({
  kind: 'line',
  label: 'L',
  geometry: { kind: 'ref_line', axis: 'x', value: 3 },
  ...over,
});

describe('threadsToRenderable', () => {
  it('groups annotation threads by component and drops the rest', () => {
    const threads: ThreadLike[] = [
      { id: 'a', number: 1, status: 'open', annotation: ann(), anchor: { component_index: 'c1' } },
      { id: 'b', number: 2, status: 'resolved', annotation: ann(), anchor: { component_index: 'c1' } },
      { id: 'c', status: 'rejected', annotation: ann(), anchor: { component_index: 'c1' } },
      { id: 'd', status: 'open', annotation: null, anchor: { component_index: 'c1' } },
      { id: 'e', status: 'open', annotation: ann(), anchor: { component_index: null } },
      { id: 'f', number: 3, status: 'open', annotation: ann(), anchor: { component_index: 'c2' } },
    ];
    const out = threadsToRenderable(threads);
    expect(Object.keys(out).sort()).toEqual(['c1', 'c2']);
    expect(out.c1.map((i) => i.id)).toEqual(['a', 'b']);
    expect(out.c1[0].number).toBe(1);
  });
  it('fades and dots agent proposals', () => {
    const out = threadsToRenderable([
      {
        id: 'p',
        status: 'proposed',
        annotation: ann({ kind: 'range', geometry: { kind: 'x_range', x0: 1, x1: 2 } }),
        anchor: { component_index: 'c1' },
      },
    ]);
    const style = out.c1[0].annotation.style!;
    expect(style.dash).toBe('dot');
    expect(style.opacity).toBeCloseTo(0.075);
  });
});

describe('publishedToRenderable', () => {
  it('maps published annotations', () => {
    const out = publishedToRenderable([
      {
        thread_id: 't',
        component_index: 'c1',
        number: 4,
        kind: 'note',
        geometry: { kind: 'arrow_note', x: 1, y: 2 },
        label: 'N',
        color: 'blue',
        style: {},
      },
      {
        thread_id: 'u',
        component_index: null,
        number: null,
        kind: 'note',
        geometry: { kind: 'arrow_note', x: 1, y: 2 },
        label: 'N',
        color: 'blue',
        style: {},
      },
    ]);
    expect(out.c1).toEqual([
      {
        id: 't',
        number: 4,
        annotation: {
          kind: 'note',
          geometry: { kind: 'arrow_note', x: 1, y: 2 },
          label: 'N',
          color: 'blue',
          style: {},
          published: true,
        },
      },
    ]);
    expect(Object.keys(out)).toEqual(['c1']);
  });
});

describe('pixelToData', () => {
  const layout = {
    xaxis: { _offset: 50, _length: 100, p2d: (px: number) => px / 10 },
    yaxis: { _offset: 20, _length: 80, p2d: (py: number) => 100 - py },
  };
  it('converts a click inside the plot area', () => {
    expect(pixelToData(160, 60, { left: 10, top: 10 }, layout)).toEqual({ x: 10, y: 70 });
  });
  it('ignores clicks outside the plot area or without axes', () => {
    expect(pixelToData(20, 60, { left: 10, top: 10 }, layout)).toBeNull();
    expect(pixelToData(300, 60, { left: 10, top: 10 }, layout)).toBeNull();
    expect(pixelToData(160, 60, { left: 10, top: 10 }, {})).toBeNull();
  });
});

describe('pointMisses', () => {
  it('lists annotations with missing points, by badge number', () => {
    const items = [
      { id: 'a', number: 2, annotation: ann() },
      { id: 'b', number: 1, annotation: ann() },
    ];
    expect(
      pointMisses(
        {
          a: { expected: 15, found: 12 },
          b: { expected: 3, found: 0 },
          c: { expected: 2, found: 2 },
          r: { inRange: 4 },
        },
        items,
      ),
    ).toEqual([
      { id: 'b', number: 1, expected: 3, found: 0 },
      { id: 'a', number: 2, expected: 15, found: 12 },
    ]);
  });
});
