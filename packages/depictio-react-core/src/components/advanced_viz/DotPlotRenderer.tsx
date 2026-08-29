import React, { useEffect, useMemo, useState } from 'react';
import {
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
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
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

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

type AxisSort = 'name' | 'mean' | 'frac';

const DotPlotRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as DotPlotConfig;

  const [maxSize, setMaxSize] = usePersistedVizControl(metadata, 'max_dot_size', 22);
  const [minSize, setMinSize] = usePersistedVizControl(metadata, 'min_dot_size', 2);
  const [reverseScale, setReverseScale] = usePersistedVizControl(metadata, 'reverse_scale', false);
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(metadata, 'colour_scale', 'Viridis');
  const [logTransform, setLogTransform] = usePersistedVizControl(metadata, 'log_transform', false);
  const [geneSort, setGeneSort] = usePersistedVizControl<AxisSort>(metadata, 'gene_sort', 'name');
  const [clusterSort, setClusterSort] = usePersistedVizControl<AxisSort>(metadata, 'cluster_sort', 'name');
  const [annotateTopN, setAnnotateTopN] = usePersistedVizControl(metadata, 'annotate_top_n', 0);
  const [markerOutline, setMarkerOutline] = usePersistedVizControl(metadata, 'marker_outline', true);
  // A dot plot of every gene is both illegible and slow, so by default only the
  // most cluster-discriminating genes are shown; Load-All (below) lifts the cap.
  const [maxGenes, setMaxGenes] = usePersistedVizControl(metadata, 'max_genes', 50);
  const [fullGenes, setFullGenes] = useState<boolean>(false);

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
  // The server serves this kind whole because the renderer aggregates its rows;
  // past `advanced_viz_no_sample_max_rows` it samples anyway and says so here.
  const [estimated, setEstimated] = useState(false);
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
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: requiredCols,
      filters,
      vizKind: 'dot_plot',
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

  // A dot plot draws one marker cloud, so it always competes for a bounded
  // WebGL slot; without one the trace renders as downsampled SVG — see
  // webglBudget. Asked at mount from the kind, like Volcano/Manhattan.
  const glGranted = useWebglSlot(true);

  const figure = useMemo(() => {
    if (!rows) return null;
    // Raw per-(cluster, gene) rows, before the gene cap.
    const clusterAll = (rows[config.cluster_col] || []) as (string | number)[];
    const geneAll = (rows[config.gene_col] || []) as (string | number)[];
    const meanRawAll = (rows[config.mean_expression_col] || []) as number[];
    const fracAll = (rows[config.frac_expressing_col] || []) as number[];

    const meanValsAll = logTransform
      ? meanRawAll.map((v) => Math.log10(Math.max(0, Number(v) || 0) + 1))
      : meanRawAll.map((v) => Number(v) || 0);

    const genesInDataAll = Array.from(new Set(geneAll.map(String)));
    const capActive = !fullGenes && genesInDataAll.length > maxGenes;

    // Gene cap — keep the genes whose mean-expression varies most across
    // clusters: the cluster-discriminating markers a dot plot exists to show.
    // A dot plot of thousands of near-flat genes is both illegible and slow.
    // `geneSort` still orders the visible axis independently (see below);
    // Load-All (`fullGenes`) lifts the cap. When the cap is inactive the raw
    // arrays pass through untouched — no ranking, no per-point copies.
    let clusterVals = clusterAll;
    let geneVals = geneAll;
    let meanRaw = meanRawAll;
    let meanVals = meanValsAll;
    let fracVals = fracAll;
    let pointsShown = geneAll.length;
    if (capActive) {
      const meanByGene = new Map<string, number[]>();
      for (let i = 0; i < geneAll.length; i++) {
        const g = String(geneAll[i]);
        const bucket = meanByGene.get(g);
        if (bucket) bucket.push(meanValsAll[i]);
        else meanByGene.set(g, [meanValsAll[i]]);
      }
      const geneVariance = new Map<string, number>();
      meanByGene.forEach((vals, g) => {
        const n = vals.length;
        if (n === 0) {
          geneVariance.set(g, 0);
          return;
        }
        const mean = vals.reduce((a, b) => a + b, 0) / n;
        const varr = vals.reduce((a, b) => a + (b - mean) * (b - mean), 0) / n;
        geneVariance.set(g, varr);
      });
      const keptSet = new Set(
        [...genesInDataAll]
          .sort((a, b) => (geneVariance.get(b) ?? 0) - (geneVariance.get(a) ?? 0))
          .slice(0, maxGenes),
      );
      // Subset every per-point array to the kept genes so the trace, sizes,
      // annotations and axis aggregation stay aligned.
      const keepIdx: number[] = [];
      for (let i = 0; i < geneAll.length; i++) {
        if (keptSet.has(String(geneAll[i]))) keepIdx.push(i);
      }
      clusterVals = keepIdx.map((i) => clusterAll[i]);
      geneVals = keepIdx.map((i) => geneAll[i]);
      meanRaw = keepIdx.map((i) => meanRawAll[i]);
      meanVals = keepIdx.map((i) => meanValsAll[i]);
      fracVals = keepIdx.map((i) => fracAll[i]);
      pointsShown = keepIdx.length;
    }

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
      pointsShown,
      pointsTotal: geneAll.length,
      capActive,
      data: [
        adaptGlTrace(
          {
            type: 'scattergl' as const,
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
              // marker.line (outline) is poorly supported under scattergl, so
              // the outline is honoured only on the SVG fallback path.
              line:
                markerOutline && !glGranted
                  ? {
                      width: 0.6,
                      color: colorScheme === 'dark' ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.85)',
                    }
                  : { width: 0 },
            },
          },
          glGranted,
        ),
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
    maxGenes,
    fullGenes,
    glGranted,
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
          data={COLOUR_SCALES}
          allowDeselect={false}
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Direction
          </Text>
          <Switch
          size="xs"
          checked={reverseScale}
          onChange={(e) => setReverseScale(e.currentTarget.checked)}
          label="Reverse colourscale"
        />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Sort
          </Text>
          <Switch
          size="xs"
          checked={logTransform}
          onChange={(e) => setLogTransform(e.currentTarget.checked)}
          label={`log10(${config.mean_expression_col}+1)`}
        />
        </Stack>
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
          label="Max genes"
          description="Top genes by cross-cluster variance (Load-All to override)"
          value={maxGenes}
          onChange={(v) => setMaxGenes(Math.max(5, Math.min(500, Number(v) || 50)))}
          min={5}
          max={500}
          disabled={fullGenes}
        />
        <NumberInput
          size="xs"
          label="Annotate top-N frac"
          description="0 = off"
          value={annotateTopN}
          onChange={(v) => setAnnotateTopN(Math.max(0, Math.min(40, Number(v) || 0)))}
          min={0}
          max={40}
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Markers
          </Text>
          <Switch
          size="xs"
          checked={markerOutline}
          onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
          label="Marker outline"
        />
        </Stack>
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
      maxGenes,
      fullGenes,
      config.mean_expression_col,
    ],
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Dot plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      reduction={
        figure && (figure.capActive || fullGenes)
          ? {
              // Points on screen — post-cap, and clamped to the SVG budget when
              // this plot missed a WebGL slot and fell back to downsampled SVG.
              displayed: glGranted
                ? figure.pointsShown
                : Math.min(figure.pointsShown, SVG_MAX_POINTS),
              total: figure.pointsTotal,
              sampled: figure.capActive,
              full: fullGenes,
              loading: false,
              onToggle: () => setFullGenes((v) => !v),
            }
          : undefined
      }
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
