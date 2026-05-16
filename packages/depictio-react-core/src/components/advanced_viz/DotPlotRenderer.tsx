import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
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
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';

interface DotPlotConfig {
  cluster_col: string;
  gene_col: string;
  mean_expression_col: string;
  frac_expressing_col: string;
  max_dot_size?: number;
  min_dot_size?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: DotPlotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

type ColourScale = 'Viridis' | 'Plasma' | 'Inferno' | 'Cividis' | 'Magma' | 'RdBu' | 'Spectral';
type AxisSort = 'name' | 'mean' | 'frac';

const DotPlotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as DotPlotConfig;

  const [maxSize, setMaxSize] = useState<number>(config.max_dot_size ?? 22);
  const [minSize, setMinSize] = useState<number>(config.min_dot_size ?? 2);
  const [reverseScale, setReverseScale] = useState<boolean>(false);
  const [colourScale, setColourScale] = useState<ColourScale>('Viridis');
  const [logTransform, setLogTransform] = useState<boolean>(false);
  const [geneSort, setGeneSort] = useState<AxisSort>('name');
  const [clusterSort, setClusterSort] = useState<AxisSort>('name');
  const [annotateTopN, setAnnotateTopN] = useState<number>(0);
  const [markerOutline, setMarkerOutline] = useState<boolean>(true);

  const requiredCols = useMemo(
    () =>
      [
        config.cluster_col,
        config.gene_col,
        config.mean_expression_col,
        config.frac_expressing_col,
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [clusterUniverse, setClusterUniverse] = useState<string[] | null>(null);
  const [geneUniverse, setGeneUniverse] = useState<string[] | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Dot plot: missing data binding');
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
    if (!metadata.dc_id || !config.cluster_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.cluster_col)
      .then((v) => !cancelled && setClusterUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.cluster_col]);

  useEffect(() => {
    if (!metadata.dc_id || !config.gene_col) return;
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.gene_col)
      .then((v) => !cancelled && setGeneUniverse(v))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.gene_col]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const clusterVals = (rows[config.cluster_col] || []) as (string | number)[];
    const geneVals = (rows[config.gene_col] || []) as (string | number)[];
    const meanRaw = (rows[config.mean_expression_col] || []) as number[];
    const fracVals = (rows[config.frac_expressing_col] || []) as number[];

    const meanVals = logTransform
      ? meanRaw.map((v) => Math.log10(Math.max(0, Number(v) || 0) + 1))
      : meanRaw.map((v) => Number(v) || 0);

    const clustersInData = Array.from(new Set(clusterVals.map(String)));
    const genesInData = Array.from(new Set(geneVals.map(String)));

    // Per-axis aggregation for the "mean" / "frac" sort orders.
    const axisAgg = (key: 'cluster' | 'gene', metric: 'mean' | 'frac'): Map<string, number> => {
      const agg = new Map<string, { sum: number; n: number }>();
      for (let i = 0; i < clusterVals.length; i++) {
        const k = key === 'cluster' ? String(clusterVals[i]) : String(geneVals[i]);
        const v = metric === 'mean' ? meanVals[i] : Math.max(0, Math.min(1, Number(fracVals[i]) || 0));
        const a = agg.get(k) ?? { sum: 0, n: 0 };
        a.sum += v;
        a.n += 1;
        agg.set(k, a);
      }
      const out = new Map<string, number>();
      agg.forEach((v, k) => out.set(k, v.n === 0 ? 0 : v.sum / v.n));
      return out;
    };

    const sortAxis = (
      members: string[],
      sortKey: AxisSort,
      universe: string[] | null,
      axisKey: 'cluster' | 'gene',
    ): string[] => {
      if (sortKey === 'name') {
        return universe ? universe.filter((c) => members.includes(c)) : [...members].sort();
      }
      const score = axisAgg(axisKey, sortKey === 'mean' ? 'mean' : 'frac');
      return [...members].sort((a, b) => (score.get(b) ?? 0) - (score.get(a) ?? 0));
    };

    const clusters = sortAxis(clustersInData, clusterSort, clusterUniverse, 'cluster');
    const genes = sortAxis(genesInData, geneSort, geneUniverse, 'gene');

    const sizes = fracVals.map((f) => {
      const clamped = Math.max(0, Math.min(1, Number(f) || 0));
      return minSize + clamped * (maxSize - minSize);
    });

    // Annotation overlay: top-N (cluster, gene) cells by frac_expressing.
    const annotations: any[] = [];
    if (annotateTopN > 0) {
      const ranked = fracVals
        .map((f, i) => ({ i, f: Number(f) || 0 }))
        .filter((r) => r.f > 0)
        .sort((a, b) => b.f - a.f)
        .slice(0, annotateTopN);
      for (const r of ranked) {
        annotations.push({
          x: String(clusterVals[r.i] ?? ''),
          y: String(geneVals[r.i] ?? ''),
          text: r.f.toFixed(2),
          showarrow: false,
          font: { size: 9, color: colorScheme === 'dark' ? '#fff' : '#111' },
        });
      }
    }

    const meanLabel = logTransform
      ? `log10(${config.mean_expression_col}+1)`
      : config.mean_expression_col;

    return {
      data: [
        {
          type: 'scatter' as const,
          mode: 'markers' as const,
          x: clusterVals.map(String),
          y: geneVals.map(String),
          customdata: fracVals.map((f, i) => [
            String(geneVals[i] ?? ''),
            String(clusterVals[i] ?? ''),
            Number(f).toFixed(3),
            Number(meanRaw[i]).toFixed(3),
          ]),
          hovertemplate:
            `<b>%{customdata[0]}</b> in <b>%{customdata[1]}</b>` +
            `<br>${config.mean_expression_col}: %{customdata[3]}` +
            `<br>${config.frac_expressing_col}: %{customdata[2]}` +
            `<extra></extra>`,
          marker: {
            size: sizes,
            color: meanVals,
            colorscale: colourScale,
            reversescale: reverseScale,
            showscale: true,
            colorbar: {
              title: { text: meanLabel, side: 'right' as const },
              thickness: 12,
              len: 0.85,
            },
            line: markerOutline
              ? {
                  width: 0.6,
                  color: colorScheme === 'dark' ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.85)',
                }
              : { width: 0 },
          },
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 120, r: 60, t: 20, b: 100 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          type: 'category' as const,
          categoryorder: 'array' as const,
          categoryarray: clusters,
          tickangle: -45,
          title: { text: config.cluster_col },
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          type: 'category' as const,
          categoryorder: 'array' as const,
          categoryarray: genes,
          autorange: 'reversed' as const,
          title: { text: config.gene_col },
        },
        annotations,
        showlegend: false,
        autosize: true,
      },
    };
  }, [
    rows,
    config,
    maxSize,
    minSize,
    reverseScale,
    colourScale,
    logTransform,
    geneSort,
    clusterSort,
    annotateTopN,
    markerOutline,
    colorScheme,
    theme,
    isDark,
    clusterUniverse,
    geneUniverse,
  ]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Colourscale"
          value={colourScale}
          onChange={(v) => v && setColourScale(v as ColourScale)}
          data={['Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis', 'RdBu', 'Spectral']}
          allowDeselect={false}
        />
        <Switch
          size="xs"
          checked={reverseScale}
          onChange={(e) => setReverseScale(e.currentTarget.checked)}
          label="Reverse colourscale"
        />
        <Switch
          size="xs"
          checked={logTransform}
          onChange={(e) => setLogTransform(e.currentTarget.checked)}
          label={`log10(${config.mean_expression_col}+1)`}
        />
        <Group gap="xs" grow>
          <Select
            size="xs"
            label="Sort genes"
            value={geneSort}
            onChange={(v) => v && setGeneSort(v as AxisSort)}
            data={[
              { value: 'name', label: 'Name' },
              { value: 'mean', label: 'Mean expression' },
              { value: 'frac', label: 'Fraction expressing' },
            ]}
            allowDeselect={false}
          />
          <Select
            size="xs"
            label="Sort clusters"
            value={clusterSort}
            onChange={(v) => v && setClusterSort(v as AxisSort)}
            data={[
              { value: 'name', label: 'Name' },
              { value: 'mean', label: 'Mean expression' },
              { value: 'frac', label: 'Fraction expressing' },
            ]}
            allowDeselect={false}
          />
        </Group>
        <Group gap="xs" grow>
          <NumberInput
            size="xs"
            label="Max dot size"
            value={maxSize}
            onChange={(v) => setMaxSize(Math.max(4, Math.min(60, Number(v) || 22)))}
            min={4}
            max={60}
          />
          <NumberInput
            size="xs"
            label="Min dot size"
            value={minSize}
            onChange={(v) => setMinSize(Math.max(0, Math.min(20, Number(v) || 2)))}
            min={0}
            max={20}
          />
        </Group>
        <NumberInput
          size="xs"
          label="Annotate top-N frac"
          description="0 = off"
          value={annotateTopN}
          onChange={(v) => setAnnotateTopN(Math.max(0, Math.min(40, Number(v) || 0)))}
          min={0}
          max={40}
        />
        <Switch
          size="xs"
          checked={markerOutline}
          onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
          label="Marker outline"
        />
      </Stack>
    ),
    [
      colourScale,
      reverseScale,
      logTransform,
      geneSort,
      clusterSort,
      maxSize,
      minSize,
      annotateTopN,
      markerOutline,
      config.mean_expression_col,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Dot plot'}
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

export default DotPlotRenderer;
