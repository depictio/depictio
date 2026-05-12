import React, { useEffect, useMemo, useState } from 'react';
import { MultiSelect, NumberInput, Stack, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface EnrichmentConfig {
  term_col: string;
  nes_col: string;
  padj_col: string;
  gene_count_col: string;
  source_col?: string | null;
  padj_threshold?: number;
  top_n?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: EnrichmentConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const EnrichmentRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as EnrichmentConfig;
  const isDark = colorScheme === 'dark';

  const [topN, setTopN] = useState<number>(config.top_n ?? 20);
  const [padjThreshold, setPadjThreshold] = useState<number>(config.padj_threshold ?? 0.05);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);

  const requiredCols = useMemo(() => {
    const cols = [
      config.term_col,
      config.nes_col,
      config.padj_col,
      config.gene_count_col,
    ].filter(Boolean) as string[];
    if (config.source_col && !cols.includes(config.source_col)) cols.push(config.source_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Enrichment: missing data binding');
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

  const sources = useMemo(() => {
    if (!rows || !config.source_col) return [] as string[];
    const seen = new Set<string>();
    for (const v of (rows[config.source_col] || []) as unknown[]) seen.add(String(v ?? ''));
    return Array.from(seen).sort();
  }, [rows, config.source_col]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const terms = (rows[config.term_col] || []) as (string | number)[];
    const nesArr = (rows[config.nes_col] || []) as number[];
    const padjArr = (rows[config.padj_col] || []) as number[];
    const counts = (rows[config.gene_count_col] || []) as number[];
    const srcArr = config.source_col ? (rows[config.source_col] as (string | number)[]) : null;

    type Row = { term: string; nes: number; padj: number; count: number; src: string };
    const collected: Row[] = [];
    for (let i = 0; i < terms.length; i++) {
      const padj = Number(padjArr[i]);
      const nes = Number(nesArr[i]);
      if (!Number.isFinite(padj) || !Number.isFinite(nes)) continue;
      if (padj > padjThreshold) continue;
      const src = srcArr ? String(srcArr[i] ?? '') : '';
      if (
        selectedSources.length > 0 &&
        srcArr &&
        !selectedSources.includes(src)
      )
        continue;
      collected.push({
        term: String(terms[i] ?? ''),
        nes,
        padj,
        count: Number(counts[i]) || 0,
        src,
      });
    }
    // Top-N by significance (smallest padj wins).
    collected.sort((a, b) => a.padj - b.padj);
    const top = collected.slice(0, topN);
    // Then re-sort by NES ascending so positive NES sits at the top of
    // the y-axis (plotly draws first item at the bottom).
    top.sort((a, b) => a.nes - b.nes);

    if (top.length === 0) {
      return null;
    }

    // Map gene_count → marker size (sqrt scaled, capped).
    const counts2 = top.map((r) => r.count);
    const cMax = Math.max(...counts2, 1);
    const sizes = counts2.map((c) => 6 + Math.sqrt(c / cMax) * 24);
    const neg_log10_padj = top.map((r) => -Math.log10(Math.max(r.padj, 1e-300)));

    return {
      data: [
        {
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: top.map((r) => r.nes),
          y: top.map((r) => r.term),
          customdata: top.map((r) => [r.padj, r.count, r.src]),
          hovertemplate:
            `<b>%{y}</b><br>NES: %{x:.2f}<br>padj: %{customdata[0]:.2e}` +
            `<br>genes: %{customdata[1]}` +
            (config.source_col ? `<br>source: %{customdata[2]}` : '') +
            `<extra></extra>`,
          marker: {
            size: sizes,
            color: neg_log10_padj,
            colorscale: isDark ? 'Plasma' : 'Viridis',
            showscale: true,
            colorbar: {
              title: { text: '-log10(padj)', side: 'right' },
              thickness: 10,
              len: 0.85,
            },
            line: { width: 0 },
          },
        },
      ],
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 220, r: 60, t: 16, b: 48 },
        xaxis: {
          title: { text: 'NES (normalized enrichment score)' },
          zeroline: true,
          zerolinecolor: isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)',
        },
        yaxis: { automargin: true, ticks: '', showgrid: true },
        showlegend: false,
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      },
    };
  }, [rows, config, topN, padjThreshold, selectedSources, isDark]);

  const controls = (
    <Stack gap="xs">
      {sources.length > 0 ? (
        <MultiSelect
          size="xs"
          label="Source"
          value={selectedSources}
          onChange={setSelectedSources}
          data={sources}
          placeholder="all sources"
          clearable
        />
      ) : null}
      <NumberInput
        size="xs"
        label="Top-N pathways"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
        min={1}
        max={100}
      />
      <NumberInput
        size="xs"
        label="padj threshold"
        description="Hide pathways with padj above this cutoff"
        value={padjThreshold}
        onChange={(v) => setPadjThreshold(Math.max(0, Math.min(1, Number(v) || 0.05)))}
        min={0}
        max={1}
        step={0.01}
        decimalScale={3}
      />
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Pathway enrichment'}
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

export default EnrichmentRenderer;
