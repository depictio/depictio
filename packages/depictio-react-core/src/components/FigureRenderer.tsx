import React, { useEffect, useMemo, useState } from 'react';
import { Paper, Loader, Text, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderFigure, InteractiveFilter, StoredMetadata } from '../api';
import { extractScatterSelection } from '../selection';
import { useInView } from '../hooks/useInView';
import { useNewItemIds } from '../hooks/useNewItemIds';
import { useTransientFlag } from '../hooks/useTransientFlag';
import { asNumberArray, extractCustomdataIds } from '../plotlyData';
import RefetchOverlay from './RefetchOverlay';

interface FigureRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** Receives a filter entry whenever the user lassos / clicks points. Pass
   *  ``value: []`` to clear. The parent merges by ``(index, source)``. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
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
}) => {
  const [figure, setFigure] = useState<{ data?: unknown[]; layout?: Record<string, unknown> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  const selectionEnabled = Boolean(metadata.selection_enabled) && !!onFilterChange;
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  const selectionColumnIndex =
    typeof metadata.selection_column_index === 'number'
      ? (metadata.selection_column_index as number)
      : 0;

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderFigure(dashboardId, metadata.index, filters, theme)
      .then((res) => {
        if (cancelled) return;
        // Keep the previous figure mounted while the next response is in
        // flight; only the data/layout dicts swap. Plotly diffs props, so
        // this avoids the full SVG teardown/init the old "unmount + full
        // loader" pattern triggered.
        setFigure(res.figure);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filters), theme, inView, refreshTick]);

  // First-paint loader vs refetch overlay: only show the big "Rendering…"
  // block until we have something to show; subsequent fetches keep the
  // previous content visible with a small overlay spinner.
  const isInitialLoad = figure === null;
  const showInitialLoader = (!inView || (isInitialLoad && loading));
  const showRefetchOverlay = !isInitialLoad && loading;

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

  // Build an overlay trace (one per realtime tick) with markers at the new
  // points' coordinates. We re-derive x/y from the trace's own arrays by
  // matching customdata index → trace index. No mutation of existing traces.
  const overlayTrace = useMemo<Record<string, unknown> | null>(() => {
    if (!highlightActive || !isScatterLike || newIds.size === 0 || !figure) return null;
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
        if (newIds.has(ids[i]) && i < xArr.length && i < yArr.length) {
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
  }, [highlightActive, isScatterLike, newIds, figure, selectionColumnIndex, highlightColor]);

  const figureData = useMemo<unknown[]>(() => {
    const base = (figure?.data as unknown[]) || [];
    return overlayTrace ? [...base, overlayTrace] : base;
  }, [figure, overlayTrace]);

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
    // Preserve zoom / pan / legend state across data refreshes triggered by
    // filter changes. Without uirevision, swapping `figure.data` resets the
    // view, which reads as flicker. Bumping uirevision per refreshTick forces
    // Plotly to repaint on realtime updates even when data shape is identical.
    if (!base.uirevision) base.uirevision = `tick-${refreshTick ?? 0}`;
    return base;
  }, [figure, selectionEnabled, metadata.selection_mode, refreshTick]);

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
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title}
        </Text>
      )}
      {showInitialLoader && (
        <Stack align="center" justify="center" gap="xs" style={{ flex: 1 }}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Rendering figure…</Text>
        </Stack>
      )}
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
            config={{ displaylogo: false, responsive: true }}
            style={{ width: '100%', height: '100%' }}
            useResizeHandler
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
