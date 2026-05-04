import React, { useEffect, useMemo, useState } from 'react';
import { Paper, Loader, Text, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderMap, InteractiveFilter, StoredMetadata } from '../api';
import { extractScatterSelection } from '../selection';
import RefetchOverlay from './RefetchOverlay';

interface MapRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** Receives a filter entry with ``source="map_selection"`` whenever the
   *  user lassos / clicks points on the map. ``value: []`` clears. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
}

/**
 * Renders a Plotly map component (px.scatter_map / density_map / choropleth_map).
 * Mirrors FigureRenderer: server returns a Plotly figure dict via
 * ``POST /dashboards/render_map/{id}/{component_id}``, React renders via
 * react-plotly.js. No Leaflet — Depictio's map module is Plotly-based.
 *
 * Selection wiring matches the scatter-figure path (lasso / click → emit a
 * filter with ``source="map_selection"``). Skipped for ``choropleth_map`` —
 * choropleth shapes are non-point geometries that Plotly's selection events
 * don't cover, mirroring Dash's behavior.
 */
const MapRenderer: React.FC<MapRendererProps> = ({
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

  const mapType = (metadata.map_type as string) || 'scatter_map';
  const selectionEnabled =
    Boolean(metadata.selection_enabled) &&
    mapType !== 'choropleth_map' &&
    !!onFilterChange;
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  const selectionColumnIndex =
    typeof metadata.selection_column_index === 'number'
      ? (metadata.selection_column_index as number)
      : 0;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderMap(dashboardId, metadata.index, filters, theme)
      .then((res) => {
        if (cancelled) return;
        // Keep the previous map mounted while the next response is in
        // flight; Plotly diffs props so swapping data/layout in place
        // avoids the full tile-layer teardown the old loader pattern caused.
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
  }, [dashboardId, metadata.index, JSON.stringify(filters), theme, refreshTick]);

  const isInitialLoad = figure === null;
  const showInitialLoader = isInitialLoad && loading;
  const showRefetchOverlay = !isInitialLoad && loading;

  const emitSelection = (values: string[]) => {
    if (!onFilterChange) return;
    onFilterChange({
      index: metadata.index,
      value: values,
      source: 'map_selection',
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
    emitSelection(extractScatterSelection(event, selectionColumnIndex));
  };

  const handleClick = (event: any) => {
    if (!selectionEnabled || !selectionColumn) return;
    emitSelection(extractScatterSelection(event, selectionColumnIndex));
  };

  const handleDeselect = () => {
    if (!selectionEnabled) return;
    emitSelection([]);
  };

  const layout = useMemo<Record<string, unknown>>(() => {
    const base: Record<string, unknown> = {
      ...((figure?.layout as Record<string, unknown>) || {}),
      autosize: true,
      margin: {
        l: 0,
        r: 0,
        t: 30,
        b: 0,
        ...((figure?.layout?.margin as Record<string, unknown>) || {}),
      },
    };
    if (selectionEnabled && !base.dragmode) {
      // Respect a YAML-level ``selection_mode`` ('lasso' | 'select' | 'pan').
      // Default 'lasso' matches the Dash map component default.
      const mode =
        typeof metadata.selection_mode === 'string' ? metadata.selection_mode : 'lasso';
      base.dragmode = mode;
    }
    if (!base.uirevision) base.uirevision = 'persistent';
    return base;
  }, [figure, selectionEnabled, metadata.selection_mode]);

  return (
    <Paper p="sm" withBorder radius="md" style={{ minHeight: 320 }}>
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title}
        </Text>
      )}
      {showInitialLoader && (
        <Stack align="center" justify="center" gap="xs" mih={250}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Rendering map…</Text>
        </Stack>
      )}
      {error && isInitialLoad && (
        <Stack mih={250} justify="center" align="center">
          <Text size="sm" c="red" className="dashboard-error">Map failed: {error}</Text>
        </Stack>
      )}
      {figure && (
        <div style={{ position: 'relative' }}>
          <Plot
            data={(figure.data as any[]) || []}
            layout={layout}
            config={{ displaylogo: false, responsive: true, scrollZoom: true }}
            style={{ width: '100%', height: 320 }}
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

export default MapRenderer;
