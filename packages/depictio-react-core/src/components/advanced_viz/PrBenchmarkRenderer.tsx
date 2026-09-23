import React, { useEffect, useMemo, useState } from 'react';
import {
  alpha,
  SegmentedControl,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import { fetchAdvancedVizData, InteractiveFilter, StoredMetadata } from '../../api';
import { resolveCategoricalPalette, stableColorMap } from '../../colors';
import AdvancedVizFrame from './AdvancedVizFrame';
import { applyDataTheme, applyLayoutTheme, plotlyAxisOverrides, plotlyThemeFragment } from './plotlyTheme';
import { groupIndices, largestGroup, sortCurveIndices, trapezoidArea } from './prCurves';
import { usePersistedVizControl } from './usePersistedVizControl';
import { COLORSCALE_NAMES, plotlyColorscale } from '../../utils/colorScale';

/** One benchmark, read at two zoom levels.
 *
 *  `pr` is where each callset ended up: one operating point per row, against
 *  F1 iso-contours. `roc` is the threshold sweep those points were picked off.
 *  `both` draws the sweep with the points on it, which is the reading the pair
 *  exists for. They come from one table and one fetch, so the switch only
 *  swaps the trace builder. */
const ALL_VIEWS = ['pr', 'roc', 'both'] as const;
type View = (typeof ALL_VIEWS)[number];

interface PrBenchmarkConfig {
  label_col: string;
  recall_col: string;
  precision_col: string;
  f1_col?: string | null;
  support_col?: string | null;
  category_col?: string | null;
  show_iso_f1?: boolean;
  show_diagonal?: boolean;
  show_labels?: boolean;
  colorscale?: string;
  /** Sweep-view bindings. All optional: a plain benchmark binds none. */
  fpr_col?: string | null;
  threshold_col?: string | null;
  group_col?: string | null;
  show_auc?: boolean;
  fill?: boolean;
  view?: View;
  views?: View[] | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: PrBenchmarkConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
}

// F1 iso-contour: for fixed F1 = c, precision = c*r / (2r - c), valid where 2r > c.
function isoF1Line(c: number): { x: number[]; y: number[] } {
  const x: number[] = [];
  const y: number[] = [];
  for (let r = c / 2 + 0.001; r <= 1.0001; r += 0.01) {
    const p = (c * r) / (2 * r - c);
    if (p >= 0 && p <= 1) {
      x.push(Math.min(r, 1));
      y.push(p);
    }
  }
  return { x, y };
}

const PrBenchmarkRenderer: React.FC<Props> = ({ metadata, filters, refreshTick }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const isDark = colorScheme === 'dark';
  const config = (metadata.config || {}) as PrBenchmarkConfig;

  const [view, setView] = usePersistedVizControl<View>(metadata, 'view', 'pr');
  const [showIso, setShowIso] = useState<boolean>(config.show_iso_f1 ?? true);
  const [showDiag, setShowDiag] = useState<boolean>(config.show_diagonal ?? true);
  const [showLabels, setShowLabels] = useState<boolean>(config.show_labels ?? true);
  const [colorscale, setColorscale] = useState<string>(config.colorscale ?? 'Tealgrn');
  const [sizeMode, setSizeMode] = useState<'support' | 'uniform'>(config.support_col ? 'support' : 'uniform');
  const [baseSize, setBaseSize] = useState<number>(14);
  const [labelFont, setLabelFont] = useState<number>(12);
  const [unitRange, setUnitRange] = useState<boolean>(true);
  const [showColorbar, setShowColorbar] = useState<boolean>(true);
  // Sweep views.
  const [showAuc, setShowAuc] = useState<boolean>(config.show_auc ?? true);
  const [fill, setFill] = useState<boolean>(config.fill ?? false);
  const [showMarkers, setShowMarkers] = useState<boolean>(true);
  const [showLegend, setShowLegend] = useState<boolean>(true);
  const [markerSize, setMarkerSize] = useState<number>(6);

  const hasFpr = Boolean(config.fpr_col);

  const requiredCols = useMemo(
    () =>
      [
        config.label_col,
        config.recall_col,
        config.precision_col,
        ...(config.f1_col ? [config.f1_col] : []),
        ...(config.support_col ? [config.support_col] : []),
        ...(config.category_col ? [config.category_col] : []),
        // Only fetched when bound, which is also the only way a sweep view can
        // be offered: an unoffered view never widens the fetch.
        ...(config.fpr_col ? [config.fpr_col] : []),
        ...(config.threshold_col ? [config.threshold_col] : []),
        ...(config.group_col ? [config.group_col] : []),
      ].filter(Boolean) as string[],
    [config],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 2) {
      setError('Precision-recall benchmark: missing data binding');
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
      vizKind: 'pr_benchmark',
      roles: {
        ...(config.label_col ? { label: config.label_col } : {}),
        recall: config.recall_col,
        precision: config.precision_col,
      },
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

  // Rows bucketed into the curves they belong to, which is also what decides
  // whether there is a sweep to draw at all.
  const curveGroups = useMemo(() => {
    const count = rows ? ((rows[config.recall_col] || []) as unknown[]).length : 0;
    const groupVals = config.group_col ? ((rows?.[config.group_col] || []) as unknown[]) : null;
    return groupIndices(groupVals, count);
  }, [rows, config.recall_col, config.group_col]);

  // A sweep needs a parameter to sweep along. A threshold or an FPR column is
  // one by declaration; a group column is one only once the data shows more
  // than a single point per group, since one point per callset is a plain
  // benchmark and joining those with a line would invent a curve.
  const sweepDrawable =
    Boolean(config.threshold_col || config.fpr_col) ||
    (Boolean(config.group_col) && largestGroup(curveGroups) > 1);

  const offeredViews = useMemo<View[]>(() => {
    const drawable = ALL_VIEWS.filter((v) => v === 'pr' || sweepDrawable);
    const requested = config.views;
    const offered = requested ? drawable.filter((v) => requested.includes(v)) : drawable;
    return offered.length > 0 ? offered : ['pr'];
  }, [sweepDrawable, config.views]);

  // Honoured only while it is on offer, and resolved here rather than through
  // the setter: a config pinned to a sweep view still has to render before the
  // rows that would make the sweep drawable have arrived.
  const activeView: View = offeredViews.includes(view) ? view : offeredViews[0];

  const figure = useMemo(() => {
    if (!rows) return null;
    const recall = (rows[config.recall_col] || []) as number[];
    const precision = (rows[config.precision_col] || []) as number[];
    const labels = config.label_col ? ((rows[config.label_col] || []) as (string | number)[]) : null;
    const f1 = config.f1_col ? ((rows[config.f1_col] || []) as number[]) : null;
    const support = config.support_col ? ((rows[config.support_col] || []) as number[]) : null;
    const category = config.category_col
      ? ((rows[config.category_col] || []) as (string | number)[])
      : null;
    const fpr = config.fpr_col ? ((rows[config.fpr_col] || []) as number[]) : null;
    const thr = config.threshold_col ? ((rows[config.threshold_col] || []) as number[]) : null;

    const drawCurves = activeView !== 'pr';
    const drawPoints = activeView !== 'roc';
    // A true ROC has axes of its own, so it can only be drawn on its own: the
    // `both` view stays in PR space, which is where the operating points live.
    const rocSpace = activeView === 'roc' && Boolean(fpr);

    // One colour per curve, shared with the operating points so a point and
    // the curve it sits on read as the same callset.
    const groupColours = stableColorMap(
      Array.from(curveGroups.keys()),
      resolveCategoricalPalette(theme),
    );
    const groupOf = config.group_col
      ? ((rows[config.group_col] || []) as (string | number)[])
      : null;

    const traces: any[] = [];

    // F1 iso-contours (drawn first, behind everything). They belong to the
    // operating points: a contour says which (precision, recall) pairs score
    // the same F1, which is a question about a point, not about a sweep.
    if (showIso && drawPoints) {
      for (const c of [0.2, 0.4, 0.6, 0.8]) {
        const { x, y } = isoF1Line(c);
        traces.push({
          type: 'scatter',
          mode: 'lines',
          x,
          y,
          line: { dash: 'dot', width: 1, color: 'rgba(140,140,140,0.5)' },
          hoverinfo: 'skip',
          showlegend: false,
          name: `F1=${c}`,
        });
        // Label the contour near its right end.
        if (x.length) {
          traces.push({
            type: 'scatter',
            mode: 'text',
            x: [x[x.length - 1]],
            y: [y[y.length - 1]],
            text: [`F1 ${c}`],
            textposition: 'top left',
            textfont: { size: 9, color: 'rgba(140,140,140,0.8)' },
            hoverinfo: 'skip',
            showlegend: false,
          });
        }
      }
    }

    if (drawCurves) {
      const lineMode = showMarkers ? 'lines+markers' : 'lines';
      const xCol = rocSpace ? (fpr as number[]) : recall;
      const yCol = rocSpace ? recall : precision;
      const xLabel = rocSpace ? 'FPR' : 'Recall';
      const yLabel = rocSpace ? 'TPR' : 'Precision';
      curveGroups.forEach((idx, key) => {
        const colour = groupColours.get(key);
        // A ROC sorts by its own x; every other curve follows the sweep.
        const sorted = rocSpace
          ? sortCurveIndices(idx, xCol, null)
          : sortCurveIndices(idx, xCol, thr);
        const xs = sorted.map((i) => xCol[i]);
        const ys = sorted.map((i) => yCol[i]);
        const area = showAuc ? trapezoidArea(xs, ys) : null;
        const name = (key || (rocSpace ? 'ROC' : 'curve')) +
          (area != null ? `  (AUC ${area.toFixed(3)})` : '');
        traces.push({
          type: 'scatter',
          mode: lineMode,
          x: xs,
          y: ys,
          name,
          line: { width: 2, color: colour },
          marker: { size: markerSize, color: colour },
          fill: fill ? 'tozeroy' : 'none',
          fillcolor: fill ? alpha(colour, 0.13) : undefined,
          opacity: 0.95,
          customdata: thr ? sorted.map((i) => thr[i]) : undefined,
          hovertemplate:
            `<b>${key || (rocSpace ? 'ROC' : 'curve')}</b>` +
            `<br>${xLabel}: %{x:.3f}<br>${yLabel}: %{y:.3f}` +
            (thr ? `<br>${config.threshold_col}: %{customdata}` : '') +
            `<extra></extra>`,
        });
      });
    }

    if (drawPoints) {
      // Point size from support (sqrt scale so area ~ count), else uniform.
      const sizes =
        support && sizeMode === 'support'
          ? (() => {
              const max = Math.max(...support.map((v) => v || 0), 1);
              return support.map((v) => baseSize * 0.6 + baseSize * 1.4 * Math.sqrt((v || 0) / max));
            })()
          : recall.map(() => baseSize);

      const customdata = recall.map((_, i) => [
        String(labels?.[i] ?? ''),
        f1 ? f1[i] ?? null : null,
        support ? support[i] ?? null : null,
      ]);

      // Colour: the curve's own colour when there are curves to sit on, so the
      // two layers agree; otherwise a discrete palette per category if bound,
      // else the continuous F1 scale.
      const palette = resolveCategoricalPalette(theme);
      let markerColorArr: (string | number)[] | string;
      let useColorscale = false;
      if (drawCurves && groupOf) {
        markerColorArr = groupOf.map((v) => groupColours.get(String(v ?? '')));
      } else if (category) {
        const swatches = stableColorMap(category.map((v) => String(v ?? '')), palette);
        markerColorArr = category.map((v) => swatches.get(String(v ?? '')));
      } else if (f1) {
        markerColorArr = f1;
        useColorscale = true;
      } else {
        markerColorArr = '#3b82c4';
      }
      traces.push({
        type: 'scatter',
        mode: showLabels && labels ? 'markers+text' : 'markers',
        x: recall,
        y: precision,
        text: labels ? labels.map((v) => String(v ?? '')) : undefined,
        textposition: 'top center',
        textfont: { size: labelFont, color: isDark ? '#e6e6e6' : '#222', family: 'Inter, sans-serif' },
        cliponaxis: false,
        customdata,
        showlegend: false,
        hovertemplate:
          `<b>%{customdata[0]}</b>` +
          `<br>${config.recall_col}: %{x:.3f}` +
          `<br>${config.precision_col}: %{y:.3f}` +
          (f1 ? `<br>F1: %{customdata[1]:.3f}` : '') +
          (support ? `<br>${config.support_col}: %{customdata[2]}` : '') +
          `<extra></extra>`,
        marker: {
          size: sizes,
          color: markerColorArr,
          ...(useColorscale
            ? {
                colorscale: plotlyColorscale(colorscale),
                cmin: 0,
                cmax: 1,
                showscale: showColorbar,
                colorbar: { title: { text: 'F1' }, thickness: 12, len: 0.8 },
              }
            : {}),
          opacity: 0.9,
          line: { width: 1, color: '#fff' },
        },
      });
    }

    // The chance diagonal is a ROC reference; y = x is the operating points'.
    // Only one of them can be true of the axes on screen, and a sweep drawn on
    // its own gets neither: y = x says nothing in PR space.
    const shapes = rocSpace
      ? [
          {
            type: 'line' as const,
            x0: 0,
            y0: 0,
            x1: 1,
            y1: 1,
            line: { dash: 'dot', width: 1, color: 'rgba(128,128,128,0.5)' },
          },
        ]
      : showDiag && drawPoints
        ? [
            {
              type: 'line' as const,
              x0: 0,
              y0: 0,
              x1: 1,
              y1: 1,
              line: { dash: 'dash', width: 1, color: 'rgba(128,128,128,0.5)' },
            },
          ]
        : [];

    return {
      data: traces,
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 55, r: 20, t: 20, b: 45 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: rocSpace ? 'False positive rate' : 'Recall' },
          // The points carry text labels, so their view leaves headroom the
          // curve-only view has no use for.
          range: drawPoints ? (unitRange ? [-0.02, 1.06] : undefined) : [0, 1.03],
          zeroline: false,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: rocSpace ? 'True positive rate' : 'Precision' },
          range: drawPoints ? (unitRange ? [0, 1.14] : undefined) : [0, 1.03],
          zeroline: false,
        },
        shapes,
        annotations: drawPoints
          ? [
              {
                xref: 'paper',
                yref: 'paper',
                x: 0.99,
                y: 0.99,
                xanchor: 'right',
                yanchor: 'top',
                text: 'best ↗',
                showarrow: false,
                font: { size: 12, color: 'rgba(110,110,110,0.95)' },
              },
            ]
          : [],
        // The curve names carry the AUC, so the legend is the sweep views' own.
        showlegend: drawCurves && showLegend,
        legend: {
          x: 0.98,
          y: 0.02,
          xanchor: 'right',
          yanchor: 'bottom',
          bgcolor: isDark ? 'rgba(30,30,30,0.6)' : 'rgba(255,255,255,0.65)',
          bordercolor: 'rgba(128,128,128,0.3)',
          borderwidth: 1,
        },
        autosize: true,
      },
    };
  }, [
    rows,
    config,
    activeView,
    curveGroups,
    showIso,
    showDiag,
    showLabels,
    colorscale,
    sizeMode,
    baseSize,
    labelFont,
    unitRange,
    showColorbar,
    showAuc,
    fill,
    showMarkers,
    showLegend,
    markerSize,
    isDark,
    theme,
  ]);

  const hasSupport = Boolean(config.support_col);
  const controls = useMemo(
    () => (
      <Stack gap="xs">
        {activeView !== 'roc' ? (
          <>
            <Switch size="xs" checked={showIso} onChange={(e) => setShowIso(e.currentTarget.checked)} label="F1 iso-contours" />
            <Switch size="xs" checked={showDiag} onChange={(e) => setShowDiag(e.currentTarget.checked)} label="y = x diagonal" />
            <Switch size="xs" checked={showLabels} onChange={(e) => setShowLabels(e.currentTarget.checked)} label="Point labels" />
            <Switch size="xs" checked={showColorbar} onChange={(e) => setShowColorbar(e.currentTarget.checked)} label="Colour bar" />
            <Switch size="xs" checked={unitRange} onChange={(e) => setUnitRange(e.currentTarget.checked)} label="Fixed 0–1 axes" />
            <Stack gap={4}>
              <Text size="xs" fw={500}>Base marker size</Text>
              <Slider size="xs" min={6} max={30} value={baseSize} onChange={setBaseSize} />
            </Stack>
            <Stack gap={4}>
              <Text size="xs" fw={500}>Label font</Text>
              <Slider size="xs" min={8} max={18} value={labelFont} onChange={setLabelFont} />
            </Stack>
          </>
        ) : null}
        {activeView !== 'pr' ? (
          <>
            <Switch size="xs" checked={showLegend} onChange={(e) => setShowLegend(e.currentTarget.checked)} label="Legend" />
            <Switch size="xs" checked={showMarkers} onChange={(e) => setShowMarkers(e.currentTarget.checked)} label="Curve markers" />
            {showMarkers ? (
              <Stack gap={4}>
                <Text size="xs" fw={500}>Curve marker size</Text>
                <Slider size="xs" min={2} max={14} value={markerSize} onChange={setMarkerSize} />
              </Stack>
            ) : null}
            <Switch size="xs" checked={fill} onChange={(e) => setFill(e.currentTarget.checked)} label="Shade area" />
            <Switch size="xs" checked={showAuc} onChange={(e) => setShowAuc(e.currentTarget.checked)} label="Show AUC" />
            {!hasFpr ? (
              <Text size="9px" c="dimmed">
                A true ROC needs a false-positive-rate column (true negatives). Without one the
                curve stays precision against recall, which is the variant-calling standard.
              </Text>
            ) : null}
          </>
        ) : null}
      </Stack>
    ),
    [
      activeView,
      showIso,
      showDiag,
      showLabels,
      showColorbar,
      unitRange,
      baseSize,
      labelFont,
      showLegend,
      showMarkers,
      markerSize,
      fill,
      showAuc,
      hasFpr,
    ],
  );

  const viewControl = useMemo(() => {
    const viewLabel = (v: View): string =>
      v === 'pr' ? 'Points' : v === 'roc' ? (hasFpr ? 'ROC' : 'Curve') : 'Both';
    return offeredViews.length > 1 ? (
      <SegmentedControl
        size="xs"
        value={activeView}
        onChange={(v) => setView(v as View)}
        data={offeredViews.map((v) => ({ value: v, label: viewLabel(v) }))}
      />
    ) : null;
  }, [offeredViews, activeView, setView, hasFpr]);

  // Encoding tier: which view, whether point size encodes support, and the
  // colour scale that maps the metric. Drawn as chips in the header, so every
  // control carries a fixed width and no description.
  const primaryControls = useMemo(
    () => (
      <>
        {viewControl}
        {activeView !== 'roc' ? (
          <>
            {hasSupport ? (
              <SegmentedControl
                size="xs"
                value={sizeMode}
                onChange={(v) => setSizeMode(v as 'support' | 'uniform')}
                data={[
                  { label: 'By support', value: 'support' },
                  { label: 'Uniform', value: 'uniform' },
                ]}
              />
            ) : null}
            <Select
              size="xs"
              w={150}
              label="Colour scale"
              value={colorscale}
              onChange={(v) => setColorscale(v || 'Tealgrn')}
              data={COLORSCALE_NAMES}
              comboboxProps={{ withinPortal: true }}
            />
          </>
        ) : null}
      </>
    ),
    [viewControl, activeView, hasSupport, sizeMode, colorscale],
  );

  return (
    <AdvancedVizFrame
      title={metadata.title || 'Precision-recall benchmark'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      primaryControls={primaryControls}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <Plot
          data={applyDataTheme(figure.data, isDark, theme) as any}
          layout={applyLayoutTheme(figure.layout as any, isDark, theme) as any}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
          config={{ displaylogo: false, responsive: true } as any}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default PrBenchmarkRenderer;
