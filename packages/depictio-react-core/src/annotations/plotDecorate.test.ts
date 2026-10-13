import { describe, expect, it, vi } from 'vitest';

import {
  ANNOTATABLE_VIZ_KINDS,
  appendAnnotationTraces,
  componentSupportsAnnotation,
  decorateAnnotationLayout,
  ANNOTATE_MODEBAR_REMOVE,
  annotationIdFromClick,
  annotationIdFromName,
  mergePlotHandlers,
  restoreSelectionUpdates,
  snapshotSelection,
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
  it('accepts the single-subplot cartesian kinds', () => {
    for (const kind of [
      'stacked_taxonomy',
      'rarefaction',
      'enrichment',
      'dot_plot',
      'lollipop',
      'qq',
      'pr_benchmark',
      'roc_pr_curve',
      'confusion_matrix',
      'metric_ci_bars',
      'profile',
      'gsea_running_score',
      'coverage_track',
    ]) {
      expect(componentSupportsAnnotation('advanced_viz', { viz_kind: kind })).toBe(true);
    }
  });
  it('leaves out multi-subplot, non-cartesian and schematic kinds', () => {
    for (const kind of [
      'complex_heatmap',
      'oncoplot',
      'signal_matrix',
      'upset_plot',
      'sunburst',
      'sankey',
      'phylogenetic',
      'sashimi',
      'fusion_structure',
      'gene_arrow_track',
    ]) {
      expect(componentSupportsAnnotation('advanced_viz', { viz_kind: kind })).toBe(false);
    }
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
  it('takes the overlays out of hover in annotate mode', () => {
    const overlay = { name: 'annotation-1', hoverinfo: 'text' };
    const out = appendAnnotationTraces(data, { overlayTraces: [overlay] }, true);
    expect(out[1]).toMatchObject({ hoverinfo: 'skip' });
    expect(appendAnnotationTraces(data, { overlayTraces: [overlay] })[1]).toMatchObject({ hoverinfo: 'text' });
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
  it('applies the tool dragmode and never freezes an axis', () => {
    const out = decorateAnnotationLayout({ xaxis: { title: 'x' } }, null, { dragmode: 'select' });
    expect(out.dragmode).toBe('select');
    expect(out.xaxis).toEqual({ title: 'x' });
    expect(out).not.toHaveProperty('yaxis');
    expect(decorateAnnotationLayout({}, null, { dragmode: false }).dragmode).toBe(false);
  });
  it('makes clicks event-only and hides only the select/lasso modebar buttons while annotating', () => {
    const own = { modebar: { orientation: 'v', remove: ['toImage', 'lasso2d'] }, clickmode: 'event+select' };
    const out = decorateAnnotationLayout(own, null, { dragmode: 'select' });
    expect(out.clickmode).toBe('event');
    const modebar = out.modebar as { orientation: string; remove: string[] };
    expect(modebar.orientation).toBe('v');
    expect(modebar.remove).toContain('toImage');
    expect(ANNOTATE_MODEBAR_REMOVE).toEqual(['select2d', 'lasso2d']);
    for (const b of ANNOTATE_MODEBAR_REMOVE) expect(modebar.remove).toContain(b);
    for (const b of ['zoom2d', 'pan2d', 'zoomIn2d', 'zoomOut2d', 'autoScale2d', 'resetScale2d']) {
      expect(modebar.remove).not.toContain(b);
    }
    expect(modebar.remove.filter((b) => b === 'lasso2d')).toHaveLength(1);
    expect(own.modebar.remove).toEqual(['toImage', 'lasso2d']);
    const str = decorateAnnotationLayout({ modebar: { remove: 'toImage' } }, null, { dragmode: 'lasso' });
    expect((str.modebar as { remove: string[] }).remove[0]).toBe('toImage');
  });
  it('stops labels capturing clicks in annotate mode only', () => {
    const plotly = { shapes: [], annotations: [{ text: 'a', captureevents: true }, { text: 'b' }] };
    const outside = decorateAnnotationLayout({}, plotly, null);
    expect(outside.annotations).toEqual(plotly.annotations);
    const inside = decorateAnnotationLayout({}, plotly, { dragmode: 'select' });
    expect(inside.annotations).toEqual([{ text: 'a', captureevents: false }, { text: 'b' }]);
    expect(plotly.annotations[0].captureevents).toBe(true);
  });
  it('leaves clickmode and the modebar alone outside annotate mode', () => {
    const out = decorateAnnotationLayout({}, { shapes: [{ type: 'rect' }], annotations: [] }, null);
    expect(out).not.toHaveProperty('clickmode');
    expect(out).not.toHaveProperty('modebar');
  });
});

describe('selection snapshot', () => {
  it('records drawn selections and per-trace selectedpoints as copies', () => {
    const selections = [{ type: 'rect', x0: 0, x1: 1 }];
    const data = [{ selectedpoints: [1, 2] }, {}, { selectedpoints: new Int32Array([4]) }];
    const snap = snapshotSelection({ selections }, data);
    expect(snap.selections).toEqual(selections);
    expect(snap.selections![0]).not.toBe(selections[0]);
    expect(snap.selectedpoints).toEqual([[1, 2], null, [4]]);
    (data[0].selectedpoints as number[]).push(9);
    expect(snap.selectedpoints[0]).toEqual([1, 2]);
  });
  it('builds the relayout/restyle calls that put it back', () => {
    const snap = snapshotSelection({ selections: [{ type: 'rect' }] }, [{ selectedpoints: [3] }, {}]);
    const { relayout, restyle } = restoreSelectionUpdates(snap);
    expect(relayout).toEqual({ selections: [{ type: 'rect' }] });
    expect(restyle).toEqual({ update: { selectedpoints: [[3], null] }, indices: [0, 1] });
  });
  it('clears everything when nothing was selected', () => {
    const { relayout, restyle } = restoreSelectionUpdates(snapshotSelection({}, [{}]));
    expect(relayout).toEqual({ selections: null });
    expect(restyle).toEqual({ update: { selectedpoints: [null] }, indices: [0] });
    expect(restoreSelectionUpdates(snapshotSelection(null, null)).restyle).toBeNull();
  });
});

describe('annotation click ids', () => {
  it('reads the thread id from overlay and label names', () => {
    expect(annotationIdFromName('annotation-t1')).toBe('t1');
    expect(annotationIdFromName('annotation-__preview__')).toBeNull();
    expect(annotationIdFromName('annotation-')).toBeNull();
    expect(annotationIdFromName('trace 0')).toBeNull();
    expect(annotationIdFromName(undefined)).toBeNull();
  });
  it('recognises label clicks and marked-point ring clicks', () => {
    expect(annotationIdFromClick({ index: 0, annotation: { name: 'annotation-t1' } })).toBe('t1');
    expect(annotationIdFromClick({ index: 0, annotation: { text: 'top gene' } })).toBeNull();
    expect(annotationIdFromClick({ points: [{ data: { name: 'annotation-t2' } }] })).toBe('t2');
    expect(annotationIdFromClick({ points: [{ fullData: { name: 'annotation-t3' } }] })).toBe('t3');
    expect(
      annotationIdFromClick({ points: [{ data: { name: 'real' } }, { data: { name: 'annotation-t2' } }] }),
    ).toBeNull();
    expect(annotationIdFromClick(null)).toBeNull();
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
  it('routes clicks on saved annotations to the thread, others to the renderer', () => {
    const open = vi.fn();
    const onClick = vi.fn();
    const out = mergePlotHandlers({ ...own, onClick }, annotate, null, open);
    expect(out.onSelected).toBe(own.onSelected);
    const click = { points: [{ data: { name: 'annotation-t1' } }], event: { clientX: 1, clientY: 2 } };
    out.onClick!(click);
    // The Plotly event rides along, for the editor's anchor.
    expect(open).toHaveBeenCalledWith('t1', click);
    expect(onClick).not.toHaveBeenCalled();
    out.onClick!({ points: [{ data: { name: 'trace' } }] });
    expect(onClick).toHaveBeenCalledTimes(1);
    const labelClick = { annotation: { name: 'annotation-t9' } };
    out.onClickAnnotation!(labelClick);
    expect(open).toHaveBeenLastCalledWith('t9', labelClick);
    // A renderer without a click handler still opens threads.
    const bare = mergePlotHandlers({}, annotate, null, open);
    expect(() => bare.onClick!({ points: [{ data: { name: 'x' } }] })).not.toThrow();
  });
  it('detaches the selection and click handlers in every annotate capture', () => {
    const open = vi.fn();
    for (const capture of ['click', 'selected'] as const) {
      const out = mergePlotHandlers(own, annotate, capture, open);
      expect(out.onClick).toBeUndefined();
      expect(out.onClickAnnotation).toBeUndefined();
      expect(out.onDeselect).toBeUndefined();
      expect(out.onSelecting).toBeUndefined();
      expect(out.onSelected).toBe(capture === 'selected' ? annotate.onSelected : undefined);
    }
  });
  it('lets the layer observe relayout before the renderer, and hands hover to the click tools', () => {
    const sel = mergePlotHandlers(own, annotate, 'selected');
    sel.onRelayout!({ dragmode: 'zoom' });
    expect(annotate.onRelayout).toHaveBeenCalledWith({ dragmode: 'zoom' });
    expect(own.onRelayout).toHaveBeenCalledWith({ dragmode: 'zoom' });
    expect(sel.onHover).toBe(own.onHover);
    const click = mergePlotHandlers(own, annotate, 'click');
    expect(click.onHover).toBe(annotate.onHover);
    expect(click.onUnhover).toBe(annotate.onUnhover);
  });
});
