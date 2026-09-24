import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Paper,
  Text,
  Stack,
  Badge,
  Group,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';
// Vite resolve.alias in depictio/viewer/vite.config.ts rewrites bare
// `plotly.js` to `plotly.js/dist/plotly`, so this import grabs the prebuilt
// browser UMD bundle that react-plotly.js itself uses internally — no
// `buffer/` source walk, no extra bundle weight, single Plotly instance.
import Plotly from 'plotly.js';

import { renderFigure, InteractiveFilter, StoredMetadata, FigureResponse } from '../api';
import {
  GROUP_DECLINED_REASONS,
  groupBadgeLabel,
  groupBadgeReasons,
  summarizeGroupStatus,
} from '../groupStatus';
import { useReportGroupReach } from '../groupReach';
import GroupStatusBadge from './GroupStatusBadge';
import type { GroupRenderState } from '../selectionGroups';
import { enqueueFetch, isStaleFetch } from '../fetchQueue';
import { extractScatterSelection } from '../selection';
import { useInView } from '../hooks/useInView';
import { useNewItemIds } from '../hooks/useNewItemIds';
import { useTransientFlag } from '../hooks/useTransientFlag';
import { ActiveHighlight } from '../highlight';
import { asNumberArray, extractCustomdataIds } from '../plotlyData';
import { adaptGlTraces, PlotlyTrace, useWebglSlot } from '../webglBudget';
import { useUiScale } from '../uiScale';
import RefetchOverlay from './RefetchOverlay';
import ComponentSkeleton from './ComponentSkeleton';
import { useReportLoadStatus } from './DashboardLoadingProvider';
import { LoadAllState } from './chrome/LoadAllButton';
import { useAnnotationLayer } from '../annotations/AnnotationLayerContext';
import {
  annotateInteraction,
  DEFAULT_ANNOTATE_OPTIONS,
  normalizeTraces,
  pixelToData,
  pointMisses,
  restoreAxesUpdate,
  snapshotAxes,
  stripOverlayPoints,
  supportsAnnotation,
} from '../annotations/layer';
import type { AnnotateOptions, AxisSnapshot } from '../annotations/layer';
import { annotationsToPlotly } from '../annotations/toPlotly';
import { arrowNoteFromClick, markedPointsFromSelection, rangeFromRelayout, refLineFromClick } from '../annotations/capture';
import { makeColorResolver } from '../annotations/resolveColor';
import { numberBadge } from '../annotations/types';
import type { RenderableAnnotation } from '../annotations/types';
import AnnotateToolbar from './annotations/AnnotateToolbar';

const NO_ANNOTATIONS: RenderableAnnotation[] = [];

type PlotlyTarget = Parameters<typeof Plotly.relayout>[0];

/** Wipe a drawn lasso/box and un-dim every trace. Best effort: the graph div
 *  may have unmounted between scheduling and running. */
function clearDrawnSelection(gd: HTMLElement | null): void {
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

interface FigureRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** Receives a filter entry whenever the user lassos / clicks points. Pass
   *  ``value: []`` to clear. The parent merges by ``(index, source)``. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
  /** Batch to glow — a live arrival (auto-fade) or a pinned re-selection from
   *  the event log. Its ``ids`` are matched against the scatter customdata. */
  activeHighlight?: ActiveHighlight | null;
  /** Reports the sample/full state so the chrome can render a "load all points"
   *  action icon. ``null`` when the figure isn't downsampled. */
  onLoadAllState?: (state: LoadAllState | null) => void;
  /** Selection groups to color the figure by. Folded into the render request;
   *  the server annotates rows and colors traces by group membership. */
  groupRender?: GroupRenderState;
}

/**
 * Renders a Plotly figure component. Server-side path: FastAPI calls
 * `_create_figure_from_data` (the same function the Dash callback uses) and
 * returns the figure JSON. Client renders via react-plotly.js — no Dash
 * callback round-trip, no `_dash-update-component`.
 *
 * When ``selection_enabled`` is set on the component metadata, lasso / box
 * selections and point clicks are extracted from Plotly events and dispatched
 * via ``onFilterChange`` with ``source="scatter_selection"`` (mirrors the Dash
 * scatter selection callback in
 * ``depictio/dash/modules/figure_component/callbacks/selection.py``).
 */
const FigureRenderer: React.FC<FigureRendererProps> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  activeHighlight,
  onLoadAllState,
  groupRender,
}) => {
  const [figure, setFigure] = useState<{ data?: unknown[]; layout?: Record<string, unknown> } | null>(null);
  const [renderMeta, setRenderMeta] = useState<FigureResponse['metadata'] | null>(null);
  // User opted to render every point for this component (bypasses the cap).
  // Reset whenever the filters change so a new slice starts capped again.
  const [fullLoad, setFullLoad] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const uiScale = useUiScale();
  // Per-figure font-size multiplier on top of the dashboard-wide preference.
  const componentFontScale =
    typeof metadata.font_scale === 'number' && metadata.font_scale > 0 ? metadata.font_scale : 1;
  const effectiveFontScale = uiScale * componentFontScale;
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  // Cross-filtering only fires meaningful events on scatter-like traces —
  // histograms / bars / pies aggregate input rows into bins, so Plotly's
  // `onSelected` would emit per-bin envelopes (no per-row identity) and the
  // downstream filter would point at nothing useful. Builders hide the
  // toggle for non-scatter visus; the renderer hardens the same gate so
  // legacy metadata with `selection_enabled: true` on (say) a histogram is
  // silently no-op'd instead of producing junk filters.
  const isScatterLikeForSelection =
    metadata.visu_type === 'scatter' || metadata.visu_type === 'scatter_3d';
  const selectionEnabled =
    Boolean(metadata.selection_enabled) && !!onFilterChange && isScatterLikeForSelection;
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  const selectionColumnIndex =
    typeof metadata.selection_column_index === 'number'
      ? (metadata.selection_column_index as number)
      : 0;

  // The figure must NOT filter itself by its own scatter selection — otherwise
  // a lasso shrinks the chart to the selected points and the user can't lasso
  // again. Strip our own ``scatter_selection`` entry before fetching. Other
  // components still see it in their filters[] and narrow accordingly.
  //
  // Deliberately NOT stripped: a `group_filter` derived from a selection that
  // was saved on this very figure. Once saved, a group is an ordinary
  // dashboard filter (the live selection slot has been freed), so it narrows
  // its source figure like everything else — see selectionGroups.ts.
  const filtersForFetch = useMemo(
    () =>
      filters.filter(
        (f) => !(f.index === metadata.index && f.source === 'scatter_selection'),
      ),
    [filters, metadata.index],
  );

  // A new filter slice may have a different point count — go back to the capped
  // render so the user re-opts into a full load for the new data.
  useEffect(() => {
    setFullLoad(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filtersForFetch)]);

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    // Abort the request itself, not just its result handling: a stale render
    // otherwise keeps its queue slot and its API worker for as long as it takes
    // to finish work nobody will look at.
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    // Queued so a dense dashboard doesn't fire every figure's render at once;
    // the vertical position is the priority, so the top of the page paints first.
    enqueueFetch(
      () =>
        renderFigure(
          dashboardId,
          metadata.index,
          filtersForFetch,
          theme,
          fullLoad,
          ctrl.signal,
          groupRender
            ? {
                groups: groupRender.groups,
                colorByGroup: groupRender.colorByGroup,
                colorByColumn: groupRender.colorByColumn,
                display: groupRender.display,
                showOther: groupRender.showOther,
              }
            : undefined,
        ),
      metadata.layout?.y ?? 0,
    )
      .then((res) => {
        if (cancelled) return;
        // Keep the previous figure mounted while the next response is in
        // flight; only the data/layout dicts swap. Plotly diffs props, so
        // this avoids the full SVG teardown/init the old "unmount + full
        // loader" pattern triggered.
        setFigure(res.figure);
        setRenderMeta(res.metadata ?? null);
      })
      .catch((err) => {
        // A superseded round is the user changing their mind, not a failure:
        // surfacing it would flash an error on a component that is about to be
        // re-rendered anyway.
        if (cancelled || isStaleFetch(err)) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filtersForFetch), theme, inView, refreshTick, fullLoad, JSON.stringify(groupRender ?? null)]);

  // First-paint loader vs refetch overlay: only show the big "Rendering…"
  // block until we have something to show; subsequent fetches keep the
  // previous content visible with a small overlay spinner.
  const isInitialLoad = figure === null;
  const showInitialLoader = (!inView || (isInitialLoad && loading));
  const showRefetchOverlay = !isInitialLoad && loading;

  // Report load status to the dashboard registry. Off-screen → pending (null);
  // once we have a figure it stays "ready" through any refetch overlay.
  useReportLoadStatus(
    metadata.index,
    !inView ? null : figure != null ? 'ready' : error ? 'error' : 'loading',
  );

  const emitSelection = (values: string[]) => {
    if (!onFilterChange) return;
    onFilterChange({
      index: metadata.index,
      value: values,
      source: 'scatter_selection',
      column_name: selectionColumn,
      interactive_component_type: 'MultiSelect',
      metadata: {
        dc_id: metadata.dc_id,
        column_name: selectionColumn,
        interactive_component_type: 'MultiSelect',
        selection_column: selectionColumn,
      },
    });
  };

  const handleSelected = (event: any) => {
    if (!selectionEnabled || !selectionColumn) return;
    const values = extractScatterSelection(stripOverlayPoints(event), selectionColumnIndex);
    emitSelection(values);
  };

  const handleClick = (event: any) => {
    if (!selectionEnabled || !selectionColumn) return;
    // Treat single-point click as a one-element selection — Dash does the same.
    const values = extractScatterSelection(stripOverlayPoints(event), selectionColumnIndex);
    emitSelection(values);
  };

  const handleDeselect = () => {
    if (!selectionEnabled) return;
    emitSelection([]);
  };

  // Plotly graph div captured on init/update so we can imperatively clear the
  // visual lasso/box selection when the user clicks the chrome reset button.
  // react-plotly.js is a controlled wrapper for `data` + `layout`, but the
  // drawn selection lives in Plotly's internal UI state (`layout.selections`
  // and per-trace `selectedpoints`) which isn't reflected back into our props.
  // Forcing those to null via `relayout` / `restyle` is the documented escape
  // hatch.
  const gdRef = useRef<HTMLElement | null>(null);

  const hasOwnSelection = useMemo(() => {
    return filters.some(
      (f) =>
        f.index === metadata.index &&
        f.source === 'scatter_selection' &&
        Array.isArray(f.value) &&
        f.value.length > 0,
    );
  }, [filters, metadata.index]);

  // Track whether THIS component had its own selection on the previous render
  // so we only fire the clear effect on the true→false transition (someone
  // pressed the chrome reset button or deselected externally). Without this
  // gate the effect would also run on first mount before any selection ever
  // existed.
  const prevHadOwnSelection = useRef(false);

  useEffect(() => {
    const wasActive = prevHadOwnSelection.current;
    prevHadOwnSelection.current = hasOwnSelection;
    if (!wasActive || hasOwnSelection) return;

    // relayout({selections: null}) wipes drawn selection shapes (lasso/box
    // outline) and restyle({selectedpoints: null}) restores the un-dimmed
    // look on every trace.
    clearDrawnSelection(gdRef.current);
  }, [hasOwnSelection]);

  // ── New-item highlight pipeline ───────────────────────────────────────────
  // Only wired for scatter visualisations — histograms / box / bar aggregate
  // points and have no per-row identity in the rendered figure dict. The IDs
  // come from the same ``customdata[selection_column_index]`` channel that
  // drives lasso/click selection, so the hook works whether or not selection
  // is enabled on the component.
  const isScatterLike = metadata.visu_type === 'scatter' || metadata.visu_type === 'scatter_3d';
  const highlightDurationMs =
    typeof metadata.highlight_duration_ms === 'number'
      ? (metadata.highlight_duration_ms as number)
      : 3000;
  const highlightColor =
    typeof metadata.highlight_color === 'string' && metadata.highlight_color
      ? (metadata.highlight_color as string)
      : 'rgba(255,193,7,0.85)';

  const figureIds = useMemo<string[]>(() => {
    if (!isScatterLike || !figure || !Array.isArray(figure.data)) return [];
    const out: string[] = [];
    for (const trace of figure.data as Array<{ customdata?: unknown }>) {
      const ids = extractCustomdataIds(trace?.customdata, selectionColumnIndex);
      out.push(...ids);
    }
    return out;
  }, [figure, isScatterLike, selectionColumnIndex]);

  const newIds = useNewItemIds(figureIds, refreshTick);
  const highlightActive = useTransientFlag(refreshTick, highlightDurationMs);

  // Per-batch highlight, payload-driven. The scatter overlay only carries the
  // selection column's values in customdata, so a batch can only match when its
  // ``idColumn`` equals ``selectionColumn``. This is ADDITIVE with the legacy
  // client-side diff: live arrivals overlay via either path, a sticky batch
  // re-overlays with no refetch.
  const batchColumnAligned =
    !!activeHighlight &&
    (!activeHighlight.dcId || activeHighlight.dcId === metadata.dc_id) &&
    (!activeHighlight.idColumn || activeHighlight.idColumn === selectionColumn);
  const batchFadeActive = useTransientFlag(activeHighlight?.nonce, highlightDurationMs);
  const batchHighlightOn =
    batchColumnAligned && (activeHighlight!.sticky || batchFadeActive);
  // Union of the legacy diff (when its window is open) and the batch ids (when
  // its gate is on) — the overlay marks every id in the combined set.
  const effectiveIds = useMemo<Set<string>>(() => {
    const s = new Set<string>();
    if (highlightActive) newIds.forEach((id) => s.add(id));
    if (batchHighlightOn) activeHighlight!.ids.forEach((id) => s.add(id));
    return s;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightActive, newIds, batchHighlightOn, activeHighlight?.ids]);
  const overlayActive = (highlightActive && newIds.size > 0) || batchHighlightOn;

  // Build an overlay trace with markers at the highlighted points' coordinates.
  // We re-derive x/y from the trace's own arrays by matching customdata index →
  // trace index. No mutation of existing traces.
  const overlayTrace = useMemo<Record<string, unknown> | null>(() => {
    if (!overlayActive || !isScatterLike || effectiveIds.size === 0 || !figure) return null;
    const data = (figure.data as Array<{
      x?: unknown;
      y?: unknown;
      customdata?: unknown;
    }>) || [];
    const xs: number[] = [];
    const ys: number[] = [];
    for (const trace of data) {
      const ids = extractCustomdataIds(trace?.customdata, selectionColumnIndex);
      if (ids.length === 0) continue;
      const xArr = asNumberArray(trace?.x);
      const yArr = asNumberArray(trace?.y);
      for (let i = 0; i < ids.length; i++) {
        if (effectiveIds.has(ids[i]) && i < xArr.length && i < yArr.length) {
          xs.push(xArr[i]);
          ys.push(yArr[i]);
        }
      }
    }
    if (xs.length === 0) return null;
    return {
      type: 'scatter',
      mode: 'markers',
      x: xs,
      y: ys,
      marker: {
        size: 16,
        color: highlightColor,
        line: { width: 2, color: '#ff9800' },
        symbol: 'circle-open',
      },
      hoverinfo: 'skip',
      showlegend: false,
      name: '__depictio_new_items',
    };
  }, [overlayActive, isScatterLike, effectiveIds, figure, selectionColumnIndex, highlightColor]);

  // Plotly Express emits `scattergl` above ~1000 points and the server passes
  // that verdict through in the figure JSON, so scatter figures are the ones
  // that consume the scarce GL contexts. Aggregated visus (bar, box,
  // histogram) never do and don't take a slot — see webglBudget.
  const glGranted = useWebglSlot(isScatterLike);

  // ── Annotation layer ──────────────────────────────────────────────────────
  // Datawrapper-style annotations (ranges, reference lines, marked points,
  // arrow notes) are drawn client-side on top of the server figure. The app
  // decides which are visible (see AnnotationLayerContext); a null layer
  // means no annotations and no annotate mode.
  const layer = useAnnotationLayer();
  const componentIndex = String(metadata.index);
  const annotatable = !!layer && supportsAnnotation(metadata);
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
  const annotationTraces = useMemo(
    () =>
      hasPointAnnotations && figure ? normalizeTraces(figure.data, selectionColumnIndex) : undefined,
    [hasPointAnnotations, figure, selectionColumnIndex],
  );
  const highlightAnnotationId = layer?.highlightId ?? null;
  const plotlyAnnotations = useMemo(() => {
    if (!layerItems.length) return null;
    return annotationsToPlotly(layerItems, {
      resolveColor: colorResolver,
      fontColor: annotationFontColor,
      traces: annotationTraces,
      // normalizeTraces already picked the selection column.
      selectionColumnIndex: 0,
      highlightId: highlightAnnotationId,
    });
  }, [layerItems, colorResolver, annotationFontColor, annotationTraces, highlightAnnotationId]);
  const missingPoints = useMemo(
    () =>
      layer?.canAnnotate && plotlyAnnotations
        ? pointMisses(plotlyAnnotations.stats, layerItems)
        : [],
    [layer?.canAnnotate, plotlyAnnotations, layerItems],
  );

  // Annotate mode for this figure: which tool, and how Plotly must behave.
  const annotateTool =
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
  const [graphDiv, setGraphDiv] = useState<HTMLElement | null>(null);

  const figureData = useMemo<unknown[]>(() => {
    const base = adaptGlTraces(((figure?.data as PlotlyTrace[]) || []), glGranted);
    const out: unknown[] = overlayTrace ? [...base, overlayTrace] : [...base];
    // Annotation overlays go AFTER the figure's own traces so the curveNumber
    // of every real trace is unchanged; they never dim under a selection.
    plotlyAnnotations?.overlayTraces.forEach((t) =>
      out.push({ ...(t as Record<string, unknown>), unselected: { marker: { opacity: 1 } } }),
    );
    return out;
  }, [figure, overlayTrace, glGranted, plotlyAnnotations]);

  const layout = useMemo<Record<string, unknown>>(() => {
    const base: Record<string, unknown> = {
      ...((figure?.layout as Record<string, unknown>) || {}),
      autosize: true,
      margin: {
        l: 50,
        r: 20,
        t: 30,
        b: 50,
        ...((figure?.layout?.margin as Record<string, unknown>) || {}),
      },
    };
    if (effectiveFontScale !== 1) {
      // The mantine templates set font family only, so server figures land at
      // Plotly's default 12px base. Scale it with the dashboard-wide font
      // preference times this figure's own `font_scale` (labels, ticks and
      // legend all inherit layout.font); per-figure size overrides (if any)
      // are preserved by scaling whatever base the server sent.
      const serverFont = (figure?.layout?.font as Record<string, unknown>) || {};
      const serverSize = typeof serverFont.size === 'number' ? serverFont.size : 12;
      base.font = { ...serverFont, size: serverSize * effectiveFontScale };
    }
    if (selectionEnabled && !base.dragmode) {
      const mode =
        typeof metadata.selection_mode === 'string' ? metadata.selection_mode : 'lasso';
      base.dragmode = mode;
    }
    if (plotlyAnnotations) {
      const serverShapes = Array.isArray(base.shapes) ? (base.shapes as unknown[]) : [];
      const serverAnnotations = Array.isArray(base.annotations)
        ? (base.annotations as unknown[])
        : [];
      if (plotlyAnnotations.shapes.length) base.shapes = [...serverShapes, ...plotlyAnnotations.shapes];
      if (plotlyAnnotations.annotations.length) {
        base.annotations = [...serverAnnotations, ...plotlyAnnotations.annotations];
      }
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
    // uirevision controls when Plotly preserves zoom/pan/legend state. The
    // server bakes in `uirevision: "persistent"` so filter-driven refetches
    // keep the view stable, but that also makes realtime ticks invisible:
    // identical uirevision → Plotly assumes "same view" and skips repaint
    // even when data changes. Always overwrite per refreshTick so a true
    // realtime update produces a unique uirevision and a fresh draw. Filter
    // changes don't bump refreshTick, so zoom/pan still survive those.
    base.uirevision = `tick-${refreshTick ?? 0}`;
    return base;
    // uirevision above stays tied to refreshTick only: entering or leaving
    // annotate mode, or adding an annotation, must not reset the user's zoom.
  }, [
    figure,
    selectionEnabled,
    metadata.selection_mode,
    refreshTick,
    effectiveFontScale,
    plotlyAnnotations,
    interaction?.dragmode,
    interaction?.fixedAxis,
  ]);

  // ── Annotate-mode capture ────────────────────────────────────────────────
  // Range: a box zoom is captured, then immediately undone so the zoom never
  // sticks. `restoringRef` swallows the relayout event our own undo emits.
  const axisSnapshotRef = useRef<AxisSnapshot | null>(null);
  const restoringRef = useRef(false);
  const readFullLayout = (gd: HTMLElement | null) =>
    (gd as unknown as { _fullLayout?: Record<string, never> } | null)?._fullLayout ?? null;

  useEffect(() => {
    if (interaction?.capture !== 'relayout' || !graphDiv) return;
    axisSnapshotRef.current = snapshotAxes(readFullLayout(graphDiv));
  }, [interaction?.capture, graphDiv, annotateOptions.rangeAxis]);

  const handleAnnotateRelayout = (event: Record<string, unknown>) => {
    if (!layer || restoringRef.current || annotateTool !== 'range') return;
    const gd = gdRef.current;
    const geometry = rangeFromRelayout(event, annotateOptions.rangeAxis);
    if (!geometry) {
      // Autorange (double-click) or anything else: that is the new baseline.
      axisSnapshotRef.current = snapshotAxes(readFullLayout(gd));
      return;
    }
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
    if (!pendingRef.current) layer.onCaptured(componentIndex, geometry, 'range');
  };

  // Points: a lasso/box selection is captured, then cleared; nothing reaches
  // the dashboard filters.
  const handleAnnotateSelected = (event: any) => {
    if (!layer || annotateTool !== 'points' || !event) return;
    const geometry = markedPointsFromSelection(
      stripOverlayPoints(event),
      selectionColumn ? selectionColumnIndex : undefined,
      selectionColumn,
    );
    clearDrawnSelection(gdRef.current);
    if (geometry && !pendingRef.current) layer.onCaptured(componentIndex, geometry, 'points');
  };

  // Line / note: any click in the plot area. Snaps to the hovered data point
  // when there is one, else converts the click position to data coordinates.
  const hoverPointRef = useRef<{ x: unknown; y: unknown } | null>(null);
  const handleAnnotateHover = (event: any) => {
    const p = stripOverlayPoints(event).points[0];
    hoverPointRef.current = p ? { x: p.x, y: p.y } : null;
  };
  const handleAnnotateUnhover = () => {
    hoverPointRef.current = null;
  };
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
      annotateTool === 'line'
        ? refLineFromClick(point, annotateOptions.lineAxis)
        : arrowNoteFromClick(point);
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
      if (e.key !== 'Escape') return;
      if (pendingRef.current) layer.cancelPending();
      else layer.setAnnotate(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [annotating, layer]);

  // A shape the reader cannot see in full: "12/15 points found" per marked-
  // points annotation whose points are not all in the current figure.
  const missingPointsBadges = missingPoints.map((m) => (
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

  // "N of M points" indicator. Passive/informational — the full-load toggle
  // itself lives in the component chrome (see the onLoadAllState effect below),
  // matching the table's row indicator for a consistent look and placement.
  const reductionBadge = useMemo(() => {
    if (!renderMeta) return null;
    const displayed = renderMeta.displayed_data_count;
    const total = renderMeta.total_data_count;
    if (typeof displayed !== 'number') return null;
    if (renderMeta.was_sampled && typeof total === 'number') {
      return (
        <Badge variant="light" color="gray" size="xs" radius="sm">
          {displayed.toLocaleString()} / {total.toLocaleString()} pts
        </Badge>
      );
    }
    if (fullLoad && renderMeta.full_data_loaded) {
      return (
        <Badge variant="light" color="gray" size="xs" radius="sm">
          {displayed.toLocaleString()} pts (all)
        </Badge>
      );
    }
    return null;
  }, [renderMeta, fullLoad]);

  // "Grouped" / "by <column>" tag: the server confirmed it colored this figure
  // by the user's selection groups or by the global Color-by column (it may
  // decline, e.g. when the column isn't in this figure's data collection).
  // Explicit because both modes temporarily override the figure's own `color`
  // mapping.
  //
  // A group that could not reach this frame gets a badge too. Silence was the
  // old behaviour and it is indistinguishable from a tile that ignores
  // grouping altogether: the reader has no way to tell "these ids aren't this
  // component's" from "this is broken". The dimmed variant says which groups
  // missed and why, on hover. So does a figure that every group reached but
  // that still drew none of them: a code figure that never spreads the groups,
  // or a chart type the override cannot repaint.
  const groupStatus = summarizeGroupStatus(renderMeta?.group_status);
  const groupColored = Boolean(renderMeta?.group_colored);
  let groupedBadgeLabel: string | null = groupBadgeLabel(groupColored, groupStatus);
  if (!groupedBadgeLabel && renderMeta?.column_colored) {
    groupedBadgeLabel = `by ${renderMeta.column_colored}`;
  }
  const groupedBadge = groupedBadgeLabel ? (
    <GroupStatusBadge
      label={groupedBadgeLabel}
      colored={groupColored || Boolean(renderMeta?.column_colored)}
      faulted={groupStatus?.faulted}
      reasons={groupBadgeReasons(
        groupColored,
        groupStatus,
        metadata.mode === 'code' ? GROUP_DECLINED_REASONS.code : GROUP_DECLINED_REASONS.ui,
      )}
    />
  ) : null;
  // Pooled for the Analysis panel, only while groups are asked for and the
  // server has answered for them. A column override is a different question.
  useReportGroupReach(
    metadata.index,
    groupRender?.colorByGroup && groupStatus ? groupColored : null,
  );

  // Publish the sample/full state so the chrome can render the "load all points"
  // action icon in the same cluster as reset / fullscreen. Bidirectional: the
  // toggle flips back to the sampled view once fully loaded.
  useEffect(() => {
    if (!onLoadAllState) return;
    const canToggle =
      !!renderMeta && (renderMeta.was_sampled || (fullLoad && !!renderMeta.full_data_loaded));
    onLoadAllState(
      canToggle
        ? {
            reduced: !fullLoad,
            full: fullLoad,
            loading,
            toggle: () => setFullLoad((v) => !v),
            noun: 'points',
          }
        : null,
    );
  }, [onLoadAllState, renderMeta, fullLoad, loading]);

  return (
    <Paper
      ref={containerRef}
      p="sm"
      withBorder
      radius="md"
      style={{
        flex: 1,
        minHeight: 0,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {(metadata.title || reductionBadge || groupedBadge || missingPointsBadges.length > 0) && (
        <Group gap="xs" mb="xs" wrap="nowrap">
          {metadata.title && (
            <Text fw={600} size="sm">
              {metadata.title}
            </Text>
          )}
          {reductionBadge}
          {groupedBadge}
          {missingPointsBadges}
        </Group>
      )}
      {showInitialLoader && <ComponentSkeleton variant="block" />}
      {error && isInitialLoad && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red">Figure failed: {error}</Text>
        </Stack>
      )}
      {figure && (
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <Plot
            data={figureData as any[]}
            layout={layout}
            revision={refreshTick ?? 0}
            config={{ displaylogo: false, responsive: true }}
            style={{ width: '100%', height: '100%' }}
            useResizeHandler
            onInitialized={(_fig, gd) => {
              gdRef.current = gd as HTMLElement;
              setGraphDiv(gd as HTMLElement);
            }}
            onUpdate={(_fig, gd) => {
              gdRef.current = gd as HTMLElement;
              setGraphDiv(gd as HTMLElement);
            }}
            // In annotate mode the selection handlers are detached: gestures
            // draw annotations and never filter the dashboard.
            onSelected={
              annotating
                ? interaction?.capture === 'selected'
                  ? handleAnnotateSelected
                  : undefined
                : selectionEnabled
                  ? handleSelected
                  : undefined
            }
            onClick={!annotating && selectionEnabled ? handleClick : undefined}
            onDeselect={!annotating && selectionEnabled ? handleDeselect : undefined}
            onRelayout={
              interaction?.capture === 'relayout'
                ? (handleAnnotateRelayout as (e: Readonly<Plotly.PlotRelayoutEvent>) => void)
                : undefined
            }
            onHover={interaction?.capture === 'click' ? handleAnnotateHover : undefined}
            onUnhover={interaction?.capture === 'click' ? handleAnnotateUnhover : undefined}
          />
          {annotating && layer && annotateTool && (
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
          )}
          <RefetchOverlay visible={showRefetchOverlay} />
        </div>
      )}
    </Paper>
  );
};

export default FigureRenderer;
