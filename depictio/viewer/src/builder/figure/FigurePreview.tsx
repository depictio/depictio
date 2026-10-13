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
import { FigureHeader, figurePlotConfig, previewFigure, resolveFigureStyle } from 'depictio-react-core';
import type { FigureResponse, FigureStyle } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { useBuilderPreviewFilters } from '../useBuilderPreviewFilters';
import { buildMetadata } from '../buildMetadata';
import { useSectionFigureStyle } from '../shared/useSectionCardVariant';

const DEBOUNCE_MS = 400;

const PLOT_STYLE: React.CSSProperties = { width: '100%', height: 400 };

/** The grid's default margins, under whatever the server set: a minimal
 *  figure comes back with tight margins of its own, which must survive. */
function previewLayout(layout: Record<string, unknown> | undefined): Partial<Plotly.Layout> {
  const own = layout || {};
  return {
    ...own,
    autosize: true,
    margin: {
      t: 30,
      r: 20,
      b: 40,
      l: 50,
      ...((own.margin as Record<string, unknown>) || {}),
    },
  } as Partial<Plotly.Layout>;
}

interface FigureDisplayConfig {
  title?: string;
  subtitle?: string;
  figure_style?: string | null;
  icon_name?: string | null;
  icon_color?: string | null;
  hide_legend?: boolean | null;
}

const FigurePreview: React.FC = () => {
  const state = useBuilderStore();
  const [figure, setFigure] = useState<FigureResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reqId = useRef(0);

  const previewFilters = useBuilderPreviewFilters();
  const sectionStyle = useSectionFigureStyle();
  const display = state.config as FigureDisplayConfig;
  const style: FigureStyle = resolveFigureStyle(display.figure_style, sectionStyle);

  // Inputs that affect UI-mode preview rendering. Code mode is excluded so
  // typing in the editor doesn't trigger a request. The active dashboard
  // filters are part of the key: toggling "Apply to preview" must refire.
  const inputKey = JSON.stringify({
    componentType: state.componentType,
    wfId: state.wfId,
    dcId: state.dcId,
    visuType: state.visuType,
    figureMode: state.figureMode,
    dictKwargs: state.dictKwargs,
    filters: previewFilters,
    // The server restyles the plot for the minimal look and drops its title
    // when the card header shows one.
    style,
    title: display.title?.trim() || '',
    hideLegend: Boolean(display.hide_legend),
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
      previewFigure({
        // The resolved style, so a figure following its section's minimal
        // style previews in it before it is saved into the section.
        metadata: { ...buildMetadata(state), figure_style: style },
        filters: previewFilters,
        // Fold the dashboard's plot_theme defaults into the preview so it
        // matches what the saved component will render.
        dashboard_id: state.dashboardId ?? undefined,
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

  // The card header the grid will draw above a minimal figure.
  const title = display.title?.trim();
  const subtitle = display.subtitle?.trim();
  const header =
    style === 'minimal' && (title || subtitle || display.icon_name) ? (
      <FigureHeader
        title={title}
        subtitle={subtitle}
        icon={display.icon_name || undefined}
        iconColor={display.icon_color || undefined}
      />
    ) : null;
  const plotConfig = figurePlotConfig(style);

  return (
    <Box pos="relative" style={{ width: '100%', height: '100%' }}>
      {header}
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
          layout={previewLayout(figure.figure?.layout as Record<string, unknown> | undefined)}
          useResizeHandler
          style={PLOT_STYLE}
          config={plotConfig}
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
          layout={previewLayout(codeFig.layout)}
          useResizeHandler
          style={PLOT_STYLE}
          config={plotConfig}
        />
      )}
    </Box>
  );
};

export default FigurePreview;
