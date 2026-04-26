import React, { useEffect, useState } from 'react';
import { Paper, Loader, Text, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderFigure, InteractiveFilter, StoredMetadata } from '../api';

interface FigureRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
}

/**
 * Renders a Plotly figure component. Server-side path: FastAPI calls
 * `_create_figure_from_data` (the same function the Dash callback uses) and
 * returns the figure JSON. Client renders via react-plotly.js — no Dash
 * callback round-trip, no `_dash-update-component`.
 */
const FigureRenderer: React.FC<FigureRendererProps> = ({
  dashboardId,
  metadata,
  filters,
}) => {
  const [figure, setFigure] = useState<{ data?: unknown[]; layout?: Record<string, unknown> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderFigure(dashboardId, metadata.index, filters, theme)
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
  }, [dashboardId, metadata.index, JSON.stringify(filters), theme]);

  return (
    <Paper
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
      {loading && (
        <Stack align="center" justify="center" gap="xs" style={{ flex: 1 }}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Rendering figure…</Text>
        </Stack>
      )}
      {error && !loading && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red">Figure failed: {error}</Text>
        </Stack>
      )}
      {figure && !loading && !error && (
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <Plot
            data={(figure.data as any[]) || []}
            layout={{
              ...((figure.layout as Record<string, unknown>) || {}),
              autosize: true,
              margin: {
                l: 50,
                r: 20,
                t: 30,
                b: 50,
                ...((figure.layout?.margin as Record<string, unknown>) || {}),
              },
            }}
            config={{ displaylogo: false, responsive: true }}
            style={{ width: '100%', height: '100%' }}
            useResizeHandler
          />
        </div>
      )}
    </Paper>
  );
};

export default FigureRenderer;
