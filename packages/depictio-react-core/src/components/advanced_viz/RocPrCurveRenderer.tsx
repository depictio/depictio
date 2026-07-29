import React, { useEffect, useMemo, useState } from 'react';
import { SegmentedControl, Slider, Stack, Switch, Text, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

interface RocPrCurveConfig {
  recall_col: string;
  precision_col: string;
  fpr_col?: string | null;
  threshold_col?: string | null;
  group_col?: string | null;
  show_auc?: boolean;
  fill?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RocPrCurveConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const PALETTE = ['#4C72B0', '#DD8452', '#55A467', '#C44E52', '#8172B3', '#937860', '#DA8BC3'];

// Trapezoidal area under precision(recall), points sorted by recall ascending.
function auc(recall: number[], precision: number[]): number {
  const pts = recall
    .map((r, i) => [r, precision[i]] as [number, number])
    .filter(([r, p]) => Number.isFinite(r) && Number.isFinite(p))
    .sort((a, b) => a[0] - b[0]);
  let area = 0;
  for (let i = 1; i < pts.length; i++) {
    area += ((pts[i][0] - pts[i - 1][0]) * (pts[i][1] + pts[i - 1][1])) / 2;
  }
  return area;
}

const RocPrCurveRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as RocPrCurveConfig;

  const [showAuc, setShowAuc] = useState<boolean>(config.show_auc ?? true);
  const [fill, setFill] = useState<boolean>(config.fill ?? false);
  const [markerSize, setMarkerSize] = useState<number>(6);
  // "case" switch: PR sweep (precision vs recall) or metrics-vs-threshold.
  // A true ROC (TPR vs FPR) is intentionally absent — variant calling has no
  // enumerable true-negative set, so FPR is undefined (PR is the field standard).
  const [mode, setMode] = useState<'pr' | 'roc' | 'threshold'>('pr');
  const [showMarkers, setShowMarkers] = useState<boolean>(true);
  const [showLegend, setShowLegend] = useState<boolean>(true);
  const hasThreshold = Boolean(config.threshold_col);
  const hasFpr = Boolean(config.fpr_col);
  const lineMode = showMarkers ? 'lines+markers' : 'lines';

  const requiredCols = useMemo(
    () =>
      [
        config.recall_col,
        config.precision_col,
        ...(config.fpr_col ? [config.fpr_col] : []),
        ...(config.threshold_col ? [config.threshold_col] : []),
        ...(config.group_col ? [config.group_col] : []),
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 2) {
      setError('ROC / PR curve: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(metadata.wf_id, metadata.dc_id, requiredCols, filters)
      .then((res) => {
        if (!cancelled) setRows(res.rows);
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
    const recall = (rows[config.recall_col] || []) as number[];
    const precision = (rows[config.precision_col] || []) as number[];
    const fpr = config.fpr_col ? ((rows[config.fpr_col] || []) as number[]) : null;
    const thr = config.threshold_col ? ((rows[config.threshold_col] || []) as number[]) : null;
    const group = config.group_col
      ? ((rows[config.group_col] || []) as (string | number)[])
      : null;

    // Group indices into one curve per group (or a single curve).
    const groups = new Map<string, number[]>();
    recall.forEach((_, i) => {
      const key = group ? String(group[i] ?? '') : '';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(i);
    });

    const traces: any[] = [];
    let ci = 0;
    const threshMode = mode === 'threshold' && !!thr;
    const rocMode = mode === 'roc' && !!fpr;
    for (const [key, idx] of groups) {
      const sorted = [...idx].sort((a, b) =>
        thr ? (thr[a] ?? 0) - (thr[b] ?? 0) : (recall[a] ?? 0) - (recall[b] ?? 0),
      );
      const color = PALETTE[ci % PALETTE.length];
      ci += 1;
      const pfx = key ? `${key} · ` : '';
      if (rocMode) {
        // True ROC: x = FPR, y = TPR (recall), sorted by FPR ascending.
        const rs = [...idx].sort((a, b) => (fpr![a] ?? 0) - (fpr![b] ?? 0));
        const xs = rs.map((i) => fpr![i]);
        const ys = rs.map((i) => recall[i]);
        const a = showAuc ? auc(xs, ys) : null;
        traces.push({
          type: 'scatter', mode: lineMode, x: xs, y: ys,
          name: (key || 'ROC') + (a != null ? `  (AUC ${a.toFixed(3)})` : ''),
          line: { width: 2, color }, marker: { size: markerSize, color },
          fill: fill ? 'tozeroy' : 'none', fillcolor: fill ? color + '22' : undefined,
          opacity: 0.95,
          hovertemplate: `<b>${key || 'ROC'}</b><br>FPR: %{x:.3f}<br>TPR: %{y:.3f}<extra></extra>`,
        });
      } else if (threshMode) {
        const tx = sorted.map((i) => thr![i]);
        traces.push({
          type: 'scatter', mode: lineMode, x: tx, y: sorted.map((i) => precision[i]),
          name: `${pfx}precision`, line: { width: 2, color }, marker: { size: markerSize, color },
          hovertemplate: `<b>${key || ''}</b><br>${config.threshold_col}: %{x}<br>Precision: %{y:.3f}<extra></extra>`,
        });
        traces.push({
          type: 'scatter', mode: lineMode, x: tx, y: sorted.map((i) => recall[i]),
          name: `${pfx}recall`, line: { width: 2, color, dash: 'dot' }, marker: { size: markerSize, color },
          hovertemplate: `<b>${key || ''}</b><br>${config.threshold_col}: %{x}<br>Recall: %{y:.3f}<extra></extra>`,
        });
      } else {
        const xs = sorted.map((i) => recall[i]);
        const ys = sorted.map((i) => precision[i]);
        const a = showAuc ? auc(xs, ys) : null;
        const name = (key || 'curve') + (a != null ? `  (AUC ${a.toFixed(3)})` : '');
        traces.push({
          type: 'scatter', mode: lineMode, x: xs, y: ys, name,
          line: { width: 2, color }, marker: { size: markerSize, color },
          fill: fill ? 'tozeroy' : 'none',
          fillcolor: fill ? color + '22' : undefined,
          opacity: 0.95,
          customdata: thr ? sorted.map((i) => thr![i]) : undefined,
          hovertemplate:
            `<b>${key || 'curve'}</b><br>Recall: %{x:.3f}<br>Precision: %{y:.3f}` +
            (thr ? `<br>${config.threshold_col}: %{customdata}` : '') + `<extra></extra>`,
        });
      }
    }

    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 55, r: 20, t: 20, b: 45 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: threshMode ? config.threshold_col || 'threshold' : rocMode ? 'False positive rate' : 'Recall' },
          range: threshMode ? undefined : [0, 1.03],
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: threshMode ? 'Score' : rocMode ? 'True positive rate' : 'Precision' },
          range: [0, 1.03],
        },
        shapes: rocMode
          ? [{ type: 'line', x0: 0, y0: 0, x1: 1, y1: 1, line: { dash: 'dot', width: 1, color: 'rgba(128,128,128,0.5)' } }]
          : [],
        showlegend: showLegend,
        legend: {
          x: 0.98,
          y: 0.02,
          xanchor: 'right',
          yanchor: 'bottom',
          bgcolor: isDark ? 'rgba(30,30,30,0.6)' : 'rgba(255,255,255,0.65)',
          bordercolor: 'rgba(128,128,128,0.3)',
          borderwidth: 1,
        },
        autosize: true,
      },
    };
  }, [rows, config, showAuc, fill, mode, showMarkers, showLegend, markerSize, isDark, theme]);

  // Settings-gear controls (Tier-2). The case switch itself is a visible tab
  // bar above the plot (see below), not hidden here.
  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Switch size="xs" checked={showLegend} onChange={(e) => setShowLegend(e.currentTarget.checked)} label="Legend" />
        <Switch size="xs" checked={showMarkers} onChange={(e) => setShowMarkers(e.currentTarget.checked)} label="Markers" />
        {showMarkers ? (
          <Stack gap={2}>
            <Text size="xs" fw={500}>Marker size</Text>
            <Slider size="xs" min={2} max={14} value={markerSize} onChange={setMarkerSize} />
          </Stack>
        ) : null}
        {mode !== 'threshold' ? (
          <>
            <Switch size="xs" checked={fill} onChange={(e) => setFill(e.currentTarget.checked)} label="Shade area" />
            <Switch size="xs" checked={showAuc} onChange={(e) => setShowAuc(e.currentTarget.checked)} label="Show AUC" />
          </>
        ) : null}
        {!hasFpr ? (
          <Text size="9px" c="dimmed">
            ROC needs a false-positive-rate column (true negatives) — absent here, so only PR / threshold are shown.
          </Text>
        ) : null}
      </Stack>
    ),
    [fill, showAuc, mode, showMarkers, showLegend, markerSize, hasFpr],
  );

  // Visible case-switch tabs at the top of the panel.
  const caseTabs = useMemo(
    () => (
      <SegmentedControl
        fullWidth
        size="xs"
        value={mode}
        onChange={(v) => setMode(v as 'pr' | 'roc' | 'threshold')}
        data={[
          { label: 'PR curve', value: 'pr' },
          { label: 'ROC', value: 'roc', disabled: !hasFpr },
          { label: 'vs threshold', value: 'threshold', disabled: !hasThreshold },
        ]}
      />
    ),
    [mode, hasFpr, hasThreshold],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'ROC / PR curve'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      <Stack gap={4} style={{ width: '100%', height: '100%' }}>
        {caseTabs}
        <div style={{ flex: 1, minHeight: 0 }}>
          {figure ? (
            <Plot
              data={applyDataTheme(figure.data, isDark, theme) as any}
              layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
              useResizeHandler
              style={{ width: '100%', height: '100%' }}
              config={{ displaylogo: false, responsive: true } as any}
            />
          ) : null}
        </div>
      </Stack>
    </AdvancedVizFrame>
  );
};

export default RocPrCurveRenderer;
