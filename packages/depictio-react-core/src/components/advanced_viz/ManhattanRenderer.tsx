import React, { useEffect, useMemo, useState } from 'react';
import {
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  extractScatterSelection,
  filtersExcludingOwn,
  hasOwnSelection,
} from '../../selection';
import { adaptGlTrace, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame, { TIER_COLORS } from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { regionXRange, useFollowedRegion } from './genomicAxis';
import { rainfallDistances } from './rainfallDistances';
import { usePersistedVizControl } from './usePersistedVizControl';
import { useGestureGuardedSelection, useSelectionRevision } from './selectionGesture';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';

type Highlight = 'above' | 'below' | 'none';

/** `manhattan` puts the score on y. `rainfall` puts log10 of the distance to
 *  the previous variant on the same chromosome there instead: the mutation-
 *  density figure, where clustered events (kataegis) fall to the bottom of the
 *  plot and the eye reads density rather than significance. The x axis, the
 *  chromosome blocks, the selection and the labels are the same in both. */
type VizMode = 'manhattan' | 'rainfall';

const RAINFALL_Y_TITLE = 'log10(distance to previous variant, bp)';

interface ManhattanConfig {
  chr_col: string;
  pos_col: string;
  score_col: string;
  feature_col?: string | null;
  effect_col?: string | null;
  score_kind?: string;
  score_threshold?: number | null;
  top_n_labels?: number | null;
  marker_size_above?: number;
  marker_size_below?: number;
  marker_size_uniform?: number;
  highlight?: Highlight;
  /** Extra columns to fetch + expose in the Colour-by dropdown. */
  color_by_columns?: string[];
  /** Opt into lasso/box/click selection as a dashboard filter. Inert without
   *  `selection_column`; resolved through `advancedVizSelectionColumn`. */
  selection_enabled?: boolean;
  /** Column the emitted values belong to. No default: see the field's
   *  description in depictio/models/components/advanced_viz/configs.py. */
  selection_column?: string | null;
  /** `rainfall` swaps the score on y for the distance to the previous variant
   *  on the same chromosome. See `VizMode` below. */
  mode?: VizMode;
  /** Rainfall only: column whose values colour each point. */
  rainfall_class_col?: string | null;
}

/** Sentinel values for the Colour-by Select that aren't real DC columns. */
const COLOR_BY_CHROMOSOME = '__chromosome__';
const COLOR_BY_SCORE = '__score__';

const PLOT_CONFIG = { displaylogo: false, responsive: true } as any;

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ManhattanConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Emits this component's selection as a dashboard filter. Absent on
   *  read-only hosts (catalog, project previews), which is what keeps the
   *  lasso off there. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Dashboard-wide analysis grouping, applied client-side to the built
   *  figure. Colour only, never facets: a Manhattan reads as one genome-wide
   *  axis, and cutting it into panels would break the very continuity that
   *  makes it legible. See `splitFigureByGroups`. */
  groupRender?: GroupRenderState;
}

const _palette = [
  '#1c7ed6',
  '#e64980',
  '#fab005',
  '#37b24d',
  '#7048e8',
  '#f76707',
  '#0ca678',
  '#d6336c',
];

// Natural chromosome order: chr1..chr22, chrX, chrY, chrMT, then anything else
// alphabetically. Returns Infinity for unrecognised labels so they sort last.
function chromosomeSortKey(label: string): number {
  const stripped = label.replace(/^chr/i, '').toUpperCase();
  if (stripped === 'X') return 23;
  if (stripped === 'Y') return 24;
  if (stripped === 'MT' || stripped === 'M') return 25;
  const n = Number.parseInt(stripped, 10);
  return Number.isFinite(n) ? n : 100;
}

const ManhattanRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
  groupRender,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as ManhattanConfig;

  const [scoreThreshold, setScoreThreshold] = usePersistedVizControl<number | undefined>(
    metadata,
    'score_threshold',
    undefined,
  );
  const [topNLabels, setTopNLabels] = usePersistedVizControl<number>(
    metadata,
    'top_n_labels',
    8,
  );
  // A narrowed chromosome set is what the reader is looking at now, not what
  // the plot is, so it stays local.
  const [selectedChrs, setSelectedChrs] = useState<string[]>([]);
  const [markerSizeAbove, setMarkerSizeAbove] = usePersistedVizControl<number>(
    metadata,
    'marker_size_above',
    6,
  );
  const [markerSizeBelow, setMarkerSizeBelow] = usePersistedVizControl<number>(
    metadata,
    'marker_size_below',
    4,
  );
  const [markerSizeUniform, setMarkerSizeUniform] = usePersistedVizControl<number>(
    metadata,
    'marker_size_uniform',
    5,
  );
  const [highlight, setHighlight] = usePersistedVizControl<Highlight>(
    metadata,
    'highlight',
    'above',
  );
  const [colorBy, setColorBy] = usePersistedVizControl<string>(
    metadata,
    'default_color_by',
    COLOR_BY_CHROMOSOME,
  );
  const [mode, setMode] = usePersistedVizControl<VizMode>(
    metadata,
    'mode',
    'manhattan',
  );
  const rainfall = mode === 'rainfall';
  const rainfallClassCol = rainfall ? config.rainfall_class_col || null : null;

  // ---- Following a region someone else brushed ----------------------------
  // A `genome_selection` filter on this collection's own `chr_col` / `pos_col`
  // already narrows the rows the server returns; what the tile adds is moving
  // its chromosome narrowing onto the same contig and clamping the axis to the
  // window, so a Manhattan under a genome_view reads as the same locus.
  const followedRegion = useFollowedRegion(metadata, config, filters);
  useEffect(() => {
    if (!followedRegion) return;
    setSelectedChrs((current) =>
      current.length === 1 && current[0] === followedRegion.chrom
        ? current
        : [followedRegion.chrom],
    );
  }, [followedRegion]);

  // ---- Selection as a cross-filter ---------------------------------------
  // `undefined` means this component does not select: either the dashboard
  // did not opt in, or it opted in without naming a column (a Manhattan point
  // is one row of a long variant table, so there is nothing safe to guess).
  // The same resolution drives the chrome's capability marker, see
  // selection.ts. A host with no onFilterChange is read-only.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const requiredCols = useMemo(() => {
    const cols = [config.chr_col, config.pos_col, config.score_col].filter(Boolean) as string[];
    if (config.feature_col) cols.push(config.feature_col);
    // Fetch the user-declared colour-by columns alongside so swapping colour
    // mode doesn't require a re-fetch (the data endpoint caps at 100k rows
    // which is plenty for variant tracks).
    for (const c of config.color_by_columns ?? []) {
      if (!cols.includes(c)) cols.push(c);
    }
    // The selection column is fetched whether or not it is also a colour-by
    // option, so a dashboard only has to name it once.
    if (selectionColumn && !cols.includes(selectionColumn)) cols.push(selectionColumn);
    // Only while rainfall is the mode: a Manhattan has no use for the class
    // column, and fetching it anyway would widen every variant frame.
    if (rainfallClassCol && !cols.includes(rainfallClassCol)) cols.push(rainfallClassCol);
    return cols;
  }, [config, selectionColumn, rainfallClassCol]);

  // This component must NOT narrow itself by its own selection: a lasso would
  // otherwise redraw the track as only the variants it caught, and the user
  // could never widen it again. Same rule FigureRenderer follows; every other
  // component still sees the entry and narrows.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );
  const selectionRevision = useSelectionRevision(
    hasOwnSelection(filters, metadata.index, 'scatter_selection'),
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Manhattan: missing data binding');
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
      vizKind: 'manhattan',
      roles: { chr: config.chr_col, pos: config.pos_col, score: config.score_col },
      // The threshold line the plot already draws is exactly the cut the server
      // must not sample across, and `highlight` says which side of it is the
      // population being looked at. Without a line there is no declared tail and
      // the server falls back to reading the score column's range.
      //
      // Never in rainfall mode: keeping the score's tail whole and thinning the
      // rest is exactly what a distance-to-the-previous-variant axis must not
      // be handed, since every dropped row stretches its neighbour's distance.
      tail:
        !rainfall && config.score_threshold != null && config.highlight !== 'none'
          ? {
              column: config.score_col,
              direction: config.highlight === 'below' ? 'low' : 'high',
              threshold: config.score_threshold,
            }
          : undefined,
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
  }, [
    metadata.wf_id,
    metadata.dc_id,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    refreshTick,
    // The two modes ask the server for differently-reduced frames, so a switch
    // has to re-fetch even when the column list happens to be identical.
    rainfall,
  ]);

  // Variant clouds are the densest thing on a dashboard, so always compete for
  // a WebGL slot; without one the trace renders as downsampled SVG — see
  // webglBudget.
  const glGranted = useWebglSlot(true);

  const { figure, allChrs, tiers, counts } = useMemo(() => {
    if (!rows)
      return {
        figure: null,
        allChrs: [] as string[],
        tiers: null as ('ABOVE' | 'BELOW')[] | null,
        counts: undefined as Record<string, number> | undefined,
      };

    const chrs = (rows[config.chr_col] || []).map((v) => String(v ?? '')) as string[];
    const positions = (rows[config.pos_col] || []) as number[];
    const scores = (rows[config.score_col] || []) as number[];
    const feats = config.feature_col ? (rows[config.feature_col] as (string | number)[]) : [];

    // Natural-sorted chromosome list (chr1..chr22, chrX, chrY, chrMT). This is
    // the full domain of the data: it feeds the Chromosomes dropdown and the
    // colour palette, so a chromosome keeps its colour whatever is selected.
    const allChrs = Array.from(new Set(chrs)).sort(
      (a, b) => chromosomeSortKey(a) - chromosomeSortKey(b),
    );
    // Chromosomes actually drawn. A selection that no longer intersects the
    // data (the left-panel filters moved under us, or a value persisted from a
    // previous dataset) falls back to "everything" rather than blanking the
    // tile with no explanation.
    const narrowed = allChrs.filter((c) => selectedChrs.includes(c));
    const visibleChrs = narrowed.length > 0 ? narrowed : allChrs;
    const visibleSet = new Set(visibleChrs);

    // Row indices surviving the chromosome selection. Everything the trace
    // draws is built by walking this list and indexing the full-length source
    // arrays, so the per-row colour / size / label rules below are untouched
    // while the hidden chromosomes never reach the figure at all.
    const rowIdx: number[] = [];
    for (let i = 0; i < chrs.length; i++) {
      if (visibleSet.has(chrs[i])) rowIdx.push(i);
    }

    // Rainfall's y: the distance to the previous variant on the same
    // chromosome. The first variant of each chromosome has no predecessor, so
    // it leaves the figure altogether rather than being drawn at some invented
    // distance. Computed over the whole frame, because a distance never spans
    // a chromosome boundary and the narrowing above only ever drops whole
    // chromosomes.
    const rainfallByRow = rainfall
      ? new Map(rainfallDistances(chrs, positions).map((d) => [d.row, d.logDistance]))
      : null;
    if (rainfallByRow) {
      let kept = 0;
      for (const i of rowIdx) {
        if (rainfallByRow.has(i)) rowIdx[kept++] = i;
      }
      rowIdx.length = kept;
    }
    /** The y a row carries in the current mode. */
    const yAt = (i: number) => (rainfallByRow ? (rainfallByRow.get(i) as number) : scores[i]);

    // 1) Per-chromosome cumulative x-offset, over the visible chromosomes only
    //    so that narrowing the selection zooms the axis onto them instead of
    //    leaving one cluster stranded in an otherwise empty genome. Each
    //    chromosome's block spans [offset, offset + max_pos]; we pad between
    //    chromosomes by ~2% of the largest visible chromosome so they don't
    //    visually butt against each other.
    const maxPosByChr = new Map<string, number>();
    for (const i of rowIdx) {
      const c = chrs[i];
      const p = positions[i] ?? 0;
      const prev = maxPosByChr.get(c) ?? 0;
      if (p > prev) maxPosByChr.set(c, p);
    }
    const globalMax = Math.max(0, ...Array.from(maxPosByChr.values()));
    const padding = Math.max(1, Math.round(globalMax * 0.02));

    const offsetByChr = new Map<string, number>();
    const chrSpan = new Map<string, { start: number; end: number; mid: number }>();
    let cursor = 0;
    for (const c of visibleChrs) {
      offsetByChr.set(c, cursor);
      const span = maxPosByChr.get(c) ?? 0;
      const start = cursor;
      const end = cursor + span;
      chrSpan.set(c, { start, end, mid: start + span / 2 });
      cursor = end + padding;
    }
    // Drop the trailing inter-chromosome pad and hand half of it to each end,
    // so a single-chromosome view sits centred on its own axis instead of
    // being pushed against the left edge with dead space on the right.
    const totalSpan = Math.max(1, cursor - padding);
    const fullXRange: [number, number] = [-padding / 2, totalSpan + padding / 2];
    // A followed region is a window on one chromosome, so it becomes a window
    // on the cumulative axis through that chromosome's own offset. Outside the
    // drawn span it is not this tile's locus and the axis stays put.
    const regionWindow = (() => {
      if (!followedRegion) return null;
      const offset = offsetByChr.get(followedRegion.chrom);
      if (offset === undefined) return null;
      const window = regionXRange(followedRegion);
      if (!window) return null;
      const lo = offset + window[0];
      const hi = offset + window[1];
      return hi < fullXRange[0] || lo > fullXRange[1] ? null : ([lo, hi] as [number, number]);
    })();
    const xRange: [number, number] = regionWindow ?? fullXRange;

    // 2) Map every visible row to its cumulative x and chromosome colour. When
    //    a threshold is set, points below it dim to grey so the eye is drawn to
    //    the "hits" instead of the chromosome blocks. `tiers` mirrors the
    //    Volcano/MA classification so the data popover can highlight the same
    //    rows and the counts row shows ABOVE / BELOW. It stays full-length
    //    because AdvancedVizFrame aligns it against the unfiltered `dataRows`.
    const xs = rowIdx.map((i) => (offsetByChr.get(chrs[i]) ?? 0) + (positions[i] ?? 0));
    const colorByChr = new Map<string, string>(
      allChrs.map((c, i) => [c, _palette[i % _palette.length]]),
    );
    // Rainfall does not read the score at all, so the threshold line, the
    // above/below sizing, the tier chips and the tier-coloured markers all go
    // with it rather than annotating an axis that is no longer on the plot.
    const hasThreshold = !rainfall && scoreThreshold != null && Number.isFinite(scoreThreshold);
    const tiers: ('ABOVE' | 'BELOW')[] | null = hasThreshold
      ? scores.map((s) => (s != null && s >= (scoreThreshold as number) ? 'ABOVE' : 'BELOW'))
      : null;

    // Marker colouring rules — composed from two orthogonal axes:
    //  1) ``colorBy`` (Colour-by Select): chromosome / score / any extra
    //     fetched column. Categorical columns get hash→palette assignment;
    //     numeric columns (incl. ``score`` itself) use a continuous teal-
    //     orange gradient that matches the tier palette so the chip ↔ dot
    //     visual language stays consistent. Chromosome mode keeps the
    //     canonical GWAS-style chromosome palette + the tier palette as a
    //     special case when a threshold is set.
    //  2) ``highlight`` (when a threshold is set): the dimmed tier overrides
    //     whatever colour rule (1) produced and falls back to grey. This is
    //     what lets the user emphasise consensus vs subconsensus regardless
    //     of which Colour-by mode they picked.
    const dimColor = 'rgba(160,160,160,0.45)';
    const tierColorHex = (tier: 'ABOVE' | 'BELOW') => {
      const name = TIER_COLORS[tier];
      const swatch = (theme.colors as Record<string, readonly string[]>)[name];
      return swatch?.[5] ?? colorByChr.values().next().value ?? '#777';
    };

    // Detect numeric vs categorical for an arbitrary colour-by column.
    const colorByValues =
      colorBy === COLOR_BY_CHROMOSOME || colorBy === COLOR_BY_SCORE
        ? null
        : (rows[colorBy] as (string | number | null)[] | undefined) ?? null;
    const colorByIsNumeric =
      colorBy === COLOR_BY_SCORE ||
      (colorByValues != null &&
        colorByValues.find((v) => v != null) != null &&
        typeof colorByValues.find((v) => v != null) === 'number');

    // Hex helpers for the palette + gradient endpoints.
    const tealHex = tierColorHex('ABOVE');
    const orangeHex = tierColorHex('BELOW');

    /** Linear interpolate between two #rrggbb colours. */
    const lerp = (a: string, b: string, t: number) => {
      const tt = Math.max(0, Math.min(1, t));
      const pa = [
        parseInt(a.slice(1, 3), 16),
        parseInt(a.slice(3, 5), 16),
        parseInt(a.slice(5, 7), 16),
      ];
      const pb = [
        parseInt(b.slice(1, 3), 16),
        parseInt(b.slice(3, 5), 16),
        parseInt(b.slice(5, 7), 16),
      ];
      const mix = pa.map((c, j) => Math.round(c + (pb[j] - c) * tt));
      return `rgb(${mix[0]},${mix[1]},${mix[2]})`;
    };

    // Continuous gradient for numeric colour-by: orange (low) → teal (high)
    // so it matches the tier palette semantics (low score = below threshold
    // = orange; high score = above = teal).
    const numericSrc = colorBy === COLOR_BY_SCORE ? scores : (colorByValues as number[] | null) ?? null;
    let numericMin = 0;
    let numericMax = 1;
    if (colorByIsNumeric && numericSrc) {
      let lo = Infinity;
      let hi = -Infinity;
      for (const v of numericSrc) {
        if (typeof v === 'number' && Number.isFinite(v)) {
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
      if (lo < hi) {
        numericMin = lo;
        numericMax = hi;
      }
    }
    const numericColor = (v: number) =>
      lerp(orangeHex, tealHex, (v - numericMin) / Math.max(1e-9, numericMax - numericMin));

    // Categorical palette assignment for non-numeric colour-by. The
    // ``categoricalLegendItems`` list is exposed to the figure builder so it
    // can emit one invisible legend trace per value — Plotly then draws a
    // proper colour legend the user can read.
    let categoricalColor: ((idx: number) => string) | null = null;
    let categoricalLegendItems: { name: string; color: string }[] = [];
    if (colorByValues && !colorByIsNumeric) {
      const uniqueVals: string[] = [];
      const seen = new Set<string>();
      for (const v of colorByValues) {
        const s = v == null ? '∅' : String(v);
        if (!seen.has(s)) {
          seen.add(s);
          uniqueVals.push(s);
        }
      }
      const map = new Map(uniqueVals.map((v, i) => [v, _palette[i % _palette.length]]));
      categoricalColor = (i: number) => {
        const v = colorByValues[i];
        const key = v == null ? '∅' : String(v);
        return map.get(key) ?? '#777';
      };
      // Palette assignment stays over the whole column so a value keeps its
      // colour when the chromosome selection narrows; only the legend list
      // follows the visible rows, so it never advertises a colour that isn't
      // on screen.
      const visibleKeys = new Set(
        rowIdx.map((i) => {
          const v = colorByValues[i];
          return v == null ? '∅' : String(v);
        }),
      );
      categoricalLegendItems = uniqueVals
        .filter((v) => visibleKeys.has(v))
        .map((v) => ({
          name: v,
          color: map.get(v) ?? '#777',
        }));
    }

    // Rainfall's class column gets its own categorical palette and legend, and
    // replaces the Colour-by rules wholesale rather than composing with them:
    // mutation class is what this figure is about, and Colour-by (chromosome,
    // score, an extra column) belongs to the view where the score is the axis.
    // With no class column bound the chromosome palette stays, as today.
    const classValues = rainfallClassCol
      ? ((rows[rainfallClassCol] as (string | number | null)[] | undefined) ?? null)
      : null;
    let rainfallClassColor: ((idx: number) => string) | null = null;
    let rainfallLegendItems: { name: string; color: string }[] = [];
    if (classValues) {
      const keyOf = (i: number) => (classValues[i] == null ? '∅' : String(classValues[i]));
      const uniqueVals = Array.from(new Set(rowIdx.map(keyOf))).sort();
      const map = new Map(uniqueVals.map((v, i) => [v, _palette[i % _palette.length]]));
      rainfallClassColor = (i: number) => map.get(keyOf(i)) ?? _palette[0];
      rainfallLegendItems = uniqueVals.map((v) => ({
        name: v,
        color: map.get(v) ?? _palette[0],
      }));
    }

    // Chromosomes dropped by the dropdown are already out of `rowIdx`, so no
    // colour rule has to account for them any more.
    const colors = rowIdx.map((i) => {
      const c = chrs[i];

      // Highlight-driven dimming wins over colour-by for the non-highlighted
      // tier — same logic as before, just composed with arbitrary colour rules.
      if (tiers && highlight !== 'none') {
        const isAbove = tiers[i] === 'ABOVE';
        const isHighlighted = highlight === 'above' ? isAbove : !isAbove;
        if (!isHighlighted) return dimColor;
      }

      if (rainfallClassColor) return rainfallClassColor(i);

      // Highlighted (or no-threshold) points: paint by the Colour-by mode.
      if (colorBy === COLOR_BY_CHROMOSOME) {
        // Chromosome mode → tier palette if a threshold is set (so chip ↔ dot
        // colours match), otherwise the canonical chromosome palette.
        if (tiers) return tierColorHex(tiers[i]);
        return colorByChr.get(c) || '#777';
      }
      if (colorByIsNumeric && numericSrc) {
        const v = numericSrc[i];
        if (typeof v !== 'number' || !Number.isFinite(v)) return dimColor;
        return numericColor(v);
      }
      if (categoricalColor) return categoricalColor(i);
      // Fallback to chromosome palette if the chosen column had no usable data.
      return colorByChr.get(c) || '#777';
    });
    const sizes = tiers
      ? rowIdx.map((i) => {
          const isAbove = tiers[i] === 'ABOVE';
          if (highlight === 'none') return isAbove ? markerSizeAbove : markerSizeBelow;
          const isHighlighted = highlight === 'above' ? isAbove : !isAbove;
          // Highlighted tier gets the larger size, dimmed tier the smaller.
          return isHighlighted ? markerSizeAbove : markerSizeBelow;
        })
      : markerSizeUniform;

    // 3) Alternating background band shapes, one per visible chromosome, so
    //    the bands line up with the narrowed axis. A lone chromosome gets no
    //    band: there is nothing left for it to alternate against, and a
    //    full-width wash would just read as a tinted plot.
    const bandFill = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)';
    const layoutShapes: any[] = [];
    const bandChrs: string[] = visibleChrs.length > 1 ? visibleChrs : [];
    bandChrs.forEach((c, idx) => {
      if (idx % 2 !== 0) return;
      const span = chrSpan.get(c)!;
      layoutShapes.push({
        type: 'rect',
        xref: 'x',
        yref: 'paper',
        x0: span.start,
        x1: span.end,
        y0: 0,
        y1: 1,
        fillcolor: bandFill,
        line: { width: 0 },
        layer: 'below',
      });
    });

    // 4) Threshold horizontal line. Solid + accent colour so it actually
    //    catches the eye — the previous dotted rgba(128,128,128,0.6) was
    //    invisible against the grey theme. Paired with the per-point recolour
    //    above (hits in chromosome colour, misses dimmed), the line is now
    //    informational rather than load-bearing.
    if (hasThreshold) {
      const accent =
        colorScheme === 'dark' ? 'rgba(232,62,140,0.85)' : 'rgba(214,51,108,0.85)';
      layoutShapes.push({
        type: 'line',
        xref: 'paper',
        x0: 0,
        x1: 1,
        y0: scoreThreshold as number,
        y1: scoreThreshold as number,
        line: { dash: 'solid', color: accent, width: 1.5 },
      });
    }

    // 5) Top-N label annotations. Use the feature column when present,
    //    fall back to "chr:pos". Three filters apply:
    //    a) active chromosomes: the dropdown already dropped the others from
    //       ``rowIdx``, so walking it is the filter.
    //    b) score threshold (when set) — only label the highlighted tier so
    //       labels match the recoloured markers. ``highlight === 'above'``
    //       labels the high-score side (classic GWAS hits); ``below`` labels
    //       the sub-threshold candidates (minority-allele hunting).
    //    c) sort direction follows the highlight target — highest scores first
    //       when highlighting above, lowest first when highlighting below.
    //    ``candidates`` holds positions in the plotted arrays (``xs``), not raw
    //    row indices, so ``rowIdx[j]`` is the hop back to the source columns.
    const annotations: any[] = [];
    if (topNLabels > 0) {
      const candidates: number[] = [];
      for (let j = 0; j < rowIdx.length; j++) {
        const i = rowIdx[j];
        if (hasThreshold && highlight !== 'none') {
          const isAbove = scores[i] != null && scores[i] >= (scoreThreshold as number);
          const isHighlighted = highlight === 'above' ? isAbove : !isAbove;
          if (!isHighlighted) continue;
        }
        candidates.push(j);
      }
      const direction = hasThreshold && highlight === 'below' ? 1 : -1;
      // Rainfall ranks the other way round: the notable variants are the ones
      // closest to their neighbour, since a tight cluster is the whole point
      // of the figure. Negating the y keeps one comparator for both modes.
      const rankOf = (i: number) =>
        rainfallByRow ? -yAt(i) : (scores[i] ?? Infinity);
      candidates.sort((a, b) => direction * (rankOf(rowIdx[a]) - rankOf(rowIdx[b])));
      const top = candidates.slice(0, topNLabels);
      for (const j of top) {
        const i = rowIdx[j];
        const labelRaw = feats.length > 0 ? feats[i] : null;
        const label = labelRaw != null && String(labelRaw).length > 0
          ? String(labelRaw)
          : `${chrs[i]}:${positions[i]}`;
        annotations.push({
          x: xs[j],
          y: yAt(i),
          text: label,
          showarrow: true,
          arrowhead: 0,
          arrowsize: 0.7,
          arrowwidth: 1,
          ax: 0,
          ay: -20,
          font: { size: 10 },
          bgcolor: isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.85)',
          bordercolor: 'rgba(0,0,0,0.2)',
          borderwidth: 1,
          borderpad: 2,
        });
      }
    }

    // 6) Chromosome tick labels at the midpoint of each visible block. The
    //    label is the raw column value ("chr1"), i.e. exactly the token the
    //    Chromosomes dropdown and the left-panel filter show. Stripping it down
    //    to "1" here used to make the axis look like a different, integer,
    //    chromosome naming scheme than the one you filter with.
    const tickvals = visibleChrs.map((c) => chrSpan.get(c)!.mid);
    const ticktext = visibleChrs.slice();
    // Hide the tick labels only for datasets that are natively single-
    // chromosome (viral genomes and the like), where the contig is already
    // named in the tile description. Once a multi-chromosome dataset is
    // narrowed down, the tick label is the only thing saying which chromosome
    // is on screen, so it has to stay.
    const showChrTicks = allChrs.length > 1 || selectedChrs.length > 0;

    // Counts (and `tiers`) deliberately stay genome-wide: they annotate the
    // Show-data table, which lists every fetched row, not just the plotted
    // chromosomes.
    const counts: Record<string, number> | undefined = tiers
      ? tiers.reduce<Record<string, number>>(
          (acc, t) => {
            acc[t] += 1;
            return acc;
          },
          { ABOVE: 0, BELOW: 0 },
        )
      : undefined;

    // Main scatter trace (the visible points). For numeric colour-by we attach
    // a continuous colorscale + colorbar so the gradient reads as a legend.
    // ``customdata`` carries [selection value, chromosome, genomic position]:
    // ``x`` is the cumulative genome-wide coordinate, which means nothing to a
    // reader, so the hover quotes the real position from the source column
    // instead. Slot 0 is the selection value because that is the slot
    // ``extractScatterSelection`` reads by convention (the frontend-only
    // ``selection_column_index`` is 0 everywhere); it stays present, as an
    // empty string, when the component does not select, so there is one slot
    // layout and one hover template rather than two of each.
    const selectionSource = selectionColumn ? (rows[selectionColumn] as unknown[]) ?? [] : [];
    const hasFeatureText = feats.length > 0;
    const yHoverLabel = rainfall ? 'log10 distance' : 'score';
    const mainTrace: Record<string, unknown> = {
      type: 'scattergl' as const,
      mode: 'markers' as const,
      x: xs,
      y: rowIdx.map(yAt),
      ...(hasFeatureText ? { text: rowIdx.map((i) => String(feats[i] ?? '')) } : {}),
      customdata: rowIdx.map((i) => [
        // null rather than '' for a row the selection column has no value for:
        // `extractScatterSelection` skips null, so such a point contributes
        // nothing instead of adding a blank to the filter.
        selectionColumn && selectionSource[i] != null ? String(selectionSource[i]) : null,
        chrs[i],
        Number(positions[i] ?? 0),
      ]),
      hovertemplate: hasFeatureText
        ? `%{customdata[1]}:%{customdata[2]:,d}<br>${yHoverLabel}: %{y}<br>%{text}<extra></extra>`
        : `%{customdata[1]}:%{customdata[2]:,d}<br>${yHoverLabel}: %{y}<extra></extra>`,
      marker: { color: colors, size: sizes, opacity: 0.85 },
      showlegend: false,
    };

    // Invisible legend traces — one per categorical value — so Plotly draws a
    // proper colour legend the user can decode. Same pattern as
    // OncoplotRenderer uses for mutation-type colours. Rainfall's class
    // column, when bound, is the legend instead of the Colour-by column.
    const legendItems = rainfallClassColor ? rainfallLegendItems : categoricalLegendItems;
    const legendTraces = legendItems.map((item) => ({
      type: 'scatter' as const,
      mode: 'markers' as const,
      x: [null as unknown as number],
      y: [null as unknown as number],
      name: item.name,
      marker: { color: item.color, size: 10 },
      showlegend: true,
      hoverinfo: 'skip' as const,
    }));

    // Colorbar trace for numeric colour-by — invisible scatter that just
    // hosts the colorscale + colorbar config. Plotly renders the bar to the
    // right of the plot area.
    const numericColorbarTrace =
      colorByIsNumeric && numericSrc
        ? [
            {
              type: 'scatter' as const,
              mode: 'markers' as const,
              x: [null as unknown as number],
              y: [null as unknown as number],
              showlegend: false,
              hoverinfo: 'skip' as const,
              marker: {
                color: [numericMin, numericMax],
                colorscale: [
                  [0, orangeHex],
                  [1, tealHex],
                ],
                cmin: numericMin,
                cmax: numericMax,
                showscale: true,
                colorbar: {
                  title: {
                    text:
                      colorBy === COLOR_BY_SCORE
                        ? config.score_kind || config.score_col
                        : colorBy,
                    side: 'right' as const,
                  },
                  thickness: 12,
                  len: 0.9,
                  x: 1.02,
                  xpad: 0,
                },
                size: 0.001,
              },
            },
          ]
        : [];

    const showLegend = legendTraces.length > 0;

    return {
      figure: {
        data: [adaptGlTrace(mainTrace, glGranted), ...legendTraces, ...numericColorbarTrace],
        layout: {
          ...plotlyThemeFragment(isDark, theme),
          // Slightly more right margin to give the colorbar / legend breathing
          // room so it doesn't crowd the plot area.
          // Bottom margin: for single-chromosome datasets (viral genomes etc.)
          // the chromosome name is shown in the tile description, so we hide
          // ticks entirely and trim margin.b to a minimum. Multi-chromosome
          // datasets still need ~22 px for the tick labels.
          margin: {
            l: 55,
            r: showLegend || numericColorbarTrace.length ? 110 : 20,
            t: 10,
            b: showChrTicks ? 22 : 8,
          },
          xaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            // No axis title — the chromosome tick labels are the axis label.
            // Removes ~22 px of dead space under the plot.
            zeroline: false,
            showgrid: false,
            tickmode: 'array',
            tickvals,
            ticktext,
            showticklabels: showChrTicks,
            // Prefixed labels ("chr1" through "chr22") are wider than the bare
            // numbers they replaced, so keep them small and let Plotly rotate
            // them and claim the bottom margin it needs rather than overlap.
            tickfont: { size: 10 },
            automargin: true,
            range: xRange,
          },
          yaxis: {
            ...plotlyAxisOverrides(isDark, theme),
            title: { text: rainfall ? RAINFALL_Y_TITLE : config.score_kind || config.score_col },
            zeroline: false,
            // Clamp range for bounded score types. Plotly's autorange
            // over-pads when annotation labels sit at the data ceiling
            // (variant labels at AF=1), which is what created the giant
            // [-1, 4] empty band under the variant dots. The clamp is a
            // statement about the score, so it goes with it in rainfall mode.
            ...(!rainfall &&
            /(af|allele frequency|frequency|proportion|fraction)/i.test(
              String(config.score_kind || ''),
            )
              ? { range: [0, 1.05], autorange: false, fixedrange: false }
              : {}),
          },
          shapes: layoutShapes,
          annotations,
          showlegend: showLegend,
          legend: showLegend
            ? {
                orientation: 'v' as const,
                x: 1.02,
                y: 1,
                font: { size: 10 },
                title: {
                  text: rainfallClassCol || (typeof colorBy === 'string' ? colorBy : ''),
                  font: { size: 10 },
                },
              }
            : undefined,
          // Drag draws a lasso instead of zooming, so the selection is
          // reachable without opening the modebar. Zoom stays available from
          // the modebar, which the track keeps.
          ...(selectionEnabled ? { dragmode: 'lasso' as const } : {}),
          // Plotly wipes UI state — the drawn lasso and every trace's
          // `selectedpoints` — on each `Plotly.react`, and `applyDataTheme`
          // hands the wrapper a fresh trace array on every render, so one
          // happens as soon as the emitted selection lands back in
          // `filters`. Without a stable `uirevision` the lasso the user has
          // just drawn disappears the instant it takes effect. Keyed on
          // `refreshTick` like FigureRenderer: a realtime tick still
          // repaints, a filter change does not.
          uirevision: `tick-${refreshTick ?? 0}`,
          // Selected points are keyed apart from the zoom: an outside clear
          // (group saved, filter removed) undims the plot and keeps the view.
          selectionrevision: `sel-${selectionRevision}`,
          autosize: true,
        },
      },
      allChrs,
      tiers,
      counts,
    };
  }, [
    rows,
    config,
    refreshTick,
    selectionRevision,
    selectionColumn,
    selectionEnabled,
    scoreThreshold,
    selectedChrs,
    followedRegion,
    topNLabels,
    markerSizeAbove,
    markerSizeBelow,
    markerSizeUniform,
    highlight,
    colorBy,
    rainfall,
    rainfallClassCol,
    colorScheme,
    theme,
    glGranted,
  ]);

  // Memoised so AdvancedVizFrame's `extras` useMemo stays stable between
  // renders, see VolcanoRenderer for the full reasoning. Rainfall ignores the
  // score, so the threshold-driven controls go with it.
  const hasThreshold = !rainfall && scoreThreshold != null && Number.isFinite(scoreThreshold);

  // Build Colour-by Select options from the live data — always include the two
  // sentinels (Chromosome / Score), then any extra ``color_by_columns`` that
  // actually came back in ``rows`` (so a stale config doesn't surface a column
  // the DC no longer has).
  const colorByOptions = useMemo(() => {
    const opts: { value: string; label: string }[] = [
      { value: COLOR_BY_CHROMOSOME, label: 'Chromosome' },
      { value: COLOR_BY_SCORE, label: `${config.score_kind || 'Score'} (continuous)` },
    ];
    for (const c of config.color_by_columns ?? []) {
      if (rows && c in rows) opts.push({ value: c, label: c });
    }
    return opts;
  }, [config.color_by_columns, config.score_kind, rows]);

  // Encoding tier: which figure (score or rainfall), what colours it, where
  // the threshold cuts, which side of it is the hit, and which chromosomes are
  // on the axis. Labels and marker sizes are paint.
  const primaryControls = useMemo(
    () => (
      <>
        <SegmentedControl
          size="xs"
          w={160}
          value={mode}
          onChange={(v) => setMode(v as VizMode)}
          data={[
            { value: 'manhattan', label: 'Score' },
            { value: 'rainfall', label: 'Rainfall' },
          ]}
        />
        {/* A class column is the rainfall figure's colour rule, so Colour-by
            has nothing left to say while it is bound. */}
        {colorByOptions.length > 2 && !rainfallClassCol ? (
          <Select
            size="xs"
            w={170}
            label="Colour by"
            value={colorBy}
            onChange={(v) => setColorBy(v ?? COLOR_BY_CHROMOSOME)}
            data={colorByOptions}
            allowDeselect={false}
            comboboxProps={{ withinPortal: true }}
          />
        ) : null}
        {rainfall ? null : (
          <NumberInput
            size="xs"
            w={110}
            label="Threshold"
            value={scoreThreshold ?? ''}
            onChange={(v) => setScoreThreshold(v === '' ? undefined : Number(v))}
            decimalScale={3}
          />
        )}
        {hasThreshold ? (
          <Stack gap={4}>
            <Text size="xs" fw={500}>
              Highlight
            </Text>
            <SegmentedControl
              size="xs"
              w={190}
              value={highlight}
              onChange={(v) => setHighlight(v as Highlight)}
              data={[
                { value: 'above', label: 'Above' },
                { value: 'below', label: 'Below' },
                { value: 'none', label: 'Both' },
              ]}
            />
          </Stack>
        ) : null}
        <MultiSelect
          size="xs"
          w={200}
          label="Chromosomes"
          value={selectedChrs}
          onChange={setSelectedChrs}
          data={allChrs}
          placeholder="all"
          searchable
          clearable
          comboboxProps={{ withinPortal: true }}
        />
      </>
    ),
    [
      scoreThreshold,
      hasThreshold,
      highlight,
      colorBy,
      colorByOptions,
      mode,
      rainfall,
      rainfallClassCol,
      selectedChrs,
      allChrs,
    ],
  );

  const controls = useMemo(
    () => (
      <Stack gap="xs">
        <NumberInput
          size="xs"
          label="Top-N labels"
          value={topNLabels}
          onChange={(v) => setTopNLabels(Number(v) || 0)}
          min={0}
          max={50}
        />
        {hasThreshold ? (
          <>
            <NumberInput
              size="xs"
              label={
                highlight === 'below'
                  ? 'Marker size (below, highlighted)'
                  : highlight === 'above'
                  ? 'Marker size (above, highlighted)'
                  : 'Marker size (above)'
              }
              value={markerSizeAbove}
              onChange={(v) => setMarkerSizeAbove(Math.max(1, Number(v) || 1))}
              min={1}
              max={30}
            />
            <NumberInput
              size="xs"
              label={
                highlight === 'below'
                  ? 'Marker size (above, dimmed)'
                  : highlight === 'above'
                  ? 'Marker size (below, dimmed)'
                  : 'Marker size (below)'
              }
              value={markerSizeBelow}
              onChange={(v) => setMarkerSizeBelow(Math.max(1, Number(v) || 1))}
              min={1}
              max={30}
            />
          </>
        ) : (
          <NumberInput
            size="xs"
            label="Marker size"
            value={markerSizeUniform}
            onChange={(v) => setMarkerSizeUniform(Math.max(1, Number(v) || 1))}
            min={1}
            max={30}
          />
        )}
      </Stack>
    ),
    [hasThreshold, topNLabels, markerSizeAbove, markerSizeBelow, markerSizeUniform, highlight],
  );

  // Recolour by the dashboard's analysis groups, when the groups were made on
  // a column this plot's points actually carry. The join is on values, not on
  // column names, and `splitFigureByGroups` returns the figure untouched when
  // no point matches — so a group built from sample ids on another tile leaves
  // a per-variant Manhattan exactly as its own colour-by drew it.
  //
  // Slot 0 of ``customdata`` is the selection value, by the same convention
  // ``extractScatterSelection`` reads.
  const groupedFigure = useMemo(() => {
    if (!figure) return figure;
    return splitFigureByGroups(figure, {
      groupRender,
      identitySlot: 0,
      facetable: false,
      showLegend: true,
    });
  }, [figure, groupRender]);
  // Whether any point matched, for the dispatch's "not grouped" badge.
  useReportGroupColouring(groupRender, figure, groupedFigure);

  // ``selectedOrder`` drives which tier gets the "selected" treatment in the
  // top counts chips AND the Show-data table row highlighting. Follow the
  // user's highlight pick so the chips, table rows, and plot markers all agree
  // on which side of the threshold is the interesting one. ``none`` selects
  // both tiers so neither dims.
  const tierAnnotation = useMemo(
    () =>
      tiers
        ? {
            values: tiers,
            selectedOrder:
              highlight === 'below'
                ? ['BELOW']
                : highlight === 'none'
                ? ['ABOVE', 'BELOW']
                : ['ABOVE'],
            columnLabel: 'threshold',
          }
        : undefined,
    [tiers, highlight],
  );

  // Lasso / box / click all land on the same `(index, 'scatter_selection')`
  // entry, so the last gesture replaces the previous one and a deselect
  // clears it. Two caps bound what a gesture can produce: the data endpoint
  // serves a reduced, tail-sampled frame (~100k rows), so only the variants
  // actually drawn can be caught, and a selection wider than
  // MAX_GROUP_VALUES (25k distinct values) is refused by
  // `groupFromSelectionFilter` when the user tries to save it as a group. It
  // still cross-filters at any size.
  //
  // Only a gesture may empty the selection: the shared guard drops the empty
  // re-selection every `Plotly.react` emits (see selectionGesture).
  const emitSelection = (values: string[]) => {
    if (!onFilterChange || !selectionColumn) return;
    onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, values));
  };
  const { onSelecting: handleSelecting, onSelected: handleSelected } =
    useGestureGuardedSelection(
      selectionEnabled
        ? (event: any) => emitSelection(extractScatterSelection(event, 0))
        : undefined,
    );
  // A single click is a one-point selection, which is how the scatter figures
  // and the Dash viewer have always read it.
  const handleClick = (event: any) => {
    if (!selectionEnabled) return;
    emitSelection(extractScatterSelection(event, 0));
  };
  const handleDeselect = () => {
    if (!selectionEnabled) return;
    emitSelection([]);
  };

  // Stable figure props. react-plotly compares data, layout and config by
  // identity and calls `Plotly.react` on any change, so a render that draws
  // nothing new (the selection's own filter landing back in `filters`) must
  // hand it the same objects, or it redraws and re-selects for nothing.
  const plotFigure = useMemo(
    () =>
      groupedFigure
        ? {
            data: applyDataTheme(groupedFigure.data, isDark, theme) as any,
            layout: applyLayoutTheme(groupedFigure.layout as any, isDark, theme) as any,
          }
        : null,
    [groupedFigure, isDark, theme],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Manhattan'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
      counts={counts}
      tierAnnotation={tierAnnotation}
    >
      {plotFigure ? (
        <Plot
          data={plotFigure.data}
          layout={plotFigure.layout}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={PLOT_CONFIG}
          onSelecting={handleSelecting}
          onSelected={handleSelected}
          onClick={selectionEnabled ? handleClick : undefined}
          onDeselect={selectionEnabled ? handleDeselect : undefined}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ManhattanRenderer;
