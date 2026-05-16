import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  MultiSelect,
  Select,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  ComplexHeatmapResult,
  dispatchComplexHeatmap,
  fetchAdvancedVizData,
  fetchPolarsSchema,
  InteractiveFilter,
  pollComplexHeatmap,
  StoredMetadata,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';

interface ComplexHeatmapConfig {
  matrix_wf_id: string;
  matrix_dc_id: string;
  index_column: string;
  value_columns?: string[] | null;
  row_annotation_cols?: string[];
  cluster_rows?: boolean;
  cluster_cols?: boolean;
  cluster_method?: 'ward' | 'single' | 'complete' | 'average';
  cluster_metric?: 'euclidean' | 'correlation' | 'cosine';
  normalize?: 'none' | 'row_z' | 'col_z' | 'log1p';
  colorscale?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ComplexHeatmapConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const ComplexHeatmapRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as ComplexHeatmapConfig;
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';

  // Tier-2 controls — change any of these and a new Celery task is
  // dispatched (cache-keyed so repeats are instant).
  const [clusterRows, setClusterRows] = useState<boolean>(config.cluster_rows ?? true);
  const [clusterCols, setClusterCols] = useState<boolean>(config.cluster_cols ?? true);
  const [normalize, setNormalize] = useState<NonNullable<ComplexHeatmapConfig['normalize']>>(
    config.normalize ?? 'none',
  );
  const [clusterMethod, setClusterMethod] = useState<NonNullable<
    ComplexHeatmapConfig['cluster_method']
  >>(config.cluster_method ?? 'ward');
  // Row-annotation columns — editable in the popover. Seeded from config so
  // the dashboard author's defaults still apply on first paint.
  const [rowAnnotationCols, setRowAnnotationCols] = useState<string[]>(
    config.row_annotation_cols ?? [],
  );
  const [schema, setSchema] = useState<Record<string, string> | null>(null);

  const [figure, setFigure] = useState<ComplexHeatmapResult['figure'] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);
  const [dims, setDims] = useState<{ rows: number; cols: number } | null>(null);

  // Sample of the underlying matrix powering the Show-data popover.
  const [dataRows, setDataRows] = useState<Record<string, unknown[]> | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('ComplexHeatmap: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setComputeStatus('Building heatmap…');
    setComputeMs(null);

    const payload = {
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      index_column: config.index_column,
      value_columns: config.value_columns ?? null,
      row_annotation_cols: rowAnnotationCols,
      cluster_rows: clusterRows,
      cluster_cols: clusterCols,
      cluster_method: clusterMethod,
      cluster_metric: config.cluster_metric ?? 'euclidean',
      normalize,
      colorscale: config.colorscale ?? null,
      filter_metadata: filters,
    };

    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const accept = (result: ComplexHeatmapResult) => {
      if (cancelled) return;
      setFigure(result.figure);
      setDims({ rows: result.row_count, cols: result.col_count });
      setComputeMs(result.compute_ms ?? null);
      setComputeStatus(null);
      setLoading(false);
    };

    dispatchComplexHeatmap(payload)
      .then((job) => {
        if (cancelled) return;
        if (job.status === 'done' && job.result) {
          accept(job.result);
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
            const status = await pollComplexHeatmap(job.job_id);
            if (cancelled) return;
            if (status.status === 'done' && status.result) accept(status.result);
            else if (status.status === 'failed') {
              setError(status.error || 'Compute task failed');
              setLoading(false);
            } else pollTimer = setTimeout(tick, 1500);
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
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(filters),
    refreshTick,
    clusterRows,
    clusterCols,
    normalize,
    clusterMethod,
    config.index_column,
    JSON.stringify(config.value_columns),
    JSON.stringify(rowAnnotationCols),
  ]);

  // Fetch the column schema once so the MultiSelect knows what's available.
  useEffect(() => {
    if (!metadata.dc_id) return;
    let cancelled = false;
    fetchPolarsSchema(metadata.dc_id)
      .then((s) => {
        if (!cancelled) setSchema(s);
      })
      .catch(() => {
        /* schema is best-effort — fall back to config-only options */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  const annotationOptions = useMemo(() => {
    const valueSet = new Set(config.value_columns ?? []);
    const opts: string[] = [];
    if (schema) {
      for (const col of Object.keys(schema)) {
        if (col === config.index_column) continue;
        if (valueSet.has(col)) continue;
        opts.push(col);
      }
    }
    // Always include current selections even if schema-fetch failed.
    for (const c of rowAnnotationCols) if (!opts.includes(c)) opts.push(c);
    return opts;
  }, [schema, config.index_column, config.value_columns, rowAnnotationCols]);

  // Best-effort fetch of a small data sample (max 200 rows) for the
  // Show-data popover — separate from the heatmap dispatch.
  const previewCols = useMemo(
    () => [config.index_column, ...(config.value_columns ?? []).slice(0, 12)],
    [config.index_column, config.value_columns],
  );
  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || previewCols.length < 1) return;
    let cancelled = false;
    fetchAdvancedVizData(metadata.wf_id, metadata.dc_id, previewCols, filters, 200)
      .then((res) => {
        if (!cancelled) setDataRows(res.rows);
      })
      .catch(() => {
        /* preview is best-effort */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(previewCols), JSON.stringify(filters), refreshTick]);

  // Memo the controls JSX so its reference is stable across renders.
  // AdvancedVizFrame publishes `controls` up to a parent state via useEffect;
  // a fresh JSX reference on every render would refire the publish effect →
  // setState → re-render → fresh JSX → loop (manifested as React's
  // "Maximum update depth exceeded" warning).
  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Normalisation"
          value={normalize}
          onChange={(v) => v && setNormalize(v as typeof normalize)}
          data={[
            { value: 'none', label: 'None' },
            { value: 'row_z', label: 'Row z-score' },
            { value: 'col_z', label: 'Column z-score' },
            { value: 'log1p', label: 'log1p' },
          ]}
          description="Applied before clustering + colourisation"
        />
        <Select
          size="xs"
          label="Clustering method"
          value={clusterMethod}
          onChange={(v) => v && setClusterMethod(v as typeof clusterMethod)}
          data={[
            { value: 'ward', label: 'Ward' },
            { value: 'single', label: 'Single' },
            { value: 'complete', label: 'Complete' },
            { value: 'average', label: 'Average' },
          ]}
        />
        <Switch
          size="xs"
          checked={clusterRows}
          onChange={(e) => setClusterRows(e.currentTarget.checked)}
          label="Cluster rows"
        />
        <Switch
          size="xs"
          checked={clusterCols}
          onChange={(e) => setClusterCols(e.currentTarget.checked)}
          label="Cluster columns"
        />
        <MultiSelect
          size="xs"
          label="Row annotations"
          description="Metadata columns drawn as side tracks (categorical auto-coloured, numeric → bar)"
          value={rowAnnotationCols}
          onChange={setRowAnnotationCols}
          data={annotationOptions}
          placeholder={annotationOptions.length === 0 ? 'No DC columns loaded yet' : 'Pick columns'}
          searchable
          clearable
        />
        {computeStatus ? (
          <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
            {computeStatus}
          </Badge>
        ) : null}
        {computeMs != null && !computeStatus ? (
          <Text size="xs" c="dimmed">
            Built in {computeMs} ms ({dims?.rows ?? '?'} rows × {dims?.cols ?? '?'} cols)
          </Text>
        ) : null}
      </Stack>
    ),
    [
      normalize,
      clusterMethod,
      clusterRows,
      clusterCols,
      rowAnnotationCols,
      annotationOptions,
      computeStatus,
      computeMs,
      dims,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'ComplexHeatmap'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={undefined}
      dataRows={dataRows ?? undefined}
      dataColumns={previewCols}
    >
      {figure ? (
        <Plot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          // plotly-complexheatmap bakes an explicit width/height into its
          // figure layout (sized for its own jupyter/standalone use case);
          // strip them so the chart fills the chrome panel responsively.
          // applyLayoutTheme retints every axis / colorbar / legend / title
          // baked at server-render time so the dark/light flip is total.
          layout={
            applyLayoutTheme(
              {
                ...(figure.layout as Record<string, unknown>),
                width: undefined,
                height: undefined,
                autosize: true,
              },
              isDark,
              theme,
            ) as any
          }
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ComplexHeatmapRenderer;
