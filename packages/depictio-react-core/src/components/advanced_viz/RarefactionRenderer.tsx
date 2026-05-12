import React, { useEffect, useMemo, useState } from 'react';
import { Group, NumberInput, Select, Stack, Switch, useMantineColorScheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface RarefactionConfig {
  sample_id_col: string;
  depth_col: string;
  metric_col: string;
  iter_col?: string | null;
  group_col?: string | null;
  show_ci?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RarefactionConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// Same scanpy / matplotlib tab10 palette used by EmbeddingRenderer so grouped
// curves match the colour scheme of other viz in the same dashboard.
const PALETTE = [
  '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
];

const RarefactionRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as RarefactionConfig;
  const isDark = colorScheme === 'dark';

  const [showCI, setShowCI] = useState<boolean>(config.show_ci ?? true);
  const [topN, setTopN] = useState<number>(60);
  const [groupBy, setGroupBy] = useState<string | null>(config.group_col ?? null);

  const requiredCols = useMemo(() => {
    const cols = [config.sample_id_col, config.depth_col, config.metric_col].filter(Boolean) as string[];
    if (config.iter_col) cols.push(config.iter_col);
    if (config.group_col && !cols.includes(config.group_col)) cols.push(config.group_col);
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Rarefaction: missing data binding');
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

    const sampleIds = (rows[config.sample_id_col] || []) as (string | number)[];
    const depths = (rows[config.depth_col] || []) as number[];
    const metrics = (rows[config.metric_col] || []) as number[];
    const groups = groupBy ? (rows[groupBy] as (string | number)[]) : null;

    // Aggregate (sample, depth) → mean + std over iter. Without iter we still
    // collapse by (sample, depth) in case multiple rows per pair exist.
    type Acc = { sum: number; sumSq: number; n: number };
    const perSample = new Map<string, Map<number, Acc>>();
    const sampleGroup = new Map<string, string>();
    for (let i = 0; i < sampleIds.length; i++) {
      const sid = String(sampleIds[i] ?? '');
      const d = Number(depths[i]);
      const v = Number(metrics[i]);
      if (!Number.isFinite(d) || !Number.isFinite(v)) continue;
      let byDepth = perSample.get(sid);
      if (!byDepth) {
        byDepth = new Map();
        perSample.set(sid, byDepth);
      }
      const acc = byDepth.get(d) ?? { sum: 0, sumSq: 0, n: 0 };
      acc.sum += v;
      acc.sumSq += v * v;
      acc.n += 1;
      byDepth.set(d, acc);
      if (groups) sampleGroup.set(sid, String(groups[i] ?? ''));
    }

    // Limit to top-N samples (in display order) so the legend stays usable.
    const samples = Array.from(perSample.keys()).slice(0, topN);

    // Build group→colour mapping for legend consistency.
    const uniqGroups: string[] = [];
    if (groups) {
      for (const s of samples) {
        const g = sampleGroup.get(s) ?? '—';
        if (!uniqGroups.includes(g)) uniqGroups.push(g);
      }
      uniqGroups.sort();
    }
    const colourForGroup = new Map<string, string>(
      uniqGroups.map((g, i) => [g, PALETTE[i % PALETTE.length]]),
    );
    const seenGroupInLegend = new Set<string>();

    const traces: any[] = [];
    for (let i = 0; i < samples.length; i++) {
      const sid = samples[i];
      const byDepth = perSample.get(sid)!;
      const ds = Array.from(byDepth.keys()).sort((a, b) => a - b);
      const means: number[] = [];
      const ses: number[] = [];
      for (const d of ds) {
        const a = byDepth.get(d)!;
        const m = a.sum / a.n;
        const variance = Math.max(0, a.sumSq / a.n - m * m);
        const se = a.n > 1 ? Math.sqrt(variance / a.n) : 0;
        means.push(m);
        ses.push(se);
      }
      const group = groups ? sampleGroup.get(sid) ?? '—' : sid;
      const colour = groups
        ? colourForGroup.get(group)!
        : PALETTE[i % PALETTE.length];
      const legendName = groups ? group : String(sid);
      const showInLegend = !groups || !seenGroupInLegend.has(group);
      if (showInLegend && groups) seenGroupInLegend.add(group);

      if (showCI && ses.some((v) => v > 0)) {
        const upper = means.map((m, k) => m + ses[k]);
        const lower = means.map((m, k) => m - ses[k]);
        traces.push({
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: [...ds, ...ds.slice().reverse()],
          y: [...upper, ...lower.slice().reverse()],
          line: { width: 0 },
          fill: 'toself',
          fillcolor: colour.replace(')', ', 0.12)').replace('rgb', 'rgba'),
          hoverinfo: 'skip',
          showlegend: false,
        });
      }

      traces.push({
        type: 'scatter' as const,
        mode: 'lines+markers' as const,
        x: ds,
        y: means,
        name: legendName,
        legendgroup: legendName,
        showlegend: showInLegend,
        line: { color: colour, width: 1.8 },
        marker: { size: 4, color: colour },
        hovertemplate: `<b>${String(sid)}</b><br>${config.depth_col}: %{x}<br>${config.metric_col}: %{y:.3f}<extra></extra>`,
      });
    }

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 56, r: 16, t: 16, b: 48 },
        xaxis: { title: { text: config.depth_col }, zeroline: false },
        yaxis: { title: { text: config.metric_col }, zeroline: false },
        showlegend: true,
        legend: { orientation: 'v', x: 1.02, y: 1, font: { size: 10 } },
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      },
    };
  }, [rows, config, isDark, showCI, topN, groupBy]);

  // Discover group/metric options from the rows once they arrive.
  const groupOptions = useMemo(() => {
    if (!rows) return [] as { value: string; label: string }[];
    const out: { value: string; label: string }[] = [];
    for (const c of Object.keys(rows)) {
      if (c === config.sample_id_col || c === config.depth_col || c === config.metric_col)
        continue;
      out.push({ value: c, label: c });
    }
    return out;
  }, [rows, config]);

  const controls = (
    <Stack gap="xs">
      {groupOptions.length > 0 ? (
        <Select
          size="xs"
          label="Group by"
          value={groupBy}
          onChange={setGroupBy}
          data={groupOptions}
          clearable
          description="Colour curves by metadata column"
        />
      ) : null}
      <Group gap="xs" grow>
        <NumberInput
          size="xs"
          label="Top-N samples"
          value={topN}
          onChange={(v) => setTopN(Math.max(1, Number(v) || 60))}
          min={1}
          max={200}
        />
      </Group>
      <Switch
        size="xs"
        checked={showCI}
        onChange={(e) => setShowCI(e.currentTarget.checked)}
        label="±SE band"
      />
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Rarefaction curves'}
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

export default RarefactionRenderer;
