import { describe, expect, it, vi } from 'vitest';

import {
  ANNOTATABLE_VIZ_KINDS,
  appendAnnotationTraces,
  componentSupportsAnnotation,
  decorateAnnotationLayout,
  mergePlotHandlers,
  supportsAdvancedVizAnnotation,
  tableAnnotationColumn,
} from './plotDecorate';

describe('componentSupportsAnnotation', () => {
  it('keeps the cartesian-figure rule', () => {
    expect(componentSupportsAnnotation('figure', { visu_type: 'scatter' })).toBe(true);
    expect(componentSupportsAnnotation('figure', { visu_type: 'pie' })).toBe(false);
  });
  it('accepts the wired advanced_viz kinds only', () => {
    for (const kind of ['volcano', 'manhattan', 'embedding', 'scatter_xy', 'da_barplot', 'ma']) {
      expect(ANNOTATABLE_VIZ_KINDS.has(kind)).toBe(true);
      expect(componentSupportsAnnotation('advanced_viz', { viz_kind: kind })).toBe(true);
    }
    expect(componentSupportsAnnotation('advanced_viz', { viz_kind: 'sankey' })).toBe(false);
    expect(supportsAdvancedVizAnnotation({})).toBe(false);
  });
  it('accepts tables with a row-id column', () => {
    expect(componentSupportsAnnotation('table', { row_selection_column: 'sample' })).toBe(true);
    expect(componentSupportsAnnotation('table', { selection_column: 'id' })).toBe(true);
    expect(componentSupportsAnnotation('table', { row_selection_column: '' })).toBe(false);
    expect(componentSupportsAnnotation('table', {})).toBe(false);
  });
  it('rejects other component types', () => {
    expect(componentSupportsAnnotation('card', { visu_type: 'scatter' })).toBe(false);
    expect(componentSupportsAnnotation(undefined, {})).toBe(false);
  });
});

describe('tableAnnotationColumn', () => {
  it('prefers row_selection_column over selection_column', () => {
    expect(tableAnnotationColumn({ row_selection_column: 'a', selection_column: 'b' })).toBe('a');
    expect(tableAnnotationColumn({ selection_column: 'b' })).toBe('b');
    expect(tableAnnotationColumn({ selection_column: 3 })).toBeNull();
  });
});

describe('appendAnnotationTraces', () => {
  const data = [{ type: 'scatter', name: 'real' }];
  it('returns the same array when there is nothing to add', () => {
    expect(appendAnnotationTraces(data, null)).toBe(data);
    expect(appendAnnotationTraces(data, { overlayTraces: [] })).toBe(data);
  });
  it('appends overlays after the real traces, never dimmed', () => {
    const out = appendAnnotationTraces(data, { overlayTraces: [{ name: 'annotation-1' }] });
    expect(out).toHaveLength(2);
    expect(out[0]).toBe(data[0]);
    expect(out[1]).toEqual({ name: 'annotation-1', unselected: { marker: { opacity: 1 } } });
    expect(data).toHaveLength(1);
  });
});

describe('decorateAnnotationLayout', () => {
  const layout = { shapes: [{ type: 'line' }], annotations: [{ text: 'own' }], dragmode: 'lasso' };
  it('returns the same layout when there is nothing to change', () => {
    expect(decorateAnnotationLayout(layout, null, null)).toBe(layout);
    expect(decorateAnnotationLayout(layout, { shapes: [], annotations: [] }, null)).toBe(layout);
  });
  it('appends shapes and labels after the figure’s own', () => {
    const out = decorateAnnotationLayout(
      layout,
      { shapes: [{ type: 'rect' }], annotations: [{ text: 'mine' }] },
      null,
    );
    expect(out.shapes).toEqual([{ type: 'line' }, { type: 'rect' }]);
    expect(out.annotations).toEqual([{ text: 'own' }, { text: 'mine' }]);
    expect(out.dragmode).toBe('lasso');
    expect(layout.shapes).toHaveLength(1);
  });
  it('creates the arrays when the figure has none', () => {
    const out = decorateAnnotationLayout({}, { shapes: [{ type: 'rect' }], annotations: [] }, null);
    expect(out.shapes).toEqual([{ type: 'rect' }]);
    expect(out).not.toHaveProperty('annotations');
  });
  it('applies the tool dragmode and freezes the other axis of a range drag', () => {
    const out = decorateAnnotationLayout(
      { xaxis: { title: 'x' } },
      null,
      { dragmode: 'zoom', fixedAxis: 'x' },
    );
    expect(out.dragmode).toBe('zoom');
    expect(out.xaxis).toEqual({ title: 'x', fixedrange: true });
    expect(out).not.toHaveProperty('yaxis');
    expect(decorateAnnotationLayout({}, null, { dragmode: false, fixedAxis: null }).dragmode).toBe(false);
  });
});

describe('mergePlotHandlers', () => {
  const own = {
    onSelected: vi.fn(),
    onSelecting: vi.fn(),
    onClick: vi.fn(),
    onDeselect: vi.fn(),
    onRelayout: vi.fn(),
    onHover: vi.fn(),
  };
  const annotate = {
    onSelected: vi.fn(),
    onRelayout: vi.fn(),
    onHover: vi.fn(),
    onUnhover: vi.fn(),
  };
  it('keeps the renderer handlers outside annotate mode', () => {
    expect(mergePlotHandlers(own, annotate, null)).toBe(own);
  });
  it('detaches the selection handlers in every annotate capture', () => {
    for (const capture of ['relayout', 'click', 'selected'] as const) {
      const out = mergePlotHandlers(own, annotate, capture);
      expect(out.onClick).toBeUndefined();
      expect(out.onDeselect).toBeUndefined();
      expect(out.onSelecting).toBeUndefined();
      expect(out.onSelected).toBe(capture === 'selected' ? annotate.onSelected : undefined);
    }
  });
  it('hands relayout and hover to the active capture only', () => {
    const range = mergePlotHandlers(own, annotate, 'relayout');
    expect(range.onRelayout).toBe(annotate.onRelayout);
    expect(range.onHover).toBe(own.onHover);
    const click = mergePlotHandlers(own, annotate, 'click');
    expect(click.onRelayout).toBe(own.onRelayout);
    expect(click.onHover).toBe(annotate.onHover);
    expect(click.onUnhover).toBe(annotate.onUnhover);
  });
});
