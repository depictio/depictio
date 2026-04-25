import React, { useEffect, useState } from 'react';
import { Paper, Loader, Text, Stack } from '@mantine/core';
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

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderMultiQC(dashboardId, metadata.index, filters)
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

  const titleText =
    (metadata.title as string | undefined) ||
    [metadata.selected_module, metadata.selected_plot]
      .filter(Boolean)
      .join(' / ');

  return (
    <Paper p="sm" withBorder radius="md" style={{ minHeight: 320, position: 'relative' }}>
      {titleText && (
        <Text fw={600} size="sm" mb="xs">
          {titleText}
        </Text>
      )}
      {loading && (
        <Stack align="center" justify="center" gap="xs" mih={250}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">Rendering MultiQC plot…</Text>
        </Stack>
      )}
      {error && !loading && (
        <Stack mih={250} justify="center" align="center">
          <Text size="sm" c="red" className="dashboard-error">MultiQC failed: {error}</Text>
        </Stack>
      )}
      {figure && !loading && !error && (
        <>
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
            style={{ width: '100%', height: 320 }}
            useResizeHandler
          />
          <img
            src="/assets/images/logos/multiqc.png"
            alt="MultiQC"
            title="Generated with MultiQC"
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              width: 36,
              height: 36,
              opacity: 0.6,
              pointerEvents: 'none',
              zIndex: 5,
            }}
          />
        </>
      )}
    </Paper>
  );
};

export default MultiQCFigure;
