/**
 * Figure preview pane. UI mode: debounce-driven live preview hitting
 * /figure/preview. Code mode: show the last figure produced by the user
 * clicking Execute Code (stored in `lastCodeFigure`); never auto-fetch.
 *
 * Mirrors the dual-graph behaviour in design_figure() — Dash hides the UI
 * preview graph and shows a separate code-mode graph populated only on
 * Execute click.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Alert, Box, Loader, Stack, Text } from '@mantine/core';
import Plot from 'react-plotly.js';
import { previewFigure } from 'depictio-react-core';
import type { FigureResponse } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { buildMetadata } from '../buildMetadata';

const DEBOUNCE_MS = 400;

const PLOT_STYLE: React.CSSProperties = { width: '100%', height: 400 };

const FigurePreview: React.FC = () => {
  const state = useBuilderStore();
  const [figure, setFigure] = useState<FigureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);

  // Inputs that affect UI-mode preview rendering. Code mode is excluded so
  // typing in the editor doesn't trigger a request.
  const inputKey = JSON.stringify({
    componentType: state.componentType,
    wfId: state.wfId,
    dcId: state.dcId,
    visuType: state.visuType,
    figureMode: state.figureMode,
    dictKwargs: state.dictKwargs,
  });

  useEffect(() => {
    if (state.figureMode === 'code') return;
    if (!state.componentType || state.componentType !== 'figure') return;
    if (!state.wfId || !state.dcId) return;

    const hasAny = Object.values(state.dictKwargs).some(
      (v) => v != null && v !== '',
    );
    if (!hasAny) {
      setFigure(null);
      return;
    }

    const t = window.setTimeout(() => {
      const id = ++reqId.current;
      setLoading(true);
      setError(null);
      previewFigure({ metadata: buildMetadata(state) })
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
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputKey]);

  const inCode = state.figureMode === 'code';
  const codeFig = state.lastCodeFigure;

  // Two loading states. First-time fetch: centered loader + label, replaces
  // the empty-state hint. Subsequent fetches with a previous figure on screen:
  // small top-right spinner so the chart stays visible while it refreshes.
  const showCenteredLoader = !inCode && loading && !figure;
  const showInlineLoader = !inCode && loading && Boolean(figure);

  return (
    <Box pos="relative" style={{ width: '100%', height: '100%' }}>
      {showInlineLoader && (
        <Box pos="absolute" right={12} top={12} style={{ zIndex: 2 }}>
          <Loader size="xs" />
        </Box>
      )}
      {!inCode && error && (
        <Alert color="red" title="Preview failed">
          <Text size="xs">{error}</Text>
        </Alert>
      )}
      {showCenteredLoader && (
        <Stack
          align="center"
          justify="center"
          gap="sm"
          style={{ height: 400 }}
        >
          <Loader size="md" />
          <Text size="sm" c="dimmed">
            Building figure preview…
          </Text>
        </Stack>
      )}
      {!inCode && !loading && !error && !figure && (
        <Stack align="center" justify="center" style={{ height: 400 }}>
          <Text size="sm" c="dimmed">
            Configure axes to see a preview.
          </Text>
        </Stack>
      )}
      {!inCode && figure && (
        <Plot
          data={(figure.figure?.data as Plotly.Data[]) || []}
          layout={{
            ...(figure.figure?.layout || {}),
            autosize: true,
            margin: { t: 30, r: 20, b: 40, l: 50 },
          }}
          useResizeHandler
          style={PLOT_STYLE}
          config={{ displaylogo: false, responsive: true }}
        />
      )}
      {inCode && !codeFig && (
        <Stack
          align="center"
          justify="center"
          style={{ height: 400 }}
        >
          <Text size="sm" c="dimmed">
            Click "Execute Code" to render your figure.
          </Text>
        </Stack>
      )}
      {inCode && codeFig && (
        <Plot
          data={(codeFig.data as Plotly.Data[]) || []}
          layout={{
            ...(codeFig.layout || {}),
            autosize: true,
            margin: { t: 30, r: 20, b: 40, l: 50 },
          }}
          useResizeHandler
          style={PLOT_STYLE}
          config={{ displaylogo: false, responsive: true }}
        />
      )}
    </Box>
  );
};

export default FigurePreview;
