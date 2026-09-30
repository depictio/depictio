import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Badge, Tooltip, useComputedColorScheme } from '@mantine/core';
// Same prebuilt bundle react-plotly.js uses (see FigureRenderer).
import Plotly from 'plotly.js';

import { useAnnotationLayer } from '../../annotations/AnnotationLayerContext';
import {
  annotateInteraction,
  DEFAULT_ANNOTATE_OPTIONS,
  itemsForVariant,
  KIND_LABELS,
  normalizeTraces,
  pixelToData,
  pointMisses,
  stripOverlayPoints,
  toolForSurface,
  withSelectableLines,
} from '../../annotations/layer';
import type {
  AnnotateInteraction,
  AnnotateOptions,
  AnnotateSurface,
  AnnotateTool,
} from '../../annotations/layer';
import { annotationsToPlotly } from '../../annotations/toPlotly';
import type { AnnotationsToPlotlyResult } from '../../annotations/toPlotly';
import type { AnnotationStats } from '../../annotations/summary';
import {
  arrowNoteFromClick,
  markedPointsFromSelection,
  rangeFromSelection,
  refLineFromClick,
} from '../../annotations/capture';
import {
  centroidsSignature,
  geoAnnotationsToPlotly,
  geoCentroidsFromGraph,
  geoNoteAt,
  geoPointsFromSelection,
  mapSubplotOf,
  normalizeGeoTraces,
  pixelToLonLat,
} from '../../annotations/geo';
import { makeColorResolver } from '../../annotations/resolveColor';
import { renderedPointsFromGraph, renderedPointsSignature } from '../../annotations/renderedPoints';
import type { GraphLike, RenderedPoints } from '../../annotations/renderedPoints';
import { numberBadge, PREVIEW_ANNOTATION_ID } from '../../annotations/types';
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
import { clientPointFromEvent } from '../../annotations/inlineEdit';
import AnnotateToolbar from './AnnotateToolbar';
import InlineAnnotationEditor from './InlineAnnotationEditor';

const NO_ANNOTATIONS: RenderableAnnotation[] = [];
const NO_DATA: unknown[] = [];
const NO_LAYOUT: Record<string, unknown> = {};
const NO_STATS: Record<string, AnnotationStats> = {};

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

/** Saved annotations drawn first, the preview on top. */
function mergePlotly(
  a: AnnotationsToPlotlyResult | null,
  b: AnnotationsToPlotlyResult | null,
): AnnotationsToPlotlyResult | null {
  if (!a || !b) return a ?? b;
  return {
    shapes: [...a.shapes, ...b.shapes],
    annotations: [...a.annotations, ...b.annotations],
    overlayTraces: [...a.overlayTraces, ...b.overlayTraces],
    stats: a.stats,
    topLabelCount: a.topLabelCount + b.topLabelCount,
  };
}

const hasMarkedPoints = (items: RenderableAnnotation[]) =>
  items.some((i) => i.annotation.geometry.kind === 'points');

/** Pointer travel (px) past which a press is a drag (a map pan), not a click. */
const CLICK_SLOP_PX = 5;

const needsTraces = (items: RenderableAnnotation[]) =>
  items.some((i) => {
    const k = i.annotation.geometry.kind;
    return k === 'points' || k === 'x_range' || k === 'y_range';
  });

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
  /**
   * The view the plot shows, for components switching between several plots
   * (e.g. a MultiQC dataset). New annotations are stored with it, and only the
   * annotations drawn on this view (or on no particular view) are shown.
   * Undefined for a component with a single view: every annotation is shown.
   */
  variant?: string | null;
  /**
   * `map`: a Plotly map (scattermap / choroplethmap). Its annotations are in
   * longitude / latitude and drawn as overlay traces, and only the tools a
   * map can take (marked points, notes) are offered. Default `cartesian`.
   */
  surface?: AnnotateSurface;
  /**
   * Map only: where point ids are read. `customdata` (default) uses
   * `pointIdIndex`; `location` uses the region id of a choropleth, with
   * `pointIdColumn` naming the locations column.
   */
  pointIdFrom?: 'customdata' | 'location';
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
  /**
   * Tool palette + label popover, and the inline editor of a clicked
   * annotation; render inside the plot's positioned container.
   */
  toolbar: React.ReactNode;
  /** "12/15 points found" badges for marked points missing from the data. */
  badges: React.ReactNode[];
  /**
   * Hand the graph div over directly, for a plot whose `onInitialized` /
   * `onUpdate` may never fire (a map waiting on its basemap).
   */
  trackGraph: (gd: unknown) => void;
}

export interface PlotGraphHandlers {
  onInitialized?: (figure: any, gd: any) => void;
  onUpdate?: (figure: any, gd: any) => void;
}

/**
 * Datawrapper-style annotations on a Plotly plot: draws the layer's
 * annotations for `componentIndex` on top of the figure (plus a preview of
 * the capture awaiting its label), edits an annotation in place (or opens
 * its thread) when it is clicked, reports the counts measured on the data
 * and, in annotate mode, turns Plotly gestures into new annotations (range =
 * box selection on one axis, points = lasso/box, both then cleared;
 * line/note = click). Zoom and pan stay available from the modebar.
 */
export function usePlotAnnotationLayer({
  componentIndex,
  enabled,
  data,
  layout,
  sourceData,
  pointIdIndex = 0,
  pointIdColumn,
  variant,
  surface = 'cartesian',
  pointIdFrom = 'customdata',
}: UsePlotAnnotationLayerOptions): PlotAnnotationLayer {
  const onMap = surface === 'map';
  const layer = useAnnotationLayer();
  const annotatable = !!layer && enabled;
  const componentItems = annotatable ? layer!.itemsFor(componentIndex) : NO_ANNOTATIONS;
  // Stable per items array: the conversion and the stats below memoise on it.
  const layerItems = useMemo(
    () => itemsForVariant(componentItems, variant) as RenderableAnnotation[],
    [componentItems, variant],
  );
  const computedScheme = useComputedColorScheme('light');
  const colorResolver = useMemo(
    () => makeColorResolver(computedScheme),
    [computedScheme],
  );
  // Label text in the theme's own text tone, not in each annotation's colour
  // (a yellow label on a white plot is unreadable).
  const annotationFontColor = colorResolver('gray', computedScheme === 'dark' ? 1 : 8);
  // The capture awaiting its label, drawn as the popover currently has it.
  const pendingHere =
    annotatable && layer!.pending?.componentIndex === componentIndex ? layer!.pending : null;
  const pendingDraft = pendingHere ? layer!.pendingDraft : null;
  const previewItems = useMemo<RenderableAnnotation[]>(() => {
    if (!pendingHere || !pendingDraft) return NO_ANNOTATIONS;
    return [
      {
        id: PREVIEW_ANNOTATION_ID,
        number: null,
        preview: true,
        annotation: {
          kind: pendingHere.kind,
          geometry: pendingDraft.geometry,
          label: pendingDraft.label || KIND_LABELS[pendingHere.kind],
          color: pendingDraft.color,
          style: pendingDraft.style,
        },
      },
    ];
  }, [pendingHere, pendingDraft]);

  const wantsTraces = needsTraces(layerItems) || needsTraces(previewItems);
  const matchData = sourceData ?? data;
  const annotationTraces = useMemo(
    () => (!onMap && wantsTraces && matchData ? normalizeTraces(matchData, pointIdIndex) : undefined),
    [onMap, wantsTraces, matchData, pointIdIndex],
  );

  // Map: where Plotly drew each choropleth region (its centroid), read from
  // the graph div after every plot, so a marked region carries its label.
  const [centroids, setCentroids] = useState<Map<string, [number, number]> | null>(null);
  const centroidsSignatureRef = useRef('');
  const syncCentroids = useCallback((gd: unknown) => {
    const next = geoCentroidsFromGraph(gd);
    const signature = centroidsSignature(next);
    if (signature === centroidsSignatureRef.current) return;
    centroidsSignatureRef.current = signature;
    setCentroids(next);
  }, []);
  const geoTraces = useMemo(
    () => (onMap && wantsTraces && matchData ? normalizeGeoTraces(matchData, pointIdIndex, centroids) : undefined),
    [onMap, wantsTraces, matchData, pointIdIndex, centroids],
  );
  const highlightAnnotationId = layer?.highlightId ?? null;

  // Where box, violin and bar traces drew their points (group offset,
  // jitter), read from the graph div after every plot, so marked points are
  // ringed on the mark. Set only when the positions changed: the rings
  // redraw the figure, which reports back the same positions.
  const wantsRendered = !onMap && (hasMarkedPoints(layerItems) || hasMarkedPoints(previewItems));
  const wantsRenderedRef = useRef(wantsRendered);
  wantsRenderedRef.current = wantsRendered;
  const [renderedPoints, setRenderedPoints] = useState<RenderedPoints | null>(null);
  const renderedSignatureRef = useRef('');
  const syncRenderedPoints = useCallback((gd: unknown) => {
    if (!wantsRenderedRef.current) return;
    const next = renderedPointsFromGraph(gd as GraphLike | null);
    const signature = renderedPointsSignature(next);
    if (signature === renderedSignatureRef.current) return;
    renderedSignatureRef.current = signature;
    setRenderedPoints(next);
  }, []);

  const toPlotlyOptions = useMemo(
    () => ({
      resolveColor: colorResolver,
      fontColor: annotationFontColor,
      traces: annotationTraces,
      // normalizeTraces already picked the id slot.
      selectionColumnIndex: 0,
      highlightId: highlightAnnotationId,
      renderedPoints,
    }),
    [colorResolver, annotationFontColor, annotationTraces, highlightAnnotationId, renderedPoints],
  );
  const geoOptions = useMemo(
    () => ({
      resolveColor: colorResolver,
      fontColor: annotationFontColor,
      traces: geoTraces,
      highlightId: highlightAnnotationId,
    }),
    [colorResolver, annotationFontColor, geoTraces, highlightAnnotationId],
  );
  const savedPlotly = useMemo(() => {
    if (!layerItems.length) return null;
    return onMap ? geoAnnotationsToPlotly(layerItems, geoOptions) : annotationsToPlotly(layerItems, toPlotlyOptions);
  }, [layerItems, onMap, geoOptions, toPlotlyOptions]);
  // Rebuilt on every keystroke of the label: kept apart from the saved ones.
  const previewPlotly = useMemo(() => {
    if (!previewItems.length) return null;
    if (onMap) return geoAnnotationsToPlotly(previewItems, geoOptions);
    return annotationsToPlotly(previewItems, {
      ...toPlotlyOptions,
      topLabelOffset: savedPlotly?.topLabelCount ?? 0,
    });
  }, [previewItems, onMap, geoOptions, toPlotlyOptions, savedPlotly]);
  const plotlyAnnotations = useMemo(() => mergePlotly(savedPlotly, previewPlotly), [savedPlotly, previewPlotly]);
  const pendingStats = previewPlotly?.stats[PREVIEW_ANNOTATION_ID];
  const missingPoints = useMemo(
    () => (layer?.canAnnotate && savedPlotly ? pointMisses(savedPlotly.stats, layerItems) : []),
    [layer?.canAnnotate, savedPlotly, layerItems],
  );

  // Counts measured on this plot's data, for the app (thread list, drawer).
  // The layer drops reports equal to the previous one.
  const reportStats = layer?.reportStats;
  const savedStats = annotatable ? (savedPlotly?.stats ?? NO_STATS) : null;
  useEffect(() => {
    if (reportStats && savedStats) reportStats(componentIndex, savedStats);
  }, [reportStats, componentIndex, savedStats]);

  // Annotate mode for this plot: which tool, and how Plotly must behave.
  // A tool the surface does not offer (the chrome starts every component on
  // "range") falls back to marked points.
  const annotateTool: AnnotateTool | null =
    annotatable && layer!.canAnnotate && layer!.annotate?.componentIndex === componentIndex
      ? toolForSurface(layer!.annotate.tool, surface)
      : null;
  const annotating = annotateTool != null;
  const [annotateOptions, setAnnotateOptions] = useState<AnnotateOptions>(DEFAULT_ANNOTATE_OPTIONS);
  const interaction = annotateTool ? annotateInteraction(annotateTool, annotateOptions, surface) : null;
  // The modebar's zoom or pan took over the drag gesture (see onAnnotateRelayout).
  const [navigating, setNavigating] = useState(false);
  const navigatingRef = useRef(navigating);
  navigatingRef.current = navigating;
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

  // The points tool selects on lines too (Plotly's lasso skips a trace
  // without markers).
  const selectsPoints = annotateTool === 'points';
  const selectableData = useMemo(
    () => (selectsPoints ? withSelectableLines(data ?? NO_DATA) : (data ?? NO_DATA)),
    [data, selectsPoints],
  );
  const decoratedData = useMemo(
    () => appendAnnotationTraces(selectableData, plotlyAnnotations, annotating),
    [selectableData, plotlyAnnotations, annotating],
  );
  const decoratedLayout = useMemo(
    () => decorateAnnotationLayout(layout ?? NO_LAYOUT, plotlyAnnotations, interaction),
    // Only the interaction's dragmode matters; the object is rebuilt per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [layout, plotlyAnnotations, interaction?.dragmode],
  );

  // Latest render values for the stable handlers below.
  const latest = useRef({
    layer,
    annotateTool,
    annotateOptions,
    componentIndex,
    pointIdIndex,
    pointIdColumn,
    variant,
    surface,
    pointIdFrom,
  });
  latest.current = {
    layer,
    annotateTool,
    annotateOptions,
    componentIndex,
    pointIdIndex,
    pointIdColumn,
    variant,
    surface,
    pointIdFrom,
  };

  // ── Zoom / pan from the modebar: while one of them holds the drag
  // gesture no tool is active; picking a tool again (even the same one)
  // re-applies its dragmode, which a `uirevision` would otherwise keep on the
  // user's modebar choice.
  const onAnnotateRelayout = useCallback((event: Record<string, unknown>) => {
    if (!event || !('dragmode' in event)) return;
    const { annotateTool: tool, annotateOptions: opts, surface: where } = latest.current;
    if (!tool) return;
    setNavigating(event.dragmode !== annotateInteraction(tool, opts, where).dragmode);
  }, []);
  const [toolPicks, setToolPicks] = useState(0);
  const toolDragmode = interaction?.dragmode;
  useEffect(() => {
    setNavigating(false);
    const gd = gdRef.current;
    if (!gd || toolDragmode === undefined) return;
    if (readFullLayout(gd)?.dragmode === toolDragmode) return;
    Plotly.relayout(gd as unknown as PlotlyTarget, { dragmode: toolDragmode } as Partial<Plotly.Layout>).catch(
      () => {},
    );
  }, [toolPicks, toolDragmode]);

  // ── Range / points / line / note: the figure's own selection (e.g. the
  // dashboard selection highlight) is recorded on entry and put back after
  // every capture and on exit, so annotating never wipes it.
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

  // ── Range / points: a box or lasso selection is captured, then the
  // figure's previous selection is restored; nothing reaches the dashboard
  // filters. A range keeps only the tool's axis of the box.
  const onAnnotateSelected = useCallback((event: any) => {
    const {
      layer: l,
      annotateTool: tool,
      annotateOptions: opts,
      componentIndex: idx,
      pointIdIndex: slot,
      pointIdColumn: col,
      variant: view,
      surface: where,
      pointIdFrom: idFrom,
    } = latest.current;
    if (!l || !event) return;
    if (tool === 'range') {
      const range = rangeFromSelection(event, opts.rangeAxis);
      if (selectionSnapshotRef.current) restoreSelection(gdRef.current, selectionSnapshotRef.current);
      else clearDrawnSelection(gdRef.current);
      if (range && !pendingRef.current) l.onCaptured(idx, range, 'range', view);
      return;
    }
    if (tool !== 'points') return;
    // The selected area (range / lassoPoints / selections) rides along with
    // the filtered points, so the annotation can shade it.
    const stripped = { ...event, ...stripOverlayPoints(event) };
    const geometry =
      where === 'map'
        ? geoPointsFromSelection(stripped, col ? { column: col, from: idFrom, slot } : null)
        : markedPointsFromSelection(stripped, col ? slot : undefined, col);
    if (selectionSnapshotRef.current) restoreSelection(gdRef.current, selectionSnapshotRef.current);
    else clearDrawnSelection(gdRef.current);
    if (geometry && !pendingRef.current) l.onCaptured(idx, geometry, 'points', view);
  }, []);

  // ── Line / note: any click in the plot area. Snaps to the hovered data
  // point when there is one, else converts the click position to data coords
  // (on a map: longitude / latitude through the map's own projection).
  const hoverPointRef = useRef<{ x: unknown; y: unknown; lon?: unknown; lat?: unknown } | null>(null);
  const onAnnotateHover = useCallback((event: any) => {
    const p = stripOverlayPoints(event).points[0] as
      | { x?: unknown; y?: unknown; lon?: unknown; lat?: unknown }
      | undefined;
    hoverPointRef.current = p ? { x: p.x, y: p.y, lon: p.lon, lat: p.lat } : null;
  }, []);
  // Where the last press started: a press that moved is a pan, not a click.
  const pressRef = useRef<{ x: number; y: number } | null>(null);
  const onAnnotateUnhover = useCallback(() => {
    hoverPointRef.current = null;
  }, []);
  const clickCaptureRef = useRef<(e: MouseEvent) => void>(() => undefined);
  clickCaptureRef.current = (e: MouseEvent) => {
    if (!layer || (annotateTool !== 'line' && annotateTool !== 'note') || pendingRef.current) return;
    // A click while zoom/pan holds the gesture belongs to the navigation.
    if (navigatingRef.current) return;
    const press = pressRef.current;
    if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > CLICK_SLOP_PX) return;
    const target = e.target as Element | null;
    if (target?.closest?.('.modebar, .legend, .maplibregl-ctrl')) return;
    const gd = gdRef.current;
    if (!gd) return;
    if (onMap) {
      const hovered = hoverPointRef.current;
      const at =
        hovered && hovered.lon != null && hovered.lat != null
          ? { lon: hovered.lon, lat: hovered.lat }
          : pixelToLonLat(e.clientX, e.clientY, mapSubplotOf(readFullLayout(gd)));
      const note = at ? geoNoteAt(at.lon, at.lat) : null;
      if (note) layer.onCaptured(componentIndex, note, 'note', variant);
      return;
    }
    const point =
      hoverPointRef.current ??
      pixelToData(e.clientX, e.clientY, gd.getBoundingClientRect(), readFullLayout(gd));
    if (!point) return;
    const geometry =
      annotateTool === 'line' ? refLineFromClick(point, annotateOptions.lineAxis) : arrowNoteFromClick(point);
    if (geometry) layer.onCaptured(componentIndex, geometry, annotateTool, variant);
  };
  useEffect(() => {
    if (interaction?.capture !== 'click' || !graphDiv) return;
    const onDown = (e: PointerEvent) => {
      pressRef.current = { x: e.clientX, y: e.clientY };
    };
    const onClick = (e: MouseEvent) => clickCaptureRef.current(e);
    // Capture phase: the map canvas handles the press before it bubbles.
    graphDiv.addEventListener('pointerdown', onDown, true);
    graphDiv.addEventListener('click', onClick);
    return () => {
      graphDiv.removeEventListener('pointerdown', onDown, true);
      graphDiv.removeEventListener('click', onClick);
      pressRef.current = null;
    };
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
  // Runs after every plot, relayout and resize (react-plotly's onUpdate).
  const trackGraph = useCallback(
    (gd: unknown) => {
      if (!gd) return;
      gdRef.current = gd as HTMLElement;
      setGraphDiv(gd as HTMLElement);
      if (onMap) syncCentroids(gd);
      else syncRenderedPoints(gd);
    },
    [onMap, syncCentroids, syncRenderedPoints],
  );
  // A first marked-points annotation (or its preview) on an already plotted
  // figure: read the positions now rather than at the next plot.
  useEffect(() => {
    if (wantsRendered && gdRef.current) syncRenderedPoints(gdRef.current);
  }, [wantsRendered, syncRenderedPoints]);
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
  // A click on a saved annotation opens its inline editor at the click, or
  // its thread when the app does not edit in place (outside annotate mode).
  const layerOpenAnnotation = annotatable ? layer!.openAnnotation : null;
  const openAnnotation = useMemo(
    () =>
      layerOpenAnnotation
        ? (threadId: string, event: unknown) =>
            layerOpenAnnotation(threadId, componentIndex, clientPointFromEvent(event))
        : null,
    [layerOpenAnnotation, componentIndex],
  );
  const plotProps = useCallback(
    (own: PlotEventHandlers & PlotGraphHandlers = {}) => {
      const { onInitialized, onUpdate, ...events } = own;
      return {
        ...mergePlotHandlers(events, annotateHandlers, capture, openAnnotation),
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
    [annotateHandlers, capture, openAnnotation, trackGraph, trackOnly],
  );

  const annotateToolbar =
    annotating && layer && annotateTool ? (
      <AnnotateToolbar
        tool={annotateTool}
        options={annotateOptions}
        surface={surface}
        onChange={(tool, options) => {
          setAnnotateOptions(options);
          setToolPicks((n) => n + 1);
          if (tool !== annotateTool) layer.setAnnotate(componentIndex, tool);
        }}
        onDone={() => layer.setAnnotate(null)}
        pending={pendingHere}
        onSave={layer.savePending}
        onCancel={layer.cancelPending}
        onDraftChange={layer.updatePendingDraft}
        pendingStats={pendingStats}
        navigating={navigating}
      />
    ) : null;
  const toolbar = (
    <>
      {annotateToolbar}
      {annotatable && <InlineAnnotationEditor componentIndex={componentIndex} />}
    </>
  );

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
    trackGraph,
  };
}

export default usePlotAnnotationLayer;
