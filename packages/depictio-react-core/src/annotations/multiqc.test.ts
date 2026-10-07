import { describe, expect, it } from 'vitest';

import { withPendingVariant } from './AnnotationLayerContext';
import { itemsForVariant, normalizeTraces, publishedToRenderable, withSelectableLines } from './layer';
import { markedPointsFromSelection } from './capture';
import {
  MULTIQC_SAMPLE_COLUMN,
  multiqcFigureAnnotatable,
  multiqcVariantKey,
  sampleIdsForTrace,
  withSampleCustomdata,
} from './multiqc';
import { componentSupportsAnnotation } from './plotDecorate';
import { annotationsToPlotly, OVERLAY_TRACE_PREFIX } from './toPlotly';
import type { AnnotationColor, RenderableAnnotation } from './types';
import { MAX_VARIANT_CHARS } from './types';

const resolveColor = (name: AnnotationColor, shade?: number) => `tok:${name}:${shade ?? 'd'}`;

const marked = (id: string, ids: string[], variant?: string): RenderableAnnotation => ({
  id,
  number: 1,
  annotation: {
    kind: 'points',
    geometry: { kind: 'points', column: MULTIQC_SAMPLE_COLUMN, ids },
    label: 'odd',
    ...(variant ? { variant } : {}),
  },
});

// A MultiQC line graph (one line per sample) and a horizontal stacked bar
// graph (samples on y, one trace per category).
const lineFigure = [
  { type: 'scatter', mode: 'lines', name: 'S1', x: [1, 2, 3], y: [10, 20, 30] },
  { type: 'scatter', mode: 'lines', name: 'S2', x: [1, 2, 3], y: [11, 21, 31] },
];
const barFigure = [
  { type: 'bar', orientation: 'h', name: 'Unique', y: ['S1', 'S2', 'S3'], x: [5, 6, 7] },
  { type: 'bar', orientation: 'h', name: 'Duplicate', y: ['S1', 'S2', 'S3'], x: [1, 2, 3] },
];

describe('multiqcVariantKey', () => {
  it('keys module, plot and dataset', () => {
    expect(multiqcVariantKey({ module: 'fastqc', plot: 'quals', dataset: 'Read 1' })).toBe(
      'multiqc:fastqc/quals/Read 1',
    );
    expect(multiqcVariantKey({ module: 'fastqc', plot: 'quals' })).toBe('multiqc:fastqc/quals/');
  });
  it('tells datasets and switches apart', () => {
    const r1 = multiqcVariantKey({ module: 'm', plot: 'p', dataset: 'Read 1' });
    const r2 = multiqcVariantKey({ module: 'm', plot: 'p', dataset: 'Read 2' });
    expect(r1).not.toBe(r2);
    expect(multiqcVariantKey({ module: 'm', plot: 'p', dataset: 0, pct: true, log: true })).toBe(
      'multiqc:m/p/0|pct|log',
    );
  });
  it('stays within the stored length, stable and distinct', () => {
    const long = { module: 'm', plot: 'p'.repeat(300), dataset: 'a' };
    const key = multiqcVariantKey(long);
    expect(key.length).toBeLessThanOrEqual(MAX_VARIANT_CHARS);
    expect(multiqcVariantKey(long)).toBe(key);
    expect(multiqcVariantKey({ ...long, dataset: 'b' })).not.toBe(key);
  });
});

describe('sample ids', () => {
  it('maps a line or box trace to its name and a bar to its category axis', () => {
    expect(sampleIdsForTrace(lineFigure[0])).toEqual(['S1', 'S1', 'S1']);
    expect(sampleIdsForTrace({ type: 'box', name: 'S9', x: [1, 2] })).toEqual(['S9', 'S9']);
    expect(sampleIdsForTrace(barFigure[0])).toEqual(['S1', 'S2', 'S3']);
    expect(sampleIdsForTrace({ type: 'bar', x: ['A', 'B'], y: [1, 2] })).toEqual(['A', 'B']);
  });
  it('skips heatmaps, hidden traces and nameless lines', () => {
    expect(sampleIdsForTrace({ type: 'heatmap', x: ['a'], y: ['b'], z: [[1]] })).toBeNull();
    expect(sampleIdsForTrace({ ...lineFigure[0], visible: false })).toBeNull();
    expect(sampleIdsForTrace({ type: 'scatter', x: [1], y: [1] })).toBeNull();
  });
  it('decodes typed-array coordinates for the point count', () => {
    const bdata = Buffer.from(new Float64Array([1, 2]).buffer).toString('base64');
    expect(sampleIdsForTrace({ type: 'scatter', name: 'S1', x: { dtype: 'f8', bdata }, y: { dtype: 'f8', bdata } })).toEqual([
      'S1',
      'S1',
    ]);
  });
  it('writes the sample into customdata, leaving other traces untouched', () => {
    const heat = { type: 'heatmap', z: [[1]] };
    const own = { type: 'scatter', name: 'S3', x: [1], y: [1], customdata: ['keep'] };
    const out = withSampleCustomdata([lineFigure[0], heat, own]);
    expect((out[0] as { customdata: unknown[] }).customdata).toEqual(['S1', 'S1', 'S1']);
    expect(out[1]).toBe(heat);
    expect(out[2]).toBe(own);
    expect(withSampleCustomdata([heat])).toEqual([heat]);
  });
  it('captures selected bars as sample ids', () => {
    const data = withSampleCustomdata(barFigure) as Array<{ customdata: unknown[] }>;
    const geometry = markedPointsFromSelection(
      {
        points: [
          { x: 6, y: 'S2', curveNumber: 0, pointNumber: 1, customdata: data[0].customdata[1] },
          { x: 2, y: 'S2', curveNumber: 1, pointNumber: 1, customdata: data[1].customdata[1] },
          { x: 7, y: 'S3', curveNumber: 0, pointNumber: 2, customdata: data[0].customdata[2] },
        ],
      },
      0,
      MULTIQC_SAMPLE_COLUMN,
    );
    expect(geometry).toEqual({ kind: 'points', column: 'sample', ids: ['S2', 'S3'] });
  });
});

describe('multiqcFigureAnnotatable', () => {
  it('accepts single-panel cartesian figures', () => {
    expect(multiqcFigureAnnotatable(lineFigure)).toBe(true);
    expect(multiqcFigureAnnotatable(barFigure)).toBe(true);
    expect(multiqcFigureAnnotatable([{ type: 'heatmap', z: [[1]] }])).toBe(true);
  });
  it('rejects empty, multi-panel and non-cartesian figures', () => {
    expect(multiqcFigureAnnotatable([])).toBe(false);
    expect(multiqcFigureAnnotatable([{ type: 'violin', xaxis: 'x2', yaxis: 'y2' }])).toBe(false);
    expect(multiqcFigureAnnotatable([{ type: 'pie' }])).toBe(false);
  });
  it('is offered on multiqc components', () => {
    expect(componentSupportsAnnotation('multiqc', {})).toBe(true);
  });
});

describe('variants', () => {
  const a = marked('a', ['S1'], 'multiqc:m/p/Read 1');
  const b = marked('b', ['S1'], 'multiqc:m/p/Read 2');
  const any = marked('c', ['S1']);
  it('keeps the annotations of the view and those without one', () => {
    expect(itemsForVariant([a, b, any], 'multiqc:m/p/Read 1')).toEqual([a, any]);
    expect(itemsForVariant([a, b, any], 'multiqc:m/p/other')).toEqual([any]);
  });
  it('keeps everything, same array, when the component has one view', () => {
    const items = [a, b];
    expect(itemsForVariant(items, undefined)).toBe(items);
    const plain = [any];
    expect(itemsForVariant(plain, 'multiqc:m/p/Read 1')).toBe(plain);
  });
  it('stores the capture view with the saved annotation', () => {
    const draft = { annotation: { kind: 'note' as const, geometry: { kind: 'arrow_note' as const, x: 1, y: 2 }, label: 'n' } };
    const pending = { componentIndex: 'c', kind: 'note' as const, geometry: draft.annotation.geometry };
    expect(withPendingVariant(draft, pending)).toBe(draft);
    expect(withPendingVariant(draft, { ...pending, variant: 'v' }).annotation.variant).toBe('v');
  });
  it('carries a published annotation variant', () => {
    const out = publishedToRenderable([
      {
        thread_id: 't',
        component_index: 'c',
        number: 1,
        kind: 'range',
        geometry: { kind: 'x_range', x0: 1, x1: 2 },
        label: 'r',
        color: 'yellow',
        style: {},
        variant: 'v',
      },
    ]);
    expect(out.c[0].annotation.variant).toBe('v');
  });
});

describe('marked samples on a line graph', () => {
  const traces = normalizeTraces(withSampleCustomdata(lineFigure), 0);
  it('flags line traces', () => {
    expect(traces.map((t) => t.lines)).toEqual([true, true]);
    expect(normalizeTraces([{ type: 'scatter', mode: 'markers', x: [1], y: [1] }], 0)[0].lines).toBeUndefined();
  });
  it('re-draws a marked sample line in the annotation colour', () => {
    const out = annotationsToPlotly([marked('a', ['S2'])], { resolveColor, traces, selectionColumnIndex: 0 });
    expect(out.overlayTraces).toHaveLength(1);
    expect(out.overlayTraces[0]).toMatchObject({
      mode: 'lines',
      x: [1, 2, 3],
      y: [11, 21, 31],
      name: `${OVERLAY_TRACE_PREFIX}a`,
      line: { color: resolveColor('yellow') },
    });
    expect(out.stats.a).toEqual({ expected: 1, found: 1 });
    // Labelled at the middle of the line.
    expect(out.annotations[0]).toMatchObject({ x: 2, y: 21 });
  });
  it('joins several marked lines with a gap and counts missing samples', () => {
    const out = annotationsToPlotly([marked('a', ['S1', 'S2', 'gone'])], {
      resolveColor,
      traces,
      selectionColumnIndex: 0,
    });
    expect(out.overlayTraces[0]).toMatchObject({ x: [1, 2, 3, null, 1, 2, 3] });
    expect(out.stats.a).toEqual({ expected: 3, found: 2 });
  });
  it('rings bars of a marked sample instead', () => {
    const bars = normalizeTraces(withSampleCustomdata(barFigure), 0);
    const out = annotationsToPlotly([marked('a', ['S3'])], { resolveColor, traces: bars, selectionColumnIndex: 0 });
    expect(out.overlayTraces[0]).toMatchObject({ mode: 'markers', x: [7], y: ['S3'] });
    expect(out.stats.a).toEqual({ expected: 1, found: 1 });
  });
});

describe('withSelectableLines', () => {
  it('gives lines-only traces invisible markers', () => {
    const out = withSelectableLines(lineFigure) as Array<Record<string, unknown>>;
    expect(out[0]).toMatchObject({ mode: 'lines+markers', marker: { opacity: 0 } });
  });
  it('returns the same array when every trace is selectable already', () => {
    const data = [{ type: 'scatter', mode: 'lines+markers' }, { type: 'bar' }];
    expect(withSelectableLines(data)).toBe(data);
  });
});
