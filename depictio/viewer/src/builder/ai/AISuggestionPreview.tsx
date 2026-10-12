/**
 * Live preview of one AI figure suggestion on the Describe step.
 *
 * The depictio-react-ai package has no plotting dependency, so the viewer
 * renders the suggestion itself: its (visu_type, dict_kwargs) is shaped into
 * the same in-flight metadata the builder uses and rendered through
 * POST /figure/preview, under the dashboard filters the builder previews
 * apply, so the user sees the actual plot on the actual data before picking.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Alert, Box, Loader, Stack, Text } from '@mantine/core';
import { useComputedColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';
import { previewFigure } from 'depictio-react-core';
import type { FigureResponse } from 'depictio-react-core';
import { useBuilderPreviewFilters } from '../useBuilderPreviewFilters';

const PLOT_HEIGHT = 240;

/** The figure grammar of one suggestion, read off its lite component
 *  (`visu_type`, `dict_kwargs`), plus where to render it. */
interface Props {
  visuType: string;
  dictKwargs: Record<string, unknown>;
  dcId: string;
  wfId: string | null;
  dashboardId: string | null;
}

const AISuggestionPreview: React.FC<Props> = ({
  visuType,
  dictKwargs,
  dcId,
  wfId,
  dashboardId,
}) => {
  const [figure, setFigure] = useState<FigureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);
  const colorScheme = useComputedColorScheme('light');
  const previewFilters = useBuilderPreviewFilters();

  const inputKey = JSON.stringify({
    dcId,
    wfId,
    visuType,
    dictKwargs,
    colorScheme,
    filters: previewFilters,
  });

  useEffect(() => {
    const id = ++reqId.current;
    setLoading(true);
    setError(null);
    previewFigure({
      metadata: {
        index: 'ai-suggestion-preview',
        component_type: 'figure',
        wf_id: wfId ?? undefined,
        dc_id: dcId,
        mode: 'ui',
        visu_type: visuType,
        dict_kwargs: dictKwargs,
        code_content: null,
      },
      filters: previewFilters,
      dashboard_id: dashboardId ?? undefined,
      theme: colorScheme,
    })
      .then((res) => {
        if (reqId.current !== id) return;
        setFigure(res);
      })
      .catch((err) => {
        if (reqId.current !== id) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (reqId.current !== id) return;
        setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputKey]);

  if (loading) {
    return (
      <Stack align="center" justify="center" gap="xs" style={{ height: PLOT_HEIGHT }}>
        <Loader size="sm" />
        <Text size="xs" c="dimmed">
          Rendering preview…
        </Text>
      </Stack>
    );
  }
  if (error) {
    return (
      <Alert color="yellow" variant="light" p="xs">
        <Text size="xs">Preview unavailable: {error}</Text>
      </Alert>
    );
  }
  if (!figure) return null;

  return (
    <Box style={{ width: '100%' }}>
      <Plot
        data={(figure.figure?.data as Plotly.Data[]) || []}
        layout={{
          ...(figure.figure?.layout || {}),
          autosize: true,
          height: PLOT_HEIGHT,
          margin: { t: 24, r: 16, b: 36, l: 46 },
        }}
        useResizeHandler
        style={{ width: '100%', height: PLOT_HEIGHT }}
        config={{ displaylogo: false, responsive: true, staticPlot: true }}
      />
    </Box>
  );
};

export default AISuggestionPreview;
