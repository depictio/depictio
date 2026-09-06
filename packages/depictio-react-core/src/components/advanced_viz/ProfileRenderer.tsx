import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  NumberInput,
  Select,
  Slider,
  Stack,
  Switch,
  Text,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import {
  AdvancedVizKind,
  fetchAdvancedVizData,
  fetchUniqueValues,
  InteractiveFilter,
  StoredMetadata,
} from '../../api';
import { resolveCategoricalPalette, stableColorMap, TAB10_PALETTE } from '../../colors';
import {
  advancedVizSelectionColumn,
  advancedVizSelectionFilter,
  extractScatterSelection,
  filtersExcludingOwn,
} from '../../selection';
import AdvancedVizFrame from './AdvancedVizFrame';
import {
  applyDataTheme,
  applyLayoutTheme,
  plotlyAxisOverrides,
  plotlyThemeColors,
  plotlyThemeFragment,
} from './plotlyTheme';
import { usePersistedVizControl } from './usePersistedVizControl';

type LegendPos = 'right' | 'bottom' | 'none';

/** An x range to shade, as `[start, end, label]`. Mirrors the model's
 *  `list[tuple[float, float, str]]`, which arrives from Mongo as a plain
 *  array of arrays. */
type ShadedBand = [number, number, string];

/** Mirrors `ProfileConfig` in
 *  depictio/models/components/advanced_viz/configs.py. Every key read here has
 *  a field there — `test_advanced_viz_config_alignment` enforces it. */
interface ProfileConfig {
  series_col: string;
  x_col: string;
  y_col: string;
  lower_col?: string | null;
  upper_col?: string | null;
  reference_x?: number | null;
  reference_label?: string | null;
  shaded_bands?: ShadedBand[] | null;
  log_x?: boolean;
  log_y?: boolean;
  band_opacity?: number;
  line_width?: number;
  x_title?: string | null;
  y_title?: string | null;
  legend_pos?: LegendPos;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ProfileConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// Sent so the server applies this kind's reduction policy:
// `KIND_SAMPLING_POLICY` carries `profile: "none"`, because a uniform subset of
// a curve is a curve with holes.
const PROFILE_VIZ_KIND: AdvancedVizKind = 'profile';

const PLOT_STYLE = { width: '100%', height: '100%' };

// Two configs rather than one: a component that cannot emit a selection has no
// use for the box/lasso buttons, and a component that can must keep them.
// Scroll-zoom stays off in both — capturing the wheel breaks page scrolling
// when the pointer happens to sit over the tile.
const PLOT_CONFIG_PLAIN = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'],
  scrollZoom: false,
};
const PLOT_CONFIG_SELECT = {
  displaylogo: false,
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ['lasso2d', 'autoScale2d'],
  scrollZoom: false,
};

// Shaded x ranges are furniture, not data: they read as a tint behind the
// curves at a fixed weight rather than following `band_opacity`, which belongs
// to the confidence ribbon the user can actually tune away.
const SHADE_OPACITY = 0.1;

const PALETTE = TAB10_PALETTE;

/** `#rgb` / `#rrggbb` to `rgba(...)`. Returns the input untouched for any
 *  colour it does not recognise, so a themed `rgba(...)` passes through. */
function withAlpha(colour: string, alpha: number): string {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(colour.trim());
  if (!match) return colour;
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

/**
 * Pure presentation wrapper around `<Plot>`, memoised on the figure identity
 * so parent re-renders (filter churn, refresh ticks) don't rebuild the Plotly
 * figure and drop an in-flight zoom / select drag.
 */
const ProfilePlot = React.memo<{
  figure: { data?: unknown[]; layout?: Record<string, unknown> };
  isDark: boolean;
  theme: ReturnType<typeof useMantineTheme>;
  plotConfig: Record<string, unknown>;
  onSelected?: (event: any) => void;
  onClick?: (event: any) => void;
  onDeselect?: () => void;
}>(({ figure, isDark, theme, plotConfig, onSelected, onClick, onDeselect }) => {
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
      config={plotConfig as any}
      onSelected={onSelected}
      onClick={onClick}
      onDeselect={onDeselect}
    />
  );
});
ProfilePlot.displayName = 'ProfilePlot';

/**
 * One curve per series over an ordered numeric axis.
 *
 * Named for the shape rather than a domain: a TSS enrichment profile, a
 * fragment-length ladder, a Hill diversity curve with a bootstrap ribbon and a
 * rank-abundance curve are the same three columns with different axis labels,
 * so they share one renderer and differ only in their config.
 */
const ProfileRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const palette = resolveCategoricalPalette(theme, PALETTE);
  const config = (metadata.config || {}) as ProfileConfig;
  const isDark = colorScheme === 'dark';

  // Tier-2 controls. Defaults agree with ProfileConfig's own, so an
  // unconfigured component and a configured one draw the same curve.
  const [logX, setLogX] = usePersistedVizControl<boolean>(metadata, 'log_x', false);
  const [logY, setLogY] = usePersistedVizControl<boolean>(metadata, 'log_y', false);
  const [bandOpacity, setBandOpacity] = usePersistedVizControl<number>(metadata, 'band_opacity', 0.2);
  const [lineWidth, setLineWidth] = usePersistedVizControl<number>(metadata, 'line_width', 2);
  const [legendPos, setLegendPos] = usePersistedVizControl<LegendPos>(metadata, 'legend_pos', 'right');

  // ---- Selection as a cross-filter ---------------------------------------
  // The column resolves through selection.ts (named column, else the series
  // column), so the chrome's capability marker and this gate cannot disagree.
  // A host with no onFilterChange is read-only and advertises nothing.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const bandCols = useMemo(() => {
    const lower = config.lower_col || null;
    const upper = config.upper_col || null;
    return lower && upper ? { lower, upper } : null;
  }, [config.lower_col, config.upper_col]);

  const requiredCols = useMemo(() => {
    const cols = [config.series_col, config.x_col, config.y_col].filter(Boolean) as string[];
    if (bandCols) {
      if (!cols.includes(bandCols.lower)) cols.push(bandCols.lower);
      if (!cols.includes(bandCols.upper)) cols.push(bandCols.upper);
    }
    if (selectionColumn && !cols.includes(selectionColumn)) cols.push(selectionColumn);
    return cols;
  }, [config.series_col, config.x_col, config.y_col, bandCols, selectionColumn]);

  // This component must not narrow itself by its own selection: a box select
  // would otherwise redraw the profile as only the curves it caught and the
  // user could never widen it again. Every other component still narrows.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

  // What this component currently has selected, read back out of the filter
  // list — the only record of it, since the fetch above strips it.
  const selectedSeries = useMemo(() => {
    const out = new Set<string>();
    for (const f of filters) {
      if (f.index !== metadata.index || f.source !== 'scatter_selection') continue;
      if (Array.isArray(f.value)) for (const v of f.value) out.add(String(v));
    }
    return out;
  }, [filters, metadata.index]);

  // Full distinct set of series values so a curve keeps its colour when the
  // user filters down to a subset.
  const [seriesUniverse, setSeriesUniverse] = useState<string[] | null>(null);
  useEffect(() => {
    if (!metadata.dc_id || !config.series_col) {
      setSeriesUniverse(null);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(metadata.dc_id, config.series_col)
      .then((values) => {
        if (!cancelled) setSeriesUniverse(values);
      })
      .catch(() => {
        /* fall back to the filtered-set ordering if the endpoint errors */
      });
    return () => {
      cancelled = true;
    };
  }, [metadata.dc_id, config.series_col]);

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  // The server serves this kind whole because a sampled curve is a curve with
  // holes; past `advanced_viz_no_sample_max_rows` it samples anyway, and this
  // is where the frame says so.
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 3) {
      setError('Profile: missing data binding');
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
      vizKind: PROFILE_VIZ_KIND,
      roles: { series: config.series_col, x: config.x_col, y: config.y_col },
    })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setEstimated(Boolean(res.sampling?.degraded));
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
  ]);

  const figure = useMemo(() => {
    if (!rows) return null;

    const seriesVals = (rows[config.series_col] || []) as unknown[];
    const xs = (rows[config.x_col] || []) as unknown[];
    const ys = (rows[config.y_col] || []) as unknown[];
    const los = bandCols ? ((rows[bandCols.lower] || []) as unknown[]) : null;
    const his = bandCols ? ((rows[bandCols.upper] || []) as unknown[]) : null;
    const hasBand = Boolean(los && his && los.length && his.length);

    // A DC that carries a single curve need not spend a column saying so; the
    // y axis name is a better legend entry than an empty string.
    const fallbackName = config.y_title || config.y_col || 'series';

    const num = (v: unknown): number | null => {
      if (v === null || v === undefined) return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };

    type Point = { x: number; y: number; lo: number | null; hi: number | null };
    const bySeries = new Map<string, Point[]>();
    const n = Math.min(xs.length, ys.length);
    for (let i = 0; i < n; i++) {
      const x = num(xs[i]);
      const y = num(ys[i]);
      if (x === null || y === null) continue;
      const raw = seriesVals[i];
      const key = raw === null || raw === undefined ? fallbackName : String(raw);
      let pts = bySeries.get(key);
      if (!pts) {
        pts = [];
        bySeries.set(key, pts);
      }
      pts.push({
        x,
        y,
        lo: hasBand && los ? num(los[i]) : null,
        hi: hasBand && his ? num(his[i]) : null,
      });
    }

    const names = Array.from(bySeries.keys()).sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: 'base' }),
    );
    for (const name of names) {
      bySeries.get(name)!.sort((a, b) => a.x - b.x);
    }

    const colours = stableColorMap(seriesUniverse ?? names, palette, null);
    const dimming = selectedSeries.size > 0;

    const xLabel = config.x_title || config.x_col || 'x';
    const yLabel = config.y_title || config.y_col || 'y';

    // Bands go in first so no series' ribbon can cover another series' line.
    const bands: any[] = [];
    const lines: any[] = [];
    for (const name of names) {
      const pts = bySeries.get(name)!;
      const colour = colours.get(name);
      const lit = !dimming || selectedSeries.has(name);
      const px = pts.map((p) => p.x);

      if (hasBand) {
        const ribbon = pts.filter((p) => p.lo !== null && p.hi !== null);
        if (ribbon.length > 1) {
          const rx = ribbon.map((p) => p.x);
          // Upper edge first, then the lower edge filled back up to it —
          // Plotly's `tonexty` fills against the trace immediately before.
          bands.push({
            type: 'scatter' as const,
            mode: 'lines' as const,
            x: rx,
            y: ribbon.map((p) => p.hi as number),
            line: { width: 0, color: colour },
            hoverinfo: 'skip' as const,
            showlegend: false,
            legendgroup: name,
          });
          bands.push({
            type: 'scatter' as const,
            mode: 'lines' as const,
            x: rx,
            y: ribbon.map((p) => p.lo as number),
            line: { width: 0, color: colour },
            fill: 'tonexty' as const,
            fillcolor: withAlpha(colour, lit ? bandOpacity : bandOpacity * 0.25),
            hoverinfo: 'skip' as const,
            showlegend: false,
            legendgroup: name,
          });
        }
      }

      lines.push({
        type: 'scatter' as const,
        mode: 'lines' as const,
        x: px,
        y: pts.map((p) => p.y),
        name,
        legendgroup: name,
        // Slot 0 carries the series identity, which is the value
        // `extractScatterSelection` reads back out of a select / click event.
        customdata: pts.map(() => [name]),
        line: {
          color: lit ? colour : withAlpha(colour, 0.25),
          width: lineWidth,
          shape: 'linear' as const,
        },
        hovertemplate:
          `<b>${name}</b><br>${xLabel}: %{x}<br>${yLabel}: %{y:.4g}<extra></extra>`,
      });
    }

    const { textColor, gridColor, zeroLineColor } = plotlyThemeColors(isDark, theme);

    // Plotly places shapes and annotations in the axis' own coordinates, which
    // on a log axis are the log10 of the value. A non-positive x has no place
    // on a log axis at all, so those markers are dropped rather than clamped.
    const toAxisX = (v: number): number | null => {
      if (!logX) return v;
      return v > 0 ? Math.log10(v) : null;
    };

    const shapes: any[] = [];
    const annotations: any[] = [];

    for (const band of config.shaded_bands ?? []) {
      if (!Array.isArray(band) || band.length < 2) continue;
      const start = toAxisX(Number(band[0]));
      const end = toAxisX(Number(band[1]));
      if (start === null || end === null || !Number.isFinite(start) || !Number.isFinite(end)) {
        continue;
      }
      shapes.push({
        type: 'rect',
        xref: 'x',
        yref: 'paper',
        x0: Math.min(start, end),
        x1: Math.max(start, end),
        y0: 0,
        y1: 1,
        fillcolor: withAlpha(zeroLineColor, SHADE_OPACITY),
        opacity: 1,
        line: { width: 0 },
        layer: 'below',
      });
      const label = band.length > 2 ? String(band[2] ?? '') : '';
      if (label) {
        annotations.push({
          x: (Math.min(start, end) + Math.max(start, end)) / 2,
          y: 1,
          xref: 'x',
          yref: 'paper',
          text: label,
          showarrow: false,
          yanchor: 'bottom',
          font: { size: 10, color: textColor },
        });
      }
    }

    const refX = config.reference_x === null || config.reference_x === undefined
      ? null
      : toAxisX(Number(config.reference_x));
    if (refX !== null && Number.isFinite(refX)) {
      shapes.push({
        type: 'line',
        xref: 'x',
        yref: 'paper',
        x0: refX,
        x1: refX,
        y0: 0,
        y1: 1,
        line: { color: zeroLineColor, width: 1, dash: 'dot' },
        layer: 'below',
      });
      if (config.reference_label) {
        annotations.push({
          x: refX,
          y: 0,
          xref: 'x',
          yref: 'paper',
          text: config.reference_label,
          showarrow: false,
          yanchor: 'bottom',
          xanchor: 'left',
          font: { size: 10, color: textColor },
        });
      }
    }

    const legend =
      legendPos === 'bottom'
        ? { orientation: 'h', x: 0, y: -0.22, font: { size: 10, color: textColor }, bgcolor: 'rgba(0,0,0,0)' }
        : { orientation: 'v', x: 1.02, y: 1, font: { size: 10, color: textColor }, bgcolor: 'rgba(0,0,0,0)' };

    return {
      data: [...bands, ...lines],
      layout: {
        ...plotlyThemeFragment(isDark, theme),
        margin: { l: 60, r: 16, t: 24, b: legendPos === 'bottom' ? 68 : 48 },
        xaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: xLabel },
          type: logX ? 'log' : 'linear',
          zeroline: false,
          gridcolor: gridColor,
        },
        yaxis: {
          ...plotlyAxisOverrides(isDark, theme),
          title: { text: yLabel },
          type: logY ? 'log' : 'linear',
          zeroline: false,
          gridcolor: gridColor,
        },
        showlegend: legendPos !== 'none',
        legend,
        shapes,
        annotations,
        hovermode: 'closest',
        autosize: true,
        // Preserve the user's zoom / pan across re-renders. It must change
        // when the axis scale does, because a log flip is the one case where
        // the old range is meaningless and autorange should win.
        uirevision: `profile:${metadata.dc_id}:${logX ? 'logx' : 'linx'}:${logY ? 'logy' : 'liny'}`,
        dragmode: selectionEnabled ? 'select' : 'zoom',
      },
    };
  }, [
    rows,
    config,
    bandCols,
    isDark,
    theme,
    palette,
    seriesUniverse,
    selectedSeries,
    logX,
    logY,
    bandOpacity,
    lineWidth,
    legendPos,
    selectionEnabled,
    metadata.dc_id,
  ]);

  // Box select, click and deselect all land on the same
  // `(index, 'scatter_selection')` entry, so the last gesture replaces the
  // previous one and a deselect clears it.
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
  // A click on a curve is a one-curve selection, which is how the scatter
  // figures have always read a single point.
  const handleClick = useCallback(
    (event: any) => emitSelection(extractScatterSelection(event, 0)),
    [emitSelection],
  );
  const handleDeselect = useCallback(() => emitSelection([]), [emitSelection]);

  const controls = (
    <Stack gap="xs">
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Axes
        </Text>
        <Switch
          size="xs"
          checked={logX}
          onChange={(e) => setLogX(e.currentTarget.checked)}
          label="Log x"
        />
        <Switch
          size="xs"
          checked={logY}
          onChange={(e) => setLogY(e.currentTarget.checked)}
          label="Log y"
        />
      </Stack>
      <NumberInput
        size="xs"
        label="Line width"
        value={lineWidth}
        onChange={(v) => setLineWidth(Math.max(0.5, Number(v) || 2))}
        min={0.5}
        max={8}
        step={0.5}
        decimalScale={1}
      />
      {bandCols ? (
        <Stack gap={2}>
          <Text size="xs" fw={500}>
            Band opacity
          </Text>
          <Slider
            size="xs"
            value={bandOpacity}
            onChangeEnd={setBandOpacity}
            min={0}
            max={1}
            step={0.05}
            label={(v) => v.toFixed(2)}
          />
        </Stack>
      ) : null}
      <Select
        size="xs"
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
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Profile'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={rows && Object.values(rows)[0]?.length === 0 ? 'No data' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <ProfilePlot
          figure={figure}
          isDark={isDark}
          theme={theme}
          plotConfig={selectionEnabled ? PLOT_CONFIG_SELECT : PLOT_CONFIG_PLAIN}
          onSelected={selectionEnabled ? handleSelected : undefined}
          onClick={selectionEnabled ? handleClick : undefined}
          onDeselect={selectionEnabled ? handleDeselect : undefined}
        />
      ) : null}
    </AdvancedVizFrame>
  );
};

export default ProfileRenderer;
