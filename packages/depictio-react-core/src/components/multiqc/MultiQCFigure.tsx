import React, { useEffect, useMemo, useState } from 'react';
import { Paper, Loader, Text, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderMultiQC, InteractiveFilter, StoredMetadata } from '../../api';
import { useInView } from '../../hooks/useInView';
import { readMultiqcSelection } from '../../utils/multiqcSelection';
import MultiQCGeneralStats from './MultiQCGeneralStats';

interface MultiQCFigureProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// Plotly config / style passed by reference to keep <Plot> stable across renders.
const PLOT_CONFIG = { displaylogo: false, responsive: true } as const;
const PLOT_STYLE = { width: '100%', height: '100%' } as const;

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
// Defensive routing: when a General Stats component lands here (e.g. a stale
// HMR bundle of the parent dispatcher routes it as a regular figure), calling
// renderMultiQC 500s with `Module "general_stats" is not found`. Detect at
// the wrapper layer so the heavy hooks/effects of MultiQCFigureBody never
// mount in that case. Reads both `selected_*` and the legacy `multiqc_*`
// keys so pre-rename dashboards work without a re-save.
const MultiQCFigure: React.FC<MultiQCFigureProps> = (props) => {
  if (readMultiqcSelection(props.metadata as Record<string, unknown>).isGeneralStats) {
    return <MultiQCGeneralStats {...props} />;
  }
  return <MultiQCFigureBody {...props} />;
};

// Backend returns 202 when the figure cache is being prebuilt. The viewer
// polls every PREPARE_POLL_INTERVAL_MS until the figure is ready or
// PREPARE_POLL_MAX_MS elapses (then gives up with an error). 1.5s feels
// responsive without hammering the backend. 5 min covers worst-case
// rebuilds (large reports, many modules, slow workers) with margin — if
// it actually trips, something upstream is wrong and we want a clear error.
const PREPARE_POLL_INTERVAL_MS = 1500;
const PREPARE_POLL_MAX_MS = 300_000;

const MultiQCFigureBody: React.FC<MultiQCFigureProps> = ({
  dashboardId,
  metadata,
  filters,
  refreshTick,
}) => {
  const [figure, setFigure] = useState<
    { data?: unknown[]; layout?: Record<string, unknown> } | null
  >(null);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';
  const [containerRef, inView] = useInView<HTMLDivElement>('200px');

  useEffect(() => {
    if (!inView) return;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const startedAt = Date.now();

    const attempt = (): void => {
      setLoading(true);
      setError(null);
      renderMultiQC(dashboardId, metadata.index, filters, theme)
        .then((res) => {
          if (cancelled) return;
          if (res.status === 'preparing') {
            setPreparing(true);
            if (Date.now() - startedAt >= PREPARE_POLL_MAX_MS) {
              setError('MultiQC figures took too long to build.');
              setLoading(false);
              return;
            }
            timeoutId = setTimeout(attempt, PREPARE_POLL_INTERVAL_MS);
            return;
          }
          setPreparing(false);
          setFigure(res.figure);
          setLoading(false);
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err?.message || String(err));
          setLoading(false);
        });
    };

    attempt();
    return () => {
      cancelled = true;
      if (timeoutId !== null) clearTimeout(timeoutId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filters), theme, inView, refreshTick]);

  const titleText =
    (metadata.title as string | undefined) ||
    [metadata.selected_module, metadata.selected_plot]
      .filter(Boolean)
      .join(' / ');

  // Memoize the props passed to <Plot>. Without this, every parent re-render
  // (theme change, sibling layout shift, etc.) reconstructs `data` / `layout`
  // identities and triggers a full Plotly relayout, which is the dominant
  // client-side cost on big MultiQC figures.
  const plotData = useMemo(
    () => (figure?.data as unknown[]) || [],
    [figure],
  );
  const plotLayout = useMemo(
    () => ({
      ...((figure?.layout as Record<string, unknown>) || {}),
      autosize: true,
      margin: {
        l: 50,
        r: 20,
        t: 30,
        b: 50,
        ...((figure?.layout?.margin as Record<string, unknown>) || {}),
      },
      // Bump uirevision per refreshTick so realtime updates produce a unique
      // value and force Plotly to repaint. The server bakes in
      // `uirevision: "persistent"`; without overwriting it, identical
      // uirevision means Plotly skips repaint even on data changes.
      uirevision: `tick-${refreshTick ?? 0}`,
    }),
    [figure, refreshTick],
  );

  return (
    <Paper
      ref={containerRef}
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
      {(!inView || loading) && (
        <Stack align="center" justify="center" gap="xs" style={{ flex: 1 }}>
          <Loader size="sm" />
          <Text size="xs" c="dimmed">
            {preparing ? 'Preparing MultiQC figures…' : 'Rendering MultiQC plot…'}
          </Text>
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
            data={plotData as any[]}
            layout={plotLayout}
            revision={refreshTick ?? 0}
            config={PLOT_CONFIG}
            style={PLOT_STYLE}
            useResizeHandler
          />
          {/* MultiQC logo overlay — official icon set
            (https://github.com/MultiQC/logo). Dark icon on light backgrounds,
            white icon in dark mode. Asset shipped via the SPA's public/ folder
            and served by the FastAPI mount at /dashboard-beta/logos/. */}
          <img
            src={
              theme === 'dark'
                ? '/dashboard-beta/logos/multiqc_icon_white.svg'
                : '/dashboard-beta/logos/multiqc_icon_dark.svg'
            }
            title="Generated with MultiQC"
            alt="MultiQC"
            style={{
              position: 'absolute',
              top: 10,
              right: 10,
              width: 40,
              height: 40,
              opacity: 0.6,
              pointerEvents: 'none',
              zIndex: 1000,
            }}
          />
        </div>
      )}
    </Paper>
  );
};

// React.memo with a custom comparator: filters are array-shaped, so a
// reference check would re-render whenever the parent re-creates the array
// even when the contents are identical. Stringifying mirrors the comparison
// the useEffect dep already uses. ``refreshTick`` MUST be in the comparator —
// otherwise realtime updates from the parent are memoized away and the fetch
// effect never re-runs.
export default React.memo(MultiQCFigure, (prev, next) => {
  return (
    prev.dashboardId === next.dashboardId &&
    prev.metadata.index === next.metadata.index &&
    prev.metadata.title === next.metadata.title &&
    prev.metadata.selected_module === next.metadata.selected_module &&
    prev.metadata.selected_plot === next.metadata.selected_plot &&
    prev.refreshTick === next.refreshTick &&
    JSON.stringify(prev.filters) === JSON.stringify(next.filters)
  );
});
