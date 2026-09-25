import { describe, expect, it } from 'vitest';

import {
  annotationsToPlotly,
  countInRange,
  DEFAULT_RANGE_OPACITY,
  PREVIEW_OPACITY_FACTOR,
  regionShape,
  TOP_LABEL_ROW_PX,
  withAlpha,
} from './toPlotly';
import type { AnnotationColor, RenderableAnnotation } from './types';
import { ANNOTATION_COLORS, numberBadge, PREVIEW_ANNOTATION_ID } from './types';

// Fake resolver: a readable token, so tests can assert every colour went
// through it and nothing was hard-coded.
const resolveColor = (name: AnnotationColor, shade?: number) => `tok:${name}:${shade ?? 'd'}`;

const item = (
  id: string,
  number: number | null,
  annotation: RenderableAnnotation['annotation'],
): RenderableAnnotation => ({ id, number, annotation });

describe('numberBadge / palette', () => {
  it('circles 1..20 and falls back to (n)', () => {
    expect(numberBadge(1)).toBe('①');
    expect(numberBadge(20)).toBe('⑳');
    expect(numberBadge(21)).toBe('(21)');
    expect(numberBadge(0)).toBe('(0)');
  });
  it('lists the model palette in order', () => {
    expect(ANNOTATION_COLORS[0]).toBe('blue');
    expect(ANNOTATION_COLORS).toHaveLength(13);
    expect(ANNOTATION_COLORS[ANNOTATION_COLORS.length - 1]).toBe('gray');
  });
});

describe('annotationsToPlotly', () => {
  it('draws an x range as a paper-tall band behind the data, labelled on top', () => {
    const out = annotationsToPlotly(
      [item('a', 1, { kind: 'range', geometry: { kind: 'x_range', x0: 2, x1: 5 }, label: 'Outage', color: 'red' })],
      { resolveColor },
    );
    expect(out.shapes).toHaveLength(1);
    expect(out.shapes[0]).toMatchObject({
      type: 'rect',
      xref: 'x',
      yref: 'paper',
      x0: 2,
      x1: 5,
      y0: 0,
      y1: 1,
      layer: 'below',
      fillcolor: 'tok:red:d',
      opacity: 0.15,
      line: { width: 0 },
    });
    expect(out.annotations[0]).toMatchObject({ text: '① Outage', yref: 'paper', y: 1, yanchor: 'bottom' });
    expect(out.overlayTraces).toEqual([]);
  });

  it('draws a y range across the width, using the style opacity', () => {
    const out = annotationsToPlotly(
      [
        item('b', 2, {
          kind: 'range',
          geometry: { kind: 'y_range', y0: 10, y1: 3 },
          label: 'Normal',
          style: { opacity: 0.4 },
        }),
      ],
      { resolveColor },
    );
    expect(out.shapes[0]).toMatchObject({ xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: 10, y1: 3, opacity: 0.4 });
    expect(out.shapes[0].fillcolor).toBe('tok:yellow:d'); // default colour
    expect(out.annotations[0]).toMatchObject({ xref: 'paper', y: 10, text: '② Normal' });
  });

  it('draws reference lines on either axis, dashed by default', () => {
    const out = annotationsToPlotly(
      [
        item('v', 1, { kind: 'line', geometry: { kind: 'ref_line', axis: 'x', value: '2024-01-01' }, label: 'Release' }),
        item('h', 2, {
          kind: 'line',
          geometry: { kind: 'ref_line', axis: 'y', value: 0.05 },
          label: 'p = 0.05',
          style: { dash: 'dot', width: 3 },
        }),
      ],
      { resolveColor },
    );
    expect(out.shapes[0]).toMatchObject({
      type: 'line',
      layer: 'above',
      xref: 'x',
      yref: 'paper',
      x0: '2024-01-01',
      x1: '2024-01-01',
      y0: 0,
      y1: 1,
      line: { dash: 'dash', width: 1.5 },
    });
    expect(out.shapes[1]).toMatchObject({ xref: 'paper', yref: 'y', y0: 0.05, y1: 0.05, line: { dash: 'dot', width: 3 } });
    expect(out.annotations[1]).toMatchObject({ xref: 'paper', x: 1, y: 0.05 });
  });

  it('draws marked points from coords as an open-circle overlay trace', () => {
    const out = annotationsToPlotly(
      [
        item('p', 1, {
          kind: 'points',
          geometry: { kind: 'points', coords: [{ x: 1, y: 2 }, { x: 3, y: 4 }] },
          label: 'Outliers',
          color: 'grape',
        }),
      ],
      { resolveColor },
    );
    expect(out.overlayTraces).toHaveLength(1);
    expect(out.overlayTraces[0]).toMatchObject({
      type: 'scatter',
      mode: 'markers',
      x: [1, 3],
      y: [2, 4],
      hoverinfo: 'text',
      hovertext: 'Outliers<br>2 points marked',
      showlegend: false,
      name: 'annotation-p',
      marker: { symbol: 'circle-open', size: 14, color: 'tok:grape:d', line: { width: 2 } },
    });
    expect(out.annotations[0]).toMatchObject({ x: 1, y: 2, text: '① Outliers' });
    expect(out.stats.p).toEqual({ expected: 2, found: 2 });
  });

  describe('marked points on box traces', () => {
    // Trace 0 is a box drawn on a category axis: its points sit at jittered,
    // group-offset positions; trace 1 is a scatter drawn at its data coords.
    const high = { x: 0.62, y: 55.8, pos: 'Chinstrap', value: 55.8 };
    const top = { x: 0.86, y: 58, pos: 'Chinstrap', value: 58 };
    const renderedPoints = new Map([
      [0, { posLetter: 'x' as const, byIndex: new Map([[101, high], [7, top]]), points: [high, top] }],
    ]);

    it('rings box points where they are drawn, as pixel-sized circles', () => {
      const out = annotationsToPlotly(
        [
          item('p', 1, {
            kind: 'points',
            geometry: {
              kind: 'points',
              coords: [
                { x: 'Chinstrap', y: 55.8, trace: 0, index: 101 },
                { x: 'Chinstrap', y: 58, trace: 0 },
                { x: 3, y: 4, trace: 1 },
                { x: 'Chinstrap', y: 12, trace: 0 },
              ],
              region: { shape: 'box', x0: 0.52, x1: 1.17, y0: 49, y1: 59 },
            },
            label: 'Outliers',
            color: 'orange',
          }),
        ],
        { resolveColor, renderedPoints },
      );
      expect(out.shapes[0]).toMatchObject({ type: 'rect', xref: 'x', x0: 0.52, x1: 1.17, layer: 'below' });
      const rings = out.shapes.slice(1);
      expect(rings).toHaveLength(2);
      expect(rings[0]).toMatchObject({
        type: 'circle',
        xref: 'x',
        yref: 'y',
        xsizemode: 'pixel',
        ysizemode: 'pixel',
        xanchor: 0.62,
        yanchor: 55.8,
        x0: -7,
        x1: 7,
        layer: 'above',
        line: { color: 'tok:orange:d', width: 2 },
        name: 'annotation-p',
      });
      expect(rings[1]).toMatchObject({ xanchor: 0.86, yanchor: 58 });
      expect(out.overlayTraces).toHaveLength(1);
      expect(out.overlayTraces[0]).toMatchObject({ x: [3], y: [4] });
      expect(out.stats.p).toEqual({ expected: 4, found: 3 });
    });

    it('labels the first drawn ring when every point is on a box trace', () => {
      const out = annotationsToPlotly(
        [
          item('p', 1, {
            kind: 'points',
            geometry: { kind: 'points', coords: [{ x: 'Chinstrap', y: 58, trace: 0, index: 7 }] },
            label: 'Top',
          }),
        ],
        { resolveColor, renderedPoints, highlightId: 'p' },
      );
      expect(out.overlayTraces).toEqual([]);
      expect(out.shapes[0]).toMatchObject({ x0: -9, x1: 9, line: { width: 3 } });
      expect(out.annotations[0]).toMatchObject({ xref: 'x', x: 0.86, y: 58, text: '① Top' });
    });

    it('rings box points found by selection id at their drawn position', () => {
      const out = annotationsToPlotly(
        [item('p', 1, { kind: 'points', geometry: { kind: 'points', column: 'id', ids: ['b'] }, label: 'x' })],
        {
          resolveColor,
          renderedPoints,
          selectionColumnIndex: 0,
          traces: [{ x: ['Chinstrap', 'Chinstrap'], y: [55.8, 58], customdata: ['a', 'b'] }],
        },
      );
      // Row 1 is not index 1 in the rendered map: ringed at its data coords.
      expect(out.overlayTraces[0]).toMatchObject({ x: ['Chinstrap'], y: [58] });
      const byIndex = annotationsToPlotly(
        [item('p', 1, { kind: 'points', geometry: { kind: 'points', column: 'id', ids: ['b'] }, label: 'x' })],
        {
          resolveColor,
          renderedPoints,
          selectionColumnIndex: 0,
          traces: [{ x: Array(102).fill('Chinstrap'), y: Array(102).fill(55.8), customdata: [...Array(101).fill('z'), 'b'] }],
        },
      );
      expect(byIndex.overlayTraces).toEqual([]);
      expect(byIndex.shapes[0]).toMatchObject({ type: 'circle', xanchor: 0.62 });
      expect(byIndex.stats.p).toEqual({ expected: 1, found: 1 });
    });
  });

  it('shades a box region behind marked points, in the annotation colour', () => {
    const out = annotationsToPlotly(
      [
        item('p', 1, {
          kind: 'points',
          geometry: {
            kind: 'points',
            coords: [{ x: 1, y: 2 }],
            region: { shape: 'box', x0: 0, x1: 2, y0: 1, y1: 3 },
          },
          label: 'Cluster',
          color: 'teal',
        }),
      ],
      { resolveColor },
    );
    expect(out.shapes).toHaveLength(1);
    expect(out.shapes[0]).toMatchObject({
      type: 'rect',
      xref: 'x',
      yref: 'y',
      x0: 0,
      x1: 2,
      y0: 1,
      y1: 3,
      layer: 'below',
      fillcolor: 'tok:teal:d',
      opacity: DEFAULT_RANGE_OPACITY,
      line: { color: 'tok:teal:d', dash: 'dot' },
      name: 'annotation-p',
    });
    expect(out.overlayTraces).toHaveLength(1);
  });

  it('draws a lasso region as a closed path with the style fill opacity', () => {
    const geometry = {
      kind: 'points' as const,
      coords: [{ x: 1, y: 1 }],
      region: { shape: 'lasso' as const, x: [0, 2, 1], y: [0, 0, 2] },
    };
    const out = annotationsToPlotly(
      [item('p', 1, { kind: 'points', geometry, label: 'L', style: { fill_opacity: 0.4 } })],
      { resolveColor },
    );
    expect(out.shapes[0]).toMatchObject({ type: 'path', path: 'M0,0 L2,0 L1,2 Z', opacity: 0.4 });

    const hi = annotationsToPlotly(
      [item('p', 1, { kind: 'points', geometry, label: 'L', style: { fill_opacity: 0.4 } })],
      { resolveColor, highlightId: 'p' },
    );
    expect(hi.shapes[0].opacity as number).toBeGreaterThan(0.4);
  });

  it('draws no region when fill_opacity is 0 or the lasso is not numeric', () => {
    const zero = annotationsToPlotly(
      [
        item('p', 1, {
          kind: 'points',
          geometry: {
            kind: 'points',
            coords: [{ x: 1, y: 1 }],
            region: { shape: 'box', x0: 0, x1: 2, y0: 0, y1: 2 },
          },
          label: 'z',
          style: { fill_opacity: 0 },
        }),
      ],
      { resolveColor, highlightId: 'p' },
    );
    expect(zero.shapes).toHaveLength(0);
    expect(regionShape({ shape: 'lasso', x: ['a', 'b', 'c'], y: [0, 1, 2] })).toBeNull();
    expect(regionShape({ shape: 'lasso', x: [0, 1], y: [0, 1] })).toBeNull();
    expect(regionShape({ shape: 'box', x0: 'a', x1: 'c', y0: 0, y1: 1 })).toMatchObject({
      type: 'rect',
      x0: 'a',
    });
  });

  it('keeps the region when no marked point is found in the figure', () => {
    const out = annotationsToPlotly(
      [
        item('p', 1, {
          kind: 'points',
          geometry: {
            kind: 'points',
            column: 'id',
            ids: ['gone'],
            region: { shape: 'box', x0: 0, x1: 1, y0: 0, y1: 1 },
          },
          label: 'x',
        }),
      ],
      { resolveColor, traces: [], selectionColumnIndex: 0 },
    );
    expect(out.shapes).toHaveLength(1);
    expect(out.overlayTraces).toHaveLength(0);
  });

  it('resolves marked points by selection id through trace customdata', () => {
    const traces = [
      { x: [1, 2, 3], y: [10, 20, 30], customdata: [['s1', 'a'], ['s2', 'b'], ['s3', 'c']] },
      { x: [4], y: [40], customdata: [['s4', 'd']] },
    ];
    const out = annotationsToPlotly(
      [
        item('p', 1, {
          kind: 'points',
          geometry: { kind: 'points', column: 'sample', ids: ['s3', 's4', 'gone'] },
          label: 'Flagged',
        }),
      ],
      { resolveColor, traces, selectionColumnIndex: 0 },
    );
    expect(out.overlayTraces[0]).toMatchObject({ x: [3, 4], y: [30, 40] });
    expect(out.stats.p).toEqual({ expected: 3, found: 2 });
  });

  it('matches numeric ids against string customdata and dedupes repeated rows', () => {
    const traces = [{ x: [1, 1], y: [2, 2], customdata: ['7', '7'] }];
    const out = annotationsToPlotly(
      [item('p', 1, { kind: 'points', geometry: { kind: 'points', column: 'id', ids: [7] }, label: 'x' })],
      { resolveColor, traces, selectionColumnIndex: 0 },
    );
    expect(out.overlayTraces[0]).toMatchObject({ x: [1], y: [2] });
    expect(out.stats.p).toEqual({ expected: 1, found: 1 });
  });

  it('emits nothing for unresolvable ids but reports the miss', () => {
    const out = annotationsToPlotly(
      [item('p', 1, { kind: 'points', geometry: { kind: 'points', column: 'id', ids: ['a', 'b'] }, label: 'x' })],
      { resolveColor, traces: [{ x: [1], y: [1], customdata: [['z']] }], selectionColumnIndex: 0 },
    );
    expect(out.overlayTraces).toEqual([]);
    expect(out.annotations).toEqual([]);
    expect(out.stats.p).toEqual({ expected: 2, found: 0 });

    const noIndex = annotationsToPlotly(
      [item('p', 1, { kind: 'points', geometry: { kind: 'points', column: 'id', ids: ['a'] }, label: 'x' })],
      { resolveColor },
    );
    expect(noIndex.stats.p).toEqual({ expected: 1, found: 0 });
  });

  it('draws an arrow note with pixel offsets and a translucent box', () => {
    const colour = (name: AnnotationColor) => (name === 'teal' ? '#12b886' : 'x');
    const out = annotationsToPlotly(
      [item('n', 3, { kind: 'note', geometry: { kind: 'arrow_note', x: 5, y: 6, ax: 20, ay: -30 }, label: 'Peak', color: 'teal' })],
      { resolveColor: colour, fontColor: 'fg' },
    );
    expect(out.annotations[0]).toMatchObject({
      showarrow: true,
      x: 5,
      y: 6,
      ax: 20,
      ay: -30,
      text: '③ Peak',
      arrowcolor: '#12b886',
      bordercolor: '#12b886',
      bgcolor: 'rgba(18, 184, 134, 0.2)',
      font: { color: 'fg' },
    });
    expect(out.shapes).toEqual([]);
  });

  it('omits the badge for unnumbered annotations', () => {
    const out = annotationsToPlotly(
      [item('n', null, { kind: 'note', geometry: { kind: 'arrow_note', x: 1, y: 1 }, label: 'Draft' })],
      { resolveColor },
    );
    expect(out.annotations[0]).toMatchObject({ text: 'Draft', ax: -40, ay: -40 });
  });

  it('emphasises the highlighted annotation only', () => {
    const items = [
      item('a', 1, { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 1 }, label: 'a' }),
      item('b', 2, { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 2 }, label: 'b' }),
      item('c', 3, { kind: 'range', geometry: { kind: 'x_range', x0: 0, x1: 1 }, label: 'c' }),
    ];
    const plain = annotationsToPlotly(items, { resolveColor });
    const hi = annotationsToPlotly(items, { resolveColor, highlightId: 'b' });
    expect(hi.shapes[0]).toEqual(plain.shapes[0]);
    expect(hi.shapes[1].line?.width).toBeGreaterThan(plain.shapes[1].line?.width as number);
    const hiRange = annotationsToPlotly(items, { resolveColor, highlightId: 'c' });
    expect(hiRange.shapes[2].opacity as number).toBeGreaterThan(plain.shapes[2].opacity as number);
  });

  it('orders output by number then id, whatever the input order', () => {
    const a = item('a', 2, { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 2 }, label: 'two' });
    const b = item('b', 1, { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 1 }, label: 'one' });
    const c = item('c', null, { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 3 }, label: 'draft' });
    const out1 = annotationsToPlotly([c, a, b], { resolveColor });
    const out2 = annotationsToPlotly([b, c, a], { resolveColor });
    expect(out1).toEqual(out2);
    expect(out1.annotations.map((x) => x.text)).toEqual(['① one', '② two', 'draft']);
  });

  it('never emits a colour that did not come through resolveColor', () => {
    const out = annotationsToPlotly(
      [
        item('a', 1, { kind: 'range', geometry: { kind: 'x_range', x0: 0, x1: 1 }, label: 'a' }),
        item('b', 2, { kind: 'line', geometry: { kind: 'ref_line', axis: 'x', value: 1 }, label: 'b' }),
        item('c', 3, {
          kind: 'points',
          geometry: {
            kind: 'points',
            coords: [{ x: 1, y: 1 }],
            region: { shape: 'lasso', x: [0, 1, 1], y: [0, 0, 1] },
          },
          label: 'c',
        }),
        item('d', 4, { kind: 'note', geometry: { kind: 'arrow_note', x: 1, y: 1 }, label: 'd' }),
      ],
      { resolveColor },
    );
    const json = JSON.stringify(out);
    expect(json).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(json).not.toMatch(/rgba?\(/);
  });
});

describe('withAlpha', () => {
  it('handles hex, short hex and rgb, and passes unknown formats through', () => {
    expect(withAlpha('#ff0000', 0.5)).toBe('rgba(255, 0, 0, 0.5)');
    expect(withAlpha('#0f0', 1)).toBe('rgba(0, 255, 0, 1)');
    expect(withAlpha('rgb(1, 2, 3)', 0.1)).toBe('rgba(1, 2, 3, 0.1)');
    expect(withAlpha('var(--x)', 0.1)).toBe('var(--x)');
  });
});

describe('annotation facts and clicks', () => {
  const traces = [
    { x: [1, 2, 3, 4, 5], y: [10, 20, 30, 40, 50] },
    { x: [2.5, 9], y: [5, 60] },
  ];

  it('counts the data points inside x and y ranges', () => {
    const out = annotationsToPlotly(
      [
        item('x', 1, { kind: 'range', geometry: { kind: 'x_range', x0: 2, x1: 4 }, label: 'Mid' }),
        item('y', 2, { kind: 'range', geometry: { kind: 'y_range', y0: 25, y1: 60 }, label: 'High' }),
      ],
      { resolveColor, traces },
    );
    expect(out.stats).toEqual({ x: { inRange: 4 }, y: { inRange: 4 } });
    expect(out.annotations[0]).toMatchObject({ hovertext: 'x from 2 to 4<br>4 points in range' });
  });

  it('counts dates and skips categorical axes', () => {
    const dated = [{ x: ['2024-01-01', '2024-01-15', '2024-03-01'], y: [1, 2, 3] }];
    expect(countInRange(dated, 'x', '2024-01-01', '2024-02-01')).toBe(2);
    expect(countInRange([{ x: ['a', 'b'], y: [1, 2] }], 'x', 0, 1)).toBeUndefined();
    expect(countInRange(undefined, 'x', 0, 1)).toBeUndefined();
    const out = annotationsToPlotly(
      [item('c', 1, { kind: 'range', geometry: { kind: 'x_range', x0: 0.5, x1: 1.5 }, label: 'Cat' })],
      { resolveColor, traces: [{ x: ['a', 'b'], y: [1, 2] }] },
    );
    expect(out.stats).toEqual({});
    expect(out.annotations[0]).toMatchObject({ hovertext: 'x from 0.5 to 1.5' });
  });

  it('describes lines, notes and missing points in the hover text', () => {
    const out = annotationsToPlotly(
      [
        item('l', 1, { kind: 'line', geometry: { kind: 'ref_line', axis: 'y', value: 5 }, label: 'Cut' }),
        item('n', 2, { kind: 'note', geometry: { kind: 'arrow_note', x: 3, y: 4 }, label: 'Here' }),
        item('p', 3, {
          kind: 'points',
          geometry: { kind: 'points', column: 'id', ids: ['s1', 's2', 'zz'] },
          label: 'Picked',
        }),
      ],
      {
        resolveColor,
        traces: [{ x: [1, 2], y: [3, 4], customdata: ['s1', 's2'] }],
        selectionColumnIndex: 0,
      },
    );
    expect(out.annotations.map((a) => a.hovertext)).toEqual([
      'y = 5',
      'Note at (3, 4)',
      '3 points marked<br>2 of 3 found',
    ]);
    expect(out.stats.p).toEqual({ expected: 3, found: 2 });
  });

  it('makes saved labels clickable and names them after their thread', () => {
    const out = annotationsToPlotly(
      [
        item('t1', 1, { kind: 'line', geometry: { kind: 'ref_line', axis: 'x', value: 2 }, label: 'L' }),
        item('t2', 2, { kind: 'note', geometry: { kind: 'arrow_note', x: 1, y: 1 }, label: 'N' }),
      ],
      { resolveColor },
    );
    expect(out.annotations[0]).toMatchObject({ name: 'annotation-t1', captureevents: true });
    expect(out.annotations[1]).toMatchObject({ name: 'annotation-t2', captureevents: true });
  });

  it('draws the preview dashed and faded, never clickable', () => {
    const preview: RenderableAnnotation = {
      id: PREVIEW_ANNOTATION_ID,
      number: null,
      preview: true,
      annotation: {
        kind: 'range',
        geometry: { kind: 'x_range', x0: 1, x1: 2 },
        label: 'Typing',
        color: 'teal',
      },
    };
    const out = annotationsToPlotly([preview], { resolveColor, traces });
    expect(out.shapes[0]).toMatchObject({
      fillcolor: 'tok:teal:d',
      opacity: DEFAULT_RANGE_OPACITY * PREVIEW_OPACITY_FACTOR,
      line: { dash: 'dash' },
    });
    expect(out.annotations[0]).toMatchObject({ text: 'Typing', opacity: PREVIEW_OPACITY_FACTOR });
    expect(out.annotations[0]).not.toHaveProperty('captureevents');
    expect(out.annotations[0]).not.toHaveProperty('name');
    expect(out.annotations[0]).not.toHaveProperty('hovertext');
    expect(out.stats[PREVIEW_ANNOTATION_ID]).toEqual({ inRange: 2 });

    const points = annotationsToPlotly(
      [
        {
          ...preview,
          annotation: {
            kind: 'points',
            geometry: { kind: 'points', coords: [{ x: 1, y: 1 }], region: { shape: 'box', x0: 0, x1: 2, y0: 0, y1: 2 } },
            label: 'Marked points',
            style: { fill_opacity: 0.4 },
          },
        },
      ],
      { resolveColor },
    );
    expect(points.overlayTraces[0]).toMatchObject({ hoverinfo: 'skip' });
    expect(points.shapes[0]).toMatchObject({ opacity: 0.4 * PREVIEW_OPACITY_FACTOR, line: { dash: 'dash' } });
  });
});

describe('top-edge label stacking', () => {
  const resolveColor = () => '#228be6';
  const item = (id: string, geometry: RenderableAnnotation['annotation']['geometry']): RenderableAnnotation => ({
    id,
    number: null,
    annotation: { kind: geometry.kind === 'ref_line' ? 'line' : 'range', geometry, label: id },
  });

  it('puts each x range and vertical line one row above the previous', () => {
    const out = annotationsToPlotly(
      [
        item('a', { kind: 'x_range', x0: 1, x1: 2 }),
        item('b', { kind: 'ref_line', axis: 'x', value: 3 }),
        item('c', { kind: 'y_range', y0: 1, y1: 2 }),
      ],
      { resolveColor },
    );
    expect(out.annotations.map((a) => a.yshift ?? 0)).toEqual([0, TOP_LABEL_ROW_PX, 0]);
    expect(out.topLabelCount).toBe(2);
  });

  it('starts after an offset, for a preview drawn over saved labels', () => {
    const out = annotationsToPlotly([item('p', { kind: 'x_range', x0: 1, x1: 2 })], {
      resolveColor,
      topLabelOffset: 2,
    });
    expect(out.annotations[0].yshift).toBe(2 * TOP_LABEL_ROW_PX);
  });
});
