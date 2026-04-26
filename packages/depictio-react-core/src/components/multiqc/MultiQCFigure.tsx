import React, { useEffect, useState } from 'react';
import { Paper, Loader, Text, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderMultiQC, InteractiveFilter, StoredMetadata } from '../../api';

interface MultiQCFigureProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
}

/**
 * Renders one regular MultiQC Plotly figure. Server-side route wraps the pure
 * `create_multiqc_plot(s3_locations, module, plot, dataset_id, theme)` in
 * `figure_component/multiqc_vis.py:282` — same path the Dash callback uses.
 *
 * The route reads `selected_module`, `selected_plot`, `selected_dataset` and
 * `s3_locations` from the component's stored_metadata, so we just pass the
 * component_id and let the backend resolve everything.
 *
 * Mirrors FigureRenderer; the MultiQC overlay logo is a small absolutely
 * positioned image in the top-right corner (matches the Dash viewer chrome).
 */
const MultiQCFigure: React.FC<MultiQCFigureProps> = ({
  dashboardId,
  metadata,
  filters,
}) => {
  const [figure, setFigure] = useState<
    { data?: unknown[]; layout?: Record<string, unknown> } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderMultiQC(dashboardId, metadata.index, filters, theme)
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

  const titleText =
    (metadata.title as string | undefined) ||
    [metadata.selected_module, metadata.selected_plot]
      .filter(Boolean)
      .join(' / ');

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
        position: 'relative',
      }}
    >
      {titleText && (
        <Text fw={600} size="sm" mb="xs">
          {titleText}
        </Text>
      )}
      {loading && (
        <Stack align="center" justify="center" gap="xs" style={{ flex: 1 }}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Rendering MultiQC plot…</Text>
        </Stack>
      )}
      {error && !loading && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red" className="dashboard-error">MultiQC failed: {error}</Text>
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
          {/* MultiQC overlay badge — text-only since the SPA's FastAPI mount
            doesn't serve the Dash assets dir. Cheap, theme-aware, no 404. */}
          <span
            title="Generated with MultiQC"
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.5,
              padding: '2px 6px',
              borderRadius: 4,
              background: 'rgba(0,0,0,0.06)',
              color: 'var(--mantine-color-dimmed)',
              pointerEvents: 'none',
              zIndex: 5,
            }}
          >
            MultiQC
          </span>
        </div>
      )}
    </Paper>
  );
};

export default MultiQCFigure;
