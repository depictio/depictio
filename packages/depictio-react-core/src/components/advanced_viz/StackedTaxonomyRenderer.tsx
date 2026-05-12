import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  NumberInput,
  Select,
  Switch,
  useMantineColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

interface StackedTaxonomyConfig {
  sample_id_col: string;
  taxon_col: string;
  rank_col: string;
  abundance_col: string;
  default_rank?: string | null;
  top_n?: number;
  sort_by?: 'abundance' | 'alphabetical';
  normalise_to_one?: boolean;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: StackedTaxonomyConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const PALETTE = [
  '#1c7ed6', '#e64980', '#fab005', '#37b24d', '#7048e8', '#f76707',
  '#0ca678', '#d6336c', '#15aabf', '#fd7e14', '#82c91e', '#ae3ec9',
];

const StackedTaxonomyRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const config = (metadata.config || {}) as StackedTaxonomyConfig;

  const [rank, setRank] = useState<string | null>(config.default_rank ?? null);
  const [topN, setTopN] = useState<number>(config.top_n ?? 20);
  const [normalise, setNormalise] = useState<boolean>(config.normalise_to_one ?? true);

  const requiredCols = useMemo(
    () => [
      config.sample_id_col,
      config.taxon_col,
      config.rank_col,
      config.abundance_col,
    ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Stacked taxonomy: missing data binding');
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

  const { figure, allRanks } = useMemo(() => {
    if (!rows) return { figure: null, allRanks: [] as string[] };
    const samples = (rows[config.sample_id_col] || []).map((v) => String(v ?? '')) as string[];
    const taxa = (rows[config.taxon_col] || []).map((v) => String(v ?? '')) as string[];
    const ranks = (rows[config.rank_col] || []).map((v) => String(v ?? '')) as string[];
    const ab = (rows[config.abundance_col] || []) as number[];

    const allRanks = Array.from(new Set(ranks));
    const activeRank = rank || allRanks[0] || null;

    // Filter to active rank, then aggregate (sample × taxon → abundance).
    const cellTotals = new Map<string, Map<string, number>>(); // sample -> taxon -> abundance
    for (let i = 0; i < samples.length; i++) {
      if (activeRank && ranks[i] !== activeRank) continue;
      const s = samples[i];
      const t = taxa[i];
      const v = Number(ab[i]) || 0;
      if (!cellTotals.has(s)) cellTotals.set(s, new Map());
      const inner = cellTotals.get(s)!;
      inner.set(t, (inner.get(t) || 0) + v);
    }

    // Rank taxa by total abundance and keep top-N; lump others into "Other".
    const taxonTotals = new Map<string, number>();
    for (const inner of cellTotals.values()) {
      for (const [t, v] of inner.entries()) {
        taxonTotals.set(t, (taxonTotals.get(t) || 0) + v);
      }
    }
    const topTaxa = Array.from(taxonTotals.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, topN)
      .map(([t]) => t);
    const topSet = new Set(topTaxa);

    const orderedSamples = Array.from(cellTotals.keys()).sort();

    const tracesByTaxon = new Map<string, number[]>();
    for (const t of [...topTaxa, 'Other']) tracesByTaxon.set(t, orderedSamples.map(() => 0));

    orderedSamples.forEach((s, sIdx) => {
      const inner = cellTotals.get(s) || new Map();
      let total = 0;
      for (const v of inner.values()) total += v;
      for (const [t, v] of inner.entries()) {
        const bucket = topSet.has(t) ? t : 'Other';
        const arr = tracesByTaxon.get(bucket)!;
        arr[sIdx] += normalise && total > 0 ? v / total : v;
      }
    });

    const data = Array.from(tracesByTaxon.entries())
      .filter(([, arr]) => arr.some((v) => v > 0))
      .map(([t, arr], i) => ({
        type: 'bar' as const,
        name: t,
        x: orderedSamples,
        y: arr,
        marker: { color: t === 'Other' ? '#adb5bd' : PALETTE[i % PALETTE.length] },
      }));

    return {
      figure: {
        data,
        layout: {
          template: colorScheme === 'dark' ? 'plotly_dark' : 'plotly_white',
          barmode: 'stack' as const,
          margin: { l: 50, r: 20, t: 30, b: 70 },
          xaxis: { title: { text: config.sample_id_col }, tickangle: -45 },
          yaxis: {
            title: { text: normalise ? 'Relative abundance' : config.abundance_col },
          },
          showlegend: true,
          legend: { orientation: 'h', y: -0.25 },
          autosize: true,
        },
      },
      allRanks,
    };
  }, [rows, config, rank, topN, normalise, colorScheme]);

  const controls = (
    <Group gap="xs" wrap="wrap">
      <Select
        size="xs"
        label="Rank"
        value={rank}
        onChange={setRank}
        data={allRanks}
        clearable
        w={130}
      />
      <NumberInput
        size="xs"
        label="Top-N taxa"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
        min={1}
        max={50}
        w={110}
      />
      <Switch
        size="xs"
        checked={normalise}
        onChange={(e) => setNormalise(e.currentTarget.checked)}
        label="Normalise"
      />
    </Group>
  );

  return (
    <AdvancedVizFrame
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
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

export default StackedTaxonomyRenderer;
