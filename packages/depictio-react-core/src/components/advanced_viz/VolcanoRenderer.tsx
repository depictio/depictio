import React, { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Box,
  Stack,
  TextInput,
  Tooltip,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from './LegendAwarePlot';

import {
  fetchAdvancedVizData,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import { usePinnedCategoryColors } from '../../hooks/useCategoryColors';
import { isStaleFetch } from '../../fetchQueue';
import { adaptGlTrace, SVG_MAX_POINTS, useWebglSlot } from '../../webglBudget';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  VizControlGroup,
  VizFullRow,
  VizInlineField,
  VizNumberInput,
  VizSegmented,
  VizSelect,
  VizSwitch,
} from './controls/VizControls';
import { usePersistedVizControl } from './usePersistedVizControl';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import {
  classifyTiers,
  contrastLabel,
  contrastSides,
  genomicInflation,
  MA_TABLE_COLUMNS,
  maTableOf,
  matchSearch,
  offeredDeViews,
  qqConfidenceBand,
  qqSeries,
  rankTopN,
  resolveDeView,
  significancePredicate,
  tierCounts,
  type DeTier,
  type DeView,
} from './deViews';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import { supportsAdvancedVizAnnotation } from '../../annotations/plotDecorate';

/** Point labels and the axes' text: 10 read as fine print next to the tile's title. */
const LABEL_FONT_SIZE = 13;

interface VolcanoConfig {
  feature_id_col: string;
  effect_size_col: string;
  significance_col: string;
  label_col?: string;
  /** Second hover line; in the MA view it is read from the MA table. */
  hover_col?: string;
  category_col?: string;
  /** Name the category (e.g. the contrast) in the hover, in every view. */
  hover_category?: boolean;
  significance_is_neg_log10?: boolean;
  significance_threshold?: number;
  effect_threshold?: number;
  top_n_labels?: number;
  /** Volcano axis titles in words; unset, the column names. */
  effect_label?: string | null;
  significance_label?: string | null;
  /** MA and QQ view bindings. See deViews.ts for why they live on this config. */
  avg_log_intensity_col?: string | null;
  log2_fold_change_col?: string | null;
  fold_change_threshold?: number;
  p_value_col?: string | null;
  show_ci?: boolean;
  show_identity?: boolean;
  point_size?: number;
  view?: DeView;
  views?: DeView[] | null;
  /** Or an MA table of its own (`ma_dc_tag`), for a test with no abundance. */
  ma_wf_id?: string | null;
  ma_dc_id?: string | null;
  /** Marker shape per group for the hits: a point leans toward the group its
   *  contrast tests (UP) or toward the reference (DN), and takes that group's
   *  shape. Colour stays the tier's: pink up, blue down. */
  reference?: string | null;
  contrast_prefix?: string | null;
  group_symbols?: Record<string, string> | null;
  /** Columns the marker shape can be switched to (e.g. `Kingdom`), beside the
   *  group / direction readings. Fetched with the tile, so the switch is instant. */
  marker_cols?: string[] | null;
}

/** The marker shapes a categorical column cycles through, most frequent value first. */
const MARKER_SHAPES = ['circle', 'square', 'diamond', 'triangle-up', 'cross', 'x', 'star', 'hexagon'];
/** The shape-by choices that are not a column. */
const MARKER_BY_DEFAULT = '__default__';
const MARKER_BY_DIRECTION = '__direction__';

const MA_TABLE_COLUMN_LIST = Object.values(MA_TABLE_COLUMNS);

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: VolcanoConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Dashboard-wide analysis grouping, recoloured into the built figure.
   *  Colour only: this plot is keyed per feature, so panels would repeat the
   *  same marks. See `splitFigureByGroups`. */
  groupRender?: GroupRenderState;
}

/** Tier colours, kept out of the builders so all three views share one scheme. */
const TIER_COLOURS: Record<DeTier, string> = {
  UP: '#e64980',
  DN: '#1c7ed6',
  NS: 'rgba(160,160,160,0.55)',
};

interface MarkerPlan {
  /** The shape of a point; undefined leaves the tier's own (triangles by direction). */
  symbolFor?: (index: number, tier: DeTier) => string | undefined;
  /** Name and shape of each class drawn, for the key. */
  shapes: [string, string][];
}

/** The group sides of one contrast, as marker shapes. */
function groupSides(contrast: string, config: VolcanoConfig) {
  const sides = contrastSides(contrast, config, { positive: '', negative: '' });
  const symbols = config.group_symbols ?? {};
  return {
    positiveName: sides.positiveName,
    negativeName: sides.negativeName,
    positive: symbols[sides.positiveName],
    negative: sides.negativeName ? symbols[sides.negativeName] : undefined,
  };
}

/**
 * What the marker shape says, for the rows on screen. `__default__` is the
 * group reading when the dashboard names its groups (a hit takes the shape of the
 * group it leans toward: the contrast's own when UP, the reference when DN) and
 * the tier's triangles otherwise; `__direction__` is those triangles; anything
 * else is a column, whose values take the shapes in order of frequency and which
 * shapes every point, the not significant ones included.
 */
function markerPlanOf(
  source: Record<string, unknown[]> | null,
  config: VolcanoConfig,
  mode: string,
): MarkerPlan {
  if (!source) return { shapes: [] };
  if (mode === MARKER_BY_DIRECTION) return { shapes: [] };
  if (mode === MARKER_BY_DEFAULT) {
    if (!config.group_symbols) return { shapes: [] };
    const contrasts = config.category_col ? source[config.category_col] : undefined;
    const names = contrasts ? Array.from(new Set(contrasts.map((v) => String(v ?? '')))).sort() : [''];
    const shapes = new Map<string, string>();
    for (const c of names) {
      const sides = groupSides(c, config);
      if (sides.negativeName && sides.negative) shapes.set(sides.negativeName, sides.negative);
    }
    for (const c of names) {
      const sides = groupSides(c, config);
      if (sides.positive) shapes.set(sides.positiveName, sides.positive);
    }
    return {
      symbolFor: (index, tier) => {
        if (tier === 'NS') return undefined;
        const sides = groupSides(String(contrasts?.[index] ?? ''), config);
        return tier === 'UP' ? sides.positive : sides.negative;
      },
      shapes: Array.from(shapes),
    };
  }
  const values = source[mode] as unknown[] | undefined;
  if (!values) return { shapes: [] };
  const counts = new Map<string, number>();
  for (const v of values) {
    const k = String(v ?? '');
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const ranked = Array.from(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const shapeOf = new Map(ranked.map(([k], i) => [k, MARKER_SHAPES[i] ?? 'circle']));
  return {
    symbolFor: (index) => shapeOf.get(String(values[index] ?? '')),
    shapes: ranked.slice(0, MARKER_SHAPES.length).map(([k]) => [k || '(none)', shapeOf.get(k)!]),
  };
}

/**
 * Marker scheme shared by the volcano and the MA view: colour is the tier (pink
 * up, blue down, grey not significant), a hit is outlined and larger than the
 * small faded NS circles, and its shape says which group it leans toward when
 * the dashboard names them (otherwise a triangle pointing the way its effect goes).
 */
function tierMarker(
  tiers: readonly DeTier[],
  isDark: boolean,
  /** The shape of a point, by row and tier; undefined leaves the tier's own. */
  symbolFor?: (index: number, tier: DeTier) => string | undefined,
) {
  const outline = isDark ? 'rgba(255,255,255,0.9)' : 'rgba(30,30,30,0.85)';
  return {
    color: tiers.map((t) => TIER_COLOURS[t]),
    symbol: tiers.map(
      (t, i) =>
        symbolFor?.(i, t) ?? (t === 'NS' ? 'circle' : t === 'UP' ? 'triangle-up' : 'triangle-down'),
    ),
    size: tiers.map((t) => (t === 'NS' ? 4 : 10)),
    opacity: 0.85,
    line: {
      color: tiers.map((t) => (t === 'NS' ? 'rgba(0,0,0,0)' : outline)),
      width: tiers.map((t) => (t === 'NS' ? 0 : 1)),
    },
  };
}

const DOTTED_GUIDE = { dash: 'dot' as const, color: 'rgba(128,128,128,0.6)', width: 1 };

const VIEW_LABELS: Record<DeView, string> = { volcano: 'Volcano', ma: 'MA', qq: 'QQ' };

/**
 * The differential-expression tile: one table, three readings.
 *
 * Volcano (effect against significance), MA (effect against abundance) and QQ
 * (observed significance against the uniform null) answer three questions about
 * the same rows, and a reader moves between them constantly. Splitting them
 * across three tiles meant three fetches of the same table and three places to
 * set the same cutoff, and left the reader comparing plots whose thresholds had
 * quietly drifted apart. One fetch, one set of thresholds, one selection, and a
 * switch in the tile header. `ma` and `qq` stay live as kind names: their
 * renderers are thin wrappers that open this tile on their view.
 */
const VolcanoRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as VolcanoConfig;
  // The QQ view's categories wear the dashboard's colours for `category_col`.
  const categoryPinned = usePinnedCategoryColors(config.category_col);

  // Tier-2 controls (never enter the global filter array). The thresholds and
  // the label budget say what the chart is, so they persist; the search box is
  // a way of looking at it and stays local.
  const [view, setView] = usePersistedVizControl<DeView>(metadata, 'view', 'volcano');
  const [sigThreshold, setSigThreshold] = usePersistedVizControl<number>(
    metadata,
    'significance_threshold',
    0.05,
  );
  const [effectThreshold, setEffectThreshold] = usePersistedVizControl<number>(
    metadata,
    'effect_threshold',
    1.0,
  );
  const [fcThreshold, setFcThreshold] = usePersistedVizControl<number>(metadata, 'fold_change_threshold', 1.0);
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n_labels', 20);
  const [search, setSearch] = useState<string>('');
  const [showLabels, setShowLabels] = usePersistedVizControl(metadata, 'show_labels', true);
  const [showCi, setShowCi] = usePersistedVizControl(metadata, 'show_ci', true);
  const [showIdentity, setShowIdentity] = usePersistedVizControl(metadata, 'show_identity', true);
  const [pointSize, setPointSize] = usePersistedVizControl(metadata, 'point_size', 5);
  const [markerBy, setMarkerBy] = usePersistedVizControl<string>(metadata, 'marker_by', MARKER_BY_DEFAULT);

  const offered = useMemo(() => offeredDeViews(config), [config]);
  // The author's pick, unless the bindings stopped supporting it (a column was
  // renamed, or `views` narrowed). Resolved at build time rather than corrected
  // through the setter, so a stale stored value is never written back on load.
  const activeView = resolveDeView(view, offered);

  // The QQ view wants raw p-values. `p_value_col` names them explicitly;
  // otherwise `significance_col` already holds them, unless it was declared as
  // -log10, in which case `offeredDeViews` never offers the view at all.
  const pValueCol = config.p_value_col || config.significance_col;
  // The MA view's y is a log fold change, which for most tables is the same
  // column the volcano puts on x.
  const maYCol = config.log2_fold_change_col || config.effect_size_col;
  // What the marker shape can say: the group (or the tier's triangles), the
  // direction alone, or one of the columns the dashboard offers.
  const markerChoices = useMemo(
    () => [
      { value: MARKER_BY_DEFAULT, label: config.group_symbols ? 'Locality' : 'Direction' },
      ...(config.group_symbols ? [{ value: MARKER_BY_DIRECTION, label: 'Direction' }] : []),
      ...(config.marker_cols ?? []).map((c) => ({ value: c, label: c })),
    ],
    [config.group_symbols, config.marker_cols],
  );
  const activeMarkerBy = markerChoices.some((c) => c.value === markerBy) ? markerBy : MARKER_BY_DEFAULT;
  // Or the MA view reads a table of its own, in the MA plot's canonical
  // columns, fetched only while that view is on screen.
  const maTable = useMemo(() => maTableOf(config), [config]);
  const maFromTable = activeView === 'ma' && maTable !== null;

  // One fetch for the tile: the union over every view it can show, so the
  // switch is instant and never re-queries a 17M-row table.
  const requiredCols = useMemo(
    () =>
      Array.from(
        new Set(
          [
            config.feature_id_col,
            config.effect_size_col,
            config.significance_col,
            config.label_col,
            config.hover_col,
            config.category_col,
            config.avg_log_intensity_col,
            config.log2_fold_change_col,
            config.p_value_col,
            ...(config.marker_cols ?? []),
          ].filter(Boolean) as string[],
        ),
      ),
    [config],
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
  } | null>(null);

  // A new filter slice may have a different row count — drop back to the
  // sampled view so the user re-opts into a full load for the new data.
  const filterSig = JSON.stringify(filters);
  useEffect(() => {
    setFullLoad(false);
  }, [filterSig]);

  // At least one of the three views has to have somewhere to draw. Phrased over
  // the config rather than over the fetched column count because a QQ-only
  // binding names two columns, not three, and because it must not change when
  // the reader switches view: that would refetch the table on every switch.
  const hasBinding = Boolean(
    (config.effect_size_col && config.significance_col) ||
      (config.avg_log_intensity_col && maYCol) ||
      config.p_value_col,
  );

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !hasBinding) {
      setError('Volcano: missing data binding');
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
        vizKind: 'volcano',
        roles: {
          feature_id: config.feature_id_col,
          effect_size: config.effect_size_col,
          significance: config.significance_col,
        },
        // The server reduces a large frame to ~10k rows, and a uniform sample
        // of a genome-wide table keeps essentially none of the hits — the plot
        // that exists to show them would show a cloud. Sending the cutoff this
        // volcano draws its own line at keeps precisely those rows whole. The
        // MA and QQ views read the same tail, which is one more reason for the
        // three of them to share a fetch.
        //
        // Deliberately the *saved* threshold, not the live `sigThreshold`
        // control: that one is a client-side slider, and refetching a 17M-row
        // table on every drag to widen the tail is a worse trade than leaving
        // the newly-significant rows to the uniform sample of the middle.
        //
        // Skipped when nothing names the significance column: a table bound
        // through the `ma` alias may have none, and asking the server to keep
        // the tail of a column that is not there fails the whole fetch.
        ...(config.significance_col
          ? {
              tail: {
                column: config.significance_col,
                direction: config.significance_is_neg_log10 ? 'high' : ('low' as const),
                threshold: config.significance_is_neg_log10
                  ? -Math.log10(config.significance_threshold ?? 0.05)
                  : (config.significance_threshold ?? 0.05),
              },
            }
          : {}),
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), filterSig, refreshTick, fullLoad]);

  // The MA table: same filters as the test's table (its contrast column is
  // narrowed by the same contrast filter), kept whole below the cutoff.
  const maColumns = useMemo(
    () =>
      [
        ...MA_TABLE_COLUMN_LIST,
        ...(config.hover_col ? [config.hover_col] : []),
        ...(config.hover_category && config.category_col ? [config.category_col] : []),
        ...(config.marker_cols ?? []),
        ...(config.group_symbols && config.category_col ? [config.category_col] : []),
      ].filter((c, i, all) => all.indexOf(c) === i),
    [config.hover_col, config.hover_category, config.category_col, config.marker_cols, config.group_symbols],
  );
  const [maRows, setMaRows] = useState<Record<string, unknown[]> | null>(null);
  const [maLoading, setMaLoading] = useState<boolean>(false);
  const [maError, setMaError] = useState<string | null>(null);
  useEffect(() => {
    if (!maFromTable || !maTable) return;
    let cancelled = false;
    const ctrl = new AbortController();
    setMaLoading(true);
    setMaError(null);
    fetchAdvancedVizData(
      {
        wfId: maTable.wfId,
        dcId: maTable.dcId,
        columns: maColumns,
        filters,
        fullLoad,
        vizKind: 'ma',
        tail: {
          column: MA_TABLE_COLUMNS.significance,
          direction: 'low',
          threshold: config.significance_threshold ?? 0.05,
        },
      },
      ctrl.signal,
    )
      .then((res) => {
        if (!cancelled) setMaRows(res.rows);
      })
      .catch((err: unknown) => {
        if (cancelled || isStaleFetch(err)) return;
        setMaError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setMaLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
  }, [maFromTable, maTable?.wfId, maTable?.dcId, filterSig, refreshTick, fullLoad, maColumns]);

  // Every view draws a marker cloud, so the tile always competes for one of the
  // bounded WebGL slots. Without one it renders as SVG, see webglBudget.
  const glGranted = useWebglSlot(true);

  const figure = useMemo(() => {
    if (!rows) return null;
    const ids = (rows[config.feature_id_col] || []) as (string | number)[];
    const labels = config.label_col
      ? ((rows[config.label_col] || []) as (string | number)[])
      : ids;
    const hovers = hoverLines(rows, config);
    if (activeView === 'qq') {
      return buildQq({
        ps: (rows[pValueCol] || []) as number[],
        ids: config.feature_id_col ? ids : null,
        hoverCategory: Boolean(config.hover_category),
        cats: config.category_col ? ((rows[config.category_col] || []) as (string | number)[]) : null,
        catColours: categoryPinned,
        // A QQ-only binding has no significance column, and the predicate over
        // an absent one passes every row: it would draw every point as a hit.
        isSignificant:
          config.significance_col && rows[config.significance_col]?.length
            ? significancePredicate(rows[config.significance_col] as number[], {
                isNegLog10: Boolean(config.significance_is_neg_log10),
                threshold: sigThreshold,
              })
            : undefined,
        showCi,
        showIdentity,
        pointSize,
        topN,
        isDark,
        theme,
        glGranted,
      });
    }

    if (maFromTable) {
      if (!maRows) return null;
      const c = MA_TABLE_COLUMNS;
      const maIds = (maRows[c.featureId] || []) as (string | number)[];
      return buildMa({
        xs: (maRows[c.avgLogIntensity] || []) as number[],
        ys: (maRows[c.log2FoldChange] || []) as number[],
        sigRaw: (maRows[c.significance] || []) as number[],
        ids: maIds,
        labels: (maRows[c.label] as (string | number)[] | undefined) ?? maIds,
        hovers: hoverLines(maRows, config),
        hitSymbol: markerPlanOf(maRows, config, activeMarkerBy).symbolFor,
        xTitle: 'Mean log abundance',
        yTitle: config.effect_label || 'Log fold change',
        sigTitle: c.significance,
        isNegLog10: false,
        sigThreshold,
        fcThreshold,
        topN,
        search,
        showLabels,
        isDark,
        theme,
        glGranted,
      });
    }

    if (activeView === 'ma') {
      return buildMa({
        xs: (rows[config.avg_log_intensity_col ?? ''] || []) as number[],
        ys: (rows[maYCol] || []) as number[],
        sigRaw: (rows[config.significance_col] || []) as number[],
        ids,
        labels,
        hovers,
        hitSymbol: markerPlanOf(rows, config, activeMarkerBy).symbolFor,
        xTitle: config.avg_log_intensity_col ?? '',
        yTitle: maYCol,
        sigTitle: config.significance_col,
        isNegLog10: Boolean(config.significance_is_neg_log10),
        sigThreshold,
        fcThreshold,
        topN,
        search,
        showLabels,
        isDark,
        theme,
        glGranted,
      });
    }

    return buildVolcano({
      xs: (rows[config.effect_size_col] || []) as number[],
      sigRaw: (rows[config.significance_col] || []) as number[],
      ids,
      labels,
      hovers,
      hitSymbol: markerPlanOf(rows, config, activeMarkerBy).symbolFor,
      isNegLog10: Boolean(config.significance_is_neg_log10),
      effectTitle: config.effect_label || config.effect_size_col,
      sigTitle: config.significance_col,
      sigAxisTitle: config.significance_label || undefined,
      sigThreshold,
      effectThreshold,
      topN,
      search,
      showLabels,
      isDark,
      theme,
      glGranted,
    });
  }, [
    rows,
    maRows,
    maFromTable,
    config,
    activeView,
    pValueCol,
    maYCol,
    sigThreshold,
    effectThreshold,
    fcThreshold,
    activeMarkerBy,
    topN,
    search,
    showLabels,
    showCi,
    showIdentity,
    pointSize,
    categoryPinned,
    isDark,
    theme,
    glGranted,
  ]);

  // The view switch is an encoding control, not a cosmetic one: it says what
  // the tile is showing, so it belongs in the header tier rather than behind
  // the Settings icon. One offered view means nothing to switch.
  const viewControl = useMemo(
    () =>
      offered.length > 1 ? (
        <VizSegmented
          aria-label="View"
          value={activeView}
          onChange={(next) => setView(next as DeView)}
          data={offered.map((name) => ({ value: name, label: VIEW_LABELS[name] }))}
        />
      ) : null,
    [offered, activeView, setView],
  );

  // Encoding tier: which view, which features count as significant, which get
  // labelled and which are searched for. Handed to the frame as a flat
  // fragment; the strip's grid owns the widths.
  const primaryControls = useMemo(
    () => (
      <>
        {viewControl}
        {activeView !== 'qq' ? (
          <VizControlGroup title="Thresholds">
            <Tooltip label="Significance threshold (raw p/padj)">
              <Box>
                <VizNumberInput
                  label="p / padj"
                  value={sigThreshold}
                  onChange={(v) => setSigThreshold(Number(v) || 0.05)}
                  step={0.01}
                  min={0}
                  max={1}
                  decimalScale={3}
                />
              </Box>
            </Tooltip>
            {activeView === 'volcano' ? (
              <VizNumberInput
                label="|effect|"
                value={effectThreshold}
                onChange={(v) => setEffectThreshold(Number(v) || 0)}
                step={0.1}
                min={0}
                decimalScale={2}
              />
            ) : null}
            {activeView === 'ma' ? (
              <VizNumberInput
                label="|log2 FC|"
                value={fcThreshold}
                onChange={(v) => setFcThreshold(Number(v) || 0)}
                step={0.1}
                min={0}
                decimalScale={2}
              />
            ) : null}
          </VizControlGroup>
        ) : null}
        {activeView !== 'qq' && markerChoices.length > 1 ? (
          <VizControlGroup title="Markers">
            <VizSelect
              label="Shape by"
              value={activeMarkerBy}
              onChange={(v) => v && setMarkerBy(v)}
              data={markerChoices}
              allowDeselect={false}
            />
          </VizControlGroup>
        ) : null}
        <VizControlGroup title="Labels">
          <VizNumberInput
            label="Top-N labels"
            value={topN}
            onChange={(v) => setTopN(Math.max(0, Number(v) || 0))}
            min={0}
            max={500}
          />
          {activeView !== 'qq' ? (
            <VizInlineField label="Search">
              <TextInput
                size="xs"
                aria-label="Search"
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
                placeholder="gene / taxon"
              />
            </VizInlineField>
          ) : null}
        </VizControlGroup>
      </>
    ),
    [viewControl, activeView, sigThreshold, effectThreshold, fcThreshold, topN, search, markerChoices, activeMarkerBy],
  );

  // Cosmetic tier: how the same points are painted.
  // Memoised so AdvancedVizFrame's `extras` useMemo doesn't invalidate on
  // every render, otherwise the published popover JSX is republished on
  // each tick and AG Grid receives a fresh tierAnnotation reference, which
  // (combined with controlled `sort`) was clobbering user filter/sort.
  const controls = useMemo(
    () => (
      <>
        {activeView !== 'qq' ? (
          <VizControlGroup title="Labels">
            <VizSwitch
              checked={showLabels}
              onChange={(e) => setShowLabels(e.currentTarget.checked)}
              label="Show top-N labels"
            />
          </VizControlGroup>
        ) : null}
        {activeView === 'qq' ? (
          <VizControlGroup title="QQ plot">
            {figure?.lambdaOverall != null && !Number.isNaN(figure.lambdaOverall) ? (
              <VizFullRow>
                <Badge size="sm" color="grape" variant="light" radius="sm" fullWidth>
                  λ = {figure.lambdaOverall.toFixed(3)}
                </Badge>
              </VizFullRow>
            ) : null}
            {figure?.lambdaByCat?.length ? (
              <VizFullRow>
                <Stack gap={2}>
                  {figure.lambdaByCat.map((entry) => (
                    <Badge key={entry.cat} size="xs" variant="light" radius="sm" fullWidth>
                      {entry.cat}: λ = {entry.lambda.toFixed(3)}
                    </Badge>
                  ))}
                </Stack>
              </VizFullRow>
            ) : null}
            <VizSwitch
              checked={showIdentity}
              onChange={(e) => setShowIdentity(e.currentTarget.checked)}
              label="Identity line"
            />
            <VizSwitch
              checked={showCi}
              onChange={(e) => setShowCi(e.currentTarget.checked)}
              label="95% null CI band"
              disabled={Boolean(config.category_col)}
            />
            <VizNumberInput
              label="Point size"
              value={pointSize}
              onChange={(v) => setPointSize(Math.max(2, Math.min(14, Number(v) || 5)))}
              min={2}
              max={14}
            />
          </VizControlGroup>
        ) : null}
      </>
    ),
    [
      activeView,
      figure,
      showLabels,
      showCi,
      showIdentity,
      pointSize,
      config.category_col,
    ],
  );

  const tierAnnotation = useMemo(
    () =>
      figure?.tiers
        ? {
            values: figure.tiers,
            selectedOrder: ['UP', 'DN'],
            columnLabel: 'tier',
          }
        : undefined,
    [figure?.tiers],
  );

  // Recolour by the dashboard's analysis groups. The join is on values, and
  // `splitFigureByGroups` returns the figure untouched when no point matches,
  // so a group built from sample ids leaves a per-feature plot alone. Slot 0 of
  // `customdata` is the feature id.
  //
  // `contextTraces: 'drop'` in the QQ view: the 95% band is the null envelope
  // for n points across the whole set, not for any group's subset. And every
  // view stays `facetable: false`, the QQ x coordinate is a rank *within the
  // plotted set*, so per-group panels would read as each group's own QQ while
  // being drawn against the cohort's quantiles.
  const groupedFigure = useMemo(
    () =>
      figure
        ? splitFigureByGroups(figure, {
            groupRender,
            identitySlot: 0,
            facetable: false,
            ...(activeView === 'qq' ? { contextTraces: 'drop' as const } : {}),
            showLegend: true,
          })
        : figure,
    [figure, groupRender, activeView],
  );
  // Whether any point matched, for the dispatch's "not grouped" badge.
  useReportGroupColouring(groupRender, figure, groupedFigure);

  // Themed once per figure so the annotation layer can memoise on them.
  const plotData = useMemo(
    () => (groupedFigure ? applyDataTheme(groupedFigure.data, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  const plotLayout = useMemo(
    () => (groupedFigure ? applyLayoutTheme(groupedFigure.layout as any, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  // Chart annotations. Slot 0 of `customdata` is what marked points are keyed
  // on: the label (the feature id when there is no label column) in the
  // volcano and MA views, the feature id in the QQ view (only set when the
  // binding names one). The views have different axes, so annotations are
  // stored per view once the tile offers more than one.
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: supportsAdvancedVizAnnotation(metadata),
    data: plotData,
    layout: plotLayout,
    pointIdIndex: 0,
    pointIdColumn:
      (maFromTable
        ? MA_TABLE_COLUMNS.label
        : activeView === 'qq'
          ? config.feature_id_col
          : config.label_col || config.feature_id_col) || undefined,
    variant: offered.length > 1 ? activeView : undefined,
  });

  // The rows behind the figure on screen, for the frame's data view.
  const shownRows = maFromTable ? maRows : rows;
  // What the marker shapes stand for on screen, for the key.
  const legendShapes = useMemo(
    () => markerPlanOf(shownRows, config, activeMarkerBy).shapes,
    [shownRows, config, activeMarkerBy],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Volcano plot'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading || (maFromTable && maLoading)}
      error={error || (maFromTable ? maError : null)}
      emptyMessage={shownRows && Object.values(shownRows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={shownRows ?? undefined}
      dataColumns={maFromTable ? maColumns : requiredCols}
      counts={figure?.counts}
      tierAnnotation={tierAnnotation}
      badges={annotations.badges}
      reduction={
        reduction && (reduction.sampled || fullLoad)
          ? {
              // Without a WebGL slot the trace is drawn as downsampled SVG, so
              // the badge must report what is on screen, not what arrived.
              displayed: glGranted
                ? reduction.displayed
                : Math.min(reduction.displayed, SVG_MAX_POINTS),
              total: reduction.total,
              sampled: reduction.sampled,
              full: fullLoad,
              loading,
              onToggle: () => setFullLoad((v) => !v),
            }
          : undefined
      }
    >
      {groupedFigure ? (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
          {(config.group_symbols || config.marker_cols?.length) &&
            (activeView === 'qq' || legendShapes.length > 0) && (
              <DeLegend view={activeView} shapes={legendShapes} sigThreshold={sigThreshold} />
            )}
          <Plot
            data={annotations.data as any}
            layout={annotations.layout as any}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
            config={{ displaylogo: false, responsive: true } as any}
            {...annotations.plotProps()}
          />
          {annotations.toolbar}
        </div>
      ) : null}
    </AdvancedVizFrame>
  );
};

/**
 * The key to the markers, drawn over the plot's top edge: shape is the group a
 * hit leans toward, colour its direction. Outside the figure because the
 * markers are one trace. Shown only when the dashboard names its groups; without
 * them the tier badges already say which colour is which.
 */
const DeLegend: React.FC<{
  view: DeView;
  shapes: [string, string][];
  sigThreshold: number;
}> = ({ view, shapes, sigThreshold }) => {
  const glyph = (symbol: string, colour: string) => {
    const mark = { fill: colour, stroke: 'currentColor', strokeWidth: 1 };
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden style={{ marginRight: 4 }}>
        {symbol === 'triangle-up' && <path d="M6 1 L11 10 H1 Z" {...mark} />}
        {symbol === 'triangle-down' && <path d="M6 11 L11 2 H1 Z" {...mark} />}
        {symbol === 'diamond' && <path d="M6 1 L11 6 L6 11 L1 6 Z" {...mark} />}
        {symbol === 'square' && <rect x="2" y="2" width="8" height="8" {...mark} />}
        {symbol === 'cross' && <path d="M5 1 H7 V5 H11 V7 H7 V11 H5 V7 H1 V5 H5 Z" {...mark} />}
        {symbol === 'x' && <path d="M2 2 L10 10 M10 2 L2 10" fill="none" stroke="currentColor" strokeWidth="1.6" />}
        {symbol === 'star' && <path d="M6 1 L7.5 4.5 L11 4.8 L8.3 7.2 L9.1 10.8 L6 9 L2.9 10.8 L3.7 7.2 L1 4.8 L4.5 4.5 Z" {...mark} />}
        {symbol === 'hexagon' && <path d="M6 1 L10.5 3.5 V8.5 L6 11 L1.5 8.5 V3.5 Z" {...mark} />}
        {!['triangle-up', 'triangle-down', 'diamond', 'square', 'cross', 'x', 'star', 'hexagon'].includes(symbol) && (
          <circle cx="6" cy="6" r="3" {...mark} />
        )}
      </svg>
    );
  };
  const item = (key: string, node: React.ReactNode) => (
    <span key={key} style={{ display: 'inline-flex', alignItems: 'center', whiteSpace: 'nowrap' }}>
      {node}
    </span>
  );
  return (
    <div
      data-testid="de-legend"
      style={{
        position: 'absolute',
        top: 2,
        left: 56,
        // Clear of Plotly's mode bar, which sits in the top right corner.
        right: 150,
        display: 'flex',
        flexWrap: 'wrap',
        gap: '0 14px',
        fontSize: 12,
        opacity: 0.85,
        pointerEvents: 'none',
      }}
    >
      {view === 'qq' ? (
        <>
          {item('hit', <>{glyph('diamond', 'currentColor')}significant (≤ {sigThreshold})</>)}
          {item('ns', <>{glyph('circle', TIER_COLOURS.NS)}not significant</>)}
        </>
      ) : (
        <>
          {shapes.map(([name, symbol]) => item(`g-${name}`, <>{glyph(symbol, 'none')}{name}</>))}
          {item('up', <>{glyph('circle', TIER_COLOURS.UP)}up</>)}
          {item('dn', <>{glyph('circle', TIER_COLOURS.DN)}down</>)}
          {item('ns', <>{glyph('circle', TIER_COLOURS.NS)}not significant</>)}
        </>
      )}
    </div>
  );
};

interface BuiltFigure {
  tiers?: DeTier[];
  counts?: Record<string, number>;
  data: any[];
  layout: any;
  lambdaOverall?: number;
  lambdaByCat?: { cat: string; lambda: number }[];
}

/** Effect size against significance: the view the tile is named for. */
function buildVolcano(input: {
  xs: number[];
  sigRaw: number[];
  ids: (string | number)[];
  labels: (string | number)[];
  /** Second hover line per point (`hover_col`). */
  hovers?: (string | number)[];
  isNegLog10: boolean;
  effectTitle: string;
  sigTitle: string;
  /** The y axis title; unset, `-log10(<significance column>)`. */
  sigAxisTitle?: string;
  sigThreshold: number;
  effectThreshold: number;
  topN: number;
  search: string;
  showLabels: boolean;
  hitSymbol?: (index: number, tier: DeTier) => string | undefined;
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  glGranted: boolean;
}): BuiltFigure {
  const { xs, sigRaw, ids, labels, hovers, isNegLog10 } = input;
  const ys = isNegLog10
    ? sigRaw
    : sigRaw.map((p) => (p == null || p <= 0 ? null : -Math.log10(p)));
  // The threshold is always a raw p / padj cutoff (the control says so, and the
  // fetch's tail keeps rows past its -log10), whichever scale the column is on.
  const sigThresholdY = -Math.log10(input.sigThreshold);

  // Classify each point: significant + above-threshold effect ⇒ "hit".
  // The `tiers` array carries UP / DN / NS for the hover badge so the user
  // doesn't have to mentally re-derive it from x/y.
  const tiers = classifyTiers(
    xs,
    input.effectThreshold,
    significancePredicate(sigRaw, { isNegLog10, threshold: input.sigThreshold }),
  );

  // Top-N label selection, by combined (|x| × y) so both axes matter.
  const topIdx = rankTopN(
    xs.map((x, i) => (Math.abs(x) || 0) * (ys[i] ?? 0)),
    input.topN,
  );
  const matchedIdx = matchSearch(ids, labels, input.search);

  const annotations = input.showLabels
    ? xs
        .map((x, i) => {
          const y = ys[i];
          if (y == null) return null;
          if (!(matchedIdx ? matchedIdx.has(i) : topIdx.has(i))) return null;
          // Place each label slightly above its point with a thin connector
          // arrow. This keeps the (x, y) anchor on the point while moving the
          // text bounding box up by 16px, far cleaner when several top-N
          // labels cluster near the same effect/significance corner.
          return {
            x,
            y,
            text: String(labels[i] ?? ids[i] ?? ''),
            showarrow: true,
            arrowhead: 0,
            arrowwidth: 0.6,
            arrowcolor: 'rgba(120,120,120,0.6)',
            ax: 0,
            ay: -16,
            font: { size: LABEL_FONT_SIZE },
          };
        })
        .filter(Boolean)
    : [];

  return {
    tiers,
    counts: tierCounts(tiers),
    data: [
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          // customdata threads label, raw significance and tier badge into the
          // hover so the tooltip reads UP / DN / NS + values without separate
          // per-tier traces. Slot 0 is the identity `splitFigureByGroups` joins on.
          customdata: xs.map((_, i) => [
            String(labels[i] ?? ids[i] ?? ''),
            sigRaw[i] ?? null,
            tiers[i],
            hovers ? String(hovers[i] ?? '') : '',
          ]),
          hovertemplate:
            `<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>` +
            (hovers ? `<br>%{customdata[3]}` : '') +
            `<br>${input.effectTitle}: %{x:.3f}` +
            `<br>${input.sigTitle}: %{customdata[1]:.2e}` +
            `<br>-log10(sig): %{y:.2f}` +
            `<extra></extra>`,
          marker: tierMarker(tiers, input.isDark, input.hitSymbol),
        },
        input.glGranted,
      ),
    ],
    layout: {
      ...plotlyThemeFragment(input.isDark, input.theme),
      font: { ...plotlyThemeFragment(input.isDark, input.theme).font, size: LABEL_FONT_SIZE },
      margin: { l: 50, r: 20, t: 30, b: 40 },
      xaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: input.effectTitle },
        zeroline: true,
      },
      yaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: {
          text:
            input.sigAxisTitle ?? (isNegLog10 ? input.sigTitle : `-log10(${input.sigTitle})`),
        },
      },
      shapes: [
        { type: 'line' as const, x0: -input.effectThreshold, x1: -input.effectThreshold, yref: 'paper', y0: 0, y1: 1, line: DOTTED_GUIDE },
        { type: 'line' as const, x0: input.effectThreshold, x1: input.effectThreshold, yref: 'paper', y0: 0, y1: 1, line: DOTTED_GUIDE },
        { type: 'line' as const, xref: 'paper', x0: 0, x1: 1, y0: sigThresholdY, y1: sigThresholdY, line: DOTTED_GUIDE },
      ],
      annotations,
      showlegend: false,
      autosize: true,
    },
  };
}

/**
 * Mean abundance against fold change, the Bland-Altman reading.
 *
 * Same tier scheme as the volcano, so a hit stays a hit across the switch. The
 * significance column only gates the tiers here; the axes are both effect.
 */
function buildMa(input: {
  xs: number[];
  ys: number[];
  sigRaw: number[];
  ids: (string | number)[];
  labels: (string | number)[];
  hovers?: (string | number)[];
  xTitle: string;
  yTitle: string;
  sigTitle: string;
  isNegLog10: boolean;
  sigThreshold: number;
  fcThreshold: number;
  topN: number;
  search: string;
  showLabels: boolean;
  hitSymbol?: (index: number, tier: DeTier) => string | undefined;
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  glGranted: boolean;
}): BuiltFigure {
  const { xs, ys, sigRaw, ids, labels, hovers } = input;
  const hasSig = sigRaw.length > 0;
  const tiers = classifyTiers(
    ys,
    input.fcThreshold,
    significancePredicate(sigRaw, {
      isNegLog10: input.isNegLog10,
      threshold: input.sigThreshold,
    }),
  );

  // Top-N by |fold change| × -log10(sig) when available, else by |FC| alone.
  const topIdx = rankTopN(
    ys.map((fc, i) => {
      const sig = hasSig && sigRaw[i] > 0 ? -Math.log10(sigRaw[i]) : 1;
      return Math.abs(fc || 0) * sig;
    }),
    input.topN,
  );
  const matchedIdx = matchSearch(ids, labels, input.search);

  const annotations = input.showLabels
    ? xs
        .map((x, i) => {
          if (!(matchedIdx ? matchedIdx.has(i) : topIdx.has(i))) return null;
          return {
            x,
            y: ys[i],
            text: String(labels[i] ?? ids[i] ?? ''),
            showarrow: false,
            font: { size: LABEL_FONT_SIZE },
          };
        })
        .filter(Boolean)
    : [];

  return {
    tiers,
    counts: tierCounts(tiers),
    data: [
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: xs,
          y: ys,
          text: ids.map((v) => String(v ?? '')),
          customdata: xs.map((_, i) => [
            String(labels[i] ?? ids[i] ?? ''),
            hasSig ? sigRaw[i] ?? null : null,
            tiers[i],
            hovers ? String(hovers[i] ?? '') : '',
          ]),
          hovertemplate:
            `<b>%{customdata[0]}</b>  <span style="opacity:0.7">[%{customdata[2]}]</span>` +
            (hovers ? `<br>%{customdata[3]}` : '') +
            `<br>${input.xTitle}: %{x:.3f}` +
            `<br>${input.yTitle}: %{y:.3f}` +
            (hasSig ? `<br>${input.sigTitle}: %{customdata[1]:.2e}` : '') +
            `<extra></extra>`,
          marker: tierMarker(tiers, input.isDark, input.hitSymbol),
        },
        input.glGranted,
      ),
    ],
    layout: {
      ...plotlyThemeFragment(input.isDark, input.theme),
      font: { ...plotlyThemeFragment(input.isDark, input.theme).font, size: LABEL_FONT_SIZE },
      margin: { l: 50, r: 20, t: 30, b: 40 },
      xaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: input.xTitle },
        zeroline: false,
      },
      yaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: input.yTitle },
        zeroline: true,
      },
      shapes: [
        { type: 'line' as const, xref: 'paper', x0: 0, x1: 1, y0: input.fcThreshold, y1: input.fcThreshold, line: DOTTED_GUIDE },
        { type: 'line' as const, xref: 'paper', x0: 0, x1: 1, y0: -input.fcThreshold, y1: -input.fcThreshold, line: DOTTED_GUIDE },
      ],
      annotations,
      showlegend: false,
      autosize: true,
    },
  };
}

/**
 * Observed significance against the uniform null, with the inflation factor.
 *
 * Independent axis ranges (qqman / Hail convention): x bounded by the largest
 * expected value (about log10(N)), y free to grow with the hits. The identity
 * line still spans both corners, so it visibly exits the x frame when the
 * observed tail breaks from the null, which is the point of the plot.
 */
/**
 * The extra hover lines per point: `hover_col`'s value, then the category's
 * (`hover_category`), joined for a Plotly hover. Undefined when neither is set.
 */
function hoverLines(
  rows: Record<string, unknown[]>,
  config: Pick<VolcanoConfig, 'hover_col' | 'hover_category' | 'category_col' | 'reference' | 'contrast_prefix'>,
): string[] | undefined {
  const extra = config.hover_col ? ((rows[config.hover_col] || []) as unknown[]) : null;
  const cats =
    config.hover_category && config.category_col
      ? ((rows[config.category_col] || []) as unknown[])
      : null;
  if (!extra && !cats) return undefined;
  const n = Math.max(extra?.length ?? 0, cats?.length ?? 0);
  return Array.from({ length: n }, (_, i) =>
    [
      extra ? String(extra[i] ?? '') : '',
      cats ? `${config.category_col}: ${contrastLabel(String(cats[i] ?? ''), config)}` : '',
    ]
      .filter(Boolean)
      .join('<br>'),
  );
}

function buildQq(input: {
  ps: number[];
  /** Name the category (the series) in the hover. */
  hoverCategory?: boolean;
  ids: (string | number)[] | null;
  cats: (string | number)[] | null;
  /** Colours pinned for the categories (the dashboard's, see
   *  `columnCategoryColors`); the rest take the palette. */
  catColours?: Record<string, string> | null;
  /** Whether the source row clears the tile's significance cutoff: those
   *  points are drawn as outlined diamonds, as the hits are on the volcano. */
  isSignificant?: (rowIndex: number) => boolean;
  showCi: boolean;
  showIdentity: boolean;
  pointSize: number;
  topN: number;
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  glGranted: boolean;
}): BuiltFigure {
  const { ps, ids, cats } = input;
  const qqMarker = (indices: number[], colour: string | undefined) => {
    const hit = indices.map((i) => Boolean(input.isSignificant?.(i)));
    const outline = input.isDark ? 'rgba(255,255,255,0.9)' : 'rgba(30,30,30,0.85)';
    return {
      color: colour,
      symbol: hit.map((h) => (h ? 'diamond' : 'circle')),
      size: hit.map((h) => (h ? input.pointSize + 4 : input.pointSize)),
      opacity: 0.85,
      line: {
        color: hit.map((h) => (h ? outline : 'rgba(0,0,0,0)')),
        width: hit.map((h) => (h ? 1 : 0)),
      },
    };
  };
  const traces: any[] = [];
  let expectedMax = 0;
  let observedMax = 0;
  let lambdaOverall = NaN;
  const lambdaByCat: { cat: string; lambda: number }[] = [];

  const hoverTemplate = (withId: boolean, withCategory = false) =>
    (withId ? '<b>%{text}</b><br>' : '') +
    (withCategory ? '%{fullData.name}<br>' : '') +
    'expected: %{x:.3f}<br>observed: %{y:.3f}<extra></extra>';

  if (cats) {
    const names = Array.from(new Set(cats.map(String))).sort();
    const colours = stableColorMap(
      names,
      resolveCategoricalPalette(input.theme, TAB10_PALETTE),
      input.catColours,
    );
    const allPs: number[] = [];
    for (const name of names) {
      const indices: number[] = [];
      for (let i = 0; i < cats.length; i++) if (String(cats[i]) === name) indices.push(i);
      const series = qqSeries(ps, indices, ids);
      if (series.n === 0) continue;
      expectedMax = Math.max(expectedMax, series.expected[0]);
      observedMax = Math.max(observedMax, ...series.observed);
      allPs.push(...series.ps);
      lambdaByCat.push({ cat: name, lambda: genomicInflation(series.ps) });
      traces.push(
        adaptGlTrace(
          {
            type: 'scattergl' as const,
            mode: 'markers' as const,
            name,
            x: series.expected,
            y: series.observed,
            text: series.ids,
            // Slot 0 is the feature, and only when the binding names one: with
            // no id column there is no identity to carry.
            ...(ids ? { customdata: series.ids.map((id) => [id]) } : {}),
            hovertemplate: hoverTemplate(Boolean(series.ids[0]), input.hoverCategory),
            marker: qqMarker(series.indices, colours.get(name)),
          },
          input.glGranted,
        ),
      );
    }
    lambdaOverall = genomicInflation(allPs.sort((a, b) => a - b));
  } else {
    const series = qqSeries(
      ps,
      ps.map((_, i) => i),
      ids,
    );
    expectedMax = series.expected[0] ?? 0;
    observedMax = Math.max(0, ...series.observed);
    lambdaOverall = genomicInflation(series.ps);
    traces.push(
      adaptGlTrace(
        {
          type: 'scattergl' as const,
          mode: 'markers' as const,
          x: series.expected,
          y: series.observed,
          text: series.ids,
          ...(ids ? { customdata: series.ids.map((id) => [id]) } : {}),
          hovertemplate: hoverTemplate(Boolean(series.ids[0])),
          marker: qqMarker(series.indices, '#4C72B0'),
        },
        input.glGranted,
      ),
    );

    // Top-N hit labels, overlay text trace on the strongest observations.
    if (input.topN > 0 && series.ids[0]) {
      const ranked = series.observed
        .map((observed, i) => ({ observed, i }))
        .sort((a, b) => b.observed - a.observed)
        .slice(0, input.topN);
      traces.push({
        type: 'scatter' as const,
        mode: 'text' as const,
        x: ranked.map((r) => series.expected[r.i]),
        y: ranked.map((r) => series.observed[r.i] + observedMax * 0.03),
        text: ranked.map((r) => series.ids[r.i]),
        textposition: 'top center' as const,
        textfont: { size: LABEL_FONT_SIZE, color: input.isDark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.85)' },
        hoverinfo: 'skip',
        showlegend: false,
      });
    }

    if (input.showCi) {
      const band = qqConfidenceBand(series.n);
      traces.unshift(
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: band.x,
          y: band.upper,
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
        {
          type: 'scatter' as const,
          mode: 'lines' as const,
          x: band.x,
          y: band.lower,
          fill: 'tonexty',
          fillcolor: input.isDark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.08)',
          line: { width: 0 },
          showlegend: false,
          hoverinfo: 'skip',
        },
      );
    }
  }

  const xUpper = expectedMax * 1.05;
  const yUpper = observedMax * 1.05;
  const diagonalUpper = Math.max(xUpper, yUpper);
  const annotations: any[] = [];
  if (!Number.isNaN(lambdaOverall)) {
    annotations.push({
      xref: 'paper' as const,
      yref: 'paper' as const,
      x: 0.02,
      y: 0.98,
      xanchor: 'left' as const,
      yanchor: 'top' as const,
      text: `λ = ${lambdaOverall.toFixed(3)}`,
      showarrow: false,
      font: { size: 12, color: input.isDark ? '#fff' : '#222' },
      bgcolor: input.isDark ? 'rgba(20,20,20,0.6)' : 'rgba(255,255,255,0.7)',
      bordercolor: input.isDark ? 'rgba(255,255,255,0.3)' : 'rgba(0,0,0,0.2)',
      borderwidth: 1,
      borderpad: 4,
    });
  }

  return {
    data: traces,
    layout: {
      ...plotlyThemeFragment(input.isDark, input.theme),
      font: { ...plotlyThemeFragment(input.isDark, input.theme).font, size: LABEL_FONT_SIZE },
      margin: { l: 60, r: 20, t: 20, b: 50 },
      xaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: '-log10(expected)' },
        range: [0, xUpper],
      },
      yaxis: {
        ...plotlyAxisOverrides(input.isDark, input.theme),
        title: { text: '-log10(observed)' },
        range: [0, yUpper],
      },
      shapes: input.showIdentity
        ? [
            {
              type: 'line' as const,
              x0: 0,
              y0: 0,
              x1: diagonalUpper,
              y1: diagonalUpper,
              line: { dash: 'dash', color: input.isDark ? '#ddd' : '#444', width: 1 },
            },
          ]
        : [],
      annotations,
      showlegend: Boolean(cats),
      autosize: true,
    },
    lambdaOverall,
    lambdaByCat,
  };
}

export default VolcanoRenderer;
