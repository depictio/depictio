import { describe, expect, it } from 'vitest';

import { formatMetric, metricChange, readSteps, type StepColumns } from './steps';

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
