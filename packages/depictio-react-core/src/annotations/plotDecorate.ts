/**
 * Pure glue between the annotation layer and a Plotly `<Plot>`: which
 * components may carry annotations, how a figure's data/layout are decorated
 * with them, and which Plotly event handlers stay attached in annotate mode.
 * Shared by FigureRenderer and the advanced_viz renderers through
 * `usePlotAnnotationLayer`. No React, no DOM.
 */
import type { AnnotateInteraction } from './layer';
import { supportsAnnotation } from './layer';
import type { AnnotationsToPlotlyResult } from './toPlotly';

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
    default:
      return false;
  }
}

/**
 * The figure's traces followed by the annotation overlay traces. Overlays go
 * last so the curveNumber of every real trace is unchanged, and never dim
 * under a selection. Returns `data` itself when there is nothing to add.
 */
export function appendAnnotationTraces(
  data: readonly unknown[],
  plotly: Pick<AnnotationsToPlotlyResult, 'overlayTraces'> | null | undefined,
): unknown[] {
  if (!plotly || plotly.overlayTraces.length === 0) return data as unknown[];
  const out: unknown[] = [...data];
  plotly.overlayTraces.forEach((t) =>
    out.push({ ...(t as Record<string, unknown>), unselected: { marker: { opacity: 1 } } }),
  );
  return out;
}

/**
 * The layout with the annotation shapes/labels appended after the figure's
 * own, and the annotate tool's dragmode (plus the frozen axis of a range
 * drag). Returns `layout` itself when there is nothing to change.
 */
export function decorateAnnotationLayout(
  layout: Record<string, unknown>,
  plotly: Pick<AnnotationsToPlotlyResult, 'shapes' | 'annotations'> | null | undefined,
  interaction: Pick<AnnotateInteraction, 'dragmode' | 'fixedAxis'> | null | undefined,
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
    base.annotations = [...own, ...plotly!.annotations];
  }
  if (interaction) {
    base.dragmode = interaction.dragmode;
    if (interaction.fixedAxis) {
      // A range drag moves along one axis only: freeze the other so the zoom
      // box becomes a band.
      const key = `${interaction.fixedAxis}axis`;
      base[key] = { ...((base[key] as Record<string, unknown>) || {}), fixedrange: true };
    }
  }
  return base;
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
}

/**
 * The event handlers to hand `<Plot>`. Outside annotate mode (`capture`
 * null) the renderer's own handlers are kept as they are. In annotate mode
 * its selection handlers are detached, so a gesture draws an annotation and
 * never filters the dashboard; the annotation handler of the active capture
 * takes over its event, and relayout/hover stay with the renderer otherwise.
 */
export function mergePlotHandlers(
  own: PlotEventHandlers,
  annotate: Required<Pick<PlotEventHandlers, 'onSelected' | 'onRelayout' | 'onHover' | 'onUnhover'>>,
  capture: AnnotateInteraction['capture'] | null,
): PlotEventHandlers {
  if (!capture) return own;
  return {
    onSelected: capture === 'selected' ? annotate.onSelected : undefined,
    onSelecting: undefined,
    onClick: undefined,
    onDeselect: undefined,
    onRelayout: capture === 'relayout' ? annotate.onRelayout : own.onRelayout,
    onHover: capture === 'click' ? annotate.onHover : own.onHover,
    onUnhover: capture === 'click' ? annotate.onUnhover : own.onUnhover,
  };
}
