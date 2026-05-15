import React, { useEffect, useMemo, useState } from 'react';
import { Stack, Switch, useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';

interface OncoplotConfig {
  sample_id_col: string;
  gene_col: string;
  mutation_type_col: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: OncoplotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const OncoplotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as OncoplotConfig;

  const [sortByFreq, setSortByFreq] = useState<boolean>(true);

  const requiredCols = useMemo(
    () =>
      [config.sample_id_col, config.gene_col, config.mutation_type_col].filter(
        Boolean,
      ) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [mutationUniverse, setMutationUniverse] = useState<string[] | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Oncoplot: missing data binding');
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

  useEffect(() => {
    if (!metadata.dc_id || !config.mutation_type_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.mutation_type_col)
      .then((v) => !cancelled && setMutationUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.mutation_type_col]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const samples = (rows[config.sample_id_col] || []) as (string | number)[];
    const genes = (rows[config.gene_col] || []) as (string | number)[];
    const muts = (rows[config.mutation_type_col] || []) as (string | number)[];

    const sampleList = Array.from(new Set(samples.map(String)));
    const geneList = Array.from(new Set(genes.map(String)));
    const mutList = Array.from(new Set(muts.map(String)));

    // Per-gene and per-sample mutation count for axis ordering + strips.
    const geneCount: Record<string, number> = {};
    const sampleCount: Record<string, number> = {};
    for (let i = 0; i < samples.length; i++) {
      const g = String(genes[i]);
      const s = String(samples[i]);
      geneCount[g] = (geneCount[g] || 0) + 1;
      sampleCount[s] = (sampleCount[s] || 0) + 1;
    }

    const orderedGenes = sortByFreq
      ? [...geneList].sort((a, b) => (geneCount[b] || 0) - (geneCount[a] || 0))
      : [...geneList].sort();
    const orderedSamples = sortByFreq
      ? [...sampleList].sort((a, b) => (sampleCount[b] || 0) - (sampleCount[a] || 0))
      : [...sampleList].sort();

    // Cell colour from stable mutation-type palette. Background is NaN so
    // missing cells stay blank — plotly skips them in the heatmap.
    const colourSource = stableColorMap(mutationUniverse ?? mutList, TAB10_PALETTE);
    const mutToIdx = new Map<string, number>();
    mutList.forEach((m, i) => mutToIdx.set(m, i));

    // Build a discrete colourscale from the stable palette.
    const colorscale: [number, string][] = [];
    const n = mutList.length || 1;
    for (let i = 0; i < n; i++) {
      const lo = i / n;
      const hi = (i + 1) / n;
      const colour = colourSource.get(mutList[i]) ?? '#888';
      colorscale.push([lo, colour]);
      colorscale.push([hi, colour]);
    }

    // Matrix: rows = genes, cols = samples. Cell = mutation-type index.
    const matrix: (number | null)[][] = orderedGenes.map(() =>
      orderedSamples.map(() => null),
    );
    const textMatrix: string[][] = orderedGenes.map(() => orderedSamples.map(() => ''));
    const geneIdx = new Map<string, number>(orderedGenes.map((g, i) => [g, i]));
    const sampleIdx = new Map<string, number>(orderedSamples.map((s, i) => [s, i]));
    for (let i = 0; i < samples.length; i++) {
      const g = String(genes[i]);
      const s = String(samples[i]);
      const m = String(muts[i]);
      const gi = geneIdx.get(g);
      const si = sampleIdx.get(s);
      const mi = mutToIdx.get(m);
      if (gi == null || si == null || mi == null) continue;
      matrix[gi][si] = mi + 0.5;
      textMatrix[gi][si] = m;
    }

    return {
      data: [
        // Main heatmap on a 4-row × 4-col layout. Bottom-left (xaxis=x,
        // yaxis=y) is the matrix; xaxis2 (top) is per-sample mutation
        // count; yaxis2 (right) is per-gene mutation count.
        {
          type: 'heatmap' as const,
          x: orderedSamples,
          y: orderedGenes,
          z: matrix,
          text: textMatrix,
          xgap: 1,
          ygap: 1,
          colorscale,
          zmin: 0,
          zmax: n,
          showscale: false,
          hovertemplate: `<b>%{y}</b> in <b>%{x}</b><br>%{text}<extra></extra>`,
        },
        {
          type: 'bar' as const,
          orientation: 'v' as const,
          x: orderedSamples,
          y: orderedSamples.map((s) => sampleCount[s] || 0),
          xaxis: 'x',
          yaxis: 'y2',
          marker: { color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' },
          hovertemplate: `<b>%{x}</b>: %{y} mutations<extra></extra>`,
          showlegend: false,
        },
        {
          type: 'bar' as const,
          orientation: 'h' as const,
          y: orderedGenes,
          x: orderedGenes.map((g) => geneCount[g] || 0),
          xaxis: 'x2',
          yaxis: 'y',
          marker: { color: isDark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.7)' },
          hovertemplate: `<b>%{y}</b>: %{x} mutations<extra></extra>`,
          showlegend: false,
        },
        // Discrete legend rendered via dummy scatter traces — one per
        // mutation type. Their markers carry the palette colour, so plotly
        // builds a real legend the user can use as a colour key.
        ...mutList.map((m) => ({
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: [null],
          y: [null],
          name: m,
          marker: { color: colourSource.get(m), size: 10 },
          showlegend: true,
          hoverinfo: 'skip' as const,
        })),
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 100, r: 100, t: 50, b: 100 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          domain: [0, 0.85],
          tickangle: -45,
          title: { text: config.sample_id_col, standoff: 12 },
          showgrid: false,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          domain: [0, 0.85],
          title: { text: config.gene_col },
          showgrid: false,
        },
        xaxis2: {
          ...plotlyAxisOverrides(isDark, theme),
          domain: [0.86, 1],
          showgrid: false,
          zeroline: false,
          anchor: 'y' as const,
        },
        yaxis2: {
          ...plotlyAxisOverrides(isDark, theme),
          domain: [0.86, 1],
          showgrid: false,
          zeroline: false,
          anchor: 'x' as const,
        },
        legend: {
          orientation: 'h' as const,
          y: -0.2,
          font: { color: plotlyThemeColors(isDark, theme).textColor },
          bgcolor: 'rgba(0,0,0,0)',
        },
        autosize: true,
      },
    };
  }, [rows, config, sortByFreq, colorScheme, theme, mutationUniverse]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Switch
          size="xs"
          checked={sortByFreq}
          onChange={(e) => setSortByFreq(e.currentTarget.checked)}
          label="Sort by mutation frequency"
        />
      </Stack>
    ),
    [sortByFreq],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Oncoplot'}
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

export default OncoplotRenderer;
