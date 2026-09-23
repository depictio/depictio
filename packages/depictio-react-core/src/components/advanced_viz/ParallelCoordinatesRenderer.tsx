import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  fetchSpecs,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { mantineCategoricalPalette, resolveCategoricalPalette, stableColorMap } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { COLOUR_SCALES, looksContinuous } from './colourScales';
import {
  buildAxisScale,
  toNumbers,
  type AxisScale,
  type AxisScaleMode,
} from './parallel_coordinates/axisScaling';
import { chooseAxisColumns } from './parallel_coordinates/axisSelection';
import {
  applyConstraintUpdate,
  brushFilterUpdates,
  filtersExcludingOwnBrushes,
  parseConstraintUpdate,
  sameBrushes,
  type AxisBrushes,
} from './parallel_coordinates/brushFilters';
import {
  categoryIndices,
  distinctCategories,
  steppedColourScale,
  withAlpha,
} from './parallel_coordinates/lineColours';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import { demandForItems } from './contentDemand';

/** Room one axis needs to be read down: parcoords draws a tick scale the
 *  whole height of the plot, and a short tile turns it into a smear. Counted
 *  per axis because more axes means narrower columns, which is exactly when
 *  the vertical run has to carry the reading. */
const AXIS_HEIGHT_PX = 26;
/** The axis titles along the top and the colourbar / axis labels around the
 *  plot, none of which scale with the axis count. */
const PARCOORDS_CHROME_PX = 280;

/** Mirrors `ParallelCoordinatesConfig` in
 *  depictio/models/components/advanced_viz/configs.py. Every key read here has
 *  a field there, and `test_advanced_viz_config_alignment` enforces it. */
interface ParallelCoordinatesConfig {
  sample_col: string;
  metric_cols?: string[] | null;
  group_col?: string | null;
  scale?: AxisScaleMode;
  max_rows?: number;
  max_axes?: number;
  colour_scale?: string;
  line_opacity?: number;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ParallelCoordinatesConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

const PARALLEL_COORDINATES_VIZ_KIND: AdvancedVizKind = 'parallel_coordinates';

const PLOT_STYLE = { width: '100%', height: '100%' };

// No selection buttons: the only gesture here is the axis brush, which plotly
// handles itself, and no zoom, which parcoords does not have.
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'zoom2d', 'pan2d'],
  scrollZoom: false,
};

/** Plotly restyles once per pointer move while an axis brush is being dragged.
 *  Emitting each one would refetch every following tile a few dozen times per
 *  gesture, so the dashboard hears the brush once it settles. */
const BRUSH_DEBOUNCE_MS = 250;

/** Sentinel for "colour by nothing": a Mantine `Select` has no null value. */
const NO_COLOUR = '__none__';

/** One column of the bound collection, as `/deltatables/specs` describes it. */
interface ColumnSpec {
  name?: string;
  type?: string;
  description?: string | null;
}

const ParcoordsPlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  onRestyle: (event: any) => void;
}>(({ figure, isDark, theme, onRestyle }) => {
  const themedData = useMemo(
    () => applyDataTheme(figure.data, isDark, theme),
    [figure.data, isDark, theme],
  );
  const themedLayout = useMemo(
    () => applyLayoutTheme(figure.layout as any, isDark, theme),
    [figure.layout, isDark, theme],
  );
  return (
    <Plot
      data={themedData as any}
      layout={themedLayout as any}
      useResizeHandler
      style={PLOT_STYLE}
      config={PLOT_CONFIG as any}
      onRestyle={onRestyle}
    />
  );
});
ParcoordsPlot.displayName = 'ParcoordsPlot';

/**
 * One polyline per sample across N metric axes.
 *
 * The many-metric view a scatter cannot give: a QC table with a dozen columns
 * is read as a whole here, where a scatter matrix would need N*(N-1)/2 panels
 * and a heatmap would turn every metric into a colour. And because plotly
 * brushes each axis, the reader narrows the cohort on the picture rather than
 * in the filter panel: every brush leaves the tile as an ordinary range filter
 * on that column, which the rest of the dashboard already knows how to obey.
 *
 * Axes are normalised by default. Raw units put a read count and a duplication
 * rate on the same axis range and flatten one of them, so the values are
 * rescaled while the tick labels keep printing the column's own units.
 */
const ParallelCoordinatesRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const themeColors = plotlyThemeColors(isDark, theme);
  const palette = resolveCategoricalPalette(theme, mantineCategoricalPalette(theme, isDark));

  const config = (metadata.config || {}) as ParallelCoordinatesConfig;
  const sampleCol = config.sample_col || 'sample';
  const maxRows = config.max_rows ?? 2000;
  const maxAxes = config.max_axes ?? 12;

  const [scaleMode, setScaleMode] = usePersistedVizControl<AxisScaleMode>(metadata, 'scale', 'minmax');
  const [groupCol, setGroupCol] = usePersistedVizControl<string | null>(metadata, 'group_col', null);
  const [colourScale, setColourScale] = usePersistedVizControl<string>(metadata, 'colour_scale', 'Viridis');
  const [lineOpacity, setLineOpacity] = usePersistedVizControl<number>(metadata, 'line_opacity', 0.6);

  // The collection's precomputed column specs: what makes `metric_cols`
  // optional, since the axes can be inferred from the numeric columns rather
  // than listed in every dashboard that binds this collection.
  const [columnSpecs, setColumnSpecs] = useState<ColumnSpec[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id) return;
    let cancelled = false;
    fetchSpecs(metadata.dc_id)
      .then((specs) => {
        if (!cancelled) setColumnSpecs(Array.isArray(specs) ? (specs as ColumnSpec[]) : []);
      })
      // A collection with no aggregation yet has no specs. A tile that names
      // its own axes still draws; one that infers them says so below.
      .catch(() => {
        if (!cancelled) setColumnSpecs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  const axisChoice = useMemo(
    () =>
      chooseAxisColumns({
        candidates: columnSpecs ?? [],
        declared: config.metric_cols,
        sampleCol,
        groupCol,
        maxAxes,
      }),
    [columnSpecs, config.metric_cols, sampleCol, groupCol, maxAxes],
  );
  const axisColumns = axisChoice.columns;
  const axisKey = axisColumns.join('|');

  /** Columns that could colour the lines: everything the collection carries
   *  that is not already drawn as an axis or used as the line identity. */
  const colourCandidates = useMemo(
    () =>
      (columnSpecs ?? [])
        .map((spec) => spec.name)
        .filter((name): name is string => Boolean(name))
        .filter((name) => name !== sampleCol && !axisColumns.includes(name)),
    [columnSpecs, sampleCol, axisKey],
  );

  const requiredCols = useMemo(
    () => Array.from(new Set([sampleCol, ...(groupCol ? [groupCol] : []), ...axisColumns])),
    [sampleCol, groupCol, axisKey],
  );

  // Never narrowed by its own brushes: a tile that filtered itself would
  // redraw as only the polylines it caught, and the brush could never be
  // widened again.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwnBrushes(filters, metadata.index),
    [filters, metadata.index],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [fullLoad, setFullLoad] = useState(false);
  const [reduction, setReduction] = useState<{
    total: number;
    sampled: boolean;
    degraded: boolean;
  } | null>(null);

  const filterSig = JSON.stringify(filtersForFetch);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Parallel coordinates: missing data binding');
      setLoading(false);
      return;
    }
    if (axisColumns.length < 2) {
      // Nothing is known until the specs land, so an inferring tile waits
      // rather than accusing its collection of having no metrics.
      if (columnSpecs === null) return;
      setError('Parallel coordinates: needs at least two numeric columns');
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
      filters: filtersForFetch,
      fullLoad,
      vizKind: PARALLEL_COORDINATES_VIZ_KIND,
      roles: { sample: sampleCol },
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setReduction({
          total: res.total_rows ?? res.row_count,
          sampled: Boolean(res.sampled),
          degraded: Boolean(res.sampling?.degraded),
        });
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
  }, [
    metadata.wf_id,
    metadata.dc_id,
    sampleCol,
    JSON.stringify(requiredCols),
    filterSig,
    columnSpecs === null,
    refreshTick,
    fullLoad,
  ]);

  // Rows drawn as polylines: complete cases only, then capped. A polyline is
  // one path across every axis, so a row missing one metric has no path to
  // draw; dropping it is the only honest option and the count is reported.
  const drawnRows = useMemo(() => {
    if (!rows || axisColumns.length < 2) return null;
    const columns = axisColumns.map((column) => toNumbers(rows[column] ?? []));
    const length = columns.reduce((n, values) => Math.max(n, values.length), 0);
    const complete: number[] = [];
    for (let i = 0; i < length; i += 1) {
      if (columns.every((values) => values[i] !== null && values[i] !== undefined)) complete.push(i);
    }
    const cap = fullLoad ? complete.length : Math.min(complete.length, Math.max(1, maxRows));
    return {
      indices: complete.slice(0, cap),
      complete: complete.length,
      incomplete: length - complete.length,
    };
  }, [rows, axisKey, fullLoad, maxRows]);

  const scales = useMemo(() => {
    if (!rows || !drawnRows) return null;
    const out = new Map<string, AxisScale>();
    for (const column of axisColumns) {
      const source = rows[column] ?? [];
      out.set(column, buildAxisScale(drawnRows.indices.map((i) => source[i]), scaleMode));
    }
    return out;
  }, [rows, drawnRows, axisKey, scaleMode]);
  // Read by the restyle handler, which must not be rebuilt (and re-bound by
  // plotly) every time the scales are recomputed.
  const scalesRef = useRef<Map<string, AxisScale> | null>(null);
  scalesRef.current = scales;

  const colourValues = useMemo(() => {
    if (!rows || !drawnRows || !groupCol) return null;
    const source = rows[groupCol] ?? [];
    return drawnRows.indices.map((i) => source[i]);
  }, [rows, drawnRows, groupCol]);
  const numericColour = useMemo(
    () => Boolean(colourValues && looksContinuous(colourValues)),
    [colourValues],
  );

  // ---- Axis brushes -------------------------------------------------------
  const [brushes, setBrushes] = useState<AxisBrushes>({});
  const brushesRef = useRef<AxisBrushes>({});
  const emittedRef = useRef<AxisBrushes>({});
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const emitBrushes = useCallback(
    (next: AxisBrushes) => {
      // A read-only host (the catalog, a project preview) passes no handler.
      // The brush still highlights locally, it just narrows nothing.
      if (!onFilterChange) return;
      const updates = brushFilterUpdates(emittedRef.current, next, {
        index: metadata.index,
        dcId: metadata.dc_id,
      });
      emittedRef.current = { ...next };
      for (const update of updates) onFilterChange(update);
    },
    [onFilterChange, metadata.index, metadata.dc_id],
  );

  const scheduleEmit = useCallback(
    (next: AxisBrushes) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        emitBrushes(next);
      }, BRUSH_DEBOUNCE_MS);
    },
    [emitBrushes],
  );

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const handleRestyle = useCallback(
    (event: any) => {
      // react-plotly.js forwards plotly's own `[update, traceIndices]` pair.
      const parsed = parseConstraintUpdate(Array.isArray(event) ? event[0] : event);
      if (parsed.size === 0) return;
      const next = applyConstraintUpdate(
        brushesRef.current,
        parsed,
        axisColumns,
        (column, value) => scalesRef.current?.get(column)?.toOriginal(value) ?? value,
      );
      if (sameBrushes(next, brushesRef.current)) return;
      brushesRef.current = next;
      setBrushes(next);
      scheduleEmit(next);
    },
    [axisKey, scheduleEmit],
  );

  const resetBrushes = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    brushesRef.current = {};
    setBrushes({});
    emitBrushes({});
  }, [emitBrushes]);

  // An axis the tile no longer draws is not a filter the reader is still
  // asking for, so a config or colour-column change releases its brush.
  useEffect(() => {
    const kept = Object.fromEntries(
      Object.entries(brushesRef.current).filter(([column]) => axisColumns.includes(column)),
    );
    if (Object.keys(kept).length === Object.keys(brushesRef.current).length) return;
    brushesRef.current = kept;
    setBrushes(kept);
    emitBrushes(kept);
  }, [axisKey, emitBrushes]);

  const figure = useMemo(() => {
    if (!scales || !drawnRows || drawnRows.indices.length === 0) return null;

    const dimensions = axisColumns.map((column) => {
      const scale = scales.get(column) as AxisScale;
      const brush = brushes[column];
      return {
        label: column,
        values: scale.values,
        range: scale.range,
        // The reader is shown the column's own units whatever the axis was
        // rescaled to, so a z-scored axis never prints a z-score.
        ...(scale.tickvals ? { tickvals: scale.tickvals, ticktext: scale.ticktext } : {}),
        ...(brush
          ? { constraintrange: [scale.toPlotted(brush[0]), scale.toPlotted(brush[1])] }
          : {}),
      };
    });

    let line: Record<string, unknown>;
    if (colourValues && numericColour) {
      // A plotly named scale is a string, so the opacity control has nothing
      // to bake an alpha into here. It is hidden in this case rather than
      // offered and ignored.
      line = {
        color: colourValues.map((value) => Number(value) || 0),
        colorscale: colourScale,
        showscale: true,
        colorbar: {
          thickness: 10,
          len: 0.75,
          title: { text: groupCol, side: 'right' },
          tickfont: { color: themeColors.textColor },
        },
      };
    } else if (colourValues) {
      const categories = distinctCategories(colourValues);
      const colourMap = stableColorMap(categories, palette);
      const stepped = steppedColourScale(
        categories.map((category) => withAlpha(colourMap.get(category), lineOpacity)),
      );
      line = {
        color: categoryIndices(colourValues, categories),
        colorscale: stepped.colorscale,
        cmin: stepped.cmin,
        cmax: stepped.cmax,
        showscale: false,
      };
    } else {
      line = {
        color: withAlpha(theme.colors.gray[isDark ? 5 : 6], lineOpacity),
      };
    }

    const data = [
      {
        type: 'parcoords' as const,
        dimensions,
        line,
        labelfont: { size: 11, color: themeColors.textColor },
        tickfont: { size: 9, color: themeColors.textColor },
        rangefont: { size: 9, color: themeColors.textColor },
        // Lines outside a brush stay visible enough to give the selection
        // context, faint enough that it reads as a selection.
        unselected: { line: { color: themeColors.gridColor, opacity: 0.25 } },
      },
    ];

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      // Room for the axis labels above and the range readouts below.
      margin: { l: 52, r: 52, t: 44, b: 28 },
      autosize: true,
    };

    return { data, layout };
  }, [
    scales,
    drawnRows,
    axisKey,
    brushes,
    colourValues,
    numericColour,
    colourScale,
    groupCol,
    lineOpacity,
    palette,
    isDark,
    theme,
    themeColors.textColor,
    themeColors.gridColor,
  ]);

  const brushedColumns = Object.keys(brushes);
  const drawn = drawnRows?.indices.length ?? 0;
  const capped = Boolean(drawnRows && drawnRows.complete > drawn);

  const counts = useMemo(() => {
    if (!drawnRows) return undefined;
    const out: Record<string, number> = { lines: drawn, axes: axisColumns.length };
    if (drawnRows.incomplete > 0) out.incomplete = drawnRows.incomplete;
    return out;
  }, [drawnRows, drawn, axisKey]);

  // A fixed demand off the axis count: the lines fill whatever height they are
  // given, but the axes have to be tall enough to read a value off, and the
  // labels above them need room whatever the data says.
  const axisCount = figure ? axisColumns.length : 0;
  const contentDemand = useMemo(
    () => demandForItems(axisCount, AXIS_HEIGHT_PX, PARCOORDS_CHROME_PX),
    [axisCount],
  );

  // Encoding tier: how the axes are scaled, what colours the lines and the
  // brushes that narrow them. Colourscale and opacity are paint.
  const primaryControls = (
    <>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Axis scale
        </Text>
        <SegmentedControl
          size="xs"
          w={210}
          value={scaleMode}
          onChange={(value) => setScaleMode(value as AxisScaleMode)}
          data={[
            { value: 'minmax', label: 'Min-max' },
            { value: 'zscore', label: 'Z-score' },
            { value: 'raw', label: 'Raw' },
          ]}
        />
      </Stack>
      {colourCandidates.length > 1 ? (
        <Select
          size="xs"
          w={170}
          label="Colour by"
          value={groupCol ?? NO_COLOUR}
          onChange={(value) => setGroupCol(!value || value === NO_COLOUR ? null : value)}
          data={[
            { value: NO_COLOUR, label: 'Nothing' },
            ...colourCandidates.map((column) => ({ value: column, label: column })),
          ]}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
      ) : null}
      <Button
        size="xs"
        variant="light"
        onClick={resetBrushes}
        disabled={brushedColumns.length === 0}
      >
        Reset brushes
      </Button>
    </>
  );

  const controls = (
    <Stack gap="xs">
      {colourValues && numericColour ? (
        <Select
          size="xs"
          label="Colourscale"
          value={colourScale}
          onChange={(value) => value && setColourScale(value)}
          data={COLOUR_SCALES as unknown as string[]}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
      ) : (
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Line opacity
          </Text>
          <Slider
            size="xs"
            value={lineOpacity}
            onChangeEnd={setLineOpacity}
            min={0.05}
            max={1}
            step={0.05}
            label={(value) => value.toFixed(2)}
          />
        </Stack>
      )}
      {axisChoice.truncated > 0 ? (
        <Text size="xs" c="dimmed">
          {`${axisChoice.truncated} further numeric column(s) not drawn`}
        </Text>
      ) : null}
    </Stack>
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Parallel coordinates'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      // The brushes narrow the dashboard from a tile the filter chips cannot
      // name, so the tile says which axes it is holding.
      echo={brushedColumns.length ? `brushed: ${brushedColumns.join(', ')}` : undefined}
      counts={counts}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      loading={loading}
      error={error}
      emptyMessage={drawnRows && drawnRows.indices.length === 0 ? 'No complete rows' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      estimated={Boolean(reduction?.degraded)}
      reduction={
        reduction && (reduction.sampled || capped || fullLoad)
          ? {
              displayed: drawn,
              total: reduction.total,
              sampled: reduction.sampled || capped,
              full: fullLoad,
              loading,
              onToggle: () => setFullLoad((value) => !value),
            }
          : undefined
      }
    >
      {figure ? (
        <ParcoordsPlot figure={figure} isDark={isDark} theme={theme} onRestyle={handleRestyle} />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ParallelCoordinatesRenderer;
