/**
 * Live preview of one AI figure suggestion inside the "Add with AI" modal.
 *
 * The depictio-react-ai package has no plotting dependency, so it exposes a
 * `renderSuggestionPreview` slot and the viewer fills it with this component:
 * the suggestion's (visu_type, dict_kwargs) is shaped into the same in-flight
 * metadata the builder uses and rendered through POST /figure/preview, so the
 * user sees the actual plot on the actual data before picking a suggestion.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Alert, Box, Loader, Stack, Text } from '@mantine/core';
import { useComputedColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';
import { previewFigure } from 'depictio-react-core';
import type { FigureResponse } from 'depictio-react-core';
import type { AvailableDataCollection, PlotSuggestion } from 'depictio-react-ai';

const PLOT_HEIGHT = 240;

interface Props {
  suggestion: PlotSuggestion;
  dc: AvailableDataCollection;
}

const AISuggestionPreview: React.FC<Props> = ({ suggestion, dc }) => {
  const [figure, setFigure] = useState<FigureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);
  const colorScheme = useComputedColorScheme('light');

  const inputKey = JSON.stringify({
    dcId: dc.dcId,
    wfId: dc.wfId,
    visuType: suggestion.visu_type,
    dictKwargs: suggestion.dict_kwargs,
    colorScheme,
  });

  useEffect(() => {
    const id = ++reqId.current;
    setLoading(true);
    setError(null);
    previewFigure({
      metadata: {
        index: 'ai-suggestion-preview',
        component_type: 'figure',
        wf_id: dc.wfId,
        dc_id: dc.dcId,
        mode: 'ui',
        visu_type: suggestion.visu_type,
        dict_kwargs: suggestion.dict_kwargs,
        code_content: null,
      },
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
