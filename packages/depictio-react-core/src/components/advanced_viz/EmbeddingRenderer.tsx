import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  dispatchComputeEmbedding,
  fetchAdvancedVizData,
  InteractiveFilter,
  pollComputeEmbedding,
  StoredMetadata,
  type ComputeEmbeddingResult,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';

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
  const config = (metadata.config || {}) as EmbeddingConfig;
  const [pointSize, setPointSize] = useState<number>(config.point_size ?? 7);
  // Default to the discrete cluster column (clearer cluster separation),
  // falling back to the continuous color column. Either can be toggled in
  // the controls — picking the cluster column triggers a categorical legend
  // with one trace per cluster; picking the color column uses a Viridis
  // gradient with a colourbar.
  const [colorBy, setColorBy] = useState<string | null>(
    config.cluster_col || config.color_col || null,
  );
  const [showDensity, setShowDensity] = useState<boolean>(Boolean(config.show_density));

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
    return cols;
  }, [config]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);

  // Live-compute params object — re-fetches whenever the user nudges a slider.
  const computeParams = useMemo(() => {
    if (method === 'umap') return { n_neighbors: nNeighbors, min_dist: minDist };
    if (method === 'tsne') return { perplexity, n_iter: config.tsne_n_iter ?? 1000 };
    if (method === 'pcoa') return { distance: config.pcoa_distance ?? 'bray_curtis' };
    return {};
  }, [method, nNeighbors, minDist, perplexity, config.tsne_n_iter, config.pcoa_distance]);

  // Two fetch paths: precomputed (existing) or live-compute (new).
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
      // ---- Precomputed mode: read dim_1_col/dim_2_col directly ---------
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

    // ---- Live-compute mode: dispatch + poll Celery ---------------------
    setComputeStatus(`Computing ${method.toUpperCase()}…`);
    // Pass-through columns (cluster + colour) so the renderer can overlay
    // categorical/quantitative annotation on the live result.
    const extraCols: string[] = [];
    if (config.cluster_col) extraCols.push(config.cluster_col);
    if (config.color_col && !extraCols.includes(config.color_col)) {
      extraCols.push(config.color_col);
    }
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
      // Reshape the live result into the same column-oriented shape the
      // figure-builder expects below (so we don't need a second code path).
      const r: Record<string, unknown[]> = {
        [config.sample_id_col]: result.sample_ids,
        [config.dim_1_col || 'dim_1']: result.dim_1,
        [config.dim_2_col || 'dim_2']: result.dim_2,
      };
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
        // Pending — start polling.
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
    config.sample_id_col,
    config.dim_1_col,
    config.dim_2_col,
  ]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const x = (rows[config.dim_1_col] || []) as number[];
    const y = (rows[config.dim_2_col] || []) as number[];
    const ids = (rows[config.sample_id_col] || []) as (string | number)[];
    const colorValues = colorBy ? (rows[colorBy] as unknown[]) : null;
    const isDark = colorScheme === 'dark';
    const isCategorical =
      colorValues != null &&
      colorValues.length > 0 &&
      typeof colorValues[0] !== 'number';

    const traces: any[] = [];

    // Optional 2D KDE under the scatter (does NOT contribute to the legend).
    if (showDensity && x.length > 1) {
      traces.push({
        type: 'histogram2dcontour' as const,
        x,
        y,
        colorscale: isDark ? 'Greys' : 'Blues',
        reversescale: false,
        showscale: false,
        opacity: 0.45,
        contours: { coloring: 'fill', showlines: false },
        hoverinfo: 'skip',
        ncontours: 14,
        showlegend: false,
      });
    }

    // scanpy / ggplot2 publication style: NO marker outline, smaller markers,
    // slightly translucent so overlapping points hint at density.
    const baseMarker = {
      size: pointSize,
      opacity: 0.85,
      line: { width: 0 },
    };

    if (isCategorical && colorValues) {
      // Categorical: one trace per cluster so plotly renders a clean legend
      // and discrete colours instead of one rainbow blob. Palette matches
      // matplotlib's tab10 (scanpy's default).
      const palette = [
        '#1f77b4',
        '#ff7f0e',
        '#2ca02c',
        '#d62728',
        '#9467bd',
        '#8c564b',
        '#e377c2',
        '#7f7f7f',
        '#bcbd22',
        '#17becf',
      ];
      const categories = Array.from(new Set(colorValues.map((v) => String(v))));
      categories.sort();
      for (let ci = 0; ci < categories.length; ci++) {
        const cat = categories[ci];
        const idx: number[] = [];
        for (let i = 0; i < colorValues.length; i++) {
          if (String(colorValues[i]) === cat) idx.push(i);
        }
        traces.push({
          type: 'scattergl' as const,
          mode: 'markers' as const,
          name: cat,
          x: idx.map((i) => x[i]),
          y: idx.map((i) => y[i]),
          text: idx.map((i) => String(ids[i] ?? '')),
          hovertemplate:
            `<b>%{text}</b><br>${cat}<br>${config.dim_1_col}: %{x:.3f}` +
            `<br>${config.dim_2_col}: %{y:.3f}<extra></extra>`,
          marker: { ...baseMarker, color: palette[ci % palette.length] },
        });
      }
    } else {
      // Continuous gradient OR no colour binding.
      traces.push({
        type: 'scattergl' as const,
        mode: 'markers' as const,
        x,
        y,
        text: ids.map((v) => String(v ?? '')),
        hovertemplate:
          `<b>%{text}</b><br>${config.dim_1_col}: %{x:.3f}` +
          `<br>${config.dim_2_col}: %{y:.3f}<extra></extra>`,
        marker: {
          ...baseMarker,
          color: (colorValues as number[] | undefined) ?? '#4C72B0',
          colorscale: colorValues ? 'Viridis' : undefined,
          showscale: Boolean(colorValues),
          colorbar: colorValues
            ? { title: { text: colorBy ?? '', side: 'right' }, thickness: 12, len: 0.85 }
            : undefined,
        },
        showlegend: false,
      });
    }

    // scanpy / ggplot2 `theme_minimal()` style: hide axis ticks + numbers,
    // no grid, keep a small axis arrow-style title in the corner. Box stays
    // visible (one thin line, no mirror) so the plot has a clear extent.
    const axisLine = isDark ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.35)';
    const axisCommon = {
      zeroline: false,
      showgrid: false,
      showticklabels: false,
      ticks: '' as const,
      showline: true,
      linecolor: axisLine,
      linewidth: 1,
      mirror: false,
    };

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        margin: { l: 40, r: 12, t: 12, b: 40 },
        xaxis: {
          ...axisCommon,
          title: { text: config.dim_1_col, standoff: 6, font: { size: 12 } },
        },
        yaxis: {
          ...axisCommon,
          title: { text: config.dim_2_col, standoff: 6, font: { size: 12 } },
          scaleanchor: 'x',
          scaleratio: 1,
        },
        showlegend: isCategorical,
        legend: isCategorical
          ? {
              orientation: 'v',
              x: 1.02,
              y: 1,
              bgcolor: 'rgba(0,0,0,0)',
              borderwidth: 0,
              font: { size: 11 },
              itemsizing: 'constant',
              tracegroupgap: 4,
            }
          : undefined,
        autosize: true,
        plot_bgcolor: isDark ? 'rgba(0,0,0,0)' : 'rgba(255,255,255,0)',
        paper_bgcolor: isDark ? 'rgba(0,0,0,0)' : 'rgba(255,255,255,0)',
      },
    };
  }, [rows, config, pointSize, colorBy, showDensity, colorScheme]);

  const colorOptions: { value: string; label: string }[] = useMemo(() => {
    const opts: { value: string; label: string }[] = [];
    if (config.cluster_col) opts.push({ value: config.cluster_col, label: `${config.cluster_col} (cluster)` });
    if (config.color_col && config.color_col !== config.cluster_col) {
      opts.push({ value: config.color_col, label: config.color_col });
    }
    return opts;
  }, [config]);

  // Controls are rendered inside the chrome Settings popover (see
  // AdvancedVizFrame). Use a vertical Stack so each control gets a full row
  // — reads cleaner than a wrapped horizontal Group in a 380px-wide popover.
  const controls = (
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
      <Switch
        size="xs"
        checked={showDensity}
        onChange={(e) => setShowDensity(e.currentTarget.checked)}
        label="Density overlay"
      />
    </Stack>
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

export default EmbeddingRenderer;
