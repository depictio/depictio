import React, { useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Select,
  Stack,
  Switch,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { stableColorMap } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

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
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as StackedTaxonomyConfig;

  const [rank, setRank] = useState<string | null>(config.default_rank ?? null);
  const [topN, setTopN] = useState<number>(config.top_n ?? 20);
  const [normalise, setNormalise] = useState<boolean>(config.normalise_to_one ?? true);
  type SampleSort = 'input' | 'total_abundance' | 'first_taxon';
  const [sampleSort, setSampleSort] = useState<SampleSort>('input');
  const [showLegend, setShowLegend] = useState<boolean>(true);
  const [logY, setLogY] = useState<boolean>(false);

  // Stable taxon→colour universe so a habitat filter doesn't shuffle the
  // top-N taxon colours. Pulled from the DC's unique values for taxon_col;
  // falls back to the filtered ordering when the endpoint is slow/errors.
  const [taxonUniverse, setTaxonUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id || !config.taxon_col) {
      setTaxonUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.taxon_col)
      .then((values) => {
        if (!cancelled) setTaxonUniverse(values);
      })
      .catch(() => {
        /* best-effort — colours stay reactive to the current filter */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.taxon_col]);

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

    // Sort samples by the user's choice. `input` preserves insertion order
    // (Map preserves insertion order, so just spread the keys); `total_abundance`
    // sorts descending by per-sample sum; `first_taxon` sorts descending by
    // the most-abundant taxon's value per sample so the most-abundant cohort
    // forms a clear left-to-right gradient.
    const topTaxaSorted = Array.from(taxonTotals.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t);
    const firstTaxon = topTaxaSorted[0];
    const sampleKeys = Array.from(cellTotals.keys());
    const orderedSamples = (() => {
      if (sampleSort === 'input') return sampleKeys;
      const score = (s: string): number => {
        const inner = cellTotals.get(s) || new Map();
        if (sampleSort === 'first_taxon' && firstTaxon) return inner.get(firstTaxon) || 0;
        let total = 0;
        for (const v of inner.values()) total += v;
        return total;
      };
      return [...sampleKeys].sort((a, b) => score(b) - score(a));
    })();

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

    // Stable taxon→colour map so filtering (e.g. by habitat) doesn't reshuffle
    // the top-N colours. Universe = all taxa in the DC; fallback = the filtered
    // top-N set ordered as they appear in tracesByTaxon.
    const taxaForPalette = Array.from(tracesByTaxon.keys()).filter((t) => t !== 'Other');
    const colourSource = stableColorMap(taxonUniverse ?? taxaForPalette, PALETTE);
    const data = Array.from(tracesByTaxon.entries())
      .filter(([, arr]) => arr.some((v) => v > 0))
      .map(([t, arr]) => ({
        type: 'bar' as const,
        name: t,
        x: orderedSamples,
        y: arr,
        marker: { color: t === 'Other' ? '#adb5bd' : colourSource.get(t) },
      }));

    return {
      figure: {
        data,
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          barmode: 'stack' as const,
          margin: { l: 60, r: 20, t: 30, b: 70 },
          xaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            title: { text: config.sample_id_col },
            tickangle: -45,
          },
          // When normalise is ON we lock the y-axis to [0, 1] and format ticks
          // as percentages — this gives the toggle a visible effect even when
          // the input data is already pre-normalised (the old behaviour: both
          // toggle states rendered identically because each sample already
          // summed to 1).
          yaxis: normalise
            ? {
                ...plotlyAxisOverrides(isDark, theme),
                title: { text: 'Relative abundance' },
                range: [0, 1],
                tickformat: '.0%',
              }
            : {
                ...plotlyAxisOverrides(isDark, theme),
                title: { text: config.abundance_col },
                // Log y is only meaningful for raw counts — normalised data
                // is bounded [0,1] and log would compress to noise.
                ...(logY ? { type: 'log' as const } : {}),
              },
          showlegend: showLegend,
          legend: { orientation: 'h', y: -0.25 },
          autosize: true,
        },
      },
      allRanks,
    };
  }, [rows, config, rank, topN, normalise, sampleSort, showLegend, logY, isDark, theme, taxonUniverse]);

  const controls = (
    <Stack gap="xs">
      <Select
        size="xs"
        label="Rank"
        value={rank}
        onChange={setRank}
        data={allRanks}
        clearable
      />
      <Select
        size="xs"
        label="Sort samples"
        value={sampleSort}
        onChange={(v) => v && setSampleSort(v as SampleSort)}
        data={[
          { value: 'input', label: 'Input order' },
          { value: 'total_abundance', label: 'Total abundance' },
          { value: 'first_taxon', label: 'Top taxon' },
        ]}
        allowDeselect={false}
      />
      <NumberInput
        size="xs"
        label="Top-N taxa"
        value={topN}
        onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
        min={1}
        max={50}
      />
      <Switch
        size="xs"
        checked={normalise}
        onChange={(e) => setNormalise(e.currentTarget.checked)}
        label="Normalise"
      />
      <Switch
        size="xs"
        checked={showLegend}
        onChange={(e) => setShowLegend(e.currentTarget.checked)}
        label="Legend"
      />
      {!normalise ? (
        <Switch
          size="xs"
          checked={logY}
          onChange={(e) => setLogY(e.currentTarget.checked)}
          label="Log y"
        />
      ) : null}
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Stacked taxonomy'}
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
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default StackedTaxonomyRenderer;
