import React, { useEffect, useState } from 'react';
import { Paper, Loader, Text, Stack } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderMap, InteractiveFilter, StoredMetadata } from '../api';

interface MapRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
}

/**
 * Renders a Plotly map component (px.scatter_map / density_map / choropleth_map).
 * Mirrors FigureRenderer: server returns a Plotly figure dict via
 * `POST /dashboards/render_map/{id}/{component_id}`, React renders via
 * react-plotly.js. No Leaflet — Depictio's map module is Plotly-based.
 */
const MapRenderer: React.FC<MapRendererProps> = ({
  dashboardId,
  metadata,
  filters,
}) => {
  const [figure, setFigure] = useState<{ data?: unknown[]; layout?: Record<string, unknown> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderMap(dashboardId, metadata.index, filters)
      .then((res) => {
        if (cancelled) return;
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
  }, [dashboardId, metadata.index, JSON.stringify(filters)]);

  return (
    <Paper p="sm" withBorder radius="md" style={{ minHeight: 320 }}>
      {metadata.title && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title}
        </Text>
      )}
      {loading && (
        <Stack align="center" justify="center" gap="xs" mih={250}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Rendering map…</Text>
        </Stack>
      )}
      {error && !loading && (
        <Stack mih={250} justify="center" align="center">
          <Text size="sm" c="red" className="dashboard-error">Map failed: {error}</Text>
        </Stack>
      )}
      {figure && !loading && !error && (
        <Plot
          data={(figure.data as any[]) || []}
          layout={{
            ...((figure.layout as Record<string, unknown>) || {}),
            autosize: true,
            margin: {
              l: 0,
              r: 0,
              t: 30,
              b: 0,
              ...((figure.layout?.margin as Record<string, unknown>) || {}),
            },
          }}
          config={{ displaylogo: false, responsive: true, scrollZoom: true }}
          style={{ width: '100%', height: 320 }}
          useResizeHandler
        />
      )}
    </Paper>
  );
};

export default MapRenderer;
