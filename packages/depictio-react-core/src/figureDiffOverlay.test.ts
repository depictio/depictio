import { describe, expect, it } from 'vitest';

import type { DiffGroups, DiffPoints, DiffRows, DiffSamples } from './api';
import {
  applyFigureDiffOverlay,
  buildFigureDiffOverlay,
  DIFF_DIM_OPACITY,
  diffSummaryText,
  isDiffTraceName,
  type DiffColors,
} from './figureDiffOverlay';

const COLORS: DiffColors = { primary: 'primary-test', ghost: 'ghost-test' };

const pointsDiff = (over: Partial<DiffPoints> = {}): DiffPoints => ({
  supported: true,
  shape: 'points',
  key_column: 'id',
  x: 'a',
  y: 'b',
  color: null,
  counts: { added: 1, removed: 1, changed: 1, before: 3, after: 3 },
  added: [{ key: 'n1', x: 1, y: 2 }],
  removed: [{ key: 'r1', x: 5, y: 6 }],
  changed: [
    { key: 'm1', before: { key: 'm1', x: 3, y: 3 }, after: { key: 'm1', x: 4, y: 4 } },
  ],
  ...over,
});

const groupsDiff = (over: Partial<DiffGroups> = {}): DiffGroups => ({
  supported: true,
  shape: 'groups',
  group_columns: ['species'],
  x: 'species',
  color: null,
  metric: 'sum',
  value_column: 'n',
  counts: { added: 0, removed: 0, changed: 1, same: 1 },
  groups: [{ group: { species: 'setosa' }, before: 10, after: 15, status: 'changed' }],
  ...over,
});

describe('points', () => {
  const figure = { data: [{ type: 'scatter', mode: 'markers', x: [1, 4], y: [2, 4] }], layout: {} };

  it('rings added points, ghosts removed ones and draws a segment for moved ones', () => {
    const overlay = buildFigureDiffOverlay(figure, pointsDiff(), COLORS);
    const names = overlay.traces.map((t) => t.name);
    expect(names).toEqual([
      '__depictio_diff_added',
      '__depictio_diff_removed',
      '__depictio_diff_moved',
      '__depictio_diff_moved_from',
      '__depictio_diff_moved_to',
    ]);
    expect(names.every(isDiffTraceName)).toBe(true);
    const added = overlay.traces[0] as Record<string, any>;
    expect(added.x).toEqual([1]);
    expect(added.marker.symbol).toBe('circle-open');
    expect(added.marker.color).toBe('primary-test');
    expect(added.hovertext[0]).toContain('New since your last visit');
    const removed = overlay.traces[1] as Record<string, any>;
    expect(removed.marker.color).toBe('ghost-test');
    expect(removed.hovertext[0]).toContain('Was here');
    const segment = overlay.traces[2] as Record<string, any>;
    expect(segment.x).toEqual([3, 4, null]);
    expect(segment.line.dash).toBe('dot');
    expect(segment.hovertext[0]).toContain('Moved');
    expect(overlay.matched).toBe(3);
  });

  it('dims the points already there and keeps new and moved ones at full opacity', () => {
    const fig = {
      data: [
        { type: 'scatter', mode: 'markers', x: [1, 9, 4], y: [2, 9, 4], marker: { opacity: 0.8, color: 'teal' } },
        { type: 'scatter', mode: 'markers', x: [7], y: [7] },
        { type: 'box', y: [1, 2] },
      ],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(fig, pointsDiff(), COLORS);
    const byIndex = new Map(overlay.patches.map((p) => [p.traceIndex, p.patch as Record<string, any>]));
    expect([...byIndex.keys()]).toEqual([0, 1]);
    expect(byIndex.get(0)!.marker.opacity).toEqual([0.8, 0.8 * DIFF_DIM_OPACITY, 0.8]);
    expect(byIndex.get(0)!.marker.color).toBe('teal');
    expect(byIndex.get(1)!.marker.opacity).toEqual([DIFF_DIM_OPACITY]);
  });

  it('rings new points in the contrast colour when the theme gives one', () => {
    const overlay = buildFigureDiffOverlay(figure, pointsDiff(), { ...COLORS, contrast: 'text-test' });
    expect((overlay.traces[0] as Record<string, any>).marker.color).toBe('text-test');
  });

  it('does not mutate the figure', () => {
    const snapshot = JSON.stringify(figure);
    const overlay = buildFigureDiffOverlay(figure, pointsDiff(), COLORS);
    applyFigureDiffOverlay(figure.data, overlay);
    expect(JSON.stringify(figure)).toBe(snapshot);
  });

  it('appends the overlay traces after the figure traces', () => {
    const overlay = buildFigureDiffOverlay(figure, pointsDiff(), COLORS);
    const data = applyFigureDiffOverlay(figure.data, overlay);
    expect(data).toHaveLength(1 + overlay.traces.length);
    // The figure's own trace comes first, restyled (dimmed) over the same data.
    expect((data[0] as Record<string, unknown>).x).toBe(figure.data[0].x);
  });

  it('uses scatter3d traces in a 3D figure, placing new points on their z', () => {
    const fig3 = {
      data: [{ type: 'scatter3d', mode: 'markers', x: [1, 9], y: [2, 9], z: [7, 8] }],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(fig3, pointsDiff(), COLORS);
    expect(overlay.traces.map((t) => t.name)).toEqual(['__depictio_diff_added']);
    const added = overlay.traces[0] as Record<string, any>;
    expect(added.type).toBe('scatter3d');
    expect(added.z).toEqual([7]);
  });

  it('yields nothing for an unsupported diff', () => {
    const overlay = buildFigureDiffOverlay(figure, { supported: false, reason: 'no' }, COLORS);
    expect(overlay).toEqual({ traces: [], patches: [], matched: 0 });
  });
});

describe('groups', () => {
  it('fades the colour traces with no news, even on a binned histogram', () => {
    const fig = {
      data: [
        { type: 'histogram', name: 'Adelie', x: [18, 19] },
        { type: 'histogram', name: 'Gentoo', x: [14, 15], opacity: 0.5 },
        { type: 'histogram', name: 'Chinstrap', x: [18, 18], opacity: 0.5 },
      ],
      layout: { barmode: 'overlay' },
    };
    const diff = groupsDiff({
      x: 'bill_depth',
      color: 'species',
      group_columns: ['bill_depth', 'species'],
      groups: [{ group: { bill_depth: 14, species: 'Gentoo' }, before: null, after: 3, status: 'added' }],
    });
    const overlay = buildFigureDiffOverlay(fig, diff, COLORS);
    expect(overlay.patches).toEqual([
      { traceIndex: 0, patch: { opacity: DIFF_DIM_OPACITY } },
      { traceIndex: 2, patch: { opacity: 0.5 * DIFF_DIM_OPACITY } },
    ]);
    expect(overlay.matched).toBe(1);
  });

  it('fades nothing when every colour trace has news', () => {
    const fig = {
      data: [
        { type: 'box', name: 'male', x: ['Adelie', 'Gentoo'], y: [40, 50] },
        { type: 'box', name: 'female', x: ['Adelie', 'Gentoo'], y: [38, 46] },
      ],
      layout: {},
    };
    const diff = groupsDiff({
      x: 'species',
      color: 'sex',
      group_columns: ['species', 'sex'],
      groups: [
        { group: { species: 'Gentoo', sex: 'male' }, before: null, after: 50, status: 'added' },
        { group: { species: 'Gentoo', sex: 'female' }, before: null, after: 46, status: 'added' },
      ],
    });
    const overlay = buildFigureDiffOverlay(fig, diff, COLORS);
    expect(overlay.patches.filter((p) => 'opacity' in p.patch)).toEqual([]);
  });

  it('draws a ghost bar at the previous value on a vertical bar chart', () => {
    const figure = {
      data: [
        {
          type: 'bar',
          name: '',
          x: ['setosa', 'virginica'],
          y: [15, 20],
          offsetgroup: 'g',
          alignmentgroup: 'True',
        },
      ],
      layout: { barmode: 'group' },
    };
    const overlay = buildFigureDiffOverlay(figure, groupsDiff(), COLORS);
    expect(overlay.traces).toHaveLength(1);
    const ghost = overlay.traces[0] as Record<string, any>;
    expect(ghost.type).toBe('bar');
    expect(ghost.name).toBe('__depictio_diff_ghost_bar');
    expect(ghost.x).toEqual(['setosa']);
    expect(ghost.y).toEqual([10]);
    expect(ghost.offsetgroup).toBe('g');
    expect(ghost.alignmentgroup).toBe('True');
    expect(ghost.marker.color).toBe('rgba(0,0,0,0)');
    expect(ghost.marker.line.color).toBe('ghost-test');
  });

  it('respects a horizontal bar chart', () => {
    const figure = {
      data: [{ type: 'bar', orientation: 'h', x: [15, 20], y: ['setosa', 'virginica'] }],
      layout: { barmode: 'group' },
    };
    const overlay = buildFigureDiffOverlay(figure, groupsDiff(), COLORS);
    const ghost = overlay.traces[0] as Record<string, any>;
    expect(ghost.orientation).toBe('h');
    expect(ghost.y).toEqual(['setosa']);
    expect(ghost.x).toEqual([10]);
  });

  it('matches the colour value to the trace name', () => {
    const figure = {
      data: [
        { type: 'bar', name: 'A', x: ['s'], y: [1], offsetgroup: 'A' },
        { type: 'bar', name: 'B', x: ['s'], y: [2], offsetgroup: 'B' },
      ],
      layout: { barmode: 'group' },
    };
    const diff = groupsDiff({
      group_columns: ['species', 'site'],
      x: 'species',
      color: 'site',
      groups: [{ group: { species: 's', site: 'B' }, before: 9, after: 2, status: 'changed' }],
    });
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    expect(overlay.traces).toHaveLength(1);
    expect((overlay.traces[0] as Record<string, any>).offsetgroup).toBe('B');
  });

  it('puts a tick at the cumulative previous height in a stacked chart', () => {
    const figure = {
      data: [
        { type: 'bar', name: 'A', x: ['s'], y: [4] },
        { type: 'bar', name: 'B', x: ['s'], y: [6] },
      ],
      layout: { barmode: 'relative' },
    };
    const diff = groupsDiff({
      color: 'site',
      group_columns: ['species', 'site'],
      groups: [{ group: { species: 's', site: 'B' }, before: 1, after: 6, status: 'changed' }],
    });
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    const tick = overlay.traces[0] as Record<string, any>;
    expect(tick.name).toBe('__depictio_diff_ghost_tick');
    expect(tick.marker.symbol).toBe('line-ew');
    // A kept 4, B was 1: the previous stack reached 5.
    expect(tick.y).toEqual([5]);
  });

  it('outlines a new bar with a patch, leaving the input alone', () => {
    const figure = {
      data: [{ type: 'bar', x: ['a', 'b'], y: [1, 2], marker: { color: 'x' } }],
      layout: { barmode: 'group' },
    };
    const diff = groupsDiff({
      groups: [{ group: { species: 'b' }, before: null, after: 2, status: 'added' }],
    });
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    expect(overlay.traces).toHaveLength(0);
    expect(overlay.patches).toHaveLength(1);
    const marker = overlay.patches[0].patch.marker as Record<string, any>;
    expect(marker.color).toBe('x');
    expect(marker.line.width).toEqual([0, 3]);
    expect(marker.line.color[1]).toBe('primary-test');
    expect((figure.data[0].marker as Record<string, unknown>).line).toBeUndefined();
    const applied = applyFigureDiffOverlay(figure.data, overlay) as Array<Record<string, any>>;
    expect(applied[0].marker.line.width).toEqual([0, 3]);
  });

  it('draws a ghost box at the previous median', () => {
    const figure = {
      data: [{ type: 'box', name: '', x: ['setosa', 'setosa'], y: [1, 2] }],
      layout: {},
    };
    const diff = groupsDiff({ metric: 'median' });
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    const ghost = overlay.traces[0] as Record<string, any>;
    expect(ghost.type).toBe('box');
    expect(ghost.x).toEqual(['setosa']);
    expect(ghost.y).toEqual([10]);
  });

  it('puts a tick on a violin', () => {
    const figure = { data: [{ type: 'violin', x: ['setosa'], y: [1] }], layout: {} };
    const overlay = buildFigureDiffOverlay(figure, groupsDiff({ metric: 'median' }), COLORS);
    expect((overlay.traces[0] as Record<string, any>).name).toBe('__depictio_diff_ghost_tick');
  });

  it('skips a numeric histogram, which is binned', () => {
    const figure = { data: [{ type: 'histogram', x: [1, 2, 3] }], layout: {} };
    const overlay = buildFigureDiffOverlay(figure, groupsDiff({ metric: 'count' }), COLORS);
    expect(overlay).toEqual({ traces: [], patches: [], matched: 0 });
  });

  it('finds nothing when no trace carries the group', () => {
    const figure = { data: [{ type: 'pie', labels: ['setosa'], values: [1] }], layout: {} };
    const overlay = buildFigureDiffOverlay(figure, groupsDiff(), COLORS);
    expect(overlay.matched).toBe(0);
    expect(overlay.traces).toHaveLength(0);
  });
});

describe('samples', () => {
  const diff: DiffSamples = {
    supported: true,
    shape: 'samples',
    counts: { added: 1, removed: 0, before: 1, after: 2 },
    added: ['s2'],
    removed: [],
  };

  it('emphasises the lines of new samples and dims the others', () => {
    const figure = {
      data: [
        { type: 'scatter', mode: 'lines', name: 's1', x: [1, 2], y: [1, 2], line: { width: 1 } },
        { type: 'scatter', mode: 'lines', name: 's2', x: [1, 2], y: [2, 3] },
      ],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    const byIndex = Object.fromEntries(overlay.patches.map((p) => [p.traceIndex, p.patch]));
    expect(byIndex[0]).toEqual({ opacity: DIFF_DIM_OPACITY });
    // The new sample's line is left in place (it keeps its hover) and drawn
    // again on top, in its own colour, a little wider.
    expect(byIndex[1]).toBeUndefined();
    const [copy] = overlay.traces as Array<Record<string, any>>;
    expect(isDiffTraceName(copy.name)).toBe(true);
    expect(copy.line.color).toBeUndefined();
    expect(copy.line.width).toBeGreaterThan(2);
    expect(copy.y).toEqual([2, 3]);
    expect(overlay.matched).toBe(1);
    // The input stays as it was.
    expect(figure.data[0]).toEqual({
      type: 'scatter',
      mode: 'lines',
      name: 's1',
      x: [1, 2],
      y: [1, 2],
      line: { width: 1 },
    });
  });

  it('fades the bars of the samples seen before, keeping every colour', () => {
    const figure = {
      data: [
        { type: 'bar', orientation: 'h', name: 'Pass', x: [1, 2], y: ['s1', 's2'], marker: { color: 'green' } },
      ],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    const marker = overlay.patches[0].patch.marker as Record<string, any>;
    expect(marker.opacity).toEqual([DIFF_DIM_OPACITY, 1]);
    expect(marker.color).toBe('green');
    expect(marker.line).toBeUndefined();
  });

  it('dims a heatmap and redraws only the rows of new samples on top', () => {
    const figure = {
      data: [
        {
          type: 'heatmap',
          x: ['Basic', 'Quality', 'Adapter'],
          y: ['s1', 's2'],
          z: [
            [1, 0, 1],
            [1, 1, 0],
          ],
        },
      ],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    expect(overlay.patches).toEqual([{ traceIndex: 0, patch: { opacity: DIFF_DIM_OPACITY } }]);
    const [top] = overlay.traces as Array<Record<string, any>>;
    expect(isDiffTraceName(top.name)).toBe(true);
    expect(top.type).toBe('heatmap');
    expect(top.z).toEqual([
      [null, null, null],
      [1, 1, 0],
    ]);
    expect(top.showscale).toBe(false);
    expect(overlay.matched).toBe(1);
  });

  it('keeps the columns of new samples when the samples are on x', () => {
    const figure = {
      data: [{ type: 'heatmap', x: ['s1', 's2'], y: ['a', 'b'], z: [[1, 0], [0, 1]] }],
      layout: {},
    };
    const [top] = buildFigureDiffOverlay(figure, diff, COLORS).traces as Array<Record<string, any>>;
    expect(top.z).toEqual([
      [null, 0],
      [null, 1],
    ]);
  });

  it('changes nothing when no new sample is in the figure', () => {
    const figure = {
      data: [{ type: 'scatter', mode: 'lines', name: 's1', x: [1], y: [1] }],
      layout: {},
    };
    expect(buildFigureDiffOverlay(figure, diff, COLORS).patches).toEqual([]);
  });
});

describe('rows', () => {
  const diff: DiffRows = {
    supported: true,
    shape: 'rows',
    key_column: 'gene',
    value_columns: ['lfc'],
    counts: { added: 1, removed: 1, changed: 1, before: 2, after: 2 },
    added: [{ key: 'G1', values: { gene: 'G1', lfc: 1 } }],
    removed: [{ key: 'G9', values: { gene: 'G9', lfc: 2 } }],
    changed: [{ key: 'G2', before: { lfc: 1 }, after: { lfc: 2 } }],
  };

  it('rings points whose customdata holds a new or changed row key', () => {
    const figure = {
      data: [
        {
          type: 'scatter',
          mode: 'markers',
          x: [1, 2, 3],
          y: [4, 5, 6],
          customdata: [['G1'], ['G2'], ['G3']],
        },
      ],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    expect(overlay.traces.map((t) => t.name)).toEqual([
      '__depictio_diff_added',
      '__depictio_diff_changed',
    ]);
    expect((overlay.traces[0] as Record<string, any>).x).toEqual([1]);
    expect((overlay.traces[1] as Record<string, any>).x).toEqual([2]);
    expect(overlay.matched).toBe(2);
  });

  it('matches on text and ids too', () => {
    const figure = {
      data: [
        { type: 'scatter', x: [1, 2], y: [1, 2], text: ['G3', 'G1'] },
        { type: 'scatter', x: [7], y: [8], ids: ['G2'] },
      ],
      layout: {},
    };
    const overlay = buildFigureDiffOverlay(figure, diff, COLORS);
    expect((overlay.traces[0] as Record<string, any>).x).toEqual([2]);
    expect((overlay.traces[1] as Record<string, any>).x).toEqual([7]);
  });

  it('marks nothing when the traces name no row', () => {
    const figure = { data: [{ type: 'scatter', x: [1], y: [1] }], layout: {} };
    expect(buildFigureDiffOverlay(figure, diff, COLORS)).toEqual({
      traces: [],
      patches: [],
      matched: 0,
    });
  });
});

describe('summary', () => {
  it('words the counts', () => {
    expect(diffSummaryText(pointsDiff())).toBe('Compared with your last visit: +1 · −1 · 1 moved');
    expect(diffSummaryText(groupsDiff())).toContain('1 changed');
    expect(diffSummaryText({ supported: false, reason: 'x' })).toBeNull();
  });
});
