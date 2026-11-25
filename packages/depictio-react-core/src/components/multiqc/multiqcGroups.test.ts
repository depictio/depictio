import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from '../../selectionGroups';
import {
  allIdentical,
  bandRows,
  bandsReach,
  figureSamples,
  figureSignature,
  multiqcDeclineReasons,
  overlayGroupsOnFigure,
  planMultiQCGroups,
} from './multiqcGroups';

function groups(n: number, extra: Partial<GroupRenderState> = {}): GroupRenderState {
  return {
    groups: Array.from({ length: n }, (_, i) => ({
      name: `G${i + 1}`,
      column_name: 'sample',
      values: [`s${i + 1}`],
      color: '#ff0000',
      dc_id: 'dc1',
    })),
    colorByGroup: true,
    display: 'facet',
    ...extra,
  };
}

describe('planMultiQCGroups', () => {
  it('does nothing without groups', () => {
    expect(planMultiQCGroups(undefined, [], false).kind).toBe('none');
    expect(planMultiQCGroups(groups(0), [], false).kind).toBe('none');
  });

  it('leaves the groups of runs to the "what\'s new" split', () => {
    const runs: GroupRenderState = {
      colorByGroup: true,
      display: 'facet',
      groups: [{ name: 'New', column_name: 'depictio_run_id', values: ['r1'], color: '#000' }],
    };
    expect(planMultiQCGroups(runs, [], false).kind).toBe('none');
  });

  it('splits into one panel per group, within the limit', () => {
    const plan = planMultiQCGroups(groups(3), [], false);
    expect(plan.kind).toBe('split');
    if (plan.kind === 'split') expect(plan.panels.length).toBeGreaterThanOrEqual(3);
  });

  it('draws whole, with a reason, past the panel limit', () => {
    const plan = planMultiQCGroups(groups(9), [], false);
    expect(plan).toMatchObject({ kind: 'declined', reason: 'too_many' });
  });

  it('narrows to a lone group', () => {
    const plan = planMultiQCGroups(groups(1), [], false);
    expect(['filter', 'split']).toContain(plan.kind);
  });

  it('overlays the groups on a plot, bands them on General Stats', () => {
    const overlay = groups(2, { display: 'color' });
    const onPlot = planMultiQCGroups(overlay, [], false);
    expect(onPlot.kind).toBe('overlay');
    if (onPlot.kind === 'overlay') expect(onPlot.panels.map((p) => p.name)).toEqual(['G1', 'G2']);
    const plan = planMultiQCGroups(overlay, [], true);
    expect(plan.kind).toBe('bands');
    if (plan.kind === 'bands') {
      expect(plan.panels.map((p) => p.name).slice(0, 2)).toEqual(['G1', 'G2']);
      expect(plan.showOther).toBe(true);
    }
  });

  it('carries showOther=false to the bands', () => {
    const plan = planMultiQCGroups(groups(2, { display: 'color', showOther: false }), [], true);
    expect(plan).toMatchObject({ kind: 'bands', showOther: false });
  });
});

describe('bandRows', () => {
  const rows = ['a', 'b', 'c', 'd', 'e'];
  const sample = (r: string) => r;
  const members = [new Set(['d', 'b']), new Set(['a', 'b'])];

  it('orders rows by group, keeping their order inside a group, then Other', () => {
    const out = bandRows(rows, sample, members, true);
    expect(out.map((o) => o.row)).toEqual(['b', 'd', 'a', 'c', 'e']);
    expect(out.map((o) => o.band)).toEqual([0, 0, 1, 2, 2]);
  });

  it('lets the first group win a sample held by two', () => {
    expect(bandRows(['b'], sample, members, true)[0].band).toBe(0);
  });

  it('drops Other when asked', () => {
    expect(bandRows(rows, sample, members, false).map((o) => o.row)).toEqual(['b', 'd', 'a']);
  });

  it('puts a row with no readable sample in Other', () => {
    expect(bandRows(['x'], () => null, members, true)[0].band).toBe(2);
  });
});

describe('bandsReach', () => {
  const samples = ['a', 'b', 'c'];
  it('is false when no sample is in a group', () => {
    expect(bandsReach(samples, [new Set(['z'])])).toBe(false);
    expect(bandsReach([], [new Set(['a'])])).toBe(false);
  });
  it('is false when every group holds every sample (nothing narrowed)', () => {
    const all = new Set(samples);
    expect(bandsReach(samples, [all, all])).toBe(false);
  });
  it('is true when the groups narrow the table', () => {
    expect(bandsReach(samples, [new Set(['a']), new Set(['b', 'c'])])).toBe(true);
  });
});

describe('figure fingerprints', () => {
  it('tells a narrowed figure from the whole', () => {
    const whole = figureSignature([{ type: 'bar', name: 'x', x: ['a', 'b', 'c'], y: [1, 2, 3] }]);
    const part = figureSignature([{ type: 'bar', name: 'x', x: ['a'], y: [1] }]);
    expect(whole).not.toBe(part);
    expect(figureSignature([{ type: 'bar', name: 'x', x: ['a', 'b', 'c'], y: [1, 2, 3] }])).toBe(whole);
  });

  it('only calls panels identical when all reported and all equal', () => {
    expect(allIdentical(['a', 'a', 'a'])).toBe(true);
    expect(allIdentical(['a', null, 'a'])).toBe(false);
    expect(allIdentical(['a', 'b'])).toBe(false);
    expect(allIdentical(['a'])).toBe(false);
  });
});

describe('decline reasons', () => {
  it('says why in a sentence', () => {
    expect(multiqcDeclineReasons('too_many', 9)[0]).toMatch(/9 panels/);
    expect(multiqcDeclineReasons('overlay_plot')[0]).toMatch(/Split/);
    expect(multiqcDeclineReasons('unreachable')[0]).toMatch(/link/);
  });
});

describe('figure signature', () => {
  it('tells a line plot narrowed by hiding traces from the whole one', () => {
    const line = (name: string, visible?: boolean) => ({ type: 'scatter', name, x: [1, 2], y: [3, 4], ...(visible === false ? { visible } : {}) });
    const whole = figureSignature([line('s1'), line('s2')]);
    const narrowed = figureSignature([line('s1'), line('s2', false)]);
    expect(narrowed).not.toBe(whole);
  });
});

describe('overlayGroupsOnFigure', () => {
  const groupsOf = (a: string[], b: string[]) => [
    { name: 'A', color: '#ff0000', members: new Set(a) },
    { name: 'B', color: '#0000ff', members: new Set(b) },
  ];
  const line = (name: string, visible?: boolean) => ({ type: 'scatter', name, x: [1, 2], y: [3, 4], ...(visible === false ? { visible } : {}) });

  it('reads the samples a render draws, hidden traces left out', () => {
    expect([...figureSamples([line('s1'), line('s2', false)])]).toEqual(['s1']);
    expect([...figureSamples([{ type: 'bar', orientation: 'h', y: ['s1', 's2'], x: [1, 2] }])]).toEqual(['s1', 's2']);
  });

  it('colours a line per sample by its group, Other grey, with a legend per group', () => {
    const out = overlayGroupsOnFigure([line('s1'), line('s2'), line('s3')], {}, groupsOf(['s1'], ['s2']), true);
    expect('failed' in out).toBe(false);
    if ('failed' in out) return;
    const [s1, s2, s3, ...legend] = out.data as Record<string, any>[];
    expect(s1.line.color).toBe('#ff0000');
    expect(s2.line.color).toBe('#0000ff');
    expect(s3.opacity).toBeLessThan(1);
    expect(legend.map((t) => t.name)).toEqual(['A', 'B']);
    expect(out.layout.showlegend).toBe(true);
  });

  it('hides the samples of no group when Other is off', () => {
    const out = overlayGroupsOnFigure([line('s1'), line('s3')], {}, groupsOf(['s1'], []), false);
    if ('failed' in out) throw new Error('expected an overlay');
    expect((out.data[1] as Record<string, unknown>).visible).toBe(false);
  });

  it('marks the bars of a sample with its group strip, at its position on the category axis', () => {
    const bars = [
      { type: 'bar', orientation: 'h', name: 'Unique', y: ['s1', 's2', 's3'], x: [1, 2, 3] },
      { type: 'bar', orientation: 'h', name: 'Duplicate', y: ['s1', 's2', 's3'], x: [1, 2, 3] },
    ];
    const out = overlayGroupsOnFigure(bars, {}, groupsOf(['s2'], []), true);
    if ('failed' in out) throw new Error('expected an overlay');
    const shapes = out.layout.shapes as Record<string, any>[];
    // One strip for s2, drawn once although two traces share the axis, beside
    // the axis in pixels, the labels stepping aside for it.
    expect(shapes).toHaveLength(1);
    expect(shapes[0]).toMatchObject({ yref: 'y', xsizemode: 'pixel', xanchor: 0, fillcolor: '#ff0000' });
    expect(shapes[0].y0).toBeCloseTo(0.58);
    expect(shapes[0].x1).toBeLessThan(0);
    expect((out.layout.yaxis as Record<string, number>).ticklabelstandoff).toBeGreaterThan(0);
    // The bars keep their own category colours.
    expect((out.data[0] as Record<string, unknown>).marker).toBeUndefined();
  });

  it('says why when nothing can be drawn', () => {
    expect(overlayGroupsOnFigure([line('s9')], {}, groupsOf(['s1'], []), true)).toEqual({ failed: 'unreachable' });
    expect(overlayGroupsOnFigure([{ type: 'heatmap', z: [[1]] }], {}, groupsOf(['s1'], []), true)).toEqual({
      failed: 'unsupported',
    });
  });
});
