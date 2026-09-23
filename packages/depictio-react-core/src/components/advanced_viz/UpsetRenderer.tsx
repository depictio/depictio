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
import { namedColumns } from './namedColumns';
import { applyDataTheme, applyLayoutTheme } from './plotlyTheme';
import { emphasizeUpsetColumn, upsetHoverColumn, withUpsetHoverTargets } from './upsetHover';
import { usePersistedVizControl } from './usePersistedVizControl';
import { demandForItems } from './contentDemand';

/** Room one matrix row (one set) needs: the dot, its label and the gap that
 *  keeps the connecting line readable. */
const SET_ROW_PX = 26;
/** The intersection-size bar panel above the matrix, which is the panel the
 *  plot is actually read from and must not be squeezed. */
const INTERSECTION_PANEL_PX = 220;
/** The intersection labels along the bottom plus the figure's own margins. */
const UPSET_CHROME_PX = 90;
/** One annotation track, drawn as its own band under the matrix. */
const ANNOTATION_TRACK_PX = 90;

interface UpsetPlotConfig {
  /** Deprecated/unused: data comes from the component's resolved dc_id
   *  (metadata.dc_id), not these fields. Optional for back-compat. */
  matrix_wf_id?: string;
  matrix_dc_id?: string;
  set_columns?: string[] | null;
  /** Regex naming the set columns, for a matrix with one column per sample of
   *  the run. The worker resolves it against the frame's binary columns;
   *  mutually exclusive with set_columns. */
  set_columns_pattern?: string | null;
  /** Optional per-set colour overrides (set name → hex). Forwarded to the
   *  plotly-upset library so set-size bars + dots + intersection bars use
   *  the project's domain palette (e.g. habitat → Set1). */
  set_colors?: Record<string, string> | null;
  sort_by?: 'cardinality' | 'degree' | 'degree-cardinality' | 'input';
  sort_order?: 'descending' | 'ascending';
  min_size?: number;
  max_degree?: number | null;
  show_set_sizes?: boolean;
  color_intersections_by?: 'none' | 'set' | 'degree';
  /** Pre-select these columns as annotation tracks on first render. Users
   *  can still add/remove via the MultiSelect — this only seeds the default. */
  default_annotation_cols?: string[] | null;
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

  type SortBy = NonNullable<UpsetPlotConfig['sort_by']>;
  type SortOrder = NonNullable<UpsetPlotConfig['sort_order']>;
  type ColorBy = NonNullable<UpsetPlotConfig['color_intersections_by']>;
  const [sortBy, setSortBy] = usePersistedVizControl<SortBy>(metadata, 'sort_by', 'cardinality');
  const [sortOrder, setSortOrder] = usePersistedVizControl<SortOrder>(metadata, 'sort_order', 'descending');
  const [minSize, setMinSize] = usePersistedVizControl(metadata, 'min_size', 1);
  const [colorBy, setColorBy] = usePersistedVizControl<ColorBy>(metadata, 'color_intersections_by', 'none');
  const [showSetSizes, setShowSetSizes] = usePersistedVizControl(metadata, 'show_set_sizes', true);
  const [showValues, setShowValues] = usePersistedVizControl(metadata, 'show_values', false);
  // Master toggle that gates both annotation switches. When OFF, the
  // dispatch sends false for both (regardless of granular state) so the
  // UpSet renders as a bare dot-matrix.
  const [showAnnotations, setShowAnnotations] = usePersistedVizControl(metadata, 'show_annotations', true);
  const effectiveShowSetSizes = showAnnotations && showSetSizes;
  const effectiveShowValues = showAnnotations && showValues;

  // Annotation track columns. User picks non-set DC columns; backend wires
  // them through UpSetPlot.from_dataframe(annotations=...). Library
  // auto-detects numeric vs categorical and renders one extra track per
  // column. Gated by the master annotations switch.
  const [annotationCols, setAnnotationCols] = usePersistedVizControl<string[]>(metadata, 'default_annotation_cols', []);
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

  // The declared sets, or the columns a pattern names (the worker resolves it
  // against the frame's binary columns).
  const setColumns = useMemo(
    () => namedColumns(config.set_columns, config.set_columns_pattern, dcSchema),
    [config.set_columns, config.set_columns_pattern, dcSchema],
  );

  // Non-set DC columns are candidate annotation tracks. Filter out set
  // columns (already used as the binary matrix) and obvious identifier
  // columns (the library would error on a high-cardinality string ID).
  const annotationOptions = useMemo(() => {
    if (!dcSchema) return [] as string[];
    const setCols = new Set(setColumns);
    return Object.keys(dcSchema).filter((c) => !setCols.has(c));
  }, [dcSchema, setColumns]);

  const effectiveAnnotationCols = showAnnotations ? annotationCols : [];

  const [figure, setFigure] = useState<UpsetResult['figure'] | null>(null);
  // One per figure received, as the plot's `uirevision` (see plotLayout).
  const [figureRevision, setFigureRevision] = useState(0);
  const [hoveredColumn, setHoveredColumn] = useState<number | null>(null);
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
      // Sent only when set: the cache key hashes the whole payload, so an
      // always-present null would recompute every UpSet cached before it.
      ...(config.set_columns_pattern ? { set_columns_pattern: config.set_columns_pattern } : {}),
      set_colors: config.set_colors ?? null,
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
      setFigureRevision((n) => n + 1);
      // Column indices belong to the previous figure's intersection order.
      setHoveredColumn(null);
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
    config.set_columns_pattern,
    config.max_degree,
  ]);

  // Best-effort preview of the underlying binary table for the Show-data popover.
  const previewCols = useMemo(() => setColumns.slice(0, 12), [setColumns]);
  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || previewCols.length < 1) return;
    let cancelled = false;
    fetchAdvancedVizData({
      wfId: metadata.wf_id,
      dcId: metadata.dc_id,
      columns: previewCols,
      filters,
      limitRows: 200,
      vizKind: 'upset_plot',
    })
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
  // Encoding tier: which intersections are drawn, in what order, and what
  // their colour means. The annotation tracks and the count labels decorate
  // whatever survives those four.
  const primaryControls = useMemo(
    () => (
      <>
        <Select
          size="xs"
          w={190}
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
          w={130}
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
          w={140}
          label="Min intersection size"
          value={minSize}
          onChange={(v) => setMinSize(Math.max(0, Number(v) || 0))}
          min={0}
        />
        <Select
          size="xs"
          w={180}
          label="Colour intersections by"
          value={colorBy}
          onChange={(v) => v && setColorBy(v as typeof colorBy)}
          data={[
            { value: 'none', label: 'Single colour' },
            { value: 'set', label: 'Per set (degree-1 bars)' },
            { value: 'degree', label: 'By degree' },
          ]}
        />
      </>
    ),
    [sortBy, sortOrder, minSize, colorBy],
  );

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <Switch
          size="xs"
          checked={showAnnotations}
          onChange={(e) => setShowAnnotations(e.currentTarget.checked)}
          label="Show annotations"
        />
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Show
          </Text>
          <Switch
          size="xs"
          checked={showSetSizes}
          onChange={(e) => setShowSetSizes(e.currentTarget.checked)}
          disabled={!showAnnotations}
          label="Show set-size bars"
        />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Intersections
          </Text>
          <Switch
          size="xs"
          checked={showValues}
          onChange={(e) => setShowValues(e.currentTarget.checked)}
          disabled={!showAnnotations}
          label="Intersection count labels"
        />
        </Stack>
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

  const themedData = useMemo(
    () =>
      figure
        ? withUpsetHoverTargets(
            applyDataTheme(figure.data, isDark, theme) as Record<string, unknown>[],
            figure.layout as Record<string, unknown>,
          )
        : null,
    [figure, isDark, theme],
  );
  // Hovering an intersection dims everything outside it, as the UpSet Shiny
  // app does.
  const plotData = useMemo(
    () =>
      themedData && figure && hoveredColumn != null
        ? emphasizeUpsetColumn(themedData, figure.layout as Record<string, unknown>, hoveredColumn)
        : themedData,
    [themedData, figure, hoveredColumn],
  );
  // plotly-upset bakes its default width=900/height=700 into the figure
  // layout; strip so the chart fills the panel responsively (same fix applied
  // to ComplexHeatmap). applyLayoutTheme retints every axis / legend /
  // annotation / colorbar baked by plotly-upset so dark/light flips reliably
  // without depending on Plotly's template precedence. Every hover re-renders
  // the plot, and a constant `uirevision` until the next figure is what keeps
  // the reader's zoom and legend toggles through those re-renders.
  const plotLayout = useMemo(
    () =>
      figure
        ? applyLayoutTheme(
            {
              ...(figure.layout as Record<string, unknown>),
              width: undefined,
              height: undefined,
              autosize: true,
              uirevision: figureRevision,
            },
            isDark,
            theme,
          )
        : null,
    [figure, figureRevision, isDark, theme],
  );

  // One matrix row per set, under the intersection-bar panel and over any
  // annotation tracks. Only once a figure exists: the set columns are known
  // from the schema well before the worker has drawn anything, and a demand
  // published then would size the tile for a plot that is not there yet.
  const setsDrawn = figure ? setColumns.length : 0;
  const annotationTracks = effectiveAnnotationCols.length;
  const contentDemand = useMemo(
    () =>
      demandForItems(
        setsDrawn,
        SET_ROW_PX,
        INTERSECTION_PANEL_PX + UPSET_CHROME_PX + annotationTracks * ANNOTATION_TRACK_PX,
      ),
    [setsDrawn, annotationTracks],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'UpSet plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      loading={loading}
      error={error}
      emptyMessage={undefined}
      dataRows={dataRows ?? undefined}
      dataColumns={previewCols}
    >
      {plotData && plotLayout ? (
        <Plot
          data={plotData as any}
          layout={plotLayout as any}
          onHover={(e) => setHoveredColumn(upsetHoverColumn(e.points[0] as any))}
          onUnhover={() => setHoveredColumn(null)}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default UpsetRenderer;
