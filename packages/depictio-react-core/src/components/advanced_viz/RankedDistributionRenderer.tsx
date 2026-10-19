import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from './LegendAwarePlot';

import { AdvancedVizKind, fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { categoryColorMap } from '../../categoryColors';
import { mantineCategoricalPalette } from '../../colors';
import { isStaleFetch } from '../../fetchQueue';
import { useCategoryColorSource, useCategoryPalette } from '../../hooks/useCategoryColors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  filtersForSelector,
  selectionValuesFor,
  valuesOnColumn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import { demandForItems, demandForPx } from './contentDemand';
import { VizControlGroup, VizNumberInput, VizSegmented, VizSwitch } from './controls/VizControls';
import { applyDataTheme, applyLayoutTheme, plotlyThemeColors } from './plotlyTheme';
import {
  buildRankedFigure,
  clampTopN,
  columnsToFetch,
  FIGURE_CHROME_PX,
  featureIdFromPoint,
  groupsOf,
  parseRankedRows,
  PX_PER_FEATURE,
  rankFeatures,
  rankingEcho,
  selectedFeatureIds,
  selectionValueOf,
  shapeOf,
  topFeatures,
  VERTICAL_FIGURE_PX,
  type DistributionMark,
  type RankedColumns,
  type RankedOrientation,
} from './ranked_distribution/rankedLayout';
import { usePersistedVizControl } from './usePersistedVizControl';

/** Mirrors `RankedDistributionConfig` in depictio/models/components/advanced_viz/configs.py.
 *  Every key read here has a field there, and `test_advanced_viz_config_alignment`
 *  enforces it. */
interface RankedDistributionConfig {
  feature_id_col: string;
  score_col: string;
  rank_col?: string | null;
  label_col?: string | null;
  group_col?: string | null;
  value_col?: string | null;
  q1_col?: string | null;
  median_col?: string | null;
  q3_col?: string | null;
  lower_col?: string | null;
  upper_col?: string | null;
  mean_col?: string | null;
  top_n?: number;
  ascending?: boolean;
  distribution?: DistributionMark;
  orientation?: RankedOrientation;
  score_label?: string | null;
  value_label?: string | null;
  log_value?: boolean;
  max_features?: number;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: RankedDistributionConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// Sent so the server applies this kind's `none` policy: the ranking and, in
// long form, every feature's quartiles are taken off the rows themselves, so a
// sample would move the boxes and could drop a feature out of the top N.
const RANKED_DISTRIBUTION_VIZ_KIND: AdvancedVizKind = 'ranked_distribution';

const DEFAULT_TOP_N = 25;
const DEFAULT_MAX_FEATURES = 200;
const PLOT_STYLE = { width: '100%', height: '100%' };
const PLOT_CONFIG = {
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
};

/**
 * The top-N features ranked by a score, each with its distribution across
 * samples, on two panels sharing one ordered category axis: a box (or violin)
 * per feature, and a lollipop of the score that ranked it.
 *
 * Every number (ranking, top-N cut, long-form box statistics, the two-panel
 * figure) lives in `ranked_distribution/rankedLayout.ts`; this module fetches,
 * reads the colours off the theme and the dashboard, holds the controls and
 * turns a click into a selection.
 */
const RankedDistributionRenderer: React.FC<Props> = ({
  metadata,
  filters,
  refreshTick,
  onFilterChange,
}) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as RankedDistributionConfig;
  const maxFeatures =
    config.max_features && config.max_features > 0 ? config.max_features : DEFAULT_MAX_FEATURES;

  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n', DEFAULT_TOP_N);
  const [ascending, setAscending] = usePersistedVizControl<boolean>(metadata, 'ascending', true);
  const [mark, setMark] = usePersistedVizControl<DistributionMark>(metadata, 'distribution', 'box');
  const [orientation, setOrientation] = usePersistedVizControl<RankedOrientation>(metadata, 'orientation', 'horizontal');
  const [logValue, setLogValue] = usePersistedVizControl<boolean>(metadata, 'log_value', false);

  // ---- Selection as a cross-filter ---------------------------------------
  // Resolved through selection.ts (named column, else the feature id), so the
  // chrome's capability marker and this gate cannot disagree. A host with no
  // onFilterChange is read-only and advertises nothing.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const columns = useMemo<RankedColumns>(
    () => ({
      featureId: config.feature_id_col,
      score: config.score_col,
      rank: config.rank_col,
      label: config.label_col,
      group: config.group_col,
      value: config.value_col,
      q1: config.q1_col,
      median: config.median_col,
      q3: config.q3_col,
      lower: config.lower_col,
      upper: config.upper_col,
      mean: config.mean_col,
      selection:
        selectionColumn && selectionColumn !== config.feature_id_col ? selectionColumn : null,
    }),
    [
      config.feature_id_col,
      config.score_col,
      config.rank_col,
      config.label_col,
      config.group_col,
      config.value_col,
      config.q1_col,
      config.median_col,
      config.q3_col,
      config.lower_col,
      config.upper_col,
      config.mean_col,
      selectionColumn,
    ],
  );
  const shape = shapeOf(columns);
  const requiredCols = useMemo(() => columnsToFetch(columns), [columns]);

  // Never narrowed by its own pick, nor by any pick on the column it selects
  // on: a gene picked here or in a table beside it is marked, every other gene
  // stays, so the reader can pick another. Filters on other columns narrow it.
  const filtersForFetch = useMemo(
    () => filtersForSelector(filters, metadata.index, 'scatter_selection', selectionColumn),
    [filters, metadata.index, selectionColumn],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || !config.feature_id_col || !config.score_col) {
      setError('Ranked distribution: missing data binding');
      setLoading(false);
      return;
    }
    if (!shape) {
      setError(
        'Ranked distribution: bind either a value column (one row per feature and sample) ' +
          'or q1, median and q3 columns (one row per feature)',
      );
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
        filters: filtersForFetch,
        vizKind: RANKED_DISTRIBUTION_VIZ_KIND,
        roles: { feature_id: config.feature_id_col, score: config.score_col },
      },
      ctrl.signal,
    )
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
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
  }, [
    metadata.wf_id,
    metadata.dc_id,
    config.feature_id_col,
    config.score_col,
    shape,
    JSON.stringify(requiredCols),
    JSON.stringify(filtersForFetch),
    refreshTick,
  ]);

  const parsed = useMemo(
    () => (rows ? parseRankedRows(rows, columns, { logValue }) : null),
    [rows, columns, logValue],
  );
  const byRankColumn = Boolean(config.rank_col);
  const ranked = useMemo(
    () =>
      parsed ? rankFeatures(parsed.features, { ascending, useRankColumn: byRankColumn }) : [],
    [parsed, ascending, byRankColumn],
  );
  const shownN = clampTopN(topN, maxFeatures, DEFAULT_TOP_N);
  const top = useMemo(() => topFeatures(ranked, shownN, maxFeatures), [ranked, shownN, maxFeatures]);

  // ---- Colours ---------------------------------------------------------------
  // A group wears the dashboard's colour for it (`category_colors`, own or
  // inherited from the main tab), else the colorway's hue for its place in the
  // sorted universe: the same rule the filter chips follow, so a section has
  // one colour on the chips and on the boxes. The universe is every ranked
  // feature, not the drawn top N, so a group keeps its hue when the cut moves.
  const colourSource = useCategoryColorSource();
  const dashboardPalette = useCategoryPalette();
  const palette = useMemo(
    () => dashboardPalette ?? mantineCategoricalPalette(theme, isDark),
    [dashboardPalette, theme, isDark],
  );
  const groupUniverse = useMemo(
    () => groupsOf(ranked).filter((g): g is string => g !== null),
    [ranked],
  );
  const groupColours = useMemo(
    () => categoryColorMap(colourSource, config.group_col, groupUniverse, palette),
    [colourSource, config.group_col, groupUniverse, palette],
  );
  const themeColours = plotlyThemeColors(isDark, theme);
  const primary = theme.colors[theme.primaryColor]?.[isDark ? 4 : 6] ?? palette[0];
  const colourOf = useCallback(
    (group: string | null) => (group !== null ? groupColours.get(group) : undefined) ?? primary,
    [groupColours, primary],
  );

  // ---- Selection -------------------------------------------------------------
  // Marked from the filter list, so a pick made elsewhere on the same column
  // (a table of the same genes) shows here, and a clear from the chrome clears.
  const pickedValues = useMemo(() => valuesOnColumn(filters, selectionColumn), [filters, selectionColumn]);
  const selected = useMemo(() => selectedFeatureIds(top, pickedValues), [top, pickedValues]);

  const handleClick = useCallback(
    (event: any) => {
      if (!onFilterChange || !selectionColumn) return;
      const id = featureIdFromPoint(event?.points?.[0], orientation);
      if (!id) return;
      const value = selectionValueOf(top, id);
      if (!value) return;
      const own = selectionValuesFor(filters, metadata.index, 'scatter_selection') ?? [];
      const next = own.includes(value) ? own.filter((v) => v !== value) : [...own, value];
      onFilterChange(advancedVizSelectionFilter(metadata, selectionColumn, next));
    },
    [onFilterChange, selectionColumn, orientation, top, filters, metadata],
  );

  const scoreTitle = config.score_label || config.score_col;
  const valueTitle = `${config.value_label || 'Value'}${logValue ? ' (log10 of value + 1)' : ''}`;

  const figure = useMemo(() => {
    if (!shape || top.length === 0) return null;
    const fig = buildRankedFigure(top, {
      orientation,
      mark,
      shape,
      colourOf,
      stemColour: isDark ? theme.colors.dark[2] : theme.colors.gray[5],
      selectedOutline: themeColours.textColor,
      selected,
      scoreTitle,
      valueTitle,
      // A word for the legend, not a raw column name (`expression_section`
      // reads "Expression section").
      groupTitle: config.group_col
        ? config.group_col.charAt(0).toUpperCase() + config.group_col.slice(1).replace(/_/g, ' ')
        : null,
    });
    return {
      data: applyDataTheme(fig.data, isDark, theme),
      layout: applyLayoutTheme(fig.layout, isDark, theme),
    };
  }, [
    shape,
    top,
    orientation,
    mark,
    colourOf,
    isDark,
    theme,
    themeColours.textColor,
    selected,
    scoreTitle,
    valueTitle,
    config.group_col,
  ]);

  // A horizontal axis grows with the features (each needs a line for its
  // label); a vertical one shares the width, so its height is furniture.
  const contentDemand = useMemo(
    () =>
      orientation === 'horizontal'
        ? demandForItems(top.length, PX_PER_FEATURE, FIGURE_CHROME_PX)
        : top.length > 0
          ? demandForPx(VERTICAL_FIGURE_PX)
          : undefined,
    [orientation, top.length],
  );

  const echo = ranked.length
    ? rankingEcho({ shown: top.length, total: ranked.length, ascending, byRankColumn })
    : undefined;

  // Encoding tier: how many features, how each is drawn and which end of the
  // score comes first. Orientation and the log axis are the second tier.
  const violinAllowed = shape === 'long';
  const primaryControls = useMemo(
    () => (
      <>
        <VizNumberInput
          label="Top N"
          value={shownN}
          onChange={(v) => setTopN(clampTopN(Number(v), maxFeatures, DEFAULT_TOP_N))}
          min={1}
          max={maxFeatures}
        />
        <VizSegmented
          label="Draw"
          value={violinAllowed ? mark : 'box'}
          onChange={(v) => setMark(v === 'violin' ? 'violin' : 'box')}
          data={[
            { value: 'box', label: 'Box' },
            { value: 'violin', label: 'Violin', disabled: !violinAllowed },
          ]}
        />
        <VizSegmented
          label="First"
          value={ascending ? 'low' : 'high'}
          onChange={(v) => setAscending(v !== 'high')}
          disabled={byRankColumn}
          data={[
            { value: 'low', label: 'Lowest' },
            { value: 'high', label: 'Highest' },
          ]}
        />
      </>
    ),
    [shownN, maxFeatures, violinAllowed, mark, ascending, byRankColumn],
  );

  const controls = useMemo(
    () => (
      <VizControlGroup title="Layout">
        <VizSegmented
          label="Features"
          value={orientation}
          onChange={(v) => setOrientation(v === 'vertical' ? 'vertical' : 'horizontal')}
          data={[
            { value: 'horizontal', label: 'Rows' },
            { value: 'vertical', label: 'Columns' },
          ]}
        />
        <VizSwitch
          checked={logValue}
          onChange={(e) => setLogValue(e.currentTarget.checked)}
          label="Log value axis"
        />
      </VizControlGroup>
    ),
    [orientation, logValue],
  );

  let emptyMessage: string | undefined;
  if (rows && top.length === 0) {
    emptyMessage =
      parsed && parsed.dropped > 0
        ? 'No feature has both a score and a distribution'
        : 'No features';
  }

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Ranked distribution'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      contentDemand={contentDemand}
      echo={echo}
      loading={loading}
      error={error}
      estimated={estimated}
      emptyMessage={emptyMessage}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <Plot
          data={figure.data as any}
          layout={figure.layout as any}
          useResizeHandler
          style={PLOT_STYLE}
          config={PLOT_CONFIG as any}
          onClick={selectionEnabled ? handleClick : undefined}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default RankedDistributionRenderer;
