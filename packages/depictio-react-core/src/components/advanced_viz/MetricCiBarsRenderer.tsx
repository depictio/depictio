import React, { useEffect, useMemo, useState } from 'react';
import { useMantineColorScheme, useMantineTheme } from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import AdvancedVizFrame from './AdvancedVizFrame';
import { VizSelect, VizSlider, VizSwitch } from './controls/VizControls';
import { usePlotAnnotationLayer } from '../annotations/usePlotAnnotationLayer';
import { supportsAdvancedVizAnnotation } from '../../annotations/plotDecorate';
import { splitFigureByGroups } from './groupSplit';
import type { GroupRenderState } from '../../selectionGroups';
import { useReportGroupColouring } from '../../groupReach';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { COLORSCALE_NAMES, plotlyColorscale } from '../../utils/colorScale';
import { demandForItems } from './contentDemand';

/** Room one callset needs: the point estimate, its CI whisker, the value
 *  label that sits above the dot, and the gap to the next row. */
const CI_ROW_PX = 34;
/** The x axis and its title under the rows, plus the top margin. */
const CI_CHROME_PX = 90;

interface MetricCiBarsConfig {
  label_col: string;
  value_col: string;
  lower_col: string;
  upper_col: string;
  metric_name?: string;
  sort_desc?: boolean;
  colorscale?: string;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: MetricCiBarsConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  /** Dashboard-wide analysis grouping, applied to the finished figure. */
  groupRender?: GroupRenderState;
}

const MetricCiBarsRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, groupRender }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as MetricCiBarsConfig;
  const metricName = config.metric_name || 'Value';

  const [sortDesc, setSortDesc] = useState<boolean>(config.sort_desc ?? true);
  const [colorscale, setColorscale] = useState<string>(config.colorscale ?? 'Tealgrn');
  const [pointSize, setPointSize] = useState<number>(11);
  const [showLabels, setShowLabels] = useState<boolean>(true);

  const requiredCols = useMemo(
    () => [config.label_col, config.value_col, config.lower_col, config.upper_col].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 4) {
      setError('Metric CI bars: missing data binding');
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
      filters,
      vizKind: 'metric_ci_bars',
      roles: { label: config.label_col, value: config.value_col, lower: config.lower_col, upper: config.upper_col },
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
  }, [metadata.wf_id, metadata.dc_id, JSON.stringify(requiredCols), JSON.stringify(filters), refreshTick]);

  const figure = useMemo(() => {
    if (!rows) return null;
    const labels = (rows[config.label_col] || []).map((v) => String(v ?? ''));
    const value = (rows[config.value_col] || []) as number[];
    const lower = (rows[config.lower_col] || []) as number[];
    const upper = (rows[config.upper_col] || []) as number[];

    let order = labels.map((_, i) => i);
    order = order.sort((a, b) => (sortDesc ? value[b] - value[a] : value[a] - value[b]));
    // Horizontal bars read top→bottom; reverse so the best sits at the top.
    order.reverse();

    const y = order.map((i) => labels[i]);
    const x = order.map((i) => value[i] ?? 0);
    const arrayMinus = order.map((i) => (value[i] ?? 0) - (lower[i] ?? value[i] ?? 0));
    const arrayPlus = order.map((i) => (upper[i] ?? value[i] ?? 0) - (value[i] ?? 0));

    // Forest plot: a point estimate + horizontal CI line per callset. Bars are
    // useless when the metric is tiny (e.g. somatic recall ~0.02) — a dot on an
    // AUTO-SCALED x-axis zooms into the data, and the value label sits ABOVE the
    // dot so it never collides with the horizontal CI whisker.
    const lo = Math.min(...order.map((i) => lower[i] ?? value[i] ?? 0));
    const hi = Math.max(...order.map((i) => upper[i] ?? value[i] ?? 0));
    const pad = Math.max((hi - lo) * 0.15, 0.01);

    return {
      // Labels on the y axis, i.e. the rows the tile has to be tall enough
      // for. Feeds the content demand.
      rowsDrawn: y.length,
      data: [
        {
          type: 'scatter',
          mode: showLabels ? 'markers+text' : 'markers',
          x,
          y,
          marker: {
            size: pointSize,
            color: x,
            colorscale: plotlyColorscale(colorscale),
            cmin: lo,
            cmax: hi,
            line: { width: 1, color: '#fff' },
          },
          error_x: {
            type: 'data',
            symmetric: false,
            array: arrayPlus,
            arrayminus: arrayMinus,
            color: isDark ? 'rgba(200,200,200,0.8)' : 'rgba(70,70,70,0.85)',
            thickness: 1.6,
            width: 6,
          },
          text: x.map((v) => v.toFixed(3)),
          textposition: 'top center',
          textfont: { size: 11, color: isDark ? '#e6e6e6' : '#222' },
          cliponaxis: false,
          hovertemplate:
            `<b>%{y}</b><br>${metricName}: %{x:.3f}` +
            `<br>95% CI: [%{customdata[0]:.3f}, %{customdata[1]:.3f}]<extra></extra>`,
          // Slots 0 and 1 are the CI bounds the hover above quotes by index, so
          // the label goes on the END: renumbering them would silently rewrite
          // the hover. Slot 2 is the label — the callset for a benchmark, the
          // sample for a per-sample metric — which is what an analysis group is
          // matched against.
          customdata: order.map((i) => [lower[i] ?? null, upper[i] ?? null, labels[i]]),
        },
      ],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 90, r: 30, t: 24, b: 40 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: `${metricName} (95% CI)` },
          range: [Math.max(0, lo - pad), Math.min(1, hi + pad)],
        },
        yaxis: { ...plotlyAxisOverrides(isDark, theme), automargin: true },
        showlegend: false,
        autosize: true,
      },
    };
  }, [rows, config, sortDesc, metricName, colorscale, pointSize, showLabels, isDark, theme]);

  // Recolour by the dashboard's analysis groups, reading the label from slot 2.
  // The continuous colour ramp is the value itself, which the split replaces
  // with the group's colour — the same trade every other kind makes, and the
  // x position still carries the value.
  //
  // `facetable: false`: the y axis *is* the list of labels, so panels would
  // share it (the split links their ranges) and every panel would draw every
  // label with only its own group's rows filled in. "Split" is the dispatch's
  // job for this kind. The CI whiskers ride in `error_x`, a per-point array
  // that must be sliced alongside the points a panel keeps.
  const groupedFigure = useMemo(
    () =>
      figure
        ? splitFigureByGroups(figure, {
            groupRender,
            identitySlot: 2,
            facetable: false,
            showLegend: true,
          })
        : figure,
    [figure, groupRender],
  );
  // Whether any label matched, for the dispatch's "not grouped" badge.
  useReportGroupColouring(groupRender, figure, groupedFigure);

  // One row per callset on the y axis. Keyed on the count, so re-sorting or
  // recolouring the same callsets republishes nothing.
  const rowsDrawn = figure?.rowsDrawn ?? 0;
  const contentDemand = useMemo(
    () => demandForItems(rowsDrawn, CI_ROW_PX, CI_CHROME_PX),
    [rowsDrawn],
  );

  // Ranking the bars is what turns this into a comparison; the rest is paint.
  const primaryControls = useMemo(
    () => (
      <VizSwitch checked={sortDesc} onChange={(e) => setSortDesc(e.currentTarget.checked)} label="Sort by value" />
    ),
    [sortDesc],
  );

  const controls = useMemo(
    () => (
      <>
        <VizSwitch checked={showLabels} onChange={(e) => setShowLabels(e.currentTarget.checked)} label="Value labels" />
        <VizSelect
          label="Colour scale"
          value={colorscale}
          onChange={(v) => setColorscale(v || 'Tealgrn')}
          data={COLORSCALE_NAMES}
        />
        <VizSlider label="Point size" min={6} max={22} value={pointSize} onChange={setPointSize} />
      </>
    ),
    [showLabels, colorscale, pointSize],
  );

  // Themed once per figure so the annotation layer can memoise on them.
  const plotData = useMemo(
    () => (groupedFigure ? applyDataTheme(groupedFigure.data, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  const plotLayout = useMemo(
    () => (groupedFigure ? applyLayoutTheme(groupedFigure.layout as any, isDark, theme) : null),
    [groupedFigure, isDark, theme],
  );
  // Chart annotations. Slot 2 of `customdata` is the label, which is what
  // marked points are keyed on.
  const annotations = usePlotAnnotationLayer({
    componentIndex: String(metadata.index),
    enabled: supportsAdvancedVizAnnotation(metadata),
    data: plotData,
    layout: plotLayout,
    pointIdIndex: 2,
    pointIdColumn: config.label_col || undefined,
  });

  return (
    <AdvancedVizFrame
      title={metadata.title || `${metricName} with 95% CI`}
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
    >
      {groupedFigure ? (
        <>
          <Plot
            data={annotations.data as any}
            layout={annotations.layout as any}
            useResizeHandler
            style={{ width: '100%', height: '100%' }}
            config={{ displaylogo: false, responsive: true } as any}
            {...annotations.plotProps()}
          />
          {annotations.toolbar}
        </>
      ) : null}
    </AdvancedVizFrame>
  );
};

export default MetricCiBarsRenderer;
