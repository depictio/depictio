import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Paper,
  Text,
  Stack,
  Badge,
  Group,
  useMantineColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';
// Vite resolve.alias in depictio/viewer/vite.config.ts rewrites bare
// `plotly.js` to `plotly.js/dist/plotly`, so this import grabs the prebuilt
// browser UMD bundle that react-plotly.js itself uses internally — no
// `buffer/` source walk, no extra bundle weight, single Plotly instance.
import Plotly from 'plotly.js';

import { renderFigure, InteractiveFilter, StoredMetadata, FigureResponse } from '../api';
import type { GroupRenderState } from '../selectionGroups';
import { enqueueFetch, isStaleFetch } from '../fetchQueue';
import { extractScatterSelection } from '../selection';
import { useInView } from '../hooks/useInView';
import { useNewItemIds } from '../hooks/useNewItemIds';
import { useTransientFlag } from '../hooks/useTransientFlag';
import { ActiveHighlight } from '../highlight';
import { asNumberArray, extractCustomdataIds } from '../plotlyData';
import { adaptGlTraces, PlotlyTrace, useWebglSlot } from '../webglBudget';
import RefetchOverlay from './RefetchOverlay';
import ComponentSkeleton from './ComponentSkeleton';
import { useReportLoadStatus } from './DashboardLoadingProvider';
import { LoadAllState } from './chrome/LoadAllButton';

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
    const values = extractScatterSelection(event, selectionColumnIndex);
    emitSelection(values);
  };

  const handleClick = (event: any) => {
    if (!selectionEnabled || !selectionColumn) return;
    // Treat single-point click as a one-element selection — Dash does the same.
    const values = extractScatterSelection(event, selectionColumnIndex);
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

    const gd = gdRef.current;
    if (!gd) return;

    // Plotly methods accept a string selector or HTMLElement. The Plot's gd
    // is the chart container; relayout({selections: null}) wipes drawn
    // selection shapes (lasso/box outline) and restyle({selectedpoints:
    // null}) restores the un-dimmed look on every trace. Wrapped in
    // try/catch because the gd may have unmounted between scheduling and
    // running, and Plotly raises on a detached div.
    try {
      // Casts: @types/plotly.js wants Plotly types on gd but the wrapper
      // exposes a regular HTMLElement that Plotly accepts at runtime; and
      // `selections` / `selectedpoints` aren't in the typed layout/style
      // surface but Plotly accepts them as a known clear-state idiom.
      const target = gd as unknown as Parameters<typeof Plotly.relayout>[0];
      Plotly.relayout(target, { selections: null } as Partial<Plotly.Layout>).catch(() => {});
      const data = (gd as unknown as { data?: unknown[] }).data;
      const traceCount = Array.isArray(data) ? data.length : 0;
      if (traceCount > 0) {
        const indices = Array.from({ length: traceCount }, (_, i) => i);
        Plotly.restyle(
          target,
          { selectedpoints: [null] } as Partial<Plotly.PlotData>,
          indices,
        ).catch(() => {});
      }
    } catch {
      // best-effort: gd may have unmounted between schedule and run
    }
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

  const figureData = useMemo<unknown[]>(() => {
    const base = adaptGlTraces(((figure?.data as PlotlyTrace[]) || []), glGranted);
    return overlayTrace ? [...base, overlayTrace] : base;
  }, [figure, overlayTrace, glGranted]);

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
    if (selectionEnabled && !base.dragmode) {
      const mode =
        typeof metadata.selection_mode === 'string' ? metadata.selection_mode : 'lasso';
      base.dragmode = mode;
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
  }, [figure, selectionEnabled, metadata.selection_mode, refreshTick]);

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
  let groupedBadgeLabel: string | null = null;
  if (renderMeta?.group_colored) groupedBadgeLabel = 'grouped';
  else if (renderMeta?.column_colored) groupedBadgeLabel = `by ${renderMeta.column_colored}`;
  const groupedBadge = groupedBadgeLabel ? (
    <Badge variant="light" color="blue" size="xs" radius="sm">
      {groupedBadgeLabel}
    </Badge>
  ) : null;

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
      {(metadata.title || reductionBadge || groupedBadge) && (
        <Group gap="xs" mb="xs" wrap="nowrap">
          {metadata.title && (
            <Text fw={600} size="sm">
              {metadata.title}
            </Text>
          )}
          {reductionBadge}
          {groupedBadge}
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
            }}
            onUpdate={(_fig, gd) => {
              gdRef.current = gd as HTMLElement;
            }}
            onSelected={selectionEnabled ? handleSelected : undefined}
            onClick={selectionEnabled ? handleClick : undefined}
            onDeselect={selectionEnabled ? handleDeselect : undefined}
          />
          <RefetchOverlay visible={showRefetchOverlay} />
        </div>
      )}
    </Paper>
  );
};

export default FigureRenderer;
