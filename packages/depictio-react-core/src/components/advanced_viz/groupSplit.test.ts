import { describe, expect, it } from 'vitest';

import type { GroupRenderState } from '../../selectionGroups';
import { OTHER_LABEL, canSplitByGroups, splitFigureByGroups } from './groupSplit';

/** Six points whose sample id sits at customdata slot 0. */
function figure() {
  return {
    data: [
      {
        type: 'scattergl',
        mode: 'markers',
        x: [1, 2, 3, 4, 5, 6],
        y: [1, 2, 3, 4, 5, 6],
        customdata: [['s1'], ['s2'], ['s3'], ['s4'], ['s5'], ['s6']],
        marker: { color: ['#111', '#222', '#333', '#444', '#555', '#666'], size: 8 },
      },
    ],
    layout: { xaxis: { title: { text: 'PC1' } }, yaxis: { title: { text: 'PC2' } } },
  };
}

const GROUPS: GroupRenderState = {
  colorByGroup: true,
  groups: [
    { name: 'Soil', column_name: 'sample_id', values: ['s1', 's2'], color: '#E24A33' },
    { name: 'River', column_name: 'sample_id', values: ['s3'], color: '#348ABD' },
  ],
};

const OPTS = { groupRender: GROUPS, identitySlot: 0 };

describe('splitFigureByGroups', () => {
  it('leaves the figure alone when nothing is grouped', () => {
    const original = figure();
    expect(splitFigureByGroups(original, { ...OPTS, groupRender: undefined })).toBe(original);
    expect(canSplitByGroups({ ...OPTS, groupRender: undefined })).toBe(false);
  });

  it('applies a group captured on a differently named column of the same ids', () => {
    // The sampling-sites map emits `sample`; this ordination calls the very
    // same identifier `sample_id`. The join is on the values, so the group
    // still lands.
    const renamed: GroupRenderState = {
      ...GROUPS,
      groups: GROUPS.groups.map((g) => ({ ...g, column_name: 'sample' })),
    };
    const out = splitFigureByGroups(figure(), { ...OPTS, groupRender: renamed });
    expect(out.data.map((t: any) => t.name)).toEqual(['Soil', 'River', OTHER_LABEL]);
  });

  it('leaves the figure alone when no point carries any group value', () => {
    const original = figure();
    const foreign: GroupRenderState = {
      ...GROUPS,
      groups: GROUPS.groups.map((g) => ({ ...g, values: ['chr1', 'chr2'] })),
    };
    expect(splitFigureByGroups(original, { ...OPTS, groupRender: foreign })).toBe(original);
  });

  it('leaves the figure alone when the points carry no identity', () => {
    const bare = { data: [{ x: [1, 2], y: [1, 2] }], layout: {} };
    expect(splitFigureByGroups(bare, OPTS)).toBe(bare);
  });

  it('paints one trace per group plus Other, in declaration order', () => {
    const out = splitFigureByGroups(figure(), OPTS);
    expect(out.data.map((t: any) => t.name)).toEqual(['Soil', 'River', OTHER_LABEL]);
    expect(out.data.map((t: any) => t.marker.color)).toEqual(['#E24A33', '#348ABD', '#adb5bd']);
    expect(out.data[0].x).toEqual([1, 2]);
    expect(out.data[1].x).toEqual([3]);
    expect(out.data[2].x).toEqual([4, 5, 6]);
    // Every per-point array follows the points it belongs to.
    expect(out.data[0].customdata).toEqual([['s1'], ['s2']]);
  });

  it('drops the ungrouped points when showOther is off', () => {
    const out = splitFigureByGroups(figure(), {
      ...OPTS,
      groupRender: { ...GROUPS, showOther: false },
    });
    expect(out.data.map((t: any) => t.name)).toEqual(['Soil', 'River']);
  });

  it('gives each group its own panel in facet display', () => {
    const out = splitFigureByGroups(figure(), {
      ...OPTS,
      groupRender: { ...GROUPS, display: 'facet' },
    });
    expect(out.data.map((t: any) => t.xaxis)).toEqual(['x', 'x2', 'x3']);
    expect(out.layout.xaxis.domain[0]).toBe(0);
    expect(out.layout.xaxis3.matches).toBe('x');
    expect(out.layout.yaxis3.matches).toBe('y');
    // Panels are labelled with the group they hold.
    expect(out.layout.annotations.map((a: any) => a.text)).toEqual(['Soil', 'River', OTHER_LABEL]);
  });

  it('degrades a split to colouring when the renderer cannot facet', () => {
    const out = splitFigureByGroups(figure(), {
      ...OPTS,
      groupRender: { ...GROUPS, display: 'facet' },
      facetable: false,
    });
    expect(out.data.every((t: any) => t.xaxis === undefined)).toBe(true);
    expect(out.data).toHaveLength(3);
  });

  it('repeats a threshold line in every panel and keeps context traces out of the legend', () => {
    const base = figure();
    base.layout = {
      ...base.layout,
      shapes: [{ type: 'line', xref: 'paper', yref: 'y', x0: 0, x1: 1, y0: 3, y1: 3 }],
    } as any;
    base.data.push({ type: 'scatter', mode: 'lines', x: [0, 7], y: [0, 7] } as any);
    const out = splitFigureByGroups(base, {
      ...OPTS,
      groupRender: { ...GROUPS, display: 'facet' },
    });
    expect(out.layout.shapes).toHaveLength(3);
    expect(out.layout.shapes.map((s: any) => s.xref)).toEqual([
      'x domain',
      'x2 domain',
      'x3 domain',
    ]);
    expect(out.layout.shapes.map((s: any) => s.yref)).toEqual(['y', 'y2', 'y3']);
    expect(out.data.filter((t: any) => t.mode === 'lines')).toHaveLength(3);
    expect(out.data.filter((t: any) => t.mode === 'lines').every((t: any) => !t.showlegend)).toBe(
      true,
    );
  });

  it('drops a whole-cohort summary trace when the renderer says it is one', () => {
    const base = figure();
    base.data.push({ type: 'histogram2dcontour', x: [1, 2], y: [1, 2] } as any);
    const out = splitFigureByGroups(base, {
      ...OPTS,
      groupRender: { ...GROUPS, display: 'facet' },
      contextTraces: 'drop',
    });
    expect(out.data.some((t: any) => t.type === 'histogram2dcontour')).toBe(false);
  });

  it('keeps the legend hidden when the host has turned it off', () => {
    const out = splitFigureByGroups(figure(), { ...OPTS, showLegend: false });
    expect(out.layout.showlegend).toBe(false);
  });

  it('shows each group in the legend once across several traces', () => {
    const base = figure();
    base.data.push({ ...base.data[0], type: 'scattergl' } as any);
    const out = splitFigureByGroups(base, OPTS);
    const soil = out.data.filter((t: any) => t.name === 'Soil');
    expect(soil).toHaveLength(2);
    expect(soil.map((t: any) => t.showlegend)).toEqual([true, false]);
  });

  it('drops a colorbar the group colours have made meaningless', () => {
    const base = figure();
    base.data[0].marker = { ...base.data[0].marker, showscale: true, colorscale: 'Viridis' } as any;
    (base.layout as any).coloraxis = { colorbar: { title: 'depth' } };
    const out = splitFigureByGroups(base, OPTS);
    expect(out.data.every((t: any) => t.marker.showscale === undefined)).toBe(true);
    expect(out.layout.coloraxis).toBeUndefined();
  });
});
