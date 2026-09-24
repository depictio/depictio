import { describe, expect, it } from 'vitest';

import { annotationsToPlotly, withAlpha } from './toPlotly';
import type { AnnotationColor, RenderableAnnotation } from './types';
import { ANNOTATION_COLORS, numberBadge } from './types';

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
      hoverinfo: 'skip',
      showlegend: false,
      name: 'annotation-p',
      marker: { symbol: 'circle-open', size: 14, color: 'tok:grape:d', line: { width: 2 } },
    });
    expect(out.annotations[0]).toMatchObject({ x: 1, y: 2, text: '① Outliers' });
    expect(out.stats.p).toEqual({ expected: 2, found: 2 });
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
        item('c', 3, { kind: 'points', geometry: { kind: 'points', coords: [{ x: 1, y: 1 }] }, label: 'c' }),
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
