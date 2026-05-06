import React, { useEffect, useState } from 'react';
import { Alert, Loader, Stack, Text } from '@mantine/core';
import Plot from 'react-plotly.js';

import { previewFigure } from 'depictio-react-core';

import type { PlotSuggestion } from '../types';

interface Props {
  suggestion: PlotSuggestion;
  dataCollectionId: string;
  /** Optional — surfaced as project_id in the preview metadata. The
   *  /figure/preview endpoint resolves the workflow from the DC if both
   *  this and wfId are missing, so passing it is best-effort. */
  projectId?: string;
  workflowId?: string;
  theme?: 'light' | 'dark';
}

/**
 * Renders a Plotly chart for the AI-suggested PlotSuggestion by hitting the
 * existing /figure/preview endpoint. Lives in the AI drawer transcript so the
 * user sees the actual chart they prompted for, not just the JSON spec.
 */
const FigurePreview: React.FC<Props> = ({
  suggestion,
  dataCollectionId,
  projectId,
  workflowId,
  theme = 'light',
}) => {
  const [figure, setFigure] = useState<{
    data?: unknown[];
    layout?: Record<string, unknown>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const metadata: Record<string, unknown> = {
      index: 'ai-preview',
      component_type: 'figure',
      mode: 'ui',
      dc_id: dataCollectionId,
      visu_type: suggestion.visu_type,
      dict_kwargs: suggestion.dict_kwargs,
      code_content: null,
    };
    if (projectId) metadata.project_id = projectId;
    if (workflowId) metadata.wf_id = workflowId;

    previewFigure({ metadata, filters: [], theme })
      .then((res) => {
        if (cancelled) return;
        setFigure(res.figure || null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // Re-render only when the inputs actually change. Stringify dict_kwargs so
    // a new object identity with the same contents doesn't refetch.
  }, [
    dataCollectionId,
    projectId,
    workflowId,
    theme,
    suggestion.visu_type,
    JSON.stringify(suggestion.dict_kwargs),
  ]);

  if (loading) {
    return (
      <Stack align="center" gap={4} py="md">
        <Loader size="sm" />
        <Text size="xs" c="dimmed">
          Rendering figure…
        </Text>
      </Stack>
    );
  }

  if (error) {
    return (
      <Alert color="red" variant="light" title="Preview failed">
        <Text size="xs" style={{ whiteSpace: 'pre-wrap' }}>
          {error}
        </Text>
      </Alert>
    );
  }

  if (!figure?.data || figure.data.length === 0) {
    return (
      <Alert color="yellow" variant="light">
        <Text size="xs">
          The server returned an empty figure. Try a different prompt or
          check that the data collection has rows for the chosen columns.
        </Text>
      </Alert>
    );
  }

  return (
    <div style={{ width: '100%', minHeight: 280 }}>
      <Plot
        data={figure.data as Plotly.Data[]}
        layout={
          {
            ...(figure.layout || {}),
            autosize: true,
            margin: { t: 32, r: 8, b: 40, l: 48 },
          } as unknown as Plotly.Layout
        }
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%', height: 320 }}
        useResizeHandler
      />
    </div>
  );
};

export default FigurePreview;
