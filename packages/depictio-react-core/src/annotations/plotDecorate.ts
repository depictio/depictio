/**
 * Pure glue between the annotation layer and a Plotly `<Plot>`: which
 * components may carry annotations, how a figure's data/layout are decorated
 * with them, and which Plotly event handlers stay attached in annotate mode.
 * Shared by FigureRenderer and the advanced_viz renderers through
 * `usePlotAnnotationLayer`. No React, no DOM.
 */
import type { AnnotateInteraction, CaptureEvent } from './layer';
import { supportsAnnotation } from './layer';
import type { AnnotationsToPlotlyResult } from './toPlotly';
import { OVERLAY_TRACE_PREFIX } from './toPlotly';
import { PREVIEW_ANNOTATION_ID } from './types';

/**
 * advanced_viz kinds drawn as one cartesian Plotly plot whose renderer wires
 * the annotation layer. Kinds outside this set never show the annotate action.
 */
export const ANNOTATABLE_VIZ_KINDS: ReadonlySet<string> = new Set([
  'volcano',
  'manhattan',
  'embedding',
  'scatter_xy',
  'da_barplot',
  'ancombc_differentials',
  'ma',
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
]);

export function supportsAdvancedVizAnnotation(meta: { viz_kind?: unknown }): boolean {
  return typeof meta.viz_kind === 'string' && ANNOTATABLE_VIZ_KINDS.has(meta.viz_kind);
}

/** Row-id column a table's row annotations are keyed on, or null. */
export function tableAnnotationColumn(meta: {
  row_selection_column?: unknown;
  selection_column?: unknown;
}): string | null {
  if (typeof meta.row_selection_column === 'string' && meta.row_selection_column) {
    return meta.row_selection_column;
  }
  if (typeof meta.selection_column === 'string' && meta.selection_column) {
    return meta.selection_column;
  }
  return null;
}

/**
 * Whether a component of this type can be annotated: cartesian figures, the
 * advanced_viz kinds of ANNOTATABLE_VIZ_KINDS, and tables with a row-id column.
 */
export function componentSupportsAnnotation(
  componentType: string | null | undefined,
  meta: Record<string, unknown>,
): boolean {
  switch (componentType) {
    case 'figure':
      return supportsAnnotation({ ...meta, component_type: 'figure' });
    case 'advanced_viz':
      return supportsAdvancedVizAnnotation(meta);
    case 'table':
      return tableAnnotationColumn(meta) != null;
    case 'multiqc':
      // Figures and the General Stats table; the renderer reports which
      // views can take them (not multi-panel figures, not the violin view).
      return true;
    default:
      return false;
  }
}

/**
 * The figure's traces followed by the annotation overlay traces. Overlays go
 * last so the curveNumber of every real trace is unchanged, and never dim
 * under a selection. In annotate mode (`annotating`) they take no hover, so
 * the tools only ever see the figure's own points. Returns `data` itself when
 * there is nothing to add.
 */
export function appendAnnotationTraces(
  data: readonly unknown[],
  plotly: Pick<AnnotationsToPlotlyResult, 'overlayTraces'> | null | undefined,
  annotating = false,
): unknown[] {
  if (!plotly || plotly.overlayTraces.length === 0) return data as unknown[];
  const out: unknown[] = [...data];
  plotly.overlayTraces.forEach((t) =>
    out.push({
      ...(t as Record<string, unknown>),
      ...(annotating ? { hoverinfo: 'skip' } : {}),
      unselected: { marker: { opacity: 1 } },
    }),
  );
  return out;
}

/** Thread id carried by an overlay trace or label `name`, or null (preview, other names). */
export function annotationIdFromName(name: unknown): string | null {
  if (typeof name !== 'string' || !name.startsWith(OVERLAY_TRACE_PREFIX)) return null;
  const id = name.slice(OVERLAY_TRACE_PREFIX.length);
  return id && id !== PREVIEW_ANNOTATION_ID ? id : null;
}

/**
 * Thread id of an annotation clicked on a plot: a label (`plotly_clickannotation`
 * carries the layout annotation) or a marked-points ring (`plotly_click`,
 * when its nearest point belongs to an overlay trace). Null otherwise.
 */
export function annotationIdFromClick(event: unknown): string | null {
  if (!event || typeof event !== 'object') return null;
  const ev = event as {
    annotation?: { name?: unknown } | null;
    fullAnnotation?: { name?: unknown } | null;
    points?: Array<{ data?: { name?: unknown }; fullData?: { name?: unknown } } | null>;
  };
  if (ev.annotation || ev.fullAnnotation) {
    return annotationIdFromName(ev.annotation?.name ?? ev.fullAnnotation?.name);
  }
  const first = Array.isArray(ev.points) ? ev.points[0] : null;
  return first ? annotationIdFromName(first.data?.name ?? first.fullData?.name) : null;
}

/**
 * The layout with the annotation shapes/labels appended after the figure's
 * own, and the annotate tool's dragmode. In annotate mode the labels stop
 * capturing clicks (they belong to the tools). Returns `layout` itself when
 * there is nothing to change.
 */
export function decorateAnnotationLayout(
  layout: Record<string, unknown>,
  plotly: Pick<AnnotationsToPlotlyResult, 'shapes' | 'annotations'> | null | undefined,
  interaction: Pick<AnnotateInteraction, 'dragmode'> | null | undefined,
): Record<string, unknown> {
  const addShapes = !!plotly && plotly.shapes.length > 0;
  const addLabels = !!plotly && plotly.annotations.length > 0;
  if (!addShapes && !addLabels && !interaction) return layout;
  const base: Record<string, unknown> = { ...layout };
  if (addShapes) {
    const own = Array.isArray(base.shapes) ? (base.shapes as unknown[]) : [];
    base.shapes = [...own, ...plotly!.shapes];
  }
  if (addLabels) {
    const own = Array.isArray(base.annotations) ? (base.annotations as unknown[]) : [];
    const labels = interaction
      ? plotly!.annotations.map((a) => (a.captureevents ? { ...a, captureevents: false } : a))
      : plotly!.annotations;
    base.annotations = [...own, ...labels];
  }
  if (interaction) {
    base.dragmode = interaction.dragmode;
    // A click never selects (and so never dims) points while annotating:
    // line/note clicks are captured by the layer, not by Plotly.
    base.clickmode = 'event';
    // The tools set the select/lasso gesture themselves; zoom, pan and the
    // axis reset stay in the modebar (axis changes are never captured).
    base.modebar = {
      ...((base.modebar as Record<string, unknown>) || {}),
      remove: mergeModebarRemove((base.modebar as { remove?: unknown } | undefined)?.remove),
    };
  }
  return base;
}

/** Modebar buttons hidden while annotating (see decorateAnnotationLayout). */
export const ANNOTATE_MODEBAR_REMOVE: readonly string[] = ['select2d', 'lasso2d'];

function mergeModebarRemove(own: unknown): string[] {
  const list = Array.isArray(own)
    ? own.filter((b): b is string => typeof b === 'string' && b !== '')
    : typeof own === 'string' && own
      ? [own]
      : [];
  return Array.from(new Set([...list, ...ANNOTATE_MODEBAR_REMOVE]));
}

/**
 * The selection a figure shows (drawn `layout.selections` and each trace's
 * `selectedpoints`), e.g. a dashboard selection highlight. Captured on
 * entering a points/click tool so annotating never wipes it.
 */
export interface SelectionSnapshot {
  selections: unknown[] | null;
  /** Per trace, in trace order; null = no selection on that trace. */
  selectedpoints: Array<unknown[] | null>;
}

function copyPoints(v: unknown): unknown[] | null {
  if (Array.isArray(v)) return [...v];
  if (ArrayBuffer.isView(v) && typeof (v as unknown as { length?: unknown }).length === 'number') {
    return Array.from(v as unknown as ArrayLike<unknown>);
  }
  return null;
}

/** Snapshot of the selection state of a graph div's `layout` / `data`. */
export function snapshotSelection(
  layout: { selections?: unknown } | null | undefined,
  data: readonly unknown[] | null | undefined,
): SelectionSnapshot {
  const sel = layout?.selections;
  return {
    selections: Array.isArray(sel)
      ? sel.map((s) => (s && typeof s === 'object' ? { ...(s as Record<string, unknown>) } : s))
      : null,
    selectedpoints: (data ?? []).map((t) =>
      copyPoints((t as { selectedpoints?: unknown } | null)?.selectedpoints),
    ),
  };
}

/**
 * The `Plotly.relayout` / `Plotly.restyle` calls putting a snapshot back.
 * Only the traces present at snapshot time are restyled; `restyle` is null
 * when the figure had no traces.
 */
export function restoreSelectionUpdates(snapshot: SelectionSnapshot): {
  relayout: Record<string, unknown>;
  restyle: { update: Record<string, unknown>; indices: number[] } | null;
} {
  const n = snapshot.selectedpoints.length;
  return {
    relayout: {
      selections: snapshot.selections
        ? snapshot.selections.map((s) => (s && typeof s === 'object' ? { ...(s as object) } : s))
        : null,
    },
    restyle:
      n > 0
        ? {
            // One value per trace (restyle's per-trace array form).
            update: { selectedpoints: snapshot.selectedpoints.map((p) => (p ? [...p] : null)) },
            indices: Array.from({ length: n }, (_, i) => i),
          }
        : null,
  };
}

/** The Plotly event props a renderer and the annotation layer both use. */
export interface PlotEventHandlers {
  onSelected?: (event: any) => void;
  onSelecting?: (event: any) => void;
  onClick?: (event: any) => void;
  onDeselect?: () => void;
  onRelayout?: (event: any) => void;
  onHover?: (event: any) => void;
  onUnhover?: (event: any) => void;
  onClickAnnotation?: (event: any) => void;
}

/**
 * The event handlers to hand `<Plot>`. Outside annotate mode (`capture`
 * null) the renderer's own handlers are kept, except that a click on a saved
 * annotation (its label or a marked-points ring) goes to `openAnnotation`
 * instead of the renderer's click filter. In annotate mode the renderer's
 * selection and click handlers are detached, so a gesture draws an annotation
 * and never filters the dashboard: the selection goes to the layer, and
 * relayout is observed by the layer (to notice a zoom/pan picked in the
 * modebar) before reaching the renderer.
 */
export function mergePlotHandlers(
  own: PlotEventHandlers,
  annotate: Required<Pick<PlotEventHandlers, 'onSelected' | 'onRelayout' | 'onHover' | 'onUnhover'>>,
  capture: CaptureEvent | null,
  openAnnotation?: ((threadId: string, event: unknown) => void) | null,
): PlotEventHandlers {
  if (!capture) {
    if (!openAnnotation) return own;
    return {
      ...own,
      onClick: (event: any) => {
        const id = annotationIdFromClick(event);
        if (id) openAnnotation(id, event);
        else own.onClick?.(event);
      },
      onClickAnnotation: (event: any) => {
        const id = annotationIdFromClick(event);
        if (id) openAnnotation(id, event);
        else own.onClickAnnotation?.(event);
      },
    };
  }
  return {
    onSelected: capture === 'selected' ? annotate.onSelected : undefined,
    onSelecting: undefined,
    onClick: undefined,
    onDeselect: undefined,
    onClickAnnotation: undefined,
    onRelayout: (event: any) => {
      annotate.onRelayout(event);
      own.onRelayout?.(event);
    },
    onHover: capture === 'click' ? annotate.onHover : own.onHover,
    onUnhover: capture === 'click' ? annotate.onUnhover : own.onUnhover,
  };
}
