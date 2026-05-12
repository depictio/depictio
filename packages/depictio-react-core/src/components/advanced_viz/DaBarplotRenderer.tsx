import React, { useEffect, useMemo, useState } from 'react';
import { NumberInput, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface DaBarplotConfig {
  feature_id_col: string;
  contrast_col: string;
  lfc_col: string;
  significance_col?: string | null;
  label_col?: string | null;
  significance_threshold?: number;
  top_n?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DaBarplotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const POSITIVE = '#1f77b4';
const NEGATIVE = '#d62728';
const FADED = 'rgba(127,127,127,0.45)';

const DaBarplotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as DaBarplotConfig;
  const isDark = colorScheme === 'dark';

  const [topN, setTopN] = useState<number>(config.top_n ?? 15);
  const [sigThreshold, setSigThreshold] = useState<number>(config.significance_threshold ?? 0.05);

  const requiredCols = useMemo(() => {
    const cols = [config.feature_id_col, config.contrast_col, config.lfc_col].filter(Boolean) as string[];
    if (config.significance_col && !cols.includes(config.significance_col))
      cols.push(config.significance_col);
    if (config.label_col && !cols.includes(config.label_col)) cols.push(config.label_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('DA barplot: missing data binding');
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

    const feats = (rows[config.feature_id_col] || []) as (string | number)[];
    const contrasts = (rows[config.contrast_col] || []) as (string | number)[];
    const lfcs = (rows[config.lfc_col] || []) as number[];
    const sigs = config.significance_col
      ? ((rows[config.significance_col] || []) as number[])
      : null;
    const labels = config.label_col ? (rows[config.label_col] as (string | number)[]) : null;

    type Row = { feat: string; label: string; lfc: number; sig: number };
    const byContrast = new Map<string, Row[]>();
    for (let i = 0; i < feats.length; i++) {
      const c = String(contrasts[i] ?? '');
      const lfc = Number(lfcs[i]);
      if (!Number.isFinite(lfc)) continue;
      const sig = sigs ? Number(sigs[i]) : 1;
      const r: Row = {
        feat: String(feats[i] ?? ''),
        label: labels ? String(labels[i] ?? '') : String(feats[i] ?? ''),
        lfc,
        sig: Number.isFinite(sig) ? sig : 1,
      };
      const arr = byContrast.get(c) ?? [];
      arr.push(r);
      byContrast.set(c, arr);
    }
    const contrastNames = Array.from(byContrast.keys()).sort();
    if (contrastNames.length === 0) return null;

    // One sub-plot per contrast in an xN grid. Plotly's facet support via
    // subplots is verbose but the small fixture (≤ 4 contrasts) keeps it
    // tractable.
    const cols = Math.min(2, contrastNames.length);
    const rowsCount = Math.ceil(contrastNames.length / cols);

    const data: any[] = [];
    const annotations: any[] = [];
    const layoutAxes: Record<string, any> = {};

    contrastNames.forEach((c, idx) => {
      const all = byContrast.get(c)!;
      all.sort((a, b) => Math.abs(b.lfc) - Math.abs(a.lfc));
      const top = all.slice(0, topN);
      top.sort((a, b) => a.lfc - b.lfc);
      const colour = top.map((r) =>
        r.sig <= sigThreshold ? (r.lfc >= 0 ? POSITIVE : NEGATIVE) : FADED,
      );
      const xaxis = idx === 0 ? 'x' : `x${idx + 1}`;
      const yaxis = idx === 0 ? 'y' : `y${idx + 1}`;
      data.push({
        type: 'bar' as const,
        orientation: 'h' as const,
        x: top.map((r) => r.lfc),
        y: top.map((r, i) => `${idx}-${i}-${r.label}`),
        text: top.map((r) => r.label),
        textposition: 'auto' as const,
        insidetextanchor: 'start',
        marker: { color: colour, line: { width: 0 } },
        hovertemplate: `<b>%{text}</b><br>${config.lfc_col}: %{x:.3f}<extra></extra>`,
        showlegend: false,
        xaxis,
        yaxis,
      });
      const rowIdx = Math.floor(idx / cols);
      const colIdx = idx % cols;
      const xPaper = (colIdx + 0.5) / cols;
      const yPaper = 1 - rowIdx / rowsCount;
      annotations.push({
        text: `<b>${c}</b>`,
        x: xPaper,
        y: yPaper - 0.02,
        xref: 'paper',
        yref: 'paper',
        xanchor: 'center',
        showarrow: false,
        font: { size: 11 },
      });
    });

    return {
      data,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 8, r: 8, t: 28, b: 36 },
        grid: { rows: rowsCount, columns: cols, pattern: 'independent' as const },
        annotations,
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
        ...layoutAxes,
      },
    };
  }, [rows, topN, sigThreshold, config, isDark]);

  const controls = (
    <Stack gap="xs">
      <NumberInput
        size="xs"
        label="Top-N per contrast"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 15))}
        min={1}
        max={50}
      />
      <NumberInput
        size="xs"
        label="Significance threshold"
        value={sigThreshold}
        onChange={(v) => setSigThreshold(Math.max(0, Math.min(1, Number(v) || 0.05)))}
        min={0}
        max={1}
        step={0.01}
        decimalScale={3}
      />
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'DA barplot (per contrast)'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <Plot
          data={figure.data as any}
          layout={figure.layout as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default DaBarplotRenderer;
