import { describe, expect, it } from 'vitest';

import { tintSingleSeries } from './figureTint';
import { tabHueHex } from './tabColor';

const HUE = '#0ca678';

describe('tintSingleSeries', () => {
  it('swaps the Plotly Express default of a single series for the tab hue', () => {
    const data = [
      { type: 'histogram', x: [1, 2, 3], marker: { color: '#636efa', pattern: { shape: '' } }, name: '' },
    ];
    const out = tintSingleSeries(data, { template: { layout: {} } }, HUE);
    expect(out.tinted).toBe(true);
    expect((out.data[0] as any).marker.color).toBe(HUE);
    expect((out.data[0] as any).marker.pattern).toEqual({ shape: '' });
    expect(out.layout.colorway).toEqual([HUE]);
    // the figure it was given is not modified
    expect(data[0].marker.color).toBe('#636efa');
  });

  it('recognises the template colorway as the default', () => {
    const layout = { template: { layout: { colorway: ['#228be6', '#fa5252'] } } };
    const out = tintSingleSeries(
      [{ type: 'bar', y: [1], marker: { color: '#228BE6' } }],
      layout,
      HUE,
    );
    expect(out.tinted).toBe(true);
    expect((out.data[0] as any).marker.color).toBe(HUE);
  });

  it('tints a trace that named no colour through the colorway', () => {
    const out = tintSingleSeries([{ type: 'bar', y: [1, 2] }], {}, HUE);
    expect(out.tinted).toBe(true);
    expect(out.layout.colorway).toEqual([HUE]);
  });

  it('swaps the line of a line plot and its default fill', () => {
    const out = tintSingleSeries(
      [{ type: 'scatter', mode: 'lines', line: { color: '#636efa' }, fillcolor: '#636efa' }],
      {},
      HUE,
    );
    expect((out.data[0] as any).line.color).toBe(HUE);
    expect((out.data[0] as any).fillcolor).toBe(HUE);
  });

  it('leaves data colours alone', () => {
    const arr = tintSingleSeries([{ type: 'scatter', marker: { color: [1, 2, 3] } }], {}, HUE);
    expect(arr.tinted).toBe(false);
    const scale = tintSingleSeries(
      [{ type: 'scatter', marker: { color: '#636efa', colorscale: 'Viridis' } }],
      {},
      HUE,
    );
    expect(scale.tinted).toBe(false);
    const axis = tintSingleSeries([{ type: 'scatter', marker: { coloraxis: 'coloraxis' } }], {}, HUE);
    expect(axis.tinted).toBe(false);
    const layoutAxis = tintSingleSeries([{ type: 'bar' }], { coloraxis: { colorscale: [] } }, HUE);
    expect(layoutAxis.tinted).toBe(false);
  });

  it('leaves a category or verdict colour alone', () => {
    const mapped = tintSingleSeries(
      [{ type: 'bar', marker: { color: '#e03131' }, name: 'FAIL', legendgroup: 'FAIL' }],
      {},
      HUE,
    );
    expect(mapped.tinted).toBe(false);
    // A lone category that happens to hold the default colour keeps its identity
    const lone = tintSingleSeries(
      [{ type: 'bar', marker: { color: '#636efa' }, name: 'WT', legendgroup: 'WT' }],
      {},
      HUE,
    );
    expect(lone.tinted).toBe(false);
  });

  it('leaves a multi-series figure alone unless every trace is the default', () => {
    const split = tintSingleSeries(
      [
        { type: 'bar', marker: { color: '#636efa' } },
        { type: 'bar', marker: { color: '#EF553B' } },
      ],
      {},
      HUE,
    );
    expect(split.tinted).toBe(false);
    const bare = tintSingleSeries([{ type: 'bar' }, { type: 'bar' }], {}, HUE);
    expect(bare.tinted).toBe(false);
    const pieces = tintSingleSeries(
      [
        { type: 'scatter', marker: { color: '#636efa' } },
        { type: 'scatter', line: { color: '#636efa' } },
      ],
      {},
      HUE,
    );
    expect(pieces.tinted).toBe(true);
  });

  it('ignores trace types it does not know and a missing hue', () => {
    expect(tintSingleSeries([{ type: 'heatmap', z: [[1]] }], {}, HUE).tinted).toBe(false);
    expect(tintSingleSeries([{ type: 'pie', labels: ['a'] }], {}, HUE).tinted).toBe(false);
    expect(tintSingleSeries([{ type: 'bar' }], {}, undefined).tinted).toBe(false);
    expect(tintSingleSeries([], {}, HUE).tinted).toBe(false);
  });
});

describe('tabHueHex', () => {
  const theme = {
    colors: {
      teal: ['#0', '#1', '#2', '#3', '#4', '#5', '#6', '#7', '#8', '#9'],
      brandPrimary: ['#a0', '#a1', '#a2', '#a3', '#a4', '#a5', '#a6', '#a7', '#a8', '#a9'],
    },
  } as never;
  it('picks shade 6 on light and 4 on dark', () => {
    expect(tabHueHex(theme, 'teal', false)).toBe('#6');
    expect(tabHueHex(theme, 'teal', true)).toBe('#4');
    expect(tabHueHex(theme, 'brandPrimary', false)).toBe('#a6');
  });
  it('takes a shade the tab names', () => {
    expect(tabHueHex(theme, 'teal.8', false)).toBe('#8');
  });
  it('is no hue for ink, nothing or an unknown palette', () => {
    expect(tabHueHex(theme, 'dark', false)).toBeUndefined();
    expect(tabHueHex(theme, null, false)).toBeUndefined();
    expect(tabHueHex(theme, 'nope', false)).toBeUndefined();
  });
});
