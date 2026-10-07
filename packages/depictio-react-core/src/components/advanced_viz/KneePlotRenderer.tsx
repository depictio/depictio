import React, { useEffect, useMemo, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { VizSwitch } from './controls/VizControls';
import { logSpacedRankThin } from './kneeThinning';
import { applyDataTheme, applyLayoutTheme, plotlyThemeColors, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `KneePlotConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface KneePlotConfig {
  sample_col: string;
  rank_col: string;
  umi_count_col: string;
  is_cell_col?: string | null;
  log_x?: boolean;
  log_y?: boolean;
  show_cutoff?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: KneePlotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// Sent so the server applies this kind's `log_rank` reduction: dense near
// rank 1 (the cell/background inflection), sparse across the flat tail. See
// `KIND_SAMPLING_POLICY` in models/components/advanced_viz/sampling.py.
const KNEE_PLOT_VIZ_KIND: AdvancedVizKind = 'knee_plot';

const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
  scrollZoom: false,
};

const PALETTE = TAB10_PALETTE;

// Per-curve point budget for the SVG `scatter` trace this renderer draws
// (never `scattergl`, see the kind's renderer docstring). Matches the order
// of magnitude of `webglBudget.ts`'s `SVG_MAX_POINTS`; a knee curve has one
// point per rank, so an un-thinned real barcode-rank table can run into the
// millions.
const MAX_POINTS_PER_CURVE = 3000;

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/**
 * Rough single-curve knee (inflection) estimate in log-log space, à la the
 * "kneedle" method: the point on the curve farthest from the straight line
 * joining its own first and last point. Only used when the DC carries no
 * `is_cell` column to read the cutoff from directly.
 */
function estimateKneeRank(points: { rank: number; umi: number }[]): number | null {
  if (points.length < 3) return null;
  const lx = points.map((p) => Math.log10(Math.max(1, p.rank)));
  const ly = points.map((p) => Math.log10(Math.max(1, p.umi)));
  const x0 = lx[0];
  const y0 = ly[0];
  const x1 = lx[lx.length - 1];
  const y1 = ly[ly.length - 1];
  const dx = x1 - x0;
  const dy = y1 - y0;
  const norm = Math.sqrt(dx * dx + dy * dy) || 1;
  let bestIdx = 0;
  let bestDist = -1;
  for (let i = 0; i < points.length; i++) {
    // Perpendicular distance from (lx[i], ly[i]) to the chord (x0,y0)-(x1,y1).
    const dist = Math.abs(dy * lx[i] - dx * ly[i] + x1 * y0 - y1 * x0) / norm;
    if (dist > bestDist) {
      bestDist = dist;
      bestIdx = i;
    }
  }
  return points[bestIdx].rank;
}

const KneePlotPlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
}>(({ figure, isDark, theme }) => {
  const themedData = useMemo(() => applyDataTheme(figure.data, isDark, theme), [figure.data, isDark, theme]);
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout as any, isDark, theme),
    [figure.layout, isDark, theme],
  );
  return (
    <Plot data={themedData as any} layout={themedLayout as any} useResizeHandler style={PLOT_STYLE} config={PLOT_CONFIG as any} />
  );
});
KneePlotPlot.displayName = 'KneePlotPlot';

/**
 * Barcode-rank ("knee") curve: UMI count vs rank, one line per sample, on
 * log-log axes by default. The cell-calling threshold, where the curve
 * drops from the cell population into the empty-droplet background, is
 * drawn as a reference line, read from `is_cell_col` when bound or estimated
 * from the curve's own shape otherwise.
 */
const KneePlotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const palette = resolveCategoricalPalette(theme, PALETTE);
  const config = (metadata.config || {}) as KneePlotConfig;
  const isDark = colorScheme === 'dark';

  const [logX, setLogX] = usePersistedVizControl<boolean>(metadata, 'log_x', config.log_x ?? true);
  const [logY, setLogY] = usePersistedVizControl<boolean>(metadata, 'log_y', config.log_y ?? true);
  const [showCutoff, setShowCutoff] = usePersistedVizControl<boolean>(
    metadata,
    'show_cutoff',
    config.show_cutoff ?? true,
  );

  const requiredCols = useMemo(() => {
    const cols = [config.sample_col, config.rank_col, config.umi_count_col].filter(Boolean) as string[];
    if (config.is_cell_col && !cols.includes(config.is_cell_col)) cols.push(config.is_cell_col);
    return cols;
  }, [config.sample_col, config.rank_col, config.umi_count_col, config.is_cell_col]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Knee plot: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters,
      vizKind: KNEE_PLOT_VIZ_KIND,
      roles: {
        sample: config.sample_col,
        rank: config.rank_col,
        umi_count: config.umi_count_col,
        ...(config.is_cell_col ? { is_cell: config.is_cell_col } : {}),
      },
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), JSON.stringify(filters), refreshTick]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const samples = (rows[config.sample_col] || []) as unknown[];
    const ranks = (rows[config.rank_col] || []) as unknown[];
    const umis = (rows[config.umi_count_col] || []) as unknown[];
    const isCells = config.is_cell_col ? ((rows[config.is_cell_col] || []) as unknown[]) : null;

    type Pt = { rank: number; umi: number; isCell: boolean | null };
    const bySample = new Map<string, Pt[]>();
    const n = Math.min(ranks.length, umis.length);
    for (let i = 0; i < n; i++) {
      const rank = num(ranks[i]);
      const umi = num(umis[i]);
      if (rank === null || umi === null) continue;
      const key = samples[i] === null || samples[i] === undefined ? 'sample' : String(samples[i]);
      let pts = bySample.get(key);
      if (!pts) {
        pts = [];
        bySample.set(key, pts);
      }
      let isCell: boolean | null = null;
      if (isCells) {
        const raw = isCells[i];
        isCell = raw === true || raw === 1 || raw === '1' || raw === 'true';
      }
      pts.push({ rank, umi, isCell });
    }

    const names = Array.from(bySample.keys()).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    for (const name of names) bySample.get(name)!.sort((a, b) => a.rank - b.rank);

    const colours = stableColorMap(names, palette, null);
    const { textColor, gridColor, zeroLineColor } = plotlyThemeColors(isDark, theme);

    const traces: any[] = [];
    const shapes: any[] = [];
    const annotations: any[] = [];

    for (const name of names) {
      const pts = bySample.get(name)!;
      const colour = colours.get(name);
      // Log-spaced thin for the drawn trace only, dense near rank 1 (the
      // interesting bend), sparse across the flat tail. The cutoff below
      // reads `pts` (the full curve), not this subset, so thinning can never
      // move the cutoff line.
      const keepIdx = logSpacedRankThin(pts.length, MAX_POINTS_PER_CURVE);
      const drawn = keepIdx.map((i) => pts[i]);
      traces.push({
        type: 'scatter' as const,
        mode: 'lines' as const,
        x: drawn.map((p) => p.rank),
        y: drawn.map((p) => p.umi),
        name,
        line: { color: colour, width: 2, shape: 'linear' as const },
        hovertemplate: `<b>${name}</b><br>rank: %{x}<br>UMI count: %{y}<extra></extra>`,
      });

      if (showCutoff) {
        let cutoffRank: number | null = null;
        if (pts.some((p) => p.isCell !== null)) {
          // Boundary between the called-cell run and the background: the
          // largest rank still marked a cell.
          for (const p of pts) if (p.isCell) cutoffRank = p.rank;
        } else {
          cutoffRank = estimateKneeRank(pts);
        }
        if (cutoffRank !== null) {
          shapes.push({
            type: 'line',
            x0: cutoffRank,
            x1: cutoffRank,
            y0: 0,
            y1: 1,
            xref: 'x',
            yref: 'paper',
            line: { color: colour, width: 1, dash: 'dot' },
          });
          annotations.push({
            x: cutoffRank,
            y: 1,
            xref: 'x',
            yref: 'paper',
            text: `${name} cutoff`,
            showarrow: false,
            yanchor: 'bottom',
            font: { size: 9, color: colour },
          });
        }
      }
    }

    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        xaxis: {
          title: { text: 'Barcode rank' },
          type: logX ? ('log' as const) : ('linear' as const),
          gridcolor: gridColor,
          zerolinecolor: zeroLineColor,
          color: textColor,
        },
        yaxis: {
          title: { text: 'UMI count' },
          type: logY ? ('log' as const) : ('linear' as const),
          gridcolor: gridColor,
          zerolinecolor: zeroLineColor,
          color: textColor,
        },
        shapes,
        annotations,
        showlegend: names.length > 1,
        margin: { l: 56, r: 12, t: names.length > 1 ? 12 : 12, b: 44 },
        autosize: true,
      },
    };
  }, [rows, config, palette, isDark, theme, logX, logY, showCutoff]);

  // Encoding tier: the two axis scales are the whole reading of a knee plot  -
  // a linear rank axis hides the knee entirely.
  const primaryControls = (
    <>
      <VizSwitch checked={logX} onChange={(e) => setLogX(e.currentTarget.checked)} label="Log rank (x)" />
      <VizSwitch checked={logY} onChange={(e) => setLogY(e.currentTarget.checked)} label="Log UMI count (y)" />
    </>
  );

  const controls = (
    <VizSwitch
      checked={showCutoff}
      onChange={(e) => setShowCutoff(e.currentTarget.checked)}
      label="Show cell-calling cutoff"
    />
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Knee plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? <KneePlotPlot figure={figure} isDark={isDark} theme={theme} /> : null}
    </AdvancedVizFrame>
  );
};

export default KneePlotRenderer;
