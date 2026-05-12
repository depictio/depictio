import React, { useEffect, useMemo, useState } from 'react';
import { NumberInput, Select, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface ANCOMBCDifferentialsConfig {
  feature_id_col: string;
  contrast_col: string;
  lfc_col: string;
  significance_col: string;
  label_col?: string | null;
  significance_threshold?: number;
  top_n?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ANCOMBCDifferentialsConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const POSITIVE = '#1f77b4'; // up-regulated
const NEGATIVE = '#d62728'; // down-regulated
const FADED = 'rgba(127,127,127,0.45)';

const ANCOMBCDifferentialsRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as ANCOMBCDifferentialsConfig;
  const isDark = colorScheme === 'dark';

  const [topN, setTopN] = useState<number>(config.top_n ?? 25);
  const [sigThreshold, setSigThreshold] = useState<number>(config.significance_threshold ?? 0.05);
  const [selectedContrast, setSelectedContrast] = useState<string | null>(null);

  const requiredCols = useMemo(() => {
    const cols = [
      config.feature_id_col,
      config.contrast_col,
      config.lfc_col,
      config.significance_col,
    ].filter(Boolean) as string[];
    if (config.label_col && !cols.includes(config.label_col)) cols.push(config.label_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('ANCOM-BC differentials: missing data binding');
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

  const contrasts = useMemo(() => {
    if (!rows) return [] as string[];
    const seen = new Set<string>();
    for (const v of (rows[config.contrast_col] || []) as unknown[]) {
      seen.add(String(v ?? ''));
    }
    return Array.from(seen).sort();
  }, [rows, config.contrast_col]);

  // Default the contrast selector to the first one when data arrives.
  useEffect(() => {
    if (selectedContrast == null && contrasts.length > 0) setSelectedContrast(contrasts[0]);
  }, [contrasts, selectedContrast]);

  const figure = useMemo(() => {
    if (!rows || !selectedContrast) return null;

    const feats = (rows[config.feature_id_col] || []) as (string | number)[];
    const contrastsArr = (rows[config.contrast_col] || []) as (string | number)[];
    const lfcs = (rows[config.lfc_col] || []) as number[];
    const sigs = (rows[config.significance_col] || []) as number[];
    const labels = config.label_col ? (rows[config.label_col] as (string | number)[]) : null;

    // Filter to the selected contrast, then take top-N by |lfc|.
    type Row = { feat: string; label: string; lfc: number; sig: number };
    const rowsForContrast: Row[] = [];
    for (let i = 0; i < feats.length; i++) {
      if (String(contrastsArr[i] ?? '') !== selectedContrast) continue;
      const lfc = Number(lfcs[i]);
      const sig = Number(sigs[i]);
      if (!Number.isFinite(lfc)) continue;
      rowsForContrast.push({
        feat: String(feats[i] ?? ''),
        label: labels ? String(labels[i] ?? '') : String(feats[i] ?? ''),
        lfc,
        sig: Number.isFinite(sig) ? sig : 1,
      });
    }
    rowsForContrast.sort((a, b) => Math.abs(b.lfc) - Math.abs(a.lfc));
    const top = rowsForContrast.slice(0, topN);
    // Sort displayed bars ascending by lfc so positive features stack at the top.
    top.sort((a, b) => a.lfc - b.lfc);

    const xs = top.map((r) => r.lfc);
    const ys = top.map((r, i) => `${i}__${r.label}`); // unique key for plotly
    const tickvals = ys;
    const ticktext = top.map((r) => r.label);
    const colours = top.map((r) =>
      r.sig <= sigThreshold ? (r.lfc >= 0 ? POSITIVE : NEGATIVE) : FADED,
    );
    const hover = top.map(
      (r) =>
        `<b>${r.feat}</b><br>${config.lfc_col}: ${r.lfc.toFixed(3)}<br>${config.significance_col}: ${r.sig.toExponential(2)}`,
    );

    return {
      data: [
        {
          type: 'bar' as const,
          orientation: 'h' as const,
          x: xs,
          y: ys,
          text: top.map((r) => r.lfc.toFixed(2)),
          textposition: 'auto' as const,
          marker: { color: colours, line: { width: 0 } },
          hovertemplate: '%{customdata}<extra></extra>',
          customdata: hover,
          showlegend: false,
        },
      ],
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 200, r: 16, t: 24, b: 48 },
        xaxis: {
          title: { text: `${config.lfc_col} (signed)` },
          zeroline: true,
          zerolinecolor: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)',
        },
        yaxis: { tickmode: 'array', tickvals, ticktext, automargin: true },
        shapes: [
          {
            type: 'line',
            x0: 0,
            x1: 0,
            yref: 'paper',
            y0: 0,
            y1: 1,
            line: { color: isDark ? 'rgba(255,255,255,0.4)' : 'rgba(0,0,0,0.4)', width: 1 },
          },
        ],
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      },
    };
  }, [rows, selectedContrast, topN, sigThreshold, config, isDark]);

  const controls = (
    <Stack gap="xs">
      <Select
        size="xs"
        label="Contrast"
        value={selectedContrast}
        onChange={setSelectedContrast}
        data={contrasts.map((c) => ({ value: c, label: c }))}
        disabled={contrasts.length === 0}
      />
      <NumberInput
        size="xs"
        label="Top-N features"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 25))}
        min={1}
        max={200}
      />
      <NumberInput
        size="xs"
        label="Significance threshold"
        description="Bars with significance > threshold are greyed out"
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
      title={metadata.title || 'ANCOM-BC differentials'}
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

export default ANCOMBCDifferentialsRenderer;
