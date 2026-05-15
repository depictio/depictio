import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Group,
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  dispatchComputeEmbedding,
  fetchAdvancedVizData,
  fetchPolarsSchema,
  fetchUniqueValues,
  InteractiveFilter,
  pollComputeEmbedding,
  StoredMetadata,
  type ComputeEmbeddingResult,
} from '../../api';
import { stableColorMap, TAB10_PALETTE } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyThemeColors } from './plotlyTheme';

type ComputeMethod = 'pca' | 'umap' | 'tsne' | 'pcoa';

interface EmbeddingConfig {
  sample_id_col: string;
  dim_1_col: string;
  dim_2_col: string;
  dim_3_col?: string | null;
  cluster_col?: string | null;
  color_col?: string | null;
  point_size?: number;
  show_density?: boolean;
  // Live-compute mode (see PhylogeneticConfig / EmbeddingConfig in
  // depictio/models/components/advanced_viz/configs.py). When set, the
  // renderer dispatches a Celery task instead of reading dim_*_col.
  compute_method?: ComputeMethod | null;
  umap_n_neighbors?: number;
  umap_min_dist?: number;
  tsne_perplexity?: number;
  tsne_n_iter?: number;
  pcoa_distance?: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: EmbeddingConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const EmbeddingRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as EmbeddingConfig;
  const [pointSize, setPointSize] = useState<number>(config.point_size ?? 7);
  const [showCentroids, setShowCentroids] = useState<boolean>(false);
  const [markerOutline, setMarkerOutline] = useState<boolean>(false);
  type LegendPos = 'right' | 'bottom' | 'in-tr' | 'hidden';
  const [legendPos, setLegendPos] = useState<LegendPos>('right');
  const [ncontours, setNcontours] = useState<number>(14);
  const [densityOpacity, setDensityOpacity] = useState<number>(0.45);
  const [colorBy, setColorBy] = useState<string | null>(
    config.cluster_col || config.color_col || null,
  );
  const [showDensity, setShowDensity] = useState<boolean>(Boolean(config.show_density));

  // 3D toggle — disabled when no dim_3_col is configured. Default 2D: most
  // clustering reads happen in 2D and the third axis is opt-in.
  const has3DConfigured = Boolean(config.dim_3_col);
  const [view3D, setView3D] = useState<boolean>(false);
  // Reverse-colourscale only meaningful for the continuous (numeric) branch.
  // Spectral runs red→blue by default; reverse=true → blue=low / red=high,
  // which matches most clustering-narrative defaults.
  const [reverseScale, setReverseScale] = useState<boolean>(true);

  // Per-component schema lookup so the Hover-columns MultiSelect can list any
  // non-binding column from the DC.
  const [dcSchema, setDcSchema] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    if (!metadata.dc_id) {
      setDcSchema(null);
      return;
    }
    let cancelled = false;
    fetchPolarsSchema(metadata.dc_id)
      .then((s) => {
        if (!cancelled) setDcSchema(s);
      })
      .catch(() => {
        /* schema is optional — fall back to no hover-extras */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  // Hover-columns the user has picked. Each becomes one customdata slot in
  // the trace; the template references them by index.
  const [hoverCols, setHoverCols] = useState<string[]>([]);

  const [colorUniverse, setColorUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id || !colorBy) {
      setColorUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, colorBy)
      .then((values) => {
        if (!cancelled) setColorUniverse(values);
      })
      .catch(() => {
        /* fall back to filtered-set ordering when the endpoint errors */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, colorBy]);

  // ---- Live-compute mode state -------------------------------------------
  const liveMode = Boolean(config.compute_method);
  const [method, setMethod] = useState<ComputeMethod>(config.compute_method ?? 'pca');
  const [nNeighbors, setNNeighbors] = useState<number>(config.umap_n_neighbors ?? 15);
  const [minDist, setMinDist] = useState<number>(config.umap_min_dist ?? 0.1);
  const [perplexity, setPerplexity] = useState<number>(config.tsne_perplexity ?? 30);

  const requiredCols = useMemo(() => {
    const cols = [config.sample_id_col, config.dim_1_col, config.dim_2_col].filter(Boolean) as string[];
    if (config.dim_3_col) cols.push(config.dim_3_col);
    if (config.cluster_col) cols.push(config.cluster_col);
    if (config.color_col && !cols.includes(config.color_col)) cols.push(config.color_col);
    for (const c of hoverCols) if (c && !cols.includes(c)) cols.push(c);
    return cols;
  }, [config, hoverCols]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);

  // Live-compute params — n_components flips to 3 when 3D view is requested
  // (and dim_3_col was originally absent, so the user is asking us to compute
  // a 3rd component fresh).
  const computeParams = useMemo<Record<string, string | number | boolean>>(() => {
    const params: Record<string, string | number | boolean> = {
      n_components: view3D ? 3 : 2,
    };
    if (method === 'umap') {
      params.n_neighbors = nNeighbors;
      params.min_dist = minDist;
    } else if (method === 'tsne') {
      params.perplexity = perplexity;
      params.n_iter = config.tsne_n_iter ?? 1000;
    } else if (method === 'pcoa') {
      params.distance = config.pcoa_distance ?? 'bray_curtis';
    }
    return params;
  }, [view3D, method, nNeighbors, minDist, perplexity, config.tsne_n_iter, config.pcoa_distance]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Embedding: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setComputeStatus(null);
    setComputeMs(null);

    if (!liveMode) {
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
    }

    setComputeStatus(`Computing ${method.toUpperCase()}…`);
    const extraCols: string[] = [];
    if (config.cluster_col) extraCols.push(config.cluster_col);
    if (config.color_col && !extraCols.includes(config.color_col)) {
      extraCols.push(config.color_col);
    }
    for (const c of hoverCols) if (c && !extraCols.includes(c)) extraCols.push(c);
    const payload = {
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      feature_id_col: config.sample_id_col,
      method,
      params: computeParams,
      filter_metadata: filters,
      extra_cols: extraCols,
    };

    let pollTimer: ReturnType<typeof setTimeout> | undefined;

    const acceptResult = (result: ComputeEmbeddingResult) => {
      if (cancelled) return;
      const r: Record<string, unknown[]> = {
        [config.sample_id_col]: result.sample_ids,
        [config.dim_1_col || 'dim_1']: result.dim_1,
        [config.dim_2_col || 'dim_2']: result.dim_2,
      };
      if (view3D && result.dim_3 != null) {
        const dim3Key = config.dim_3_col || 'dim_3';
        r[dim3Key] = result.dim_3;
      }
      if (result.extras) {
        for (const [col, vals] of Object.entries(result.extras)) r[col] = vals;
      }
      setRows(r);
      setComputeMs(result.compute_ms ?? null);
      setComputeStatus(null);
      setLoading(false);
    };

    dispatchComputeEmbedding(payload)
      .then((job) => {
        if (cancelled) return;
        if (job.status === 'done' && job.result) {
          acceptResult(job.result);
          return;
        }
        if (job.status === 'failed') {
          setError(job.error || 'Compute task failed');
          setLoading(false);
          return;
        }
        const tick = async () => {
          if (cancelled) return;
          try {
            const status = await pollComputeEmbedding(job.job_id);
            if (cancelled) return;
            if (status.status === 'done' && status.result) {
              acceptResult(status.result);
            } else if (status.status === 'failed') {
              setError(status.error || 'Compute task failed');
              setLoading(false);
            } else {
              pollTimer = setTimeout(tick, 1500);
            }
          } catch (err) {
            if (!cancelled) {
              setError(err instanceof Error ? err.message : String(err));
              setLoading(false);
            }
          }
        };
        pollTimer = setTimeout(tick, 800);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [
    liveMode,
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filters),
    refreshTick,
    method,
    JSON.stringify(computeParams),
    JSON.stringify(hoverCols),
    config.sample_id_col,
    config.dim_1_col,
    config.dim_2_col,
    config.dim_3_col,
    view3D,
  ]);

  const figure = useMemo(() => {
    if (!rows) return null;
    // In live-compute mode the builder skips dim_1/dim_2 column bindings (the
    // Celery worker derives them), so config.dim_*_col are undefined. The
    // dispatch result keys those vectors under the literal "dim_1"/"dim_2"
    // (see acceptResult above). Use the same fallback here or the figure
    // silently renders empty.
    const dim1Key = config.dim_1_col || 'dim_1';
    const dim2Key = config.dim_2_col || 'dim_2';
    const dim3Key = config.dim_3_col || 'dim_3';
    const x = (rows[dim1Key] || []) as number[];
    const y = (rows[dim2Key] || []) as number[];
    const ids = (rows[config.sample_id_col] || []) as (string | number)[];
    // 3D requires the third axis to be present in the data, regardless of
    // whether the user toggled 3D. In live-compute mode the worker fills
    // `dim_3` when n_components=3; in precomputed mode the DC must have the
    // configured dim_3_col.
    const z3 = view3D && (config.dim_3_col || liveMode)
      ? ((rows[dim3Key] || []) as number[])
      : null;
    const actuallyRender3D = view3D && z3 != null && z3.length === x.length && z3.length > 0;

    const colorValues = colorBy ? (rows[colorBy] as unknown[]) : null;
    const isCategorical =
      colorValues != null &&
      colorValues.length > 0 &&
      typeof colorValues[0] !== 'number';

    // Hover-extras: customdata slot 0 = sample id, slots 1..N = extra cols.
    const extraValues = hoverCols.map((c) => (rows[c] as unknown[]) || []);
    const buildCustomdata = (idxList: number[]) =>
      idxList.map((i) => [String(ids[i] ?? ''), ...extraValues.map((vs) => vs[i] ?? '')]);
    const hoverExtraTpl = hoverCols
      .map((c, j) => `<br>${c}: %{customdata[${j + 1}]}`)
      .join('');

    const traces: any[] = [];

    // 2D KDE only — Plotly's histogram2dcontour doesn't make sense in 3D, and
    // a volumetric density would dwarf the scatter. Skip in 3D mode.
    if (!actuallyRender3D && showDensity && x.length > 1) {
      traces.push({
        type: 'histogram2dcontour' as const,
        x,
        y,
        colorscale: isDark ? 'Greys' : 'Blues',
        reversescale: false,
        showscale: false,
        opacity: densityOpacity,
        contours: { coloring: 'fill', showlines: false },
        hoverinfo: 'skip',
        ncontours,
        showlegend: false,
      });
    }

    const denseAutoSize = x.length > 1000 ? Math.min(pointSize, 4) : pointSize;
    const baseMarker2D = {
      size: denseAutoSize,
      opacity: 0.85,
      line: markerOutline
        ? { width: 0.5, color: isDark ? 'rgba(0,0,0,0.65)' : 'rgba(255,255,255,0.8)' }
        : { width: 0 },
    };
    // 3D markers don't accept the same outline shape; keep them simple.
    const baseMarker3D = { size: Math.max(2, Math.min(denseAutoSize, 6)), opacity: 0.9 };

    const scatterType = actuallyRender3D ? ('scatter3d' as const) : ('scattergl' as const);

    if (isCategorical && colorValues) {
      const categories = Array.from(new Set(colorValues.map((v) => String(v))));
      categories.sort();
      const colourSource = stableColorMap(colorUniverse ?? categories, TAB10_PALETTE);
      const centroids: { x: number; y: number; z?: number; label: string }[] = [];
      for (let ci = 0; ci < categories.length; ci++) {
        const cat = categories[ci];
        const idx: number[] = [];
        for (let i = 0; i < colorValues.length; i++) {
          if (String(colorValues[i]) === cat) idx.push(i);
        }
        const trace: any = {
          type: scatterType,
          mode: 'markers' as const,
          name: cat,
          x: idx.map((i) => x[i]),
          y: idx.map((i) => y[i]),
          customdata: buildCustomdata(idx),
          hovertemplate:
            `<b>%{customdata[0]}</b><br>${cat}<br>${config.dim_1_col}: %{x:.3f}` +
            `<br>${config.dim_2_col}: %{y:.3f}` +
            (actuallyRender3D ? `<br>${config.dim_3_col ?? 'dim_3'}: %{z:.3f}` : '') +
            hoverExtraTpl +
            '<extra></extra>',
          marker: actuallyRender3D
            ? { ...baseMarker3D, color: colourSource.get(cat) }
            : { ...baseMarker2D, color: colourSource.get(cat) },
        };
        if (actuallyRender3D && z3) trace.z = idx.map((i) => z3[i]);
        traces.push(trace);

        if (showCentroids && idx.length > 0) {
          const cx = idx.reduce((s, i) => s + x[i], 0) / idx.length;
          const cy = idx.reduce((s, i) => s + y[i], 0) / idx.length;
          const cz =
            actuallyRender3D && z3 ? idx.reduce((s, i) => s + z3[i], 0) / idx.length : undefined;
          centroids.push({ x: cx, y: cy, z: cz, label: cat });
        }
      }
      if (showCentroids && centroids.length > 0) {
        const labelTrace: any = {
          type: actuallyRender3D ? 'scatter3d' : 'scatter',
          mode: 'text' as const,
          x: centroids.map((c) => c.x),
          y: centroids.map((c) => c.y),
          text: centroids.map((c) => c.label),
          textfont: {
            size: 12,
            color: isDark ? 'rgba(255,255,255,0.95)' : 'rgba(0,0,0,0.85)',
          },
          hoverinfo: 'skip',
          showlegend: false,
        };
        if (actuallyRender3D) labelTrace.z = centroids.map((c) => c.z);
        traces.push(labelTrace);
      }
    } else {
      // Continuous gradient OR no colour binding. Use Spectral (with optional
      // reverse) for the continuous case so cluster-heavy use cases get a
      // perceptually-ordered diverging palette instead of Viridis monotone.
      const colourArr = (colorValues as number[] | undefined) ?? undefined;
      const trace: any = {
        type: scatterType,
        mode: 'markers' as const,
        x,
        y,
        customdata: buildCustomdata(x.map((_, i) => i)),
        hovertemplate:
          `<b>%{customdata[0]}</b><br>${config.dim_1_col}: %{x:.3f}` +
          `<br>${config.dim_2_col}: %{y:.3f}` +
          (actuallyRender3D ? `<br>${config.dim_3_col ?? 'dim_3'}: %{z:.3f}` : '') +
          hoverExtraTpl +
          '<extra></extra>',
        marker: {
          ...(actuallyRender3D ? baseMarker3D : baseMarker2D),
          color: colourArr ?? '#4C72B0',
          colorscale: colourArr ? 'Spectral' : undefined,
          reversescale: colourArr ? reverseScale : undefined,
          showscale: Boolean(colourArr),
          colorbar: colourArr
            ? { title: { text: colorBy ?? '', side: 'right' }, thickness: 12, len: 0.85 }
            : undefined,
        },
        showlegend: false,
      };
      if (actuallyRender3D && z3) trace.z = z3;
      traces.push(trace);
    }

    // Per-position legend placement. Pulled out of the layout literal so the
    // legend branch isn't a 5-level nested ternary.
    const inTrBg = isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.7)';
    function legendForPos(pos: LegendPos): Record<string, unknown> {
      switch (pos) {
        case 'right':
          return { orientation: 'v', x: 1.02, y: 1, bgcolor: 'rgba(0,0,0,0)' };
        case 'bottom':
          return { orientation: 'h', x: 0, y: -0.15, bgcolor: 'rgba(0,0,0,0)' };
        case 'in-tr':
          return {
            orientation: 'v',
            x: 0.98,
            y: 0.98,
            xanchor: 'right',
            yanchor: 'top',
            bgcolor: inTrBg,
          };
        default:
          return { bgcolor: 'rgba(0,0,0,0)' };
      }
    }

    const { textColor, gridColor, zeroLineColor } = plotlyThemeColors(isDark, theme);
    const axisCommon = {
      zeroline: false,
      showgrid: false,
      showticklabels: false,
      ticks: '' as const,
      showline: true,
      linecolor: zeroLineColor,
      linewidth: 1,
      mirror: false,
      color: textColor,
      tickfont: { color: textColor },
    };

    const layout2D = {
      xaxis: {
        ...axisCommon,
        title: {
          text: config.dim_1_col,
          standoff: 6,
          font: { size: 12, color: textColor },
        },
      },
      yaxis: {
        ...axisCommon,
        title: {
          text: config.dim_2_col,
          standoff: 6,
          font: { size: 12, color: textColor },
        },
        scaleanchor: 'x' as const,
        scaleratio: 1,
      },
    };
    // 3D layout — Plotly's scene primitive owns xaxis/yaxis/zaxis. uirevision
    // on the scene means camera rotation survives re-renders from filter /
    // control changes (a value swap re-triggers the useMemo here).
    const scene3D = {
      xaxis: {
        title: { text: config.dim_1_col, font: { size: 11, color: textColor } },
        color: textColor,
        gridcolor: gridColor,
        tickfont: { color: textColor },
      },
      yaxis: {
        title: { text: config.dim_2_col, font: { size: 11, color: textColor } },
        color: textColor,
        gridcolor: gridColor,
        tickfont: { color: textColor },
      },
      zaxis: {
        title: {
          text: config.dim_3_col ?? 'dim_3',
          font: { size: 11, color: textColor },
        },
        color: textColor,
        gridcolor: gridColor,
        tickfont: { color: textColor },
      },
      bgcolor: 'rgba(0,0,0,0)',
      aspectmode: 'cube' as const,
    };

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        font: { color: textColor },
        margin: actuallyRender3D ? { l: 0, r: 0, t: 8, b: 0 } : { l: 40, r: 12, t: 12, b: 40 },
        ...(actuallyRender3D ? { scene: scene3D, uirevision: 'embedding-3d' } : layout2D),
        showlegend: isCategorical && legendPos !== 'hidden',
        legend: isCategorical
          ? {
              ...legendForPos(legendPos),
              borderwidth: 0,
              font: { size: 11, color: textColor },
              itemsizing: 'constant',
              tracegroupgap: 4,
            }
          : undefined,
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      },
    };
  }, [
    rows,
    config,
    pointSize,
    colorBy,
    colorUniverse,
    showDensity,
    showCentroids,
    markerOutline,
    legendPos,
    ncontours,
    densityOpacity,
    colorScheme,
    theme,
    view3D,
    reverseScale,
    hoverCols,
    liveMode,
  ]);

  const colorOptions: { value: string; label: string }[] = useMemo(() => {
    const opts: { value: string; label: string }[] = [];
    if (config.cluster_col) opts.push({ value: config.cluster_col, label: `${config.cluster_col} (cluster)` });
    if (config.color_col && config.color_col !== config.cluster_col) {
      opts.push({ value: config.color_col, label: config.color_col });
    }
    return opts;
  }, [config]);

  // Hover-column candidates: any column in the DC schema that isn't already
  // bound as a coordinate / id / cluster / colour. Falls back to whatever
  // columns the loaded rows expose if the schema fetch fails.
  const hoverCandidates = useMemo<string[]>(() => {
    const exclude = new Set<string>(
      [
        config.sample_id_col,
        config.dim_1_col,
        config.dim_2_col,
        config.dim_3_col,
        config.cluster_col,
        config.color_col,
      ].filter(Boolean) as string[],
    );
    const source = dcSchema
      ? Object.keys(dcSchema)
      : rows
        ? Object.keys(rows)
        : [];
    return source.filter((c) => !exclude.has(c));
  }, [dcSchema, rows, config]);

  // The bool-ish colorBy check tells us whether the *current* colour binding
  // is a numeric column — that's the only case where reverseScale matters.
  const colorByIsNumeric = useMemo(() => {
    if (!rows || !colorBy) return false;
    const vs = rows[colorBy] as unknown[] | undefined;
    if (!vs || vs.length === 0) return false;
    return typeof vs[0] === 'number';
  }, [rows, colorBy]);

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {liveMode ? (
          <>
            <Select
              size="xs"
              label="Method"
              value={method}
              onChange={(v) => v && setMethod(v as ComputeMethod)}
              data={[
                { value: 'pca', label: 'PCA' },
                { value: 'umap', label: 'UMAP' },
                { value: 'tsne', label: 't-SNE' },
                { value: 'pcoa', label: 'PCoA' },
              ]}
              description="Dim-reduction algorithm dispatched as a Celery task"
            />
            {method === 'umap' ? (
              <Group gap="xs" grow>
                <NumberInput
                  size="xs"
                  label="n_neighbors"
                  description="2–100"
                  value={nNeighbors}
                  onChange={(v) => setNNeighbors(Math.max(2, Math.min(100, Number(v) || 15)))}
                  min={2}
                  max={100}
                />
                <NumberInput
                  size="xs"
                  label="min_dist"
                  description="0–1"
                  value={minDist}
                  onChange={(v) => setMinDist(Math.max(0, Math.min(1, Number(v) || 0.1)))}
                  min={0}
                  max={1}
                  step={0.05}
                  decimalScale={2}
                />
              </Group>
            ) : null}
            {method === 'tsne' ? (
              <NumberInput
                size="xs"
                label="perplexity"
                description="2–100 (clamped below sample count)"
                value={perplexity}
                onChange={(v) => setPerplexity(Math.max(2, Math.min(100, Number(v) || 30)))}
                min={2}
                max={100}
              />
            ) : null}
            {computeStatus ? (
              <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
                {computeStatus}
              </Badge>
            ) : null}
            {computeMs != null && computeStatus == null ? (
              <Text size="xs" c="dimmed">
                {method.toUpperCase()} computed in {computeMs} ms
              </Text>
            ) : null}
          </>
        ) : null}
        {/* View 2D/3D toggle. In precomputed mode this is only meaningful when
            the DC has a dim_3_col; in live mode the user can opt into 3D and
            n_components flips to 3 automatically. */}
        <SegmentedControl
          size="xs"
          value={view3D ? '3d' : '2d'}
          onChange={(v) => setView3D(v === '3d')}
          data={[
            { value: '2d', label: '2D' },
            { value: '3d', label: '3D' },
          ]}
          disabled={!liveMode && !has3DConfigured}
        />
        <Group gap="xs" grow>
          <NumberInput
            size="xs"
            label="Point size"
            value={pointSize}
            onChange={(v) => setPointSize(Math.max(1, Number(v) || 6))}
            min={1}
            max={30}
          />
          {colorOptions.length > 0 ? (
            <Select
              size="xs"
              label="Colour by"
              value={colorBy}
              onChange={setColorBy}
              data={colorOptions}
              clearable
            />
          ) : null}
        </Group>
        {colorByIsNumeric ? (
          <Switch
            size="xs"
            checked={reverseScale}
            onChange={(e) => setReverseScale(e.currentTarget.checked)}
            label="Reverse colourscale"
          />
        ) : null}
        {hoverCandidates.length > 0 ? (
          <MultiSelect
            size="xs"
            label="Hover columns"
            placeholder="Pick extra columns…"
            value={hoverCols}
            onChange={setHoverCols}
            data={hoverCandidates}
            searchable
            clearable
            maxValues={6}
          />
        ) : null}
        <Switch
          size="xs"
          checked={showDensity}
          onChange={(e) => setShowDensity(e.currentTarget.checked)}
          label="Density overlay"
          disabled={view3D}
        />
        {showDensity && !view3D ? (
          <Group gap="xs" grow>
            <NumberInput
              size="xs"
              label="Contours"
              value={ncontours}
              onChange={(v) => setNcontours(Math.max(2, Math.min(40, Number(v) || 14)))}
              min={2}
              max={40}
            />
            <NumberInput
              size="xs"
              label="Opacity"
              value={densityOpacity}
              onChange={(v) => setDensityOpacity(Math.max(0.05, Math.min(1, Number(v) || 0.45)))}
              min={0.05}
              max={1}
              step={0.05}
              decimalScale={2}
            />
          </Group>
        ) : null}
        <Switch
          size="xs"
          checked={showCentroids}
          onChange={(e) => setShowCentroids(e.currentTarget.checked)}
          label="Cluster labels"
        />
        <Switch
          size="xs"
          checked={markerOutline}
          onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
          label="Marker outline"
          disabled={view3D}
        />
        <Select
          size="xs"
          label="Legend"
          value={legendPos}
          onChange={(v) => v && setLegendPos(v as LegendPos)}
          data={[
            { value: 'right', label: 'Right (outside)' },
            { value: 'bottom', label: 'Bottom' },
            { value: 'in-tr', label: 'Inside, top-right' },
            { value: 'hidden', label: 'Hidden' },
          ]}
          allowDeselect={false}
        />
      </Stack>
    ),
    [
      liveMode,
      method,
      nNeighbors,
      minDist,
      perplexity,
      computeStatus,
      computeMs,
      view3D,
      has3DConfigured,
      pointSize,
      colorBy,
      colorOptions,
      colorByIsNumeric,
      reverseScale,
      hoverCols,
      hoverCandidates,
      showDensity,
      ncontours,
      densityOpacity,
      showCentroids,
      markerOutline,
      legendPos,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Embedding'}
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

export default EmbeddingRenderer;
