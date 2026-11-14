import { describe, expect, it } from 'vitest';

import {
  changeTone,
  formatMetric,
  metricChange,
  parseParams,
  readSteps,
  stepIcon,
  type StepColumns,
} from './steps';

const COLS: StepColumns = {
  store: 'store',
  label: 'step',
  order: 'step_order',
  sample: 'sample',
  reference: 'fixed_store',
  metrics: ['ncc', 'tre_px'],
};

const ROWS = {
  sample: ['b', 'a', 'a', 'a', 'b'],
  step: ['raw', 'affine', 'raw', 'rigid', 'rigid'],
  step_order: [0, 2, 0, 1, 1],
  store: ['b_raw.zarr', 'a_affine.zarr', 'a_raw.zarr', 'a_rigid.zarr', 'b_rigid.zarr'],
  fixed_store: ['b_fixed.zarr', 'a_fixed.zarr', 'a_fixed.zarr', 'a_fixed.zarr', 'b_fixed.zarr'],
  ncc: [0.31, 0.95, 0.4, 0.88, 0.7],
  tre_px: [20.5, 1.1, 18, 4.2, 6],
};

describe('readSteps', () => {
  it('groups the rows by sample, in step order', () => {
    const steps = readSteps(ROWS, COLS);
    expect(steps.samples).toEqual(['a', 'b']);
    expect(steps.bySample.get('a')!.map((s) => s.label)).toEqual(['raw', 'rigid', 'affine']);
    expect(steps.bySample.get('b')!.map((s) => s.store)).toEqual(['b_raw.zarr', 'b_rigid.zarr']);
    expect(steps.bySample.get('a')![2]).toMatchObject({
      reference: 'a_fixed.zarr',
      metrics: { ncc: 0.95, tre_px: 1.1 },
    });
  });

  it('keeps table order without an order column, and one sample without a sample column', () => {
    const steps = readSteps(ROWS, { store: 'store', label: 'step', metrics: [] });
    expect(steps.samples).toEqual(['']);
    expect(steps.bySample.get('')!.map((s) => s.store)).toEqual(ROWS.store);
  });

  it('labels a step by its store when there is no label column', () => {
    const steps = readSteps({ store: ['x.zarr'] }, { store: 'store', metrics: [] });
    expect(steps.bySample.get('')![0].label).toBe('x.zarr');
  });

  it('drops rows without a store', () => {
    const steps = readSteps({ store: ['a.zarr', null, ''] }, { store: 'store', metrics: [] });
    expect(steps.bySample.get('')!.map((s) => s.store)).toEqual(['a.zarr']);
  });
});

describe('metrics', () => {
  it('formats numbers to three significant decimals, text as is', () => {
    expect(formatMetric(0.912345)).toBe('0.912');
    expect(formatMetric(1234.5)).toBe('1235');
    expect(formatMetric(0)).toBe('0');
    expect(formatMetric('ok')).toBe('ok');
    expect(formatMetric(null)).toBe('n/a');
  });

  it('gives the change from the previous step, numbers only', () => {
    expect(metricChange(0.95, 0.88)).toBeCloseTo(0.07);
    expect(metricChange(0.95, null)).toBeNull();
    expect(metricChange('x', 1)).toBeNull();
  });
});

describe('step parameters and run info', () => {
  it('reads JSON parameters and key=value pairs, in their own order', () => {
    expect(parseParams('{"Transform": "AffineTransform", "Resolutions": 4}')).toEqual([
      ['Transform', 'AffineTransform'],
      ['Resolutions', '4'],
    ]);
    expect(parseParams('metric=MI; iterations: 500\ngrid=16 px')).toEqual([
      ['metric', 'MI'],
      ['iterations', '500'],
      ['grid', '16 px'],
    ]);
    expect(parseParams(null)).toEqual([]);
    expect(parseParams('{not json')).toEqual([['{not json', '']]);
  });

  it('carries each step its parameters and run info', () => {
    const steps = readSteps(
      { ...ROWS, tool: ['t', 't', 't', 't', 't'], params: ['', 'a=1', '', '', ''] },
      { ...COLS, params: 'params', info: ['tool'] },
    );
    const affine = steps.bySample.get('a')![2];
    expect(affine.params).toEqual([['a', '1']]);
    expect(affine.info).toEqual({ tool: 't' });
  });

  it('says whether a change is for the better, given which way the metric improves', () => {
    expect(changeTone(-3, 'lower')).toBe('better');
    expect(changeTone(-3, 'higher')).toBe('worse');
    expect(changeTone(0.2, 'higher')).toBe('better');
    expect(changeTone(0.2, undefined)).toBe('neutral');
    expect(changeTone(null, 'lower')).toBe('neutral');
  });
});

describe('stepIcon', () => {
  it('names the kind of a registration step', () => {
    expect(stepIcon('raw')).toBe('tabler:photo');
    expect(stepIcon('rigid')).toBe('tabler:rotate-2');
    expect(stepIcon('affine')).toBe('tabler:transform');
    expect(stepIcon('bspline')).toBe('tabler:grid-4x4');
    expect(stepIcon('B-spline (elastix)')).toBe('tabler:grid-4x4');
  });
  it('falls back to a dot', () => {
    expect(stepIcon('step 7')).toBe('tabler:point');
  });
});
