import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import AdvancedVizPlot from './AdvancedVizPlot';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  fetchDataCollectionConfig,
  fetchPolarsSchema,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  extractScatterSelection,
  filtersForSelector,
  hasOwnSelection,
  valuesOnColumn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  VizControlGroup,
  VizMultiSelect,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSlider,
  VizSwitch,
} from './controls/VizControls';
import { COLOUR_SCALES, type ColourScale } from './colourScales';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';
import { useSelectionRevision } from './selectionGesture';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';
import { usePlotSelectionReset } from '../usePlotSelectionReset';
import { demandForPx } from './contentDemand';
import {
  axisRanges,
  cellDiameters,
  cellExtent,
  clipRange,
  facetDomains,
  fillUrlTemplate,
  formatHoverNumber,
  type Frame,
  groupRowsBySample,
  heightForFrames,
  imageFrame,
  imageServeUrl,
  padFrame,
  pickMarker,
  pickSample,
  pixelsPerUnit,
  resolveMarkerColumns,
  type SpatialTransform,
  type SpatialYAxis,
  thinIndices,
  toNumber,
  transformValue,
  underlayImage,
  unionFrame,
} from './spatial_cells/spatialLayout';

type LegendPos = 'right' | 'bottom' | 'none';
type ColorBy = 'value' | 'category';
type SampleDisplay = 'select' | 'facet';

/** Mirrors `SpatialCellsConfig` in
 *  depictio/models/components/advanced_viz/configs.py. Every key read here has
 *  a field there; `test_advanced_viz_config_alignment` enforces it. */
interface SpatialCellsConfig {
  cell_id_col?: string;
  x_col?: string;
  y_col?: string;
  value_col?: string | null;
  category_col?: string | null;
  sample_col?: string | null;
  area_col?: string | null;
  value_columns?: string[] | null;
  value_columns_pattern?: string | null;
  color_by?: ColorBy | null;
  sample_display?: SampleDisplay;
  default_sample?: string | null;
  max_facets?: number;
  y_axis?: SpatialYAxis;
  colour_scale?: ColourScale;
  reverse_scale?: boolean;
  transform?: SpatialTransform;
  asinh_cofactor?: number;
  clip_low_pct?: number;
  clip_high_pct?: number;
  size_by_area?: boolean;
  point_size?: number;
  max_point_size?: number;
  opacity?: number;
  legend_pos?: LegendPos;
  hover_cols?: string[];
  max_cells?: number;
  background_wf_id?: string | null;
  background_dc_id?: string | null;
  background_image_col?: string | null;
  background_sample_col?: string;
  background_width_col?: string;
  background_height_col?: string;
  background_url?: string | null;
  background_width?: number | null;
  background_height?: number | null;
  background_image_scale?: number;
  background_opacity?: number;
  show_background?: boolean;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: SpatialCellsConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Dashboard-wide analysis grouping, applied to the finished figure. */
  groupRender?: GroupRenderState;
}

/** One image under the cells of a sample. */
interface Underlay {
  source: string;
  width: number;
  height: number;
}

// `KIND_SAMPLING_POLICY` carries `spatial_cells: "hash"`: a uniform subset of a
// tissue is the same tissue at a lower density.
const SPATIAL_CELLS_VIZ_KIND: AdvancedVizKind = 'spatial_cells';

const PLOT_STYLE = { width: '100%', height: '100%' };
// No `scrollZoom`: the zoom gate lets a plain wheel scroll the page and zooms
// on Ctrl / Cmd + wheel. Autoscale goes: the frame is the image, not the data.
const PLOT_CONFIG_PLAIN = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
};
const PLOT_CONFIG_SELECT = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['autoScale2d'],
};

const DIMMED_OPACITY = 0.15;
// Title, echo, axis ticks and facet titles around the plot area.
const SPATIAL_CHROME_PX = 96;
// A scale estimate for the first frame, before Plotly reports the real one.
const GUESS_PLOT_PX = 360;

/**
 * Segmented cells drawn where they sit in the image.
 *
 * The same marks as `embedding` (a scattergl cloud at equal aspect), read in a
 * different frame: the axes are the pixel grid of the image the cells were
 * segmented from, so y runs downwards from the top-left and the frame is the
 * image, not the data's bounding box. Each marker is drawn at the diameter of
 * its cell at the current zoom (Plotly reports the axis scale on every
 * update), the colour comes from one marker of a wide table, transformed and
 * clipped to percentiles, and an image of the same sample can sit underneath
 * through `layout.images`. Two samples are two images, so they never share a
 * frame: one at a time behind a picker, or side by side in their own frames.
 */
const SpatialCellsRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
  groupRender,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const palette = resolveCategoricalPalette(theme, TAB10_PALETTE);
  const config = (metadata.config || {}) as SpatialCellsConfig;

  const cellIdCol = config.cell_id_col || 'cell_id';
  const xCol = config.x_col || 'x';
  const yCol = config.y_col || 'y';
  const sampleCol = config.sample_col || null;
  const areaCol = config.area_col || null;
  const categoryCol = config.category_col || null;
  const maxCells = config.max_cells ?? 100_000;
  const maxFacets = config.max_facets ?? 4;
  const pinnedColours = usePinnedCategoryColors(categoryCol);

  // ---- Tier-2 controls ------------------------------------------------------
  // The marker picker writes `value_col` back: the marker a reader leaves the
  // tile on is the one a saved dashboard opens on.
  const [pickedMarker, setPickedMarker] = usePersistedVizControl<string | null>(metadata, 'value_col', null);
  const [colorBy, setColorBy] = usePersistedVizControl<ColorBy | null>(metadata, 'color_by', null);
  const [sampleDisplay, setSampleDisplay] = usePersistedVizControl<SampleDisplay>(metadata, 'sample_display', 'select');
  const [pickedSample, setPickedSample] = usePersistedVizControl<string | null>(metadata, 'default_sample', null);
  const [yAxis, setYAxis] = usePersistedVizControl<SpatialYAxis>(metadata, 'y_axis', 'image');
  const [colourScale, setColourScale] = usePersistedVizControl<ColourScale>(metadata, 'colour_scale', 'Viridis');
  const [reverseScale, setReverseScale] = usePersistedVizControl<boolean>(metadata, 'reverse_scale', false);
  const [transform, setTransform] = usePersistedVizControl<SpatialTransform>(metadata, 'transform', 'none');
  const [cofactor, setCofactor] = usePersistedVizControl<number>(metadata, 'asinh_cofactor', 150);
  const [clipLow, setClipLow] = usePersistedVizControl<number>(metadata, 'clip_low_pct', 1);
  const [clipHigh, setClipHigh] = usePersistedVizControl<number>(metadata, 'clip_high_pct', 99);
  const [sizeByArea, setSizeByArea] = usePersistedVizControl<boolean>(metadata, 'size_by_area', true);
  const [pointSize, setPointSize] = usePersistedVizControl<number>(metadata, 'point_size', 4);
  const [opacity, setOpacity] = usePersistedVizControl<number>(metadata, 'opacity', 0.9);
  const [legendPos, setLegendPos] = usePersistedVizControl<LegendPos>(metadata, 'legend_pos', 'right');
  const [showBackground, setShowBackground] = usePersistedVizControl<boolean>(metadata, 'show_background', true);
  const [backgroundOpacity, setBackgroundOpacity] = usePersistedVizControl<number>(metadata, 'background_opacity', 0.7);
  const [hoverCols, setHoverCols] = usePersistedVizControl<string[]>(metadata, 'hover_cols', []);
  const maxPointSize = config.max_point_size ?? 40;

  // ---- Marker columns -------------------------------------------------------
  // A pattern needs the schema; so does the hover-column picker. Optional: a
  // tile with an explicit marker list draws without it.
  const [schema, setSchema] = useState<Record<string, string> | null>(null);
  useEffect(() => {
    if (!metadata.dc_id) return;
    let cancelled = false;
    fetchPolarsSchema(metadata.dc_id)
      .then((s) => {
        if (!cancelled) setSchema(s);
      })
      .catch(() => {
        if (!cancelled) setSchema({});
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id]);

  const markers = useMemo(
    () =>
      resolveMarkerColumns({
        schema,
        valueColumns: config.value_columns,
        pattern: config.value_columns_pattern,
        valueCol: config.value_col,
        exclude: [cellIdCol, xCol, yCol, areaCol, sampleCol, categoryCol],
      }),
    [schema, config.value_columns, config.value_columns_pattern, config.value_col, cellIdCol, xCol, yCol, areaCol, sampleCol, categoryCol],
  );
  const marker = pickMarker(markers, pickedMarker);
  const effectiveColorBy: ColorBy =
    colorBy === 'category' && categoryCol
      ? 'category'
      : colorBy === 'value' && marker
        ? 'value'
        : marker
          ? 'value'
          : 'category';

  // ---- Selection --------------------------------------------------------------
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);
  const keyCol = selectionColumn ?? cellIdCol;

  const requiredCols = useMemo(() => {
    const cols: string[] = [];
    for (const c of [cellIdCol, xCol, yCol, keyCol, sampleCol, areaCol, categoryCol, marker, ...hoverCols]) {
      if (c && !cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [cellIdCol, xCol, yCol, keyCol, sampleCol, areaCol, categoryCol, marker, hoverCols]);

  // Never narrowed by its own lasso, nor by another tile's pick on the column
  // it selects on: it keeps every cell and marks the picked ones instead.
  const filtersForFetch = useMemo(
    () => filtersForSelector(filters, metadata.index, 'scatter_selection', selectionColumn),
    [filters, metadata.index, selectionColumn],
  );
  const ownSelectionActive = hasOwnSelection(filters, metadata.index, 'scatter_selection');
  const selectionRevision = useSelectionRevision(ownSelectionActive);
  const markedSignature = useMemo(() => {
    if (!selectionColumn || ownSelectionActive) return '';
    return JSON.stringify(Array.from(valuesOnColumn(filters, selectionColumn)).sort());
  }, [filters, selectionColumn, ownSelectionActive]);
  const markedKeys = useMemo(
    () => (markedSignature ? new Set<string>(JSON.parse(markedSignature) as string[]) : null),
    [markedSignature],
  );

  // ---- Rows ---------------------------------------------------------------
  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [fullLoad, setFullLoad] = useState(false);
  const [reduction, setReduction] = useState<{ total: number; sampled: boolean } | null>(null);
  const filterSig = JSON.stringify(filtersForFetch);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id) {
      setError('Spatial cells: missing data binding');
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
      vizKind: SPATIAL_CELLS_VIZ_KIND,
      roles: { cell_id: cellIdCol, x: xCol, y: yCol },
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setReduction({ total: res.total_rows ?? res.row_count, sampled: Boolean(res.sampled) });
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), filterSig, refreshTick, fullLoad]);

  // ---- Image underlay -------------------------------------------------------
  // Either a URL template with a fixed pixel size, or one preview per sample in
  // an Image DC (its manifest names the file and its size). The DC's
  // `s3_base_folder` turns a row's relative path into the public serve URL.
  const [underlays, setUnderlays] = useState<Map<string, Underlay> | null>(null);
  const backgroundDcId = config.background_dc_id || null;
  useEffect(() => {
    if (!backgroundDcId) {
      setUnderlays(null);
      return;
    }
    let cancelled = false;
    const sampleKey = config.background_sample_col || 'sample';
    const widthKey = config.background_width_col || 'width';
    const heightKey = config.background_height_col || 'height';
    (async () => {
      const dc = (await fetchDataCollectionConfig(backgroundDcId)) as Record<string, any>;
      const props = (dc?.config?.dc_specific_properties ?? dc?.dc_specific_properties ?? {}) as Record<
        string,
        unknown
      >;
      const imageKey = config.background_image_col || (props.image_column as string) || 'image_path';
      const base = (props.s3_base_folder as string) || '';
      const res = await fetchAdvancedVizData({
        wfId: config.background_wf_id || metadata.wf_id || '',
        dcId: backgroundDcId,
        columns: [sampleKey, imageKey, widthKey, heightKey],
        filters: [],
      });
      const out = new Map<string, Underlay>();
      const n = (res.rows[imageKey] ?? []).length;
      for (let i = 0; i < n; i += 1) {
        const path = res.rows[imageKey]?.[i];
        const width = toNumber(res.rows[widthKey]?.[i]);
        const height = toNumber(res.rows[heightKey]?.[i]);
        if (typeof path !== 'string' || !width || !height) continue;
        out.set(String(res.rows[sampleKey]?.[i] ?? ''), {
          source: imageServeUrl(base, path),
          width,
          height,
        });
      }
      if (!cancelled) setUnderlays(out);
    })().catch((err: unknown) => {
      // No underlay is a smaller picture, not a broken tile.
      console.warn('spatial_cells: image underlay unavailable', err);
      if (!cancelled) setUnderlays(new Map());
    });
    return () => {
      cancelled = true;
    };
  }, [
    backgroundDcId,
    config.background_wf_id,
    config.background_image_col,
    config.background_sample_col,
    config.background_width_col,
    config.background_height_col,
    metadata.wf_id,
  ]);

  const underlayFor = useCallback(
    (sample: string): Underlay | null => {
      if (!showBackground) return null;
      if (config.background_url && config.background_width && config.background_height) {
        return {
          source: fillUrlTemplate(config.background_url, sample),
          width: config.background_width,
          height: config.background_height,
        };
      }
      return underlays?.get(sample) ?? (underlays && underlays.size === 1 ? Array.from(underlays.values())[0] : null);
    },
    [showBackground, config.background_url, config.background_width, config.background_height, underlays],
  );
  const imageScale = config.background_image_scale ?? 1;

  // ---- Cells --------------------------------------------------------------
  const cells = useMemo(() => {
    if (!rows) return null;
    const xs = (rows[xCol] ?? []).map(toNumber);
    const ys = (rows[yCol] ?? []).map(toNumber);
    const n = Math.min(xs.length, ys.length);
    let keep: number[] = [];
    for (let i = 0; i < n; i += 1) if (xs[i] !== null && ys[i] !== null) keep.push(i);
    const thinned = thinIndices(keep.length, maxCells);
    if (thinned) keep = thinned.map((j) => keep[j]);
    return { xs, ys, keep, thinned: Boolean(thinned) };
  }, [rows, xCol, yCol, maxCells]);

  const samples = useMemo(() => {
    if (!rows || !cells) return null;
    const sampleValues = sampleCol ? (rows[sampleCol] ?? null) : null;
    const byPosition = groupRowsBySample(
      sampleValues ? cells.keep.map((i) => sampleValues[i]) : null,
      cells.keep.length,
    );
    const out = new Map<string, number[]>();
    for (const [name, positions] of byPosition) out.set(name, positions.map((p) => cells.keep[p]));
    return out;
  }, [rows, cells, sampleCol]);
  const sampleNames = useMemo(() => (samples ? Array.from(samples.keys()) : []), [samples]);
  const facetMode = Boolean(sampleCol) && sampleDisplay === 'facet' && sampleNames.length > 1;
  const shownSamples = useMemo(() => {
    if (!sampleCol) return sampleNames;
    if (facetMode) return sampleNames.slice(0, Math.max(1, maxFacets));
    const one = pickSample(sampleNames, pickedSample ?? config.default_sample);
    return one === null ? [] : [one];
  }, [sampleCol, facetMode, sampleNames, maxFacets, pickedSample, config.default_sample]);

  // The colour range is taken over the cells shown, so a dim sample is not
  // drawn in the bottom colour because a bright one sits in another facet.
  const colour = useMemo(() => {
    if (!rows || !samples || effectiveColorBy !== 'value' || !marker) return null;
    const raw = (rows[marker] ?? []).map(toNumber);
    const k = transform === 'asinh' ? cofactor : 150;
    const transformed = raw.map((v) => (v === null ? null : transformValue(v, transform, k)));
    const shown: (number | null)[] = [];
    for (const s of shownSamples) for (const i of samples.get(s) ?? []) shown.push(transformed[i]);
    return { raw, transformed, range: clipRange(shown, clipLow, clipHigh) };
  }, [rows, samples, effectiveColorBy, marker, transform, cofactor, shownSamples, clipLow, clipHigh]);

  // The frame of each shown sample: its image when it has one (the cells may
  // not reach the image edges), the cells' bounding box otherwise.
  const frames = useMemo(() => {
    if (!cells || !samples) return [];
    return shownSamples.map((s) => {
      const idx = samples.get(s) ?? [];
      const box = cellExtent(
        idx.map((i) => cells.xs[i]),
        idx.map((i) => cells.ys[i]),
      );
      const u = underlayFor(s);
      const img = u ? imageFrame(u.width, u.height, imageScale) : null;
      const frame = unionFrame(img, box ? padFrame(box) : null);
      return frame ?? { x0: 0, x1: 1, y0: 0, y1: 1 };
    });
  }, [cells, samples, shownSamples, underlayFor, imageScale]);

  // Screen px per coordinate unit, per facet, as Plotly last laid it out. It
  // follows the zoom, which is what keeps an area-sized cell the size of the
  // cell: reported on every update and stored only when it moved by > 3 %, so
  // the redraw it triggers settles in one pass.
  const [scales, setScales] = useState<number[]>([]);
  const scaleKey = `${shownSamples.join('|')}::${yAxis}`;
  useEffect(() => setScales([]), [scaleKey]);
  const [plotWidth, setPlotWidth] = useState(0);
  const readScales = useCallback(
    (gd: any) => {
      const layout = gd?._fullLayout;
      if (!layout) return;
      // The plot area's width, for the content demand below.
      const inner = Number(layout._size?.w) || 0;
      setPlotWidth((prev) => (Math.abs(inner - prev) > 4 ? inner : prev));
      const next = shownSamples.map((_, i) => Math.abs(Number(layout[i === 0 ? 'xaxis' : `xaxis${i + 1}`]?._m) || 0));
      setScales((prev) => {
        const moved =
          prev.length !== next.length ||
          next.some((v, i) => v > 0 && (!(prev[i] > 0) || Math.abs(v - prev[i]) / prev[i] > 0.03));
        return moved ? next : prev;
      });
    },
    [shownSamples],
  );

  const figure = useMemo(() => {
    if (!rows || !cells || !samples || shownSamples.length === 0) return null;
    const ids = rows[cellIdCol] ?? [];
    const keys = rows[keyCol] ?? ids;
    const areas = areaCol ? (rows[areaCol] ?? []).map(toNumber) : null;
    const categories = categoryCol ? (rows[categoryCol] ?? []) : null;
    const extras = hoverCols.map((c) => rows[c] ?? []);
    const domains = facetMode ? facetDomains(shownSamples.length) : [[0, 1] as [number, number]];
    const marked =
      markedKeys && cells.keep.some((i) => markedKeys.has(String(keys[i] ?? ''))) ? markedKeys : null;

    const categoryNames =
      effectiveColorBy === 'category' && categories
        ? Array.from(new Set(cells.keep.map((i) => String(categories[i] ?? '')))).sort()
        : [];
    const categoryColours = stableColorMap(categoryNames, palette, pinnedColours);

    const data: Record<string, unknown>[] = [];
    const images: Record<string, unknown>[] = [];
    const annotations: Record<string, unknown>[] = [];
    const layoutAxes: Record<string, unknown> = {};
    const axisStyle = plotlyAxisOverrides(isDark, theme);

    shownSamples.forEach((sample, f) => {
      const suffix = f === 0 ? '' : String(f + 1);
      const xref = `x${suffix}`;
      const yref = `y${suffix}`;
      const frame: Frame = frames[f];
      const ranges = axisRanges(frame, yAxis);
      const ppu = scales[f] > 0 ? scales[f] : pixelsPerUnit(frame, GUESS_PLOT_PX, GUESS_PLOT_PX);
      const idx = samples.get(sample) ?? [];
      const diameters =
        sizeByArea && areas
          ? cellDiameters(
              idx.map((i) => areas[i]),
              ppu,
              pointSize,
              maxPointSize,
            )
          : idx.map(() => pointSize);
      const sizeOf = new Map<number, number>();
      idx.forEach((row, j) => sizeOf.set(row, diameters[j]));

      const hoverFor = (i: number): string => {
        const lines = [`<b>${String(ids[i] ?? '')}</b>`];
        if (sampleCol && !facetMode) lines.push(`${sampleCol}: ${sample}`);
        if (marker && colour) lines.push(`${marker}: ${formatHoverNumber(colour.raw[i])}`);
        if (categories) lines.push(`${categoryCol}: ${String(categories[i] ?? '')}`);
        if (areas) lines.push(`${areaCol}: ${formatHoverNumber(areas[i])}`);
        hoverCols.forEach((c, k) => lines.push(`${c}: ${String(extras[k][i] ?? '')}`));
        lines.push(`${xCol}, ${yCol}: ${formatHoverNumber(cells.xs[i])}, ${formatHoverNumber(cells.ys[i])}`);
        return lines.join('<br>');
      };
      const traceFor = (rowsOfTrace: number[], extra: Record<string, unknown>) => ({
        type: 'scattergl' as const,
        mode: 'markers' as const,
        xaxis: xref,
        yaxis: yref,
        x: rowsOfTrace.map((i) => cells.xs[i]),
        y: rowsOfTrace.map((i) => cells.ys[i]),
        // Slot 0 is the selection key, which a lasso and the group split read.
        customdata: rowsOfTrace.map((i) => [String(keys[i] ?? '')]),
        text: rowsOfTrace.map(hoverFor),
        hovertemplate: '%{text}<extra></extra>',
        ...extra,
        marker: {
          size: rowsOfTrace.map((i) => sizeOf.get(i) ?? pointSize),
          opacity: marked
            ? rowsOfTrace.map((i) => (marked.has(String(keys[i] ?? '')) ? opacity : opacity * DIMMED_OPACITY))
            : opacity,
          line: { width: 0 },
          ...((extra.marker as Record<string, unknown>) ?? {}),
        },
      });

      if (effectiveColorBy === 'value' && colour) {
        const range = colour.range;
        data.push(
          traceFor(idx, {
            name: sample || marker || 'cells',
            showlegend: false,
            marker: {
              color: idx.map((i) => colour.transformed[i] ?? range?.min ?? 0),
              colorscale: colourScale,
              reversescale: reverseScale,
              cmin: range?.min,
              cmax: range?.max,
              // One colour bar, on the last facet, so facets do not each grow one.
              showscale: f === shownSamples.length - 1,
              colorbar: {
                thickness: 10,
                len: 0.8,
                title: {
                  text: transform === 'none' ? marker : `${transform}(${marker})`,
                  side: 'right',
                },
              },
            },
          }),
        );
      } else if (effectiveColorBy === 'category' && categories) {
        const groups = new Map<string, number[]>();
        for (const i of idx) {
          const k = String(categories[i] ?? '');
          const bucket = groups.get(k);
          if (bucket) bucket.push(i);
          else groups.set(k, [i]);
        }
        for (const name of categoryNames) {
          const g = groups.get(name);
          if (!g || g.length === 0) continue;
          data.push(
            traceFor(g, {
              name: name || '(blank)',
              legendgroup: name,
              showlegend: f === 0,
              marker: { color: categoryColours.get(name) },
            }),
          );
        }
      } else {
        data.push(
          traceFor(idx, { name: sample || 'cells', showlegend: false, marker: { color: palette[0] } }),
        );
      }

      const u = underlayFor(sample);
      if (u) {
        images.push(
          underlayImage({
            source: u.source,
            width: u.width,
            height: u.height,
            scale: imageScale,
            yAxis,
            opacity: backgroundOpacity,
            xref,
            yref,
          }),
        );
      }

      layoutAxes[`xaxis${suffix}`] = {
        ...axisStyle,
        domain: domains[f],
        range: ranges.x,
        anchor: yref,
        title: { text: 'Centroid x', standoff: 4, font: { size: 11 } },
        zeroline: false,
        showgrid: false,
        ticks: 'outside',
        tickfont: { size: 10 },
      };
      layoutAxes[`yaxis${suffix}`] = {
        ...axisStyle,
        range: ranges.y,
        anchor: xref,
        // Named once, on the first facet: the others share its meaning.
        title: { text: f === 0 ? 'Centroid y' : '', standoff: 4, font: { size: 11 } },
        // Equal aspect always: a cell is round, a tissue keeps its shape.
        scaleanchor: xref,
        scaleratio: 1,
        zeroline: false,
        showgrid: false,
        ticks: 'outside',
        tickfont: { size: 10 },
      };
      if (facetMode) {
        annotations.push({
          text: `<b>${sample}</b>`,
          xref: 'paper',
          yref: 'paper',
          x: (domains[f][0] + domains[f][1]) / 2,
          y: 1,
          yanchor: 'bottom',
          xanchor: 'center',
          showarrow: false,
          font: { size: 11 },
        });
      }
    });

    const legendShown = legendPos !== 'none' && effectiveColorBy === 'category' && categoryNames.length > 1;
    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      ...layoutAxes,
      // A bottom legend sits under the x title, not over it.
      margin: { l: 56, r: 12, t: facetMode ? 22 : 8, b: legendShown && legendPos === 'bottom' ? 76 : 44 },
      images,
      annotations,
      showlegend: legendShown,
      legend:
        legendPos === 'bottom'
          ? { orientation: 'h' as const, x: 0, y: -0.1, yanchor: 'top' as const, font: { size: 10 } }
          : { orientation: 'v' as const, x: 1.02, y: 1, font: { size: 10 }, itemsizing: 'constant' as const },
      hovermode: 'closest' as const,
      dragmode: selectionEnabled ? ('lasso' as const) : ('zoom' as const),
      // A new sample or orientation is a new picture; anything else keeps the
      // reader's zoom.
      uirevision: scaleKey,
      selectionrevision: `sel-${selectionRevision}`,
      autosize: true,
    };
    return { data, layout };
  }, [
    rows,
    cells,
    samples,
    shownSamples,
    frames,
    scales,
    cellIdCol,
    keyCol,
    areaCol,
    categoryCol,
    sampleCol,
    xCol,
    yCol,
    hoverCols,
    facetMode,
    markedKeys,
    effectiveColorBy,
    colour,
    marker,
    palette,
    pinnedColours,
    isDark,
    theme,
    yAxis,
    sizeByArea,
    pointSize,
    maxPointSize,
    opacity,
    colourScale,
    reverseScale,
    transform,
    underlayFor,
    imageScale,
    backgroundOpacity,
    legendPos,
    selectionEnabled,
    selectionRevision,
    scaleKey,
  ]);

  // Lasso, box and click all land on the same `(index, 'scatter_selection')`
  // entry: the last gesture replaces the previous one, a deselect clears it.
  const emitSelection = useCallback(
    (values: string[]) => {
      if (!onFilterChange || !selectionColumn) return;
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, values));
    },
    [onFilterChange, selectionColumn, metadata],
  );
  const handleSelected = useCallback(
    (event: any) => emitSelection(extractScatterSelection(event, 0)),
    [emitSelection],
  );
  const handleDeselect = useCallback(() => emitSelection([]), [emitSelection]);
  const gdRef = usePlotSelectionReset(filters, metadata.index);
  const onPlotUpdate = useCallback(
    (_fig: unknown, gd: unknown) => {
      gdRef.current = gd as HTMLElement;
      readScales(gd);
    },
    [gdRef, readScales],
  );
  // The relayout of a zoom carries no new data, so react-plotly fires no
  // update for it; the scale is re-read here.
  const plotHost = useRef<unknown>(null);
  const onRelayout = useCallback(() => readScales(gdRef.current ?? plotHost.current), [readScales, gdRef]);

  const groupedFigure = useMemo(
    () =>
      figure
        ? splitFigureByGroups(figure, { groupRender, identitySlot: 0, facetable: false, showLegend: true })
        : figure,
    [figure, groupRender],
  );
  useReportGroupColouring(groupRender, figure, groupedFigure);
  const plotData = useMemo(
    () => (groupedFigure ? applyDataTheme(groupedFigure.data, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  const plotLayout = useMemo(
    () => (groupedFigure ? applyLayoutTheme(groupedFigure.layout as any, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );

  // ---- Controls -------------------------------------------------------------
  const markerOptions = markers.map((m) => ({ value: m, label: m }));
  const hoverCandidates = useMemo(
    () => Object.keys(schema ?? {}).filter((c) => !requiredCols.includes(c) || hoverCols.includes(c)),
    [schema, requiredCols, hoverCols],
  );
  // Encoding tier: what the cells are coloured by and which image is shown.
  const primaryControls = (
    <>
      {markers.length > 0 ? (
        <VizSelect
          label="Marker"
          value={marker}
          onChange={(v) => {
            if (!v) return;
            setPickedMarker(v);
            setColorBy('value');
          }}
          data={markerOptions}
          searchable={markers.length > 8}
          allowDeselect={false}
        />
      ) : null}
      {marker && categoryCol ? (
        <VizSegmented
          label="Colour"
          value={effectiveColorBy}
          onChange={(v) => setColorBy(v as ColorBy)}
          data={[
            { value: 'value', label: 'Marker' },
            { value: 'category', label: categoryCol },
          ]}
        />
      ) : null}
      {sampleCol && !facetMode && sampleNames.length > 1 ? (
        <VizSelect
          label="Sample"
          value={shownSamples[0] ?? null}
          onChange={(v) => v && setPickedSample(v)}
          data={sampleNames}
          allowDeselect={false}
        />
      ) : null}
      {effectiveColorBy === 'value' && marker ? (
        <VizSegmented
          label="Transform"
          value={transform}
          onChange={(v) => setTransform(v as SpatialTransform)}
          data={[
            { value: 'none', label: 'Linear' },
            { value: 'asinh', label: 'asinh' },
            { value: 'log1p', label: 'log1p' },
          ]}
        />
      ) : null}
    </>
  );

  const controls = (
    <>
      {effectiveColorBy === 'value' && marker ? (
        <VizControlGroup title="Colour range">
          <VizNumberInput
            label="Clip low (pct)"
            value={clipLow}
            onChange={(v) => setClipLow(Math.min(Number(v) || 0, clipHigh - 1))}
            min={0}
            max={50}
          />
          <VizNumberInput
            label="Clip high (pct)"
            value={clipHigh}
            onChange={(v) => setClipHigh(Math.max(Number(v) || 100, clipLow + 1))}
            min={50}
            max={100}
          />
          {transform === 'asinh' ? (
            <VizNumberInput
              label="asinh cofactor"
              value={cofactor}
              onChange={(v) => setCofactor(Math.max(0.01, Number(v) || 150))}
              min={0.01}
            />
          ) : null}
          <VizSelect
            label="Colour scale"
            value={colourScale}
            onChange={(v) => v && setColourScale(v as ColourScale)}
            data={COLOUR_SCALES as unknown as string[]}
            allowDeselect={false}
          />
          <VizSwitch
            checked={reverseScale}
            onChange={(e) => setReverseScale(e.currentTarget.checked)}
            label="Reverse scale"
          />
        </VizControlGroup>
      ) : null}
      <VizControlGroup title="Cells">
        {areaCol ? (
          <VizSwitch
            checked={sizeByArea}
            onChange={(e) => setSizeByArea(e.currentTarget.checked)}
            label="Size by area"
          />
        ) : null}
        <VizNumberInput
          label={areaCol && sizeByArea ? 'Min size (px)' : 'Size (px)'}
          value={pointSize}
          onChange={(v) => setPointSize(Math.max(0.5, Number(v) || 4))}
          min={0.5}
          max={40}
        />
        <VizSlider
          label="Opacity"
          value={opacity}
          onChangeEnd={setOpacity}
          min={0.05}
          max={1}
          step={0.05}
          thumbLabel={(v) => v.toFixed(2)}
        />
      </VizControlGroup>
      <VizControlGroup title="Frame">
        <VizSegmented
          label="Y axis"
          value={yAxis}
          onChange={(v) => setYAxis(v as SpatialYAxis)}
          data={[
            { value: 'image', label: 'Image (y down)' },
            { value: 'cartesian', label: 'Plot (y up)' },
          ]}
        />
        {sampleCol && sampleNames.length > 1 ? (
          <VizSegmented
            label="Samples"
            value={sampleDisplay}
            onChange={(v) => setSampleDisplay(v as SampleDisplay)}
            data={[
              { value: 'select', label: 'One' },
              { value: 'facet', label: 'Side by side' },
            ]}
          />
        ) : null}
        {config.background_url || backgroundDcId ? (
          <>
            <VizSwitch
              checked={showBackground}
              onChange={(e) => setShowBackground(e.currentTarget.checked)}
              label="Image underlay"
            />
            <VizSlider
              label="Image opacity"
              value={backgroundOpacity}
              onChangeEnd={setBackgroundOpacity}
              min={0}
              max={1}
              step={0.05}
              thumbLabel={(v) => v.toFixed(2)}
            />
          </>
        ) : null}
      </VizControlGroup>
      <VizControlGroup title="Legend & hover">
        {effectiveColorBy === 'category' ? (
          <VizSelect
            label="Legend"
            value={legendPos}
            onChange={(v) => setLegendPos((v as LegendPos) || 'right')}
            data={[
              { value: 'right', label: 'Right' },
              { value: 'bottom', label: 'Bottom' },
              { value: 'none', label: 'Hidden' },
            ]}
            allowDeselect={false}
          />
        ) : null}
        <VizMultiSelect
          label="Hover columns"
          value={hoverCols}
          onChange={setHoverCols}
          data={hoverCandidates}
          searchable
          clearable
        />
      </VizControlGroup>
    </>
  );

  // ---- Echo and counts ------------------------------------------------------
  const drawn = useMemo(
    () => shownSamples.reduce((n, s) => n + (samples?.get(s)?.length ?? 0), 0),
    [shownSamples, samples],
  );
  const echo = useMemo(() => {
    if (!cells || shownSamples.length === 0) return undefined;
    const where = facetMode
      ? `${shownSamples.length} images`
      : sampleCol && shownSamples[0]
        ? shownSamples[0]
        : null;
    const what = effectiveColorBy === 'value' && marker ? marker : categoryCol;
    return [where, `${drawn.toLocaleString()} cells`, what].filter(Boolean).join(' · ');
  }, [cells, shownSamples, facetMode, sampleCol, drawn, effectiveColorBy, marker, categoryCol]);
  const capped = Boolean(cells?.thinned);
  // Content-aware sizing: the height at which the image fills the tile's
  // width, so a wide tile grows instead of letterboxing the tissue between
  // two empty bands. `advanced_viz` only grows, so a tile sized taller keeps
  // its height.
  const contentDemand = useMemo(
    () =>
      plotWidth > 0 && frames.length > 0
        ? demandForPx(heightForFrames(frames, plotWidth) + SPATIAL_CHROME_PX)
        : undefined,
    [plotWidth, frames],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Spatial cells'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      echo={echo}
      contentDemand={contentDemand}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={cells && cells.keep.length === 0 ? 'No cells with coordinates' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      reduction={
        reduction && (reduction.sampled || capped || fullLoad)
          ? {
              displayed: cells?.keep.length ?? 0,
              total: reduction.total,
              sampled: reduction.sampled || capped,
              full: fullLoad,
              loading,
              onToggle: () => setFullLoad((value) => !value),
            }
          : undefined
      }
    >
      {plotData && plotLayout ? (
        <AdvancedVizPlot
          data={plotData as any}
          layout={plotLayout as any}
          useResizeHandler
          style={PLOT_STYLE}
          config={(selectionEnabled ? PLOT_CONFIG_SELECT : PLOT_CONFIG_PLAIN) as any}
          onSelected={selectionEnabled ? handleSelected : undefined}
          onClick={selectionEnabled ? handleSelected : undefined}
          onDeselect={selectionEnabled ? handleDeselect : undefined}
          onInitialized={(fig, gd) => {
            plotHost.current = gd;
            onPlotUpdate(fig, gd);
          }}
          onUpdate={onPlotUpdate}
          onRelayout={onRelayout}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default SpatialCellsRenderer;
