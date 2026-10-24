import React, { useEffect, useMemo, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import { useElementSize } from '@mantine/hooks';
import Plot from './LegendAwarePlot';
import {
  VizControlGroup,
  VizNumberInput,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';

import {
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { isStaleFetch } from '../../fetchQueue';
import { columnCategoryColors } from '../../categoryColors';
import { resolveCategoricalPalette, stableColorMap } from '../../colors';
import { useCategoryColorSource } from '../../hooks/useCategoryColors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import { supportsAdvancedVizAnnotation } from '../../annotations/plotDecorate';
import { usePersistedVizControl } from './usePersistedVizControl';
import { withRanksInOrder } from './phylo/view';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { demandForPx } from './contentDemand';
import {
  axisBreakShapes,
  barSlots,
  compositionColumns,
  formatAxisFloor,
  groupSamples,
  isDenseTaxonomyAxis,
  isSpacerSlot,
  meltWideRows,
  percentTickFormat,
  resolveSortCategory,
  SAMPLE_SORT_OPTIONS,
  sortSamples,
  taxonomyAxisTitle,
  taxonomyLegend,
  taxonomyLegendTopPx,
  valueAxisTitle,
  visibleTaxonomyControls,
  wideCategoryName,
  zoomedValueRange,
  type TaxonomyLegendPos,
  type TaxonomyOrientation,
  type TaxonomySampleSort,
} from './stackedTaxonomyOptions';

/** The stacked bars run vertically: samples are the x axis, so the tile's
 *  height is furniture, not a count. This is the plot area a stack of
 *  proportions stays readable in once the tilted sample labels and the axis
 *  title have taken their share. */
const TAXONOMY_PLOT_PX = 300;
/** One bar of a horizontal chart (`orientation: h`), where the bar count is
 *  the tile's height problem. */
const BAR_ROW_PX = 18;
/** What a horizontal chart spends outside its rows: top margin, value axis
 *  ticks and title. */
const H_PLOT_CHROME_PX = 90;
/** One entry of the legend, a column right of the plot at 10 px: under the
 *  plot it fought the tilted sample labels for the same band. */
const LEGEND_ITEM_PX = 16;
/** Entries per row of a legend drawn in rows (`legend_pos: bottom`), roughly:
 *  a 10 px taxon name and its swatch across a w8 tile. */
const LEGEND_ROW_ITEMS = 5;
/** The legend's title and its padding. */
const LEGEND_CHROME_PX = 30;
/** One annotation strip: tall enough for its 10 px labels. */
const STRIP_BAND_PX = 22;
/** Between a strip and the bars (or the next strip), so the strip's name and
 *  the bars' top tick do not touch. */
const STRIP_GAP_PX = 8;
/** What the figure spends outside the plot area: the top margin and, below,
 *  the tilted sample labels and the axis title. */
const PLOT_CHROME_PX = 150;
/** Across a horizontal chart: the sample labels on the left and the legend
 *  column on the right. */
const H_PLOT_CHROME_W_PX = 260;
/** The frame's own header above the figure: title and row count. */
const FRAME_HEADER_PX = 60;
/** The band above a vertical chart that names its groups. */
const GROUP_LABEL_PX = 18;

/** Generic per-sample categorical annotation strip drawn above/below the
 *  stacked bars. Reusable across any viz with a sample axis when the DC
 *  carries a categorical metadata column the user wants visualised as a
 *  colour band (habitat, batch, treatment, timepoint, …). */
interface AnnotationStrip {
  /** Metadata column in the DC; values are looked up per sample. */
  column: string;
  /** Optional label shown to the left of the strip. Defaults to `column`. */
  label?: string;
  /** Where to draw the strip relative to the chart (right / left of
   *  horizontal bars). */
  position?: 'top' | 'bottom';
  /** Per-category colour overrides; falls back to TAB10-style cycling. */
  palette?: Record<string, string> | null;
}

interface StackedTaxonomyConfig {
  sample_id_col: string;
  taxon_col: string;
  /** Null (or a column the table lacks) draws a single-level composition;
   *  unset is the model default, `rank`. */
  rank_col?: string | null;
  abundance_col: string;
  /** Wide form: one numeric column per category, melted client-side. */
  value_cols?: string[] | null;
  /** Wide form: column -> category display name. */
  value_labels?: Record<string, string> | null;
  default_rank?: string | null;
  top_n?: number;
  sort_by?: 'abundance' | 'alphabetical';
  normalise_to_one?: boolean;
  /** Categorical annotation strips drawn alongside the bars. Each strip
   *  reads its values from the row's metadata column at the matching
   *  sample. Renderer ensures the fetched column list includes these. */
  annotation_strips?: AnnotationStrip[] | null;
  /** Taxon → colour overrides. The default cycle has twelve hues, so a top-15
   *  view always repeats some; pinning the taxa a reader compares keeps them
   *  apart and keeps them the same colour across dashboards. */
  taxon_palette?: Record<string, string> | null;
  /** Controls the tile does not offer; the config value still applies. */
  hidden_controls?: string[] | null;
  /** Label of the rank picker, 'Rank' when unset. */
  rank_label?: string | null;
  /** Sample axis title: unset reads 'Sample', an empty string shows none. */
  x_title?: string | null;
  /** Value axis title: unset reads 'Relative abundance' or the abundance
   *  column, an empty string shows none. */
  value_title?: string | null;
  /** The legend in a column right of the bars (default) or in rows under them. */
  legend_pos?: TaxonomyLegendPos;
  /** Vertical bars (default) or one horizontal bar per sample. */
  orientation?: TaxonomyOrientation;
  /** Per-sample column grouping the bars; the sort applies inside groups. */
  group_col?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: StackedTaxonomyConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

/** Fallback cycle for an unbranded deployment; a brand's colorway wins. */
const PALETTE = [
  '#1c7ed6', '#e64980', '#fab005', '#37b24d', '#7048e8', '#f76707',
  '#0ca678', '#d6336c', '#15aabf', '#fd7e14', '#82c91e', '#ae3ec9',
];

/** Runs of equal consecutive values, by position. */
function categoryRuns(values: readonly string[]): { value: string; start: number; end: number }[] {
  const runs: { value: string; start: number; end: number }[] = [];
  values.forEach((v, i) => {
    const last = runs[runs.length - 1];
    if (last && last.value === v && last.end === i - 1) last.end = i;
    else runs.push({ value: v, start: i, end: i });
  });
  return runs;
}

/** Dark or light text, whichever reads on a fill. */
function textOn(fill: string | undefined): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(String(fill ?? '').trim());
  if (!m) return '#212529';
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return lum < 0.4 ? '#ffffff' : '#212529';
}

/** Stand-in value of a spacer slot in a strip: breaks runs, never shown. */
const SPACER_VALUE = '\u0000';

const StackedTaxonomyRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as StackedTaxonomyConfig;
  const palette = resolveCategoricalPalette(theme, PALETTE);
  const categorySource = useCategoryColorSource();
  // A wide table (`value_cols`) is melted into the long form below; it has no
  // taxon, abundance or rank column of its own.
  const valueCols = useMemo(
    () => (config.value_cols ?? []).filter(Boolean),
    [config.value_cols],
  );
  const wide = valueCols.length > 0;
  // Unset is the model default; null is "no rank column" (one level).
  const rankCol = wide ? null : config.rank_col === undefined ? 'rank' : config.rank_col;
  const horizontal = config.orientation === 'h';

  const [rank, setRank] = usePersistedVizControl<string | null>(metadata, 'default_rank', null);
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n', 20);
  const [normalise, setNormalise] = usePersistedVizControl<boolean>(
    metadata,
    'normalise_to_one',
    true,
  );
  const [sampleSort, setSampleSort] = usePersistedVizControl<TaxonomySampleSort>(metadata, 'sample_sort', 'input');
  const [sortCategory, setSortCategory] = usePersistedVizControl<string | null>(metadata, 'sort_category', null);
  const [groupCol, setGroupCol] = usePersistedVizControl<string | null>(metadata, 'group_col', null);
  const [yZoom, setYZoom] = usePersistedVizControl<'off' | 'auto'>(metadata, 'y_zoom', 'off');
  const [showLegend, setShowLegend] = usePersistedVizControl(metadata, 'show_legend', true);
  const [logY, setLogY] = usePersistedVizControl(metadata, 'log_y', false);

  // The strips are drawn as fractions of the plot area, so they are sized from
  // the box: a fixed share was a 13 px band in a short tile, too thin for its
  // labels. Rounded so a sub-pixel reflow does not rebuild the figure. A
  // horizontal chart's strips are columns, sized from its width.
  const { ref: plotBoxRef, height: plotBoxPx, width: plotBoxW } = useElementSize();
  const plotAreaPx = horizontal
    ? Math.max(120, plotBoxW - H_PLOT_CHROME_W_PX)
    : Math.max(120, plotBoxPx - PLOT_CHROME_PX);
  const plotFraction = (px: number, cap: number) =>
    Math.round(Math.min(cap, px / plotAreaPx) * 1000) / 1000;
  const stripBand = plotFraction(STRIP_BAND_PX, 0.15);
  const stripGap = plotFraction(STRIP_GAP_PX, 0.05);
  const groupLabelBand = horizontal
    ? 0
    : Math.round(Math.min(0.2, GROUP_LABEL_PX / Math.max(120, plotBoxPx - PLOT_CHROME_PX)) * 1000) /
      1000;

  // What the bars can be grouped by: the configured group column and every
  // strip's column, all of which are fetched with the rows.
  const groupOptions = useMemo(() => {
    const out: { value: string; label: string }[] = [];
    const add = (value: string | null | undefined, label?: string) => {
      if (value && !out.some((o) => o.value === value)) out.push({ value, label: label || value });
    };
    add(config.group_col);
    for (const s of config.annotation_strips ?? []) add(s?.column, s?.label);
    return out;
  }, [config.group_col, config.annotation_strips]);
  const activeGroupCol =
    groupCol && groupOptions.some((o) => o.value === groupCol) ? groupCol : null;

  // Stable taxon→colour universe so a habitat filter doesn't shuffle the
  // top-N taxon colours. Pulled from the DC's unique values for taxon_col;
  // falls back to the filtered ordering when the endpoint is slow/errors.
  const [fetchedUniverse, setTaxonUniverse] = useState<string[] | null>(null);
  // A wide table's categories are its value columns, known up front.
  const taxonUniverse = useMemo(
    () => (wide ? valueCols.map((c) => wideCategoryName(c, config.value_labels)) : fetchedUniverse),
    [wide, valueCols, config.value_labels, fetchedUniverse],
  );
  useEffect(() => {
    if (wide || !metadata.dc_id || !config.taxon_col) {
      setTaxonUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.taxon_col)
      .then((values) => {
        if (!cancelled) setTaxonUniverse(values);
      })
      .catch(() => {
        /* best-effort — colours stay reactive to the current filter */
      });
    return () => {
      cancelled = true;
    };
  }, [wide, metadata.dc_id, config.taxon_col]);

  // The bindings (long form) or the sample id and value columns (wide form),
  // then the columns any annotation strip needs, so the renderer looks up
  // per-sample categorical values without a second fetch, then the group
  // column: after the strips, so grouping by a strip's column (which persists
  // `group_col`) leaves the column list, and the fetch, unchanged.
  const requiredCols = useMemo(
    () =>
      compositionColumns({
        sampleCol: config.sample_id_col,
        taxonCol: config.taxon_col,
        rankCol,
        abundanceCol: config.abundance_col,
        valueCols,
        extra: [...(config.annotation_strips ?? []).map((s) => s?.column), config.group_col],
      }),
    [config, rankCol, valueCols],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // Server-side downsampling state (mirrors the scatter-figure Load-All UX).
  const [fullLoad, setFullLoad] = useState(false);
  const [reduction, setReduction] = useState<{
    displayed: number;
    total: number;
    sampled: boolean;
    degraded: boolean;
  } | null>(null);

  const filterSig = JSON.stringify(filters);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  const bound = Boolean(
    config.sample_id_col && (wide || (config.taxon_col && config.abundance_col)),
  );
  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !bound) {
      setError('Stacked taxonomy: missing data binding');
      setLoading(false);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    fetchAdvancedVizData(
      {
        wfId: metadata.wf_id,
        dcId: metadata.dc_id,
        columns: requiredCols,
        filters,
        fullLoad,
        vizKind: 'stacked_taxonomy',
      },
      ctrl.signal,
    )
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setReduction({
          displayed: res.row_count,
          total: res.total_rows ?? res.row_count,
          sampled: Boolean(res.sampled),
          degraded: Boolean(res.sampling?.degraded),
        });
      })
      .catch((err: unknown) => {
        if (cancelled || isStaleFetch(err)) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [metadata.wf_id, metadata.dc_id, bound, JSON.stringify(requiredCols), filterSig, refreshTick, fullLoad]);

  const { figure, allRanks, categories, seriesCount, stripCount, slotCount, canZoom } = useMemo(() => {
    if (!rows)
      return {
        figure: null,
        allRanks: [] as string[],
        categories: [] as string[],
        seriesCount: 0,
        stripCount: 0,
        slotCount: 0,
        canZoom: false,
      };
    const legendPos = config.legend_pos ?? 'right';
    const melted = wide
      ? meltWideRows(rows, config.sample_id_col, valueCols, config.value_labels)
      : null;
    const samples =
      melted?.samples ??
      ((rows[config.sample_id_col] || []).map((v) => String(v ?? '')) as string[]);
    // A lineage that stops above the shown rank ("Eukaryota;") has a blank leaf.
    // Named, so it gets a legend entry a reader can identify rather than an
    // unlabelled swatch.
    const taxa =
      melted?.taxa ??
      ((rows[config.taxon_col] || []).map(
        (v) => String(v ?? '').trim() || 'Unclassified',
      ) as string[]);
    // No rank column bound, or none in the table (the endpoint drops a column
    // the DC lacks): one level, no filtering.
    const ranks = ((rankCol && rows[rankCol]) || []).map((v) => String(v ?? '')) as string[];
    const ab = melted?.abundances ?? ((rows[config.abundance_col] || []) as number[]);

    const seen = Array.from(new Set(ranks));
    // Root to leaf in the picker; unset, the rank stays the one the table
    // lists first, as before.
    const allRanks = withRanksInOrder(seen);
    const activeRank = seen.length ? rank || seen[0] : null;

    // Filter to active rank, then aggregate (sample × taxon → abundance).
    const cellTotals = new Map<string, Map<string, number>>(); // sample -> taxon -> abundance
    for (let i = 0; i < samples.length; i++) {
      if (activeRank && ranks[i] !== activeRank) continue;
      const s = samples[i];
      const t = taxa[i];
      const v = Number(ab[i]) || 0;
      if (!cellTotals.has(s)) cellTotals.set(s, new Map());
      const inner = cellTotals.get(s)!;
      inner.set(t, (inner.get(t) || 0) + v);
    }

    // Rank taxa by total abundance and keep top-N; lump others into "Other".
    // Largest first, which is also the stacking order: the overall largest
    // category sits at the bottom of every bar, which is what lets the zoom
    // crop a shared base away.
    const taxonTotals = new Map<string, number>();
    for (const inner of cellTotals.values()) {
      for (const [t, v] of inner.entries()) {
        taxonTotals.set(t, (taxonTotals.get(t) || 0) + v);
      }
    }
    const topTaxaSorted = Array.from(taxonTotals.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t);
    const topTaxa = topTaxaSorted.slice(0, topN);
    const topSet = new Set(topTaxa);
    const firstTaxon = topTaxaSorted[0];

    const totalOf = (s: string): number => {
      let total = 0;
      for (const v of (cellTotals.get(s) || new Map<string, number>()).values()) total += v;
      return total;
    };
    // A category's plotted value in one bar: its share when normalised.
    const shownValue = (s: string, category: string): number => {
      const inner = cellTotals.get(s) || new Map<string, number>();
      let v = 0;
      if (category === 'Other') {
        for (const [t, x] of inner.entries()) if (!topSet.has(t)) v += x;
      } else v = inner.get(category) || 0;
      const total = totalOf(s);
      return normalise && total > 0 ? v / total : v;
    };
    const shownCategories = [
      ...topTaxa.filter((t) => (taxonTotals.get(t) || 0) > 0),
      ...(topTaxaSorted.slice(topN).some((t) => (taxonTotals.get(t) || 0) > 0) ? ['Other'] : []),
    ];
    const sortCat = resolveSortCategory(sortCategory, shownCategories);

    // `input` keeps the table's order; `name` is natural; the value sorts are
    // largest first: the raw total, the raw value of the overall largest
    // category (`first_taxon`, as shipped), or the plotted value of the chosen
    // category (`category`).
    const sampleKeys = Array.from(cellTotals.keys());
    const orderedSamples = sortSamples(sampleKeys, sampleSort, {
      total: totalOf,
      firstTaxon: (s) => (firstTaxon ? cellTotals.get(s)?.get(firstTaxon) || 0 : 0),
      category: (s) => (sortCat ? shownValue(s, sortCat) : 0),
    });

    // Multi-level: bars grouped by a per-sample column, the sort applying
    // inside each group, the groups set apart by a blank slot.
    const firstValueBySample = (column: string): Map<string, string> => {
      const out = new Map<string, string>();
      const sampleCol = rows[config.sample_id_col] as unknown[] | undefined;
      const valueCol = rows[column] as unknown[] | undefined;
      if (sampleCol && valueCol) {
        for (let i = 0; i < sampleCol.length; i++) {
          const key = String(sampleCol[i] ?? '');
          if (!out.has(key)) out.set(key, String(valueCol[i] ?? '—'));
        }
      }
      return out;
    };
    const { slots, spans } = (() => {
      if (!activeGroupCol) return { slots: orderedSamples, spans: [] as ReturnType<typeof barSlots>['spans'] };
      const groupBy = firstValueBySample(activeGroupCol);
      const groups = groupSamples(
        orderedSamples,
        sampleKeys,
        (s) => groupBy.get(s) ?? '—',
        sampleSort === 'name',
      );
      return barSlots(groups, horizontal);
    })();
    const spacer = slots.map(isSpacerSlot);

    const tracesByTaxon = new Map<string, (number | null)[]>();
    for (const t of [...topTaxa, 'Other'])
      tracesByTaxon.set(t, slots.map((_, i) => (spacer[i] ? null : 0)));

    slots.forEach((s, sIdx) => {
      if (spacer[sIdx]) return;
      const inner = cellTotals.get(s) || new Map();
      let total = 0;
      for (const v of inner.values()) total += v;
      for (const [t, v] of inner.entries()) {
        const bucket = topSet.has(t) ? t : 'Other';
        const arr = tracesByTaxon.get(bucket)!;
        arr[sIdx] = (arr[sIdx] ?? 0) + (normalise && total > 0 ? v / total : v);
      }
    });

    // Stable taxon→colour map so filtering (e.g. by habitat) doesn't reshuffle
    // the top-N colours. Universe = all taxa in the DC; fallback = the filtered
    // top-N set ordered as they appear in tracesByTaxon.
    const taxaForPalette = Array.from(tracesByTaxon.keys()).filter((t) => t !== 'Other');
    // A taxon wears the dashboard's colour for it: under the rank shown (a
    // Phylum pinned in `category_colors.Phylum`), else under the taxon column,
    // the component's own `taxon_palette` winning value by value.
    const taxonPinned = columnCategoryColors(categorySource, config.taxon_col, {
      ...(columnCategoryColors(categorySource, activeRank) ?? {}),
      ...(config.taxon_palette ?? {}),
    });
    const colourSource = stableColorMap(taxonUniverse ?? taxaForPalette, palette, taxonPinned);
    const series = Array.from(tracesByTaxon.entries()).filter(([, arr]) =>
      arr.some((v) => (v ?? 0) > 0),
    );
    const data = series.map(([t, arr]) => ({
      type: 'bar' as const,
      name: t,
      ...(horizontal
        ? { orientation: 'h' as const, x: arr, y: slots }
        : { x: slots, y: arr }),
      marker: { color: t === 'Other' ? '#adb5bd' : colourSource.get(t) },
    }));

    // Zoom: the value axis starts just under the smallest bottom segment.
    // Never on a log axis, which is a crop of its own.
    const totals = slots.map((_, i) => series.reduce((acc, [, arr]) => acc + (arr[i] ?? 0), 0));
    const zoomCandidate =
      !normalise && logY ? null : zoomedValueRange(series[0]?.[1] ?? [], totals, normalise);
    const zoom = yZoom === 'auto' ? zoomCandidate : null;

    // Annotation strips — one row of per-sample coloured cells per configured
    // strip, each a one-row heatmap on its own y-axis sharing the bars' x-axis
    // (a one-column heatmap on its own x-axis beside horizontal bars).
    // A heatmap rather than layout shapes: shapes take no hover and no legend,
    // so a strip told nothing about which category a colour stood for.
    const strips = (config.annotation_strips ?? []).filter((s) => s && s.column);
    const stripTraces: Record<string, unknown>[] = [];
    // A strip's categories were legend entries after the taxa, one legend
    // holding two keys that read as one. A strip whose categories each hold a
    // block wide enough is labelled on itself instead; the others get a key
    // of their own above the plot.
    const stripLabels: Record<string, unknown>[] = [];
    let stripKey = false;
    const stripAxes: Record<string, unknown> = {};
    const step = stripBand + stripGap;
    const nTop = strips.filter((s) => s.position === 'top').length;
    const nBottom = strips.length - nTop;
    // Along y for vertical bars; along x (bottom = left) for horizontal ones.
    const barDomain: [number, number] = [nBottom * step, 1 - nTop * step];
    const nSamples = slots.length - spacer.filter(Boolean).length;
    if (strips.length > 0) {
      let topCursor = 1;
      let bottomCursor = 0;
      strips.forEach((strip, k) => {
        const sampleToValue = firstValueBySample(strip.column);
        const values = slots.map((s, i) => (spacer[i] ? SPACER_VALUE : sampleToValue.get(s) ?? '—'));
        // Stable category→colour for THIS strip's categories: the dashboard's
        // colours for its column, the strip's own `palette` winning per value.
        const categories = Array.from(new Set(values.filter((v) => v !== SPACER_VALUE))).sort();
        const stripPalette = stableColorMap(
          categories,
          palette,
          columnCategoryColors(categorySource, strip.column, strip.palette),
        );
        const n = categories.length;
        // Category i gets z = i; zmin/zmax at ±0.5 put each category in its own
        // [i/n, (i+1)/n] band of the colorscale, a step function.
        const colorscale = categories.flatMap((c, i) => [
          [i / n, stripPalette.get(c)],
          [(i + 1) / n, stripPalette.get(c)],
        ]);

        const isTop = strip.position === 'top';
        const domain: [number, number] = isTop
          ? [topCursor - stripBand, topCursor]
          : [bottomCursor, bottomCursor + stripBand];
        if (isTop) topCursor -= step;
        else bottomCursor += step;

        const axisLetter = horizontal ? 'x' : 'y';
        const axis = `${axisLetter}${k + 2}`;
        const label = strip.label || strip.column;
        stripAxes[`${axisLetter}axis${k + 2}`] = {
          domain,
          anchor: horizontal ? 'y' : 'x',
          fixedrange: true,
          showgrid: false,
          zeroline: false,
          ticks: '',
          tickfont: { size: 10, color: isDark ? '#ced4da' : '#495057' },
          ...(horizontal ? { tickangle: -90 } : {}),
          automargin: true,
        };
        const z = values.map((v) => (v === SPACER_VALUE ? null : categories.indexOf(v)));
        const shown = values.map((v) => (v === SPACER_VALUE ? '' : v));
        stripTraces.push({
          type: 'heatmap',
          ...(horizontal
            ? {
                x: [label],
                y: slots,
                z: z.map((v) => [v]),
                customdata: shown.map((v) => [v]),
                xaxis: axis,
                hovertemplate: `%{y}<br>${label}: %{customdata}<extra></extra>`,
              }
            : {
                x: slots,
                y: [label],
                z: [z],
                customdata: [shown],
                yaxis: axis,
                hovertemplate: `%{x}<br>${label}: %{customdata}<extra></extra>`,
              }),
          zmin: -0.5,
          zmax: n - 0.5,
          colorscale,
          showscale: false,
          xgap: 0,
          hoverongaps: false,
        });
        const runs = categoryRuns(values).filter((r) => r.value !== SPACER_VALUE);
        const minRun = Math.max(2, Math.ceil(nSamples * 0.12));
        const longest = new Map<string, { start: number; end: number }>();
        for (const r of runs) {
          const best = longest.get(r.value);
          if (!best || r.end - r.start > best.end - best.start) longest.set(r.value, r);
        }
        const labelled = categories.every((c) => {
          const r = longest.get(c);
          return r != null && r.end - r.start + 1 >= minRun;
        });
        if (labelled) {
          for (const c of categories) {
            const r = longest.get(c)!;
            // A category axis places numbers by position: the run's middle.
            const mid = (r.start + r.end) / 2;
            stripLabels.push({
              ...(horizontal
                ? { xref: axis, yref: 'y', x: 0, y: mid, textangle: -90 }
                : { xref: 'x', yref: axis, x: mid, y: 0 }),
              text: c,
              showarrow: false,
              font: { size: 10, color: textOn(stripPalette.get(c)) },
            });
          }
        } else {
          stripKey = true;
          categories.forEach((c) =>
            stripTraces.push({
              type: 'scatter',
              mode: 'markers',
              x: [null],
              y: [null],
              name: c,
              legend: 'legend2',
              legendgroup: `strip-${strip.column}`,
              legendgrouptitle: { text: label },
              marker: { color: stripPalette.get(c), symbol: 'square', size: 10 },
              hoverinfo: 'skip',
            }),
          );
        }
      });
    }

    // Group names: a band above vertical bars, centred on each group with a
    // rule under it; in the blank row heading each group of horizontal bars.
    const axisColour = plotlyAxisOverrides(isDark, theme).color;
    const groupLabels: Record<string, unknown>[] = [];
    const groupRules: Record<string, unknown>[] = [];
    for (const span of spans) {
      if (horizontal) {
        if (span.labelSlot == null) continue;
        groupLabels.push({
          xref: 'paper',
          yref: 'y',
          x: barDomain[0],
          y: span.labelSlot,
          xanchor: 'left',
          yanchor: 'middle',
          text: `<b>${span.name}</b>`,
          showarrow: false,
          font: { size: 10, color: axisColour },
        });
      } else {
        groupLabels.push({
          xref: 'x',
          yref: 'paper',
          x: (span.start + span.end) / 2,
          y: 1,
          yanchor: 'bottom',
          text: `<b>${span.name}</b>`,
          showarrow: false,
          font: { size: 10, color: axisColour },
        });
        groupRules.push({
          type: 'line',
          xref: 'x',
          yref: 'paper',
          x0: span.start - 0.4,
          x1: span.end + 0.4,
          y0: 1,
          y1: 1,
          line: { color: axisColour, width: 1 },
        });
      }
    }
    const groupBandPx = !horizontal && spans.length > 0 ? GROUP_LABEL_PX : 0;

    // The `//` at the base of a cropped value axis, drawn on its axis line.
    const breakShapes = zoom
      ? axisBreakShapes(
          horizontal ? 'h' : 'v',
          horizontal ? { x: barDomain[0], y: 0 } : { x: 0, y: barDomain[0] },
          { line: axisColour, background: isDark ? theme.colors.dark[7] : theme.white },
        )
      : [];

    // Past 40 bars the tilted sample labels run into each other: they go (the
    // hover still names each bar), and a legend in rows moves above the bars.
    const denseAxis = isDenseTaxonomyAxis(nSamples);
    const legendTopPx = taxonomyLegendTopPx(legendPos, denseAxis, showLegend);

    const categoryAxis = {
      ...plotlyAxisOverrides(isDark, theme),
      title: { text: taxonomyAxisTitle(config.x_title) },
      ...(horizontal ? {} : { tickangle: -45 }),
      showticklabels: !denseAxis,
      automargin: true,
      // Pinned to the edge of the plot area, past any strip on that side, and
      // to the bars' sample order so the strips line up with them.
      anchor: 'free' as const,
      position: 0,
      categoryorder: 'array' as const,
      categoryarray: slots,
      // The first sample on top, as a table reads.
      ...(horizontal ? { autorange: 'reversed' as const } : {}),
    };
    // When normalise is ON we lock the value axis to [0, 1] and format ticks
    // as percentages — this gives the toggle a visible effect even when the
    // input data is already pre-normalised (the old behaviour: both toggle
    // states rendered identically because each sample already summed to 1).
    const croppedFrom = zoom ? formatAxisFloor(zoom, normalise) : null;
    const valueAxis = {
      ...plotlyAxisOverrides(isDark, theme),
      domain: barDomain,
      title: {
        text: valueAxisTitle(
          config.value_title,
          normalise ? 'Relative abundance' : wide ? 'Value' : config.abundance_col,
          croppedFrom,
        ),
      },
      ...(normalise
        ? {
            range: zoom ? [zoom.floor, 1] : [0, 1],
            tickformat: zoom ? percentTickFormat(zoom.step) : '.0%',
          }
        : {
            // Log is only meaningful for raw counts — normalised data is
            // bounded [0,1] and log would compress to noise.
            ...(logY ? { type: 'log' as const } : {}),
            ...(zoom ? { range: [zoom.floor, zoom.top] } : {}),
          }),
      // A cropped axis draws its line, so the break has a line to cut.
      ...(zoom ? { showline: true } : {}),
    };

    return {
      // The legend and the strips are what actually grows this tile, so the
      // figure reports them back rather than the renderer re-deriving them.
      seriesCount: data.length,
      stripCount: strips.length,
      slotCount: slots.length,
      categories: shownCategories,
      canZoom: zoomCandidate != null,
      figure: {
        data: [...data, ...stripTraces],
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          barmode: 'stack' as const,
          // Automargins: the tilted sample ids, the strip names and the legend
          // take what they need instead of a guess that clipped them.
          margin: { l: 60, r: 20, t: (stripKey ? 44 : 30) + legendTopPx + groupBandPx, b: 30 },
          annotations: [...stripLabels, ...groupLabels],
          ...(breakShapes.length || groupRules.length
            ? { shapes: [...groupRules, ...breakShapes] }
            : {}),
          ...(horizontal
            ? { yaxis: categoryAxis, xaxis: valueAxis }
            : { xaxis: categoryAxis, yaxis: valueAxis }),
          ...stripAxes,
          showlegend: showLegend,
          // The taxa's key, titled with the rank they are, in a column right of
          // the plot by default: under it, it collided with the tilted sample
          // labels. `legend_pos: bottom` puts it in rows under the figure.
          legend: taxonomyLegend(legendPos, denseAxis, activeRank ?? (seen.length ? 'Taxon' : 'Category')),
          ...(stripKey
            ? {
                legend2: {
                  orientation: 'h',
                  x: 1,
                  xanchor: 'right',
                  y: 1 + (groupBandPx ? groupLabelBand : 0),
                  yanchor: 'bottom',
                  font: { size: 10 },
                },
              }
            : {}),
          autosize: true,
        },
      },
      allRanks,
    };
  }, [rows, config, rankCol, wide, valueCols, horizontal, rank, topN, normalise, sampleSort, sortCategory, activeGroupCol, yZoom, showLegend, logY, isDark, theme, taxonUniverse, categorySource, stripBand, stripGap, groupLabelBand]);

  // Memoised so AdvancedVizFrame's `extras` useMemo stays stable — an unmemoised
  // element re-fires the frame's publish effect and loops it against
  // ComponentRenderer's setState ("Maximum update depth exceeded").
  // Encoding tier: rank, how many taxa survive the pooling, sample order (and
  // its grouping), and how the value axis reads (proportions, cropped). Most
  // used first: a docked panel shows the first few (DockedControls). Change
  // one of those and it is a different figure; the legend and the log scale
  // only change how it looks.
  // A tile stacking something other than taxa (CCS outcomes per library)
  // hides the controls that mean nothing for it (`hidden_controls`); their
  // config values still apply. The rank picker also hides itself when the
  // table has a single rank, or none.
  const shown = useMemo(() => {
    const visible = visibleTaxonomyControls(config.hidden_controls);
    return {
      ...visible,
      rank: visible.rank && (allRanks.length > 1 || Boolean(rank)),
      group: visible.group && groupOptions.length > 0,
    };
  }, [config.hidden_controls, allRanks.length, rank, groupOptions.length]);
  const rankLabel = config.rank_label || 'Rank';
  const activeSortCategory = resolveSortCategory(sortCategory, categories);
  const primaryControls = useMemo(
    () =>
      Object.values(shown).some(Boolean) ? (
        <>
          {shown.rank ? (
            <VizSelect
              label={rankLabel}
              value={rank}
              onChange={setRank}
              data={allRanks}
              clearable
            />
          ) : null}
          {shown.top_n ? (
            <VizNumberInput
              label="Top-N taxa"
              value={topN}
              onChange={(v) => setTopN(Math.max(1, Number(v) || 20))}
              min={1}
              max={50}
            />
          ) : null}
          {shown.sample_sort ? (
            <VizSelect
              label="Sort samples"
              value={sampleSort}
              onChange={(v) => v && setSampleSort(v as TaxonomySampleSort)}
              data={SAMPLE_SORT_OPTIONS as { value: string; label: string }[]}
              allowDeselect={false}
            />
          ) : null}
          {shown.sample_sort && sampleSort === 'category' && categories.length > 0 ? (
            <VizSelect
              label="Sort by share of"
              value={activeSortCategory}
              onChange={(v) => v && setSortCategory(v)}
              data={categories}
              allowDeselect={false}
              searchable={categories.length > 8}
            />
          ) : null}
          {shown.group ? (
            <VizSelect
              label="Group samples by"
              value={activeGroupCol}
              onChange={(v) => setGroupCol(v || null)}
              data={groupOptions}
              placeholder="None"
              clearable
            />
          ) : null}
          {shown.normalise ? (
            <VizSwitch
              checked={normalise}
              onChange={(e) => setNormalise(e.currentTarget.checked)}
              label="Normalise"
            />
          ) : null}
          {shown.zoom ? (
            <VizSwitch
              checked={yZoom === 'auto'}
              onChange={(e) => setYZoom(e.currentTarget.checked ? 'auto' : 'off')}
              disabled={!canZoom && yZoom !== 'auto'}
              label="Zoom"
              title={
                canZoom
                  ? 'Crop the value axis to the part that varies between samples'
                  : 'Nothing to crop: the bottom segment does not fill most of every bar'
              }
            />
          ) : null}
        </>
      ) : undefined,
    [
      rank,
      sampleSort,
      topN,
      normalise,
      allRanks,
      rankLabel,
      shown,
      categories,
      activeSortCategory,
      activeGroupCol,
      groupOptions,
      yZoom,
      canZoom,
    ],
  );

  const controls = useMemo(
    () => (
      <VizControlGroup title="Display">
        <VizSwitch
          checked={showLegend}
          onChange={(e) => setShowLegend(e.currentTarget.checked)}
          label="Legend"
        />
        {!normalise ? (
          <VizSwitch
            checked={logY}
            onChange={(e) => setLogY(e.currentTarget.checked)}
            label="Log y"
          />
        ) : null}
      </VizControlGroup>
    ),
    [normalise, showLegend, logY],
  );

  // Vertical bars, so the sample count is the tile's width problem, not its
  // height: the demand is the plot area, or the legend's column when that is
  // taller (it only has the plot area's height), plus what the annotation
  // strips take off it.
  // A legend in rows (`legend_pos: bottom`) adds its rows to the plot area
  // instead. Horizontal bars turn the count into a height: one row per bar.
  const legendRows = config.legend_pos === 'bottom';
  const contentDemand = useMemo(() => {
    if (!figure) return undefined;
    const plotPx = horizontal
      ? Math.max(TAXONOMY_PLOT_PX, slotCount * BAR_ROW_PX + H_PLOT_CHROME_PX)
      : TAXONOMY_PLOT_PX;
    return demandForPx(
      (legendRows
        ? plotPx +
          (showLegend
            ? LEGEND_CHROME_PX + Math.ceil(seriesCount / LEGEND_ROW_ITEMS) * LEGEND_ITEM_PX
            : 0)
        : Math.max(
            plotPx,
            showLegend
              ? FRAME_HEADER_PX + PLOT_CHROME_PX + LEGEND_CHROME_PX + seriesCount * LEGEND_ITEM_PX
              : 0,
          )) + (horizontal ? 0 : stripCount * (STRIP_BAND_PX + STRIP_GAP_PX)),
    );
  }, [figure, showLegend, seriesCount, stripCount, legendRows, horizontal, slotCount]);

  // Themed once per figure so the annotation layer can memoise on them.
  const plotData = useMemo(
    () => (figure ? applyDataTheme(figure.data, isDark, theme) : null),
    [figure, isDark, theme],
  );
  const plotLayout = useMemo(
    () => (figure ? applyLayoutTheme(figure.layout as any, isDark, theme) : null),
    [figure, isDark, theme],
  );
  // Chart annotations. A bar is a taxon's total in one sample, not a row,
  // so marked bars are stored as coordinates.
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: supportsAdvancedVizAnnotation(metadata),
    data: plotData,
    layout: plotLayout,
  });

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Stacked taxonomy'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      badges={annotations.badges}
      estimated={Boolean(reduction?.degraded)}
      reduction={
        reduction && (reduction.sampled || fullLoad)
          ? {
              displayed: reduction.displayed,
              total: reduction.total,
              sampled: reduction.sampled,
              full: fullLoad,
              loading,
              onToggle: () => setFullLoad((v) => !v),
            }
          : undefined
      }
    >
      {figure ? (
        <>
          <div ref={plotBoxRef} style={{ width: '100%', height: '100%' }}>
            <Plot
              data={annotations.data as any}
              layout={annotations.layout as any}
              useResizeHandler
              style={{ width: '100%', height: '100%' }}
              config={{ displaylogo: false, responsive: true } as any}
              {...annotations.plotProps()}
            />
          </div>
          {annotations.toolbar}
        </>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default StackedTaxonomyRenderer;
