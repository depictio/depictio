import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  MultiSelect,
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
  dispatchUpset,
  fetchAdvancedVizData,
  fetchPolarsSchema,
  InteractiveFilter,
  pollUpset,
  StoredMetadata,
  UpsetResult,
} from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';

interface UpsetPlotConfig {
  matrix_wf_id: string;
  matrix_dc_id: string;
  set_columns?: string[] | null;
  sort_by?: 'cardinality' | 'degree' | 'degree-cardinality' | 'input';
  sort_order?: 'descending' | 'ascending';
  min_size?: number;
  max_degree?: number | null;
  show_set_sizes?: boolean;
  color_intersections_by?: 'none' | 'set' | 'degree';
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: UpsetPlotConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

const UpsetRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const config = (metadata.config || {}) as UpsetPlotConfig;
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';

  const [sortBy, setSortBy] = useState<NonNullable<UpsetPlotConfig['sort_by']>>(
    config.sort_by ?? 'cardinality',
  );
  const [sortOrder, setSortOrder] = useState<NonNullable<UpsetPlotConfig['sort_order']>>(
    config.sort_order ?? 'descending',
  );
  const [minSize, setMinSize] = useState<number>(config.min_size ?? 1);
  const [colorBy, setColorBy] = useState<NonNullable<UpsetPlotConfig['color_intersections_by']>>(
    config.color_intersections_by ?? 'none',
  );
  const [showSetSizes, setShowSetSizes] = useState<boolean>(config.show_set_sizes ?? true);
  const [showValues, setShowValues] = useState<boolean>(false);
  // Master toggle that gates both annotation switches. When OFF, the
  // dispatch sends false for both (regardless of granular state) so the
  // UpSet renders as a bare dot-matrix.
  const [showAnnotations, setShowAnnotations] = useState<boolean>(true);
  const effectiveShowSetSizes = showAnnotations && showSetSizes;
  const effectiveShowValues = showAnnotations && showValues;

  // Annotation track columns. User picks non-set DC columns; backend wires
  // them through UpSetPlot.from_dataframe(annotations=...). Library
  // auto-detects numeric vs categorical and renders one extra track per
  // column. Gated by the master annotations switch.
  const [annotationCols, setAnnotationCols] = useState<string[]>([]);
  const [dcSchema, setDcSchema] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    if (!metadata.dc_id) return;
    let cancelled = false;
    fetchPolarsSchema(metadata.dc_id)
      .then((s) => {
        if (!cancelled) setDcSchema(s);
      })
      .catch(() => {
        /* schema is best-effort — annotation MultiSelect just stays empty */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  // Non-set DC columns are candidate annotation tracks. Filter out set
  // columns (already used as the binary matrix) and obvious identifier
  // columns (the library would error on a high-cardinality string ID).
  const annotationOptions = useMemo(() => {
    if (!dcSchema) return [] as string[];
    const setCols = new Set(config.set_columns ?? []);
    return Object.keys(dcSchema).filter((c) => !setCols.has(c));
  }, [dcSchema, config.set_columns]);

  const effectiveAnnotationCols = showAnnotations ? annotationCols : [];

  const [figure, setFigure] = useState<UpsetResult['figure'] | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [computeStatus, setComputeStatus] = useState<string | null>(null);
  const [computeMs, setComputeMs] = useState<number | null>(null);
  const [rowCount, setRowCount] = useState<number | null>(null);

  const [dataRows, setDataRows] = useState<Record<string, unknown[]> | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('UpSet: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setComputeStatus('Building UpSet plot…');
    setComputeMs(null);

    const payload = {
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      set_columns: config.set_columns ?? null,
      annotation_cols: effectiveAnnotationCols.length > 0 ? effectiveAnnotationCols : null,
      sort_by: sortBy,
      sort_order: sortOrder,
      min_size: minSize,
      max_degree: config.max_degree ?? null,
      show_set_sizes: effectiveShowSetSizes,
      show_values: effectiveShowValues,
      color_intersections_by: colorBy,
      filter_metadata: filters,
    };

    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const accept = (result: UpsetResult) => {
      if (cancelled) return;
      setFigure(result.figure);
      setRowCount(result.row_count);
      setComputeMs(result.compute_ms ?? null);
      setComputeStatus(null);
      setLoading(false);
    };

    dispatchUpset(payload)
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
            const status = await pollUpset(job.job_id);
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
    sortBy,
    sortOrder,
    minSize,
    colorBy,
    showAnnotations,
    showSetSizes,
    showValues,
    JSON.stringify(effectiveAnnotationCols),
    JSON.stringify(config.set_columns),
    config.max_degree,
  ]);

  // Best-effort preview of the underlying binary table for the Show-data popover.
  const previewCols = useMemo(
    () => (config.set_columns ?? []).slice(0, 12),
    [config.set_columns],
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

  // Memo the controls JSX so its reference is stable — AdvancedVizFrame
  // publishes it via useEffect and a fresh inline JSX every render would
  // refire that effect into an infinite setState loop.
  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Sort by"
          value={sortBy}
          onChange={(v) => v && setSortBy(v as typeof sortBy)}
          data={[
            { value: 'cardinality', label: 'Cardinality (set size)' },
            { value: 'degree', label: 'Degree (# of sets)' },
            { value: 'degree-cardinality', label: 'Degree → cardinality' },
            { value: 'input', label: 'Input order' },
          ]}
        />
        <Select
          size="xs"
          label="Order"
          value={sortOrder}
          onChange={(v) => v && setSortOrder(v as typeof sortOrder)}
          data={[
            { value: 'descending', label: 'Descending' },
            { value: 'ascending', label: 'Ascending' },
          ]}
        />
        <NumberInput
          size="xs"
          label="Min intersection size"
          value={minSize}
          onChange={(v) => setMinSize(Math.max(0, Number(v) || 0))}
          min={0}
        />
        <Select
          size="xs"
          label="Colour intersections by"
          value={colorBy}
          onChange={(v) => v && setColorBy(v as typeof colorBy)}
          data={[
            { value: 'none', label: 'Single colour' },
            { value: 'set', label: 'Per set (degree-1 bars)' },
            { value: 'degree', label: 'By degree' },
          ]}
        />
        <Text size="xs" c="dimmed" fw={500} mt={4}>
          Annotations
        </Text>
        <Switch
          size="xs"
          checked={showAnnotations}
          onChange={(e) => setShowAnnotations(e.currentTarget.checked)}
          label="Show annotations"
        />
        <Switch
          size="xs"
          checked={showSetSizes}
          onChange={(e) => setShowSetSizes(e.currentTarget.checked)}
          disabled={!showAnnotations}
          label="Show set-size bars"
        />
        <Switch
          size="xs"
          checked={showValues}
          onChange={(e) => setShowValues(e.currentTarget.checked)}
          disabled={!showAnnotations}
          label="Intersection count labels"
        />
        <MultiSelect
          size="xs"
          label="Annotation tracks"
          description="Per-intersection summary tracks above the bars"
          placeholder={annotationOptions.length ? 'Pick columns…' : 'No annotation candidates'}
          value={annotationCols}
          onChange={setAnnotationCols}
          data={annotationOptions}
          disabled={!showAnnotations || annotationOptions.length === 0}
          clearable
          searchable
        />
        {computeStatus ? (
          <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
            {computeStatus}
          </Badge>
        ) : null}
        {computeMs != null && !computeStatus ? (
          <Text size="xs" c="dimmed">
            Built in {computeMs} ms ({rowCount ?? '?'} rows)
          </Text>
        ) : null}
      </Stack>
    ),
    [
      sortBy,
      sortOrder,
      minSize,
      colorBy,
      showAnnotations,
      showSetSizes,
      showValues,
      annotationCols,
      annotationOptions,
      computeStatus,
      computeMs,
      rowCount,
    ],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'UpSet plot'}
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
          // plotly-upset bakes its default width=900/height=700 into the
          // figure layout; strip so the chart fills the panel responsively
          // (same fix applied to ComplexHeatmap). applyLayoutTheme retints
          // every axis / legend / annotation / colorbar baked by plotly-upset
          // so dark/light flips reliably without depending on Plotly's
          // template precedence.
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

export default UpsetRenderer;
