import { describe, expect, it } from 'vitest';
import { drawnOncePerPanel, splitPanelsUsable } from './figureSplit';

describe('drawnOncePerPanel (#1476)', () => {
  it('splits a code figure that never names the groups, before any render', () => {
    expect(drawnOncePerPanel({ mode: 'code', code_content: "fig = px.box(df, x='a')" })).toBe(true);
  });

  it('trusts a code figure that spreads the groups itself', () => {
    const code = "fig = px.box(df, x='a', **depictio_group_kwargs)";
    expect(drawnOncePerPanel({ mode: 'code', code_content: code })).toBe(false);
    // Even when its own layout did not facet: the author chose where groups go.
    expect(drawnOncePerPanel({ mode: 'code', code_content: code }, false)).toBe(false);
  });

  it('splits a chart type Plotly cannot facet, before any render', () => {
    for (const visu_type of ['pie', 'sunburst', 'treemap', 'scatter_3d', 'scatter_polar', 'heatmap', 'parallel_coordinates']) {
      expect(drawnOncePerPanel({ mode: 'ui', visu_type })).toBe(true);
    }
  });

  it('splits a UI figure once the server says its split did not take', () => {
    expect(drawnOncePerPanel({ visu_type: 'bar' })).toBe(false);
    expect(drawnOncePerPanel({ visu_type: 'bar' }, null)).toBe(false);
    expect(drawnOncePerPanel({ visu_type: 'bar' }, true)).toBe(false);
    expect(drawnOncePerPanel({ visu_type: 'bar' }, false)).toBe(true);
  });
});

describe('splitPanelsUsable', () => {
  it('needs two to six panels for an analysis split', () => {
    expect(splitPanelsUsable(1, false)).toBe(false);
    expect(splitPanelsUsable(2, false)).toBe(true);
    expect(splitPanelsUsable(6, false)).toBe(true);
    expect(splitPanelsUsable(7, false)).toBe(false);
  });

  it('keeps the what-is-new split as it was (any panel)', () => {
    expect(splitPanelsUsable(1, true)).toBe(true);
    expect(splitPanelsUsable(0, true)).toBe(false);
  });
});
