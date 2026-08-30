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
import AdvancedVizPlot from './AdvancedVizPlot';

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
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  extractScatterSelection,
  filtersExcludingOwn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyThemeColors } from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

type ComputeMethod = 'pca' | 'umap' | 'tsne' | 'pcoa';

interface EmbeddingConfig {
  sample_id_col: string;
  dim_1_col: string;
  dim_2_col: string;
  dim_3_col?: string | null;
  cluster_col?: string | null;
  color_col?: string | null;
  /** Explicit value→colour overrides for the categorical colour column.
   *  Wins over the default palette-index assignment from stableColorMap. */
  category_palette?: Record<string, string> | null;
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
  /** Opt into lasso/box/click selection as a dashboard filter. Resolved
   *  through `advancedVizSelectionColumn`, which is what the chrome's
   *  capability marker reads too. */
  selection_enabled?: boolean;
  /** Column the emitted values belong to; null means `sample_id_col`. */
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: EmbeddingConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Emits this component's selection as a dashboard filter. Absent on
   *  read-only hosts (catalog, project previews), which is what keeps the
   *  lasso off there. */
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// Past this many distinct values, one trace and one legend entry per value is
// not a plot: colouring falls back to a single trace with a per-point colour
// array. Reachable now that the Colour-by menu lists every column of the DC.
const MAX_CATEGORY_TRACES = 40;
// A contour drawn over a handful of points is noise, not a density.
const MIN_DENSITY_POINTS = 8;
// Polars dtype prefixes that mean "this column gets a continuous colourscale".
const NUMERIC_DTYPE_PREFIXES = ['Int', 'UInt', 'Float', 'Decimal'];

/** `colour` at `alpha`, for the two-stop density colourscales. Plotly needs an
 *  explicit transparent stop and hex carries no alpha channel. Anything the
 *  helper cannot parse degrades to fully transparent below 1 and to the colour
 *  itself at 1, which is exactly the pair of stops we ever ask for. */
function withAlpha(colour: string, alpha: number): string {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(colour.trim());
  if (!match) return alpha >= 1 ? colour : 'rgba(0,0,0,0)';
  const hex =
    match[1].length === 3
      ? match[1]
          .split('')
          .map((c) => c + c)
          .join('')
      : match[1];
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

const EmbeddingRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as EmbeddingConfig;
  // 6 to agree with EmbeddingConfig.point_size in
  // depictio/models/components/advanced_viz/configs.py. The two layers used to
  // disagree, so an unconfigured component drew 7 px and a configured one 6.
  const [pointSize, setPointSize] = usePersistedVizControl(metadata, 'point_size', 6);
  const [showCentroids, setShowCentroids] = usePersistedVizControl(metadata, 'show_centroids', false);
  const [markerOutline, setMarkerOutline] = usePersistedVizControl(metadata, 'marker_outline', false);
  // Outline width in px. The old hardcoded 0.5 was invisible at any point size,
  // which is what the "outline?? je ne vois rien" report was about.
  const [outlineWidth, setOutlineWidth] = usePersistedVizControl(metadata, 'marker_outline_width', 1.5);
  // Axis furniture preset. "default" is exactly what this renderer has always
  // drawn (axis lines, no grid, no tick labels), so a shipped dashboard is
  // untouched; "grid" adds gridlines and ticks, and "clean" strips the axes,
  // which is the usual convention for a UMAP / t-SNE embedding.
  type PlotStyle = 'default' | 'grid' | 'clean';
  const [plotStyle, setPlotStyle] = usePersistedVizControl<PlotStyle>(metadata, 'plot_style', 'default');
  type LegendPos = 'right' | 'bottom' | 'in-tr' | 'hidden';
  const [legendPos, setLegendPos] = usePersistedVizControl<LegendPos>(metadata, 'legend_pos', 'right');
  const [ncontours, setNcontours] = usePersistedVizControl(metadata, 'ncontours', 14);
  const [densityOpacity, setDensityOpacity] = usePersistedVizControl(metadata, 'density_opacity', 0.45);
  const [colorBy, setColorBy] = usePersistedVizControl<string | null>(
    metadata,
    'default_color_by',
    config.cluster_col || config.color_col || null,
  );
  const [showDensity, setShowDensity] = usePersistedVizControl(metadata, 'show_density', false);

  // 3D toggle — disabled when no dim_3_col is configured. Default 2D: most
  // clustering reads happen in 2D and the third axis is opt-in.
  const has3DConfigured = Boolean(config.dim_3_col);
  const [view3D, setView3D] = usePersistedVizControl(metadata, 'view_3d', false);
  // Reverse-colourscale only meaningful for the continuous (numeric) branch.
  // Spectral runs red→blue by default; reverse=true → blue=low / red=high,
  // which matches most clustering-narrative defaults.
  const [reverseScale, setReverseScale] = usePersistedVizControl(metadata, 'reverse_scale', true);

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
  const [hoverCols, setHoverCols] = usePersistedVizControl<string[]>(metadata, 'hover_cols', []);

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
  const [nNeighbors, setNNeighbors] = usePersistedVizControl(metadata, 'umap_n_neighbors', 15);
  const [minDist, setMinDist] = usePersistedVizControl(metadata, 'umap_min_dist', 0.1);
  const [perplexity, setPerplexity] = usePersistedVizControl(metadata, 'tsne_perplexity', 30);

  // ---- Selection as a cross-filter ---------------------------------------
  // The column resolves to sample_id_col unless the dashboard names another
  // one; `undefined` means this component does not select at all, which is
  // also what the chrome's capability marker reads (see selection.ts). A host
  // with no onFilterChange is read-only, so it advertises nothing.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);
  // Every point already carries its sample id in customdata slot 0, so that is
  // the slot to read when selecting on the sample id itself. A different
  // column rides in a slot of its own after the hover extras, which leaves the
  // hover template, and the identity it shows from slot 0, exactly as it was.
  const selectionInOwnSlot = Boolean(selectionColumn) && selectionColumn !== config.sample_id_col;
  const selectionSlot = selectionInOwnSlot ? 1 + hoverCols.length : 0;

  const requiredCols = useMemo(() => {
    const cols = [config.sample_id_col, config.dim_1_col, config.dim_2_col].filter(Boolean) as string[];
    if (config.dim_3_col) cols.push(config.dim_3_col);
    if (config.cluster_col) cols.push(config.cluster_col);
    if (config.color_col && !cols.includes(config.color_col)) cols.push(config.color_col);
    // Whatever the user is colouring by right now. The projection is built from
    // the configured roles, so a column picked in the Colour-by menu would
    // otherwise never be requested and the plot would stay one flat colour.
    if (colorBy && !cols.includes(colorBy)) cols.push(colorBy);
    for (const c of hoverCols) if (c && !cols.includes(c)) cols.push(c);
    if (selectionColumn && !cols.includes(selectionColumn)) cols.push(selectionColumn);
    return cols;
  }, [config, hoverCols, colorBy, selectionColumn]);

  // This component must NOT narrow itself by its own selection: a lasso would
  // otherwise redraw the embedding as only the points it caught, and the user
  // could never widen it again. Same rule FigureRenderer follows; every other
  // component still sees the entry and narrows.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

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
      fetchAdvancedVizData({
        wfId: metadata.wf_id,
        dcId: metadata.dc_id,
        columns: requiredCols,
        filters: filtersForFetch,
        vizKind: 'embedding',
      })
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
    // Same reason as requiredCols above: the worker only returns the extras it
    // is asked for, so the active Colour-by column has to travel with the job.
    if (colorBy && !extraCols.includes(colorBy)) extraCols.push(colorBy);
    for (const c of hoverCols) if (c && !extraCols.includes(c)) extraCols.push(c);
    // The worker returns the sample ids on its own, so only a selection column
    // that is something else has to travel as an extra.
    if (selectionInOwnSlot && selectionColumn && !extraCols.includes(selectionColumn)) {
      extraCols.push(selectionColumn);
    }
    const payload = {
      wf_id: metadata.wf_id,
      dc_id: metadata.dc_id,
      feature_id_col: config.sample_id_col,
      method,
      params: computeParams,
      filter_metadata: filtersForFetch,
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
    JSON.stringify(filtersForFetch),
    refreshTick,
    method,
    JSON.stringify(computeParams),
    JSON.stringify(hoverCols),
    colorBy,
    selectionColumn,
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

    // Hover-extras: customdata slot 0 = sample id, slots 1..N = extra cols,
    // then the selection column when it is not the sample id (see
    // `selectionSlot`, which is what the Plotly handlers read).
    const extraValues = hoverCols.map((c) => (rows[c] as unknown[]) || []);
    // Nothing is appended when the column did not come back, which leaves the
    // slot the handlers read empty and degrades to "this gesture selected
    // nothing" rather than to a filter on a column of blanks. Missing values
    // ride as null for the same reason: `extractScatterSelection` skips them.
    const selectionSource =
      selectionInOwnSlot && selectionColumn
        ? (rows[selectionColumn] as unknown[] | undefined)
        : undefined;
    const selectionValues = selectionSource && selectionSource.length > 0 ? selectionSource : null;
    const buildCustomdata = (idxList: number[]) =>
      idxList.map((i) => [
        String(ids[i] ?? ''),
        ...extraValues.map((vs) => vs[i] ?? ''),
        ...(selectionValues ? [selectionValues[i] ?? null] : []),
      ]);
    const hoverExtraTpl = hoverCols
      .map((c, j) => `<br>${c}: %{customdata[${j + 1}]}`)
      .join('');

    const { textColor, gridColor, zeroLineColor } = plotlyThemeColors(isDark, theme);
    // Plaque behind in-plot text: the inside-top-right legend and the centroid
    // labels, both of which sit over the points.
    const inTrBg = isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.7)';

    const traces: any[] = [];
    const centroidAnnotations: any[] = [];

    // Category universe, per-category row indices and the colour map, built
    // once: the density overlay, the scatter traces and the centroid labels all
    // key off exactly the same grouping.
    const categories: string[] = [];
    const categoryIdx = new Map<string, number[]>();
    if (isCategorical && colorValues) {
      for (let i = 0; i < colorValues.length; i++) {
        const cat = String(colorValues[i]);
        const bucket = categoryIdx.get(cat);
        if (bucket) {
          bucket.push(i);
        } else {
          categoryIdx.set(cat, [i]);
          categories.push(cat);
        }
      }
      categories.sort();
    }
    const colourSource =
      isCategorical && colorValues
        ? stableColorMap(
            colorUniverse ?? categories,
            resolveCategoricalPalette(theme, TAB10_PALETTE),
            config.category_palette ?? null,
          )
        : null;
    // One trace per group only while the group count stays sane, see
    // MAX_CATEGORY_TRACES. Past it the colours survive but the traces collapse
    // into one, so picking a free-text column can't lock up the tab.
    const perCategoryTraces = Boolean(colourSource) && categories.length <= MAX_CATEGORY_TRACES;

    // 2D only: a volumetric density would dwarf the scatter, so 3D skips it.
    // This is a binned 2D histogram with smoothed contours, NOT a KDE: Plotly
    // has no KDE trace. Each group gets its own alpha ramp (transparent → the
    // group's own colour), which replaces the old flat Greys/Blues fill that
    // was dark-on-dark in dark mode and read as blocks rather than a density.
    if (!actuallyRender3D && showDensity && x.length > 1) {
      const densityAccent = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6] ?? textColor;
      const densityGroups =
        perCategoryTraces && colourSource
          ? categories.map((cat) => ({
              idx: categoryIdx.get(cat) ?? [],
              colour: colourSource.get(cat),
            }))
          : [{ idx: x.map((_, i) => i), colour: densityAccent }];
      for (const group of densityGroups) {
        if (group.idx.length < MIN_DENSITY_POINTS) continue;
        traces.push({
          type: 'histogram2dcontour' as const,
          x: group.idx.map((i) => x[i]),
          y: group.idx.map((i) => y[i]),
          colorscale: [
            [0, withAlpha(group.colour, 0)],
            [1, withAlpha(group.colour, 1)],
          ],
          showscale: false,
          opacity: densityOpacity,
          contours: { coloring: 'fill', showlines: false },
          // Smoothing on the contour paths is what stops the fill reading as a
          // staircase of histogram bins.
          line: { width: 0, smoothing: 1.3 },
          hoverinfo: 'skip',
          ncontours,
          showlegend: false,
        });
      }
    }

    const denseAutoSize = x.length > 1000 ? Math.min(pointSize, 4) : pointSize;
    // An opaque, contrasting stroke. The old line was 0.5 px of translucent
    // background colour, which was invisible at every point size.
    const outline = markerOutline ? { width: outlineWidth, color: textColor } : { width: 0 };
    const baseMarker2D = {
      size: denseAutoSize,
      opacity: 0.85,
      line: outline,
    };
    // scatter3d draws marker.line as a sprite border, so it takes the same
    // shape. It was simply never passed, which is why the outline toggle did
    // nothing at all in 3D.
    const baseMarker3D = {
      size: Math.max(2, Math.min(denseAutoSize, 6)),
      opacity: 0.9,
      line: outline,
    };

    const scatterType = actuallyRender3D ? ('scatter3d' as const) : ('scattergl' as const);

    if (perCategoryTraces && colourSource) {
      const centroids: { x: number; y: number; z?: number; label: string; colour: string }[] = [];
      for (const cat of categories) {
        const idx = categoryIdx.get(cat) ?? [];
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
          centroids.push({ x: cx, y: cy, z: cz, label: cat, colour: colourSource.get(cat) });
        }
      }
      if (showCentroids && centroids.length > 0) {
        // A cross marks the barycentre and the label rides above it as an
        // annotation: yshift is a pixel offset, so the text clears the points
        // at any zoom, and bgcolor gives it the plaque it needs to stay
        // readable over a dense cloud. The label used to be a text trace
        // planted exactly on the barycentre, i.e. under its own points.
        const centroidTrace: any = {
          type: scatterType,
          mode: 'markers' as const,
          x: centroids.map((c) => c.x),
          y: centroids.map((c) => c.y),
          marker: {
            symbol: 'x',
            size: Math.max(8, denseAutoSize + 4),
            color: centroids.map((c) => c.colour),
            line: { width: 1, color: textColor },
          },
          hoverinfo: 'skip' as const,
          showlegend: false,
        };
        if (actuallyRender3D) centroidTrace.z = centroids.map((c) => c.z);
        traces.push(centroidTrace);
        for (const c of centroids) {
          centroidAnnotations.push({
            x: c.x,
            y: c.y,
            ...(actuallyRender3D ? { z: c.z } : {}),
            text: c.label,
            showarrow: false,
            yshift: 16,
            font: { size: 11, color: textColor },
            bgcolor: inTrBg,
            bordercolor: c.colour,
            borderwidth: 1,
            borderpad: 2,
          });
        }
      }
    } else {
      // Three cases land here: a continuous colour column, no colour binding at
      // all, and a categorical column with more distinct values than
      // MAX_CATEGORY_TRACES (which keeps its per-value colours, as one trace).
      // The continuous case uses Spectral (optionally reversed) so cluster-heavy
      // reads get a perceptually-ordered diverging palette, not Viridis monotone.
      const colourArr = isCategorical ? undefined : (colorValues as number[] | undefined) ?? undefined;
      const categoricalColours =
        colourSource && colorValues ? colorValues.map((v) => colourSource.get(String(v))) : undefined;
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
          color: colourArr ?? categoricalColours ?? '#4C72B0',
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

    // Axis furniture, driven by the Plot style control. "default" reproduces
    // the historical look exactly, so nothing shipped moves unless the user
    // asks for gridlines or for the bare-canvas UMAP look.
    const gridStyle = plotStyle === 'grid';
    const cleanStyle = plotStyle === 'clean';
    const axisCommon = {
      zeroline: false,
      showgrid: gridStyle,
      gridcolor: gridColor,
      showticklabels: gridStyle,
      ticks: (gridStyle ? 'outside' : '') as '' | 'outside',
      showline: !cleanStyle,
      linecolor: zeroLineColor,
      linewidth: 1,
      mirror: false,
      color: textColor,
      tickfont: { color: textColor },
    };
    // The 3D scene already draws a grid and ticks by default, so only the
    // "clean" preset has anything to say there.
    const scene3DAxisStyle = cleanStyle
      ? { showgrid: false, showticklabels: false, zeroline: false }
      : {};

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
        ...scene3DAxisStyle,
      },
      yaxis: {
        title: { text: config.dim_2_col, font: { size: 11, color: textColor } },
        color: textColor,
        gridcolor: gridColor,
        tickfont: { color: textColor },
        ...scene3DAxisStyle,
      },
      zaxis: {
        title: {
          text: config.dim_3_col ?? 'dim_3',
          font: { size: 11, color: textColor },
        },
        color: textColor,
        gridcolor: gridColor,
        tickfont: { color: textColor },
        ...scene3DAxisStyle,
      },
      bgcolor: 'rgba(0,0,0,0)',
      aspectmode: 'cube' as const,
      // Scene annotations carry the centroid labels in 3D; the 2D branch puts
      // the same objects on layout.annotations below.
      ...(centroidAnnotations.length > 0 ? { annotations: centroidAnnotations } : {}),
    };

    return {
      data: traces,
      layout: {
        template: isDark ? 'plotly_dark' : 'plotly_white',
        font: { color: textColor },
        margin: actuallyRender3D ? { l: 0, r: 0, t: 8, b: 0 } : { l: 40, r: 12, t: 12, b: 40 },
        ...(actuallyRender3D ? { scene: scene3D, uirevision: 'embedding-3d' } : layout2D),
        ...(!actuallyRender3D && centroidAnnotations.length > 0
          ? { annotations: centroidAnnotations }
          : {}),
        // A legend only exists while there is one trace per group; the
        // collapsed high-cardinality fallback has nothing to list.
        showlegend: perCategoryTraces && legendPos !== 'hidden',
        legend: perCategoryTraces
          ? {
              ...legendForPos(legendPos),
              borderwidth: 0,
              font: { size: 11, color: textColor },
              itemsizing: 'constant',
              tracegroupgap: 4,
            }
          : undefined,
        // Drag draws a lasso instead of zooming, so the selection is reachable
        // without opening the modebar. 2D only: a 3D scene has no lasso, and
        // Plotly rejects the value on `scene` outright, so 3D keeps its
        // orbit-on-drag and can only select by clicking single points.
        ...(selectionEnabled && !actuallyRender3D ? { dragmode: 'lasso' as const } : {}),
        autosize: true,
        plot_bgcolor: 'rgba(0,0,0,0)',
        paper_bgcolor: 'rgba(0,0,0,0)',
      },
    };
  }, [
    rows,
    config,
    selectionEnabled,
    selectionColumn,
    selectionInOwnSlot,
    pointSize,
    colorBy,
    colorUniverse,
    showDensity,
    showCentroids,
    markerOutline,
    outlineWidth,
    plotStyle,
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

  // Colour-by candidates: every column of the DC, not only the two configured
  // roles. A computed cluster column, any annotation column and any numeric
  // column all belong in the same menu, which is what "pas uniquement legende
  // par valeur continue ou annotation mais aussi groupes realises" asks for.
  // The coordinates and the sample id stay out: colouring by a coordinate just
  // repaints an axis, and colouring by the id is one colour per point.
  const colorOptions: { value: string; label: string }[] = useMemo(() => {
    const skip = new Set<string>(
      [config.sample_id_col, config.dim_1_col, config.dim_2_col, config.dim_3_col].filter(
        Boolean,
      ) as string[],
    );
    const seen = new Set<string>();
    const opts: { value: string; label: string }[] = [];
    const push = (col: string | null | undefined, label: string) => {
      if (!col || skip.has(col) || seen.has(col)) return;
      seen.add(col);
      opts.push({ value: col, label });
    };
    // Configured roles first: they are what the dashboard author meant.
    push(config.cluster_col, `${config.cluster_col} (cluster)`);
    push(config.color_col, String(config.color_col));
    if (dcSchema) {
      for (const [col, dtype] of Object.entries(dcSchema)) {
        const numeric = NUMERIC_DTYPE_PREFIXES.some((p) => dtype.startsWith(p));
        push(col, numeric ? `${col} (continuous)` : col);
      }
    } else if (rows) {
      // No schema endpoint: offer what actually arrived, which is at least the
      // configured roles.
      for (const col of Object.keys(rows)) push(col, col);
    }
    return opts;
  }, [config, dcSchema, rows]);

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
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            View
          </Text>
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
        </Stack>
        <Select
          size="xs"
          label="Plot style"
          value={plotStyle}
          onChange={(v) => v && setPlotStyle(v as PlotStyle)}
          data={[
            { value: 'default', label: 'Axis lines' },
            { value: 'grid', label: 'Gridlines + ticks' },
            { value: 'clean', label: 'No axes' },
          ]}
          description="Axis furniture drawn around the points"
          allowDeselect={false}
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
              searchable
              clearable
            />
          ) : null}
        </Group>
        {colorByIsNumeric ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Colourscale
            </Text>
            <Switch
              size="xs"
              checked={reverseScale}
              onChange={(e) => setReverseScale(e.currentTarget.checked)}
              label="Reverse"
            />
          </Stack>
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
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Density
          </Text>
          <Switch
            size="xs"
            checked={showDensity}
            onChange={(e) => setShowDensity(e.currentTarget.checked)}
            label="Density overlay"
            disabled={view3D}
          />
        </Stack>
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
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Annotations
          </Text>
          <Switch
            size="xs"
            checked={showCentroids}
            onChange={(e) => setShowCentroids(e.currentTarget.checked)}
            label="Cluster centroids"
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Markers
          </Text>
          <Switch
            size="xs"
            checked={markerOutline}
            onChange={(e) => setMarkerOutline(e.currentTarget.checked)}
            label="Outline"
          />
          {markerOutline ? (
            <NumberInput
              size="xs"
              label="Outline width"
              value={outlineWidth}
              onChange={(v) => setOutlineWidth(Math.max(0.5, Math.min(4, Number(v) || 1.5)))}
              min={0.5}
              max={4}
              step={0.5}
              decimalScale={1}
            />
          ) : null}
        </Stack>
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
      plotStyle,
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
      outlineWidth,
      legendPos,
    ],
  );

  // Lasso / box / click all land on the same `(index, 'scatter_selection')`
  // entry, so the last gesture replaces the previous one and a deselect
  // clears it. Only the points Plotly actually drew can be caught: the data
  // endpoint serves a reduced frame (~100k rows), so a lasso over a truncated
  // cloud selects what is on screen, not the whole collection.
  const emitSelection = (values: string[]) => {
    if (!onFilterChange || !selectionColumn) return;
    onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, values));
  };
  const handleSelected = (event: any) => {
    if (!selectionEnabled) return;
    emitSelection(extractScatterSelection(event, selectionSlot));
  };
  // A single click is a one-point selection, which is how the scatter figures
  // and the Dash viewer have always read it.
  const handleClick = (event: any) => {
    if (!selectionEnabled) return;
    emitSelection(extractScatterSelection(event, selectionSlot));
  };
  const handleDeselect = () => {
    if (!selectionEnabled) return;
    emitSelection([]);
  };

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
        <AdvancedVizPlot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
          onSelected={selectionEnabled ? handleSelected : undefined}
          onClick={selectionEnabled ? handleClick : undefined}
          onDeselect={selectionEnabled ? handleDeselect : undefined}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default EmbeddingRenderer;
