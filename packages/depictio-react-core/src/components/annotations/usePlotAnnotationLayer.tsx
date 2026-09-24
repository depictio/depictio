import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Tooltip, useComputedColorScheme, useMantineTheme } from '@mantine/core';
// Same prebuilt bundle react-plotly.js uses (see FigureRenderer).
import Plotly from 'plotly.js';

import { useAnnotationLayer } from '../../annotations/AnnotationLayerContext';
import {
  annotateInteraction,
  DEFAULT_ANNOTATE_OPTIONS,
  normalizeTraces,
  pixelToData,
  pointMisses,
  relayoutSetsRange,
  restoreAxesUpdate,
  snapshotAxes,
  stripOverlayPoints,
} from '../../annotations/layer';
import type { AnnotateInteraction, AnnotateOptions, AnnotateTool, AxisSnapshot } from '../../annotations/layer';
import { annotationsToPlotly } from '../../annotations/toPlotly';
import {
  arrowNoteFromClick,
  markedPointsFromSelection,
  rangeFromRelayout,
  refLineFromClick,
} from '../../annotations/capture';
import { makeColorResolver } from '../../annotations/resolveColor';
import { numberBadge } from '../../annotations/types';
import type { RenderableAnnotation } from '../../annotations/types';
import {
  appendAnnotationTraces,
  decorateAnnotationLayout,
  mergePlotHandlers,
  restoreSelectionUpdates,
  snapshotSelection,
} from '../../annotations/plotDecorate';
import type { PlotEventHandlers, SelectionSnapshot } from '../../annotations/plotDecorate';
import { isAnnotateEscape } from '../../annotations/escape';
import AnnotateToolbar from './AnnotateToolbar';

const NO_ANNOTATIONS: RenderableAnnotation[] = [];
const NO_DATA: unknown[] = [];
const NO_LAYOUT: Record<string, unknown> = {};

type PlotlyTarget = Parameters<typeof Plotly.relayout>[0];

/** Wipe a drawn lasso/box and un-dim every trace. Best effort: the graph div
 *  may have unmounted between scheduling and running. */
export function clearDrawnSelection(gd: HTMLElement | null): void {
  if (!gd) return;
  try {
    // Casts: @types/plotly.js wants Plotly types on gd but the wrapper
    // exposes a regular HTMLElement that Plotly accepts at runtime; and
    // `selections` / `selectedpoints` aren't in the typed layout/style
    // surface but Plotly accepts them as a known clear-state idiom.
    const target = gd as unknown as PlotlyTarget;
    Plotly.relayout(target, { selections: null } as Partial<Plotly.Layout>).catch(() => {});
    const data = (gd as unknown as { data?: unknown[] }).data;
    const traceCount = Array.isArray(data) ? data.length : 0;
    if (traceCount > 0) {
      const indices = Array.from({ length: traceCount }, (_, i) => i);
      Plotly.restyle(target, { selectedpoints: [null] } as Partial<Plotly.PlotData>, indices).catch(
        () => {},
      );
    }
  } catch {
    // best-effort
  }
}

/** Put back the selection a snapshot recorded (see `snapshotSelection`). Best effort. */
function restoreSelection(gd: HTMLElement | null, snapshot: SelectionSnapshot | null): void {
  if (!gd || !snapshot) return;
  try {
    const target = gd as unknown as PlotlyTarget;
    const { relayout, restyle } = restoreSelectionUpdates(snapshot);
    Plotly.relayout(target, relayout as Partial<Plotly.Layout>).catch(() => {});
    const data = (gd as unknown as { data?: unknown[] }).data;
    const traceCount = Array.isArray(data) ? data.length : 0;
    if (restyle && traceCount > 0) {
      // Traces may have been removed since the snapshot.
      const keep = restyle.indices.filter((i) => i < traceCount);
      if (keep.length) {
        const values = (restyle.update.selectedpoints as unknown[]).slice(0, keep.length);
        Plotly.restyle(target, { selectedpoints: values } as unknown as Partial<Plotly.PlotData>, keep).catch(
          () => {},
        );
      }
    }
  } catch {
    // best-effort
  }
}

const readSelectionState = (gd: HTMLElement | null): SelectionSnapshot | null => {
  if (!gd) return null;
  const g = gd as unknown as { layout?: { selections?: unknown }; data?: unknown[] };
  return snapshotSelection(g.layout, g.data);
};

const readFullLayout = (gd: HTMLElement | null) =>
  (gd as unknown as { _fullLayout?: Record<string, never> } | null)?._fullLayout ?? null;

export interface UsePlotAnnotationLayerOptions {
  /** `String(metadata.index)`: the key annotations are stored under. */
  componentIndex: string;
  /** Renderer-side gate (cartesian plot, supported kind, not a 3D view...). */
  enabled: boolean;
  /** Traces handed to `<Plot>`; the annotation overlays are appended. */
  data: unknown[] | null | undefined;
  /** Layout handed to `<Plot>`; shapes, labels and the tool's dragmode are merged in. */
  layout: Record<string, unknown> | null | undefined;
  /** Traces marked points are matched against. Defaults to `data`. */
  sourceData?: unknown;
  /** customdata slot holding each point's id. Default 0. */
  pointIdIndex?: number;
  /**
   * Column the ids in `pointIdIndex` come from. When unset, marked points are
   * stored as coordinates rather than ids.
   */
  pointIdColumn?: string;
}

export interface PlotAnnotationLayer {
  /** `data` plus the annotation overlay traces (same identity when none). */
  data: unknown[];
  /** `layout` plus shapes/labels and the annotate interaction. */
  layout: Record<string, unknown>;
  /** This plot is in annotate mode. */
  annotating: boolean;
  interaction: AnnotateInteraction | null;
  /** The Plotly graph div, tracked through the handlers of `plotProps`. */
  gdRef: React.MutableRefObject<HTMLElement | null>;
  /**
   * Plotly props to spread on `<Plot>`: the renderer's own handlers merged
   * with the annotate-mode ones (selection handlers detached while
   * annotating), plus `onInitialized` / `onUpdate` tracking the graph div.
   */
  plotProps: (own?: PlotEventHandlers & PlotGraphHandlers) => PlotEventHandlers & PlotGraphHandlers;
  /** Tool palette + label popover; render inside the plot's positioned container. */
  toolbar: React.ReactNode;
  /** "12/15 points found" badges for marked points missing from the data. */
  badges: React.ReactNode[];
}

export interface PlotGraphHandlers {
  onInitialized?: (figure: any, gd: any) => void;
  onUpdate?: (figure: any, gd: any) => void;
}

/**
 * Datawrapper-style annotations on a Plotly plot: draws the layer's
 * annotations for `componentIndex` on top of the figure and, in annotate
 * mode, turns Plotly gestures into new annotations (range = box zoom then
 * undone, points = lasso/box then cleared, line/note = click).
 */
export function usePlotAnnotationLayer({
  componentIndex,
  enabled,
  data,
  layout,
  sourceData,
  pointIdIndex = 0,
  pointIdColumn,
}: UsePlotAnnotationLayerOptions): PlotAnnotationLayer {
  const layer = useAnnotationLayer();
  const annotatable = !!layer && enabled;
  const layerItems = annotatable ? layer!.itemsFor(componentIndex) : NO_ANNOTATIONS;
  const mantineTheme = useMantineTheme();
  const computedScheme = useComputedColorScheme('light');
  const colorResolver = useMemo(
    () => makeColorResolver(mantineTheme, computedScheme),
    [mantineTheme, computedScheme],
  );
  // Label text in the theme's own text tone, not in each annotation's colour
  // (a yellow label on a white plot is unreadable).
  const annotationFontColor = colorResolver('gray', computedScheme === 'dark' ? 1 : 8);
  const hasPointAnnotations = layerItems.some((i) => i.annotation.geometry.kind === 'points');
  const matchData = sourceData ?? data;
  const annotationTraces = useMemo(
    () => (hasPointAnnotations && matchData ? normalizeTraces(matchData, pointIdIndex) : undefined),
    [hasPointAnnotations, matchData, pointIdIndex],
  );
  const highlightAnnotationId = layer?.highlightId ?? null;
  const plotlyAnnotations = useMemo(() => {
    if (!layerItems.length) return null;
    return annotationsToPlotly(layerItems, {
      resolveColor: colorResolver,
      fontColor: annotationFontColor,
      traces: annotationTraces,
      // normalizeTraces already picked the id slot.
      selectionColumnIndex: 0,
      highlightId: highlightAnnotationId,
    });
  }, [layerItems, colorResolver, annotationFontColor, annotationTraces, highlightAnnotationId]);
  const missingPoints = useMemo(
    () =>
      layer?.canAnnotate && plotlyAnnotations ? pointMisses(plotlyAnnotations.stats, layerItems) : [],
    [layer?.canAnnotate, plotlyAnnotations, layerItems],
  );

  // Annotate mode for this plot: which tool, and how Plotly must behave.
  const annotateTool: AnnotateTool | null =
    annotatable && layer!.canAnnotate && layer!.annotate?.componentIndex === componentIndex
      ? layer!.annotate.tool
      : null;
  const annotating = annotateTool != null;
  const [annotateOptions, setAnnotateOptions] = useState<AnnotateOptions>(DEFAULT_ANNOTATE_OPTIONS);
  const interaction = annotateTool ? annotateInteraction(annotateTool, annotateOptions) : null;
  const pendingHere =
    layer?.pending && layer.pending.componentIndex === componentIndex ? layer.pending : null;
  const pendingRef = useRef(pendingHere);
  pendingRef.current = pendingHere;

  const gdRef = useRef<HTMLElement | null>(null);
  const [graphDiv, setGraphDiv] = useState<HTMLElement | null>(null);

  // Tell the chrome whether this view can take annotations (its Annotate
  // button is gated on it), and leave annotate mode if the view stops
  // supporting it (3D toggle, multi-panel tab...).
  const reportAnnotatable = layer?.reportAnnotatable;
  useEffect(() => {
    if (!reportAnnotatable) return;
    reportAnnotatable(componentIndex, annotatable);
    return () => reportAnnotatable(componentIndex, false);
  }, [reportAnnotatable, componentIndex, annotatable]);
  const annotateHereWhileDisabled =
    !!layer && !annotatable && layer.annotate?.componentIndex === componentIndex;
  useEffect(() => {
    if (annotateHereWhileDisabled) layer?.setAnnotate(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [annotateHereWhileDisabled]);

  const decoratedData = useMemo(
    () => appendAnnotationTraces(data ?? NO_DATA, plotlyAnnotations),
    [data, plotlyAnnotations],
  );
  const decoratedLayout = useMemo(
    () => decorateAnnotationLayout(layout ?? NO_LAYOUT, plotlyAnnotations, interaction),
    // Only the interaction's fields matter; the object is rebuilt per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layout, plotlyAnnotations, interaction?.dragmode, interaction?.fixedAxis],
  );

  // Latest render values for the stable handlers below.
  const latest = useRef({
    layer,
    annotateTool,
    annotateOptions,
    componentIndex,
    pointIdIndex,
    pointIdColumn,
  });
  latest.current = { layer, annotateTool, annotateOptions, componentIndex, pointIdIndex, pointIdColumn };

  // ── Range: a box zoom is captured, then immediately undone so the zoom
  // never sticks. `restoringRef` swallows the relayout event our own undo
  // emits. Only a drag started in a plot area (`.nsewdrag`) is captured; any
  // other explicit range change (scroll zoom, axis drag, a facet panel's own
  // axes) is undone without creating an annotation.
  const axisSnapshotRef = useRef<AxisSnapshot | null>(null);
  const restoringRef = useRef(false);
  const dragArmedRef = useRef(false);

  useEffect(() => {
    if (interaction?.capture !== 'relayout' || !graphDiv) return;
    axisSnapshotRef.current = snapshotAxes(readFullLayout(graphDiv));
    dragArmedRef.current = false;
    const onDown = (e: Event) => {
      const t = e.target as Element | null;
      dragArmedRef.current = !!t?.closest?.('.nsewdrag');
    };
    const onWheel = () => {
      dragArmedRef.current = false;
    };
    // Capture phase: Plotly's drag handlers may stop propagation.
    graphDiv.addEventListener('mousedown', onDown, true);
    graphDiv.addEventListener('touchstart', onDown, true);
    graphDiv.addEventListener('wheel', onWheel, true);
    return () => {
      graphDiv.removeEventListener('mousedown', onDown, true);
      graphDiv.removeEventListener('touchstart', onDown, true);
      graphDiv.removeEventListener('wheel', onWheel, true);
    };
  }, [interaction?.capture, graphDiv, annotateOptions.rangeAxis]);

  const onAnnotateRelayout = useCallback((event: Record<string, unknown>) => {
    const { layer: l, annotateTool: tool, annotateOptions: opts, componentIndex: idx } = latest.current;
    if (!l || restoringRef.current || tool !== 'range') return;
    const gd = gdRef.current;
    const armed = dragArmedRef.current;
    dragArmedRef.current = false;
    if (!relayoutSetsRange(event)) {
      // Autorange (double-click) or anything else: that is the new baseline.
      axisSnapshotRef.current = snapshotAxes(readFullLayout(gd));
      return;
    }
    const geometry = armed ? rangeFromRelayout(event, opts.rangeAxis) : null;
    const snapshot = axisSnapshotRef.current;
    if (gd && snapshot) {
      restoringRef.current = true;
      Plotly.relayout(gd as unknown as PlotlyTarget, restoreAxesUpdate(snapshot) as Partial<Plotly.Layout>)
        .catch(() => {})
        .then(() => {
          // Plotly emits plotly_relayout before resolving; release on the
          // next task so that event is certainly past.
          setTimeout(() => {
            restoringRef.current = false;
          }, 0);
        });
    }
    if (geometry && !pendingRef.current) l.onCaptured(idx, geometry, 'range');
  }, []);

  // ── Points / line / note: the figure's own selection (e.g. the dashboard
  // selection highlight) is recorded on entry and put back after every
  // capture and on exit, so annotating never wipes it.
  const selectionSnapshotRef = useRef<SelectionSnapshot | null>(null);
  const keepsSelection = interaction?.capture === 'selected' || interaction?.capture === 'click';
  useEffect(() => {
    if (!keepsSelection || !graphDiv) return;
    const snapshot = readSelectionState(graphDiv);
    selectionSnapshotRef.current = snapshot;
    return () => {
      selectionSnapshotRef.current = null;
      restoreSelection(graphDiv, snapshot);
    };
  }, [keepsSelection, graphDiv]);

  // ── Points: a lasso/box selection is captured, then the figure's previous
  // selection is restored; nothing reaches the dashboard filters.
  const onAnnotateSelected = useCallback((event: any) => {
    const { layer: l, annotateTool: tool, componentIndex: idx, pointIdIndex: slot, pointIdColumn: col } =
      latest.current;
    if (!l || tool !== 'points' || !event) return;
    const geometry = markedPointsFromSelection(stripOverlayPoints(event), col ? slot : undefined, col);
    if (selectionSnapshotRef.current) restoreSelection(gdRef.current, selectionSnapshotRef.current);
    else clearDrawnSelection(gdRef.current);
    if (geometry && !pendingRef.current) l.onCaptured(idx, geometry, 'points');
  }, []);

  // ── Line / note: any click in the plot area. Snaps to the hovered data
  // point when there is one, else converts the click position to data coords.
  const hoverPointRef = useRef<{ x: unknown; y: unknown } | null>(null);
  const onAnnotateHover = useCallback((event: any) => {
    const p = stripOverlayPoints(event).points[0];
    hoverPointRef.current = p ? { x: p.x, y: p.y } : null;
  }, []);
  const onAnnotateUnhover = useCallback(() => {
    hoverPointRef.current = null;
  }, []);
  const clickCaptureRef = useRef<(e: MouseEvent) => void>(() => undefined);
  clickCaptureRef.current = (e: MouseEvent) => {
    if (!layer || (annotateTool !== 'line' && annotateTool !== 'note') || pendingRef.current) return;
    const target = e.target as Element | null;
    if (target?.closest?.('.modebar, .legend')) return;
    const gd = gdRef.current;
    if (!gd) return;
    const point =
      hoverPointRef.current ??
      pixelToData(e.clientX, e.clientY, gd.getBoundingClientRect(), readFullLayout(gd));
    if (!point) return;
    const geometry =
      annotateTool === 'line' ? refLineFromClick(point, annotateOptions.lineAxis) : arrowNoteFromClick(point);
    if (geometry) layer.onCaptured(componentIndex, geometry, annotateTool);
  };
  useEffect(() => {
    if (interaction?.capture !== 'click' || !graphDiv) return;
    const onClick = (e: MouseEvent) => clickCaptureRef.current(e);
    graphDiv.addEventListener('click', onClick);
    return () => graphDiv.removeEventListener('click', onClick);
  }, [interaction?.capture, graphDiv]);

  // Esc cancels the pending label first, then leaves annotate mode.
  useEffect(() => {
    if (!annotating || !layer) return;
    const onKey = (e: KeyboardEvent) => {
      if (!isAnnotateEscape(e, gdRef.current)) return;
      if (pendingRef.current) layer.cancelPending();
      else layer.setAnnotate(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [annotating, layer]);

  // Graph div tracking, stable so memoised plot wrappers do not re-render.
  const trackGraph = useCallback((gd: unknown) => {
    gdRef.current = gd as HTMLElement;
    setGraphDiv(gd as HTMLElement);
  }, []);
  const trackOnly = useCallback((_fig: unknown, gd: unknown) => trackGraph(gd), [trackGraph]);

  const annotateHandlers = useMemo(
    () => ({
      onSelected: onAnnotateSelected,
      onRelayout: onAnnotateRelayout as (e: any) => void,
      onHover: onAnnotateHover,
      onUnhover: onAnnotateUnhover,
    }),
    [onAnnotateSelected, onAnnotateRelayout, onAnnotateHover, onAnnotateUnhover],
  );
  const capture = interaction?.capture ?? null;
  const plotProps = useCallback(
    (own: PlotEventHandlers & PlotGraphHandlers = {}) => {
      const { onInitialized, onUpdate, ...events } = own;
      return {
        ...mergePlotHandlers(events, annotateHandlers, capture),
        onInitialized: onInitialized
          ? (fig: any, gd: any) => {
              trackGraph(gd);
              onInitialized(fig, gd);
            }
          : trackOnly,
        onUpdate: onUpdate
          ? (fig: any, gd: any) => {
              trackGraph(gd);
              onUpdate(fig, gd);
            }
          : trackOnly,
      };
    },
    [annotateHandlers, capture, trackGraph, trackOnly],
  );

  const toolbar =
    annotating && layer && annotateTool ? (
      <AnnotateToolbar
        tool={annotateTool}
        options={annotateOptions}
        onChange={(tool, options) => {
          setAnnotateOptions(options);
          if (tool !== annotateTool) layer.setAnnotate(componentIndex, tool);
        }}
        onDone={() => layer.setAnnotate(null)}
        pending={pendingHere}
        onSave={layer.savePending}
        onCancel={layer.cancelPending}
      />
    ) : null;

  // A shape the reader cannot see in full: "12/15 points found" per marked-
  // points annotation whose points are not all in the current figure.
  const badges = missingPoints.map((m) => (
    <Tooltip
      key={m.id}
      label="Some marked points are not in the current data (filters or a newer dataset)"
      withArrow
      multiline
      w={240}
    >
      <Badge variant="light" color="orange" size="xs" radius="sm">
        {m.number != null ? `${numberBadge(m.number)} ` : ''}
        {m.found}/{m.expected} points found
      </Badge>
    </Tooltip>
  ));

  return {
    data: decoratedData,
    layout: decoratedLayout,
    annotating,
    interaction,
    gdRef,
    plotProps,
    toolbar,
    badges,
  };
}

export default usePlotAnnotationLayer;
