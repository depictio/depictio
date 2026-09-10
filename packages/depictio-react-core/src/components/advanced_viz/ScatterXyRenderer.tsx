import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Group,
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
type ReferenceLine = 'none' | 'diagonal' | 'horizontal' | 'vertical';

/** Mirrors `ScatterXyConfig` in
 *  depictio/models/components/advanced_viz/configs.py. Every key read here has
 *  a field there — `test_advanced_viz_config_alignment` enforces it. */
interface ScatterXyConfig {
  x_col: string;
  y_col: string;
  label_col?: string | null;
  color_col?: string | null;
  size_col?: string | null;
  log_x?: boolean;
  log_y?: boolean;
  x_title?: string | null;
  y_title?: string | null;
  reference_line?: ReferenceLine;
  reference_value?: number | null;
  min_size?: number;
  max_size?: number;
  marker_size?: number;
  opacity?: number;
  marker_outline?: boolean;
  top_n_labels?: number;
  color_scale?: string;
  legend_pos?: LegendPos;
  selection_enabled?: boolean;
  selection_column?: string | null;
}

interface Props {
  metadata: StoredMetadata & { viz_kind?: string; config?: ScatterXyConfig };
  filters: InteractiveFilter[];
  refreshTick?: number;
  onFilterChange?: (filter: InteractiveFilter) => void;
}

// Sent so the server applies this kind's reduction policy: `KIND_SAMPLING_POLICY`
// carries `scatter_xy: "hash"`, because a uniform subset of a cloud is a
// lower-resolution cloud and no axis here has a distinguished tail to keep.
const SCATTER_XY_VIZ_KIND: AdvancedVizKind = 'scatter_xy';

const PLOT_STYLE = { width: '100%', height: '100%' };

// Two configs: a component that cannot emit a selection has no use for the
// box/lasso buttons. Scroll-zoom stays off in both, because capturing the wheel
// breaks page scrolling whenever the pointer crosses the tile.
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
  modeBarButtonsToRemove: ['autoScale2d'],
  scrollZoom: false,
};

// Only the scales that are actually present in the bundled plotly.js build.
// Plasma, Inferno, Magma and Spectral are named in other renderers and silently
// fall back to the default there; this list is deliberately the verified subset.
const COLOUR_SCALES = ['Viridis', 'Cividis', 'RdBu', 'Blackbody'] as const;

const PALETTE = TAB10_PALETTE;

/** Categorical until proven numeric: a colour column of run ids that happen to
 *  be integers should still get discrete swatches, so a value only counts as
 *  numeric when every non-null entry parses AND the column has more distinct
 *  values than a small palette would exhaust. */
function looksNumeric(values: unknown[]): boolean {
  let seen = 0;
  const distinct = new Set<string>();
  for (const v of values) {
    if (v === null || v === undefined || v === '') continue;
    if (!Number.isFinite(Number(v))) return false;
    seen += 1;
    if (distinct.size <= 12) distinct.add(String(v));
  }
  return seen > 0 && distinct.size > 12;
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const ScatterXyPlot = React.memo<{
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
ScatterXyPlot.displayName = 'ScatterXyPlot';

/**
 * Numeric against numeric: the plainest kind in the registry, and the one the
 * templates reach for most.
 *
 * Twenty-eight figures across ten nf-core templates draw a scatter in code
 * mode, and none of them does it for the shape. They do it for a marker size
 * column, a `custom_data` selection key, a reference diagonal or a log axis, so
 * those four are what this renderer exists to make declarable.
 */
const ScatterXyRenderer: React.FC<Props> = ({ metadata, filters, refreshTick, onFilterChange }) => {
  const { colorScheme } = useMantineColorScheme();
  const theme = useMantineTheme();
  const palette = resolveCategoricalPalette(theme, PALETTE);
  const config = (metadata.config || {}) as ScatterXyConfig;
  const isDark = colorScheme === 'dark';
  const themeColors = plotlyThemeColors(isDark, theme);

  // Tier-2 controls. Defaults agree with ScatterXyConfig's own, so an
  // unconfigured component and a configured one draw the same cloud.
  const [logX, setLogX] = usePersistedVizControl<boolean>(metadata, 'log_x', false);
  const [logY, setLogY] = usePersistedVizControl<boolean>(metadata, 'log_y', false);
  const [opacity, setOpacity] = usePersistedVizControl<number>(metadata, 'opacity', 0.8);
  const [maxSize, setMaxSize] = usePersistedVizControl<number>(metadata, 'max_size', 22);
  const [minSize, setMinSize] = usePersistedVizControl<number>(metadata, 'min_size', 4);
  const [markerSize, setMarkerSize] = usePersistedVizControl<number>(metadata, 'marker_size', 7);
  const [outline, setOutline] = usePersistedVizControl<boolean>(metadata, 'marker_outline', true);
  const [topN, setTopN] = usePersistedVizControl<number>(metadata, 'top_n_labels', 0);
  const [colourScale, setColourScale] = usePersistedVizControl<string>(
    metadata,
    'color_scale',
    'Viridis',
  );
  const [refLine, setRefLine] = usePersistedVizControl<ReferenceLine>(
    metadata,
    'reference_line',
    'none',
  );
  const [legendPos, setLegendPos] = usePersistedVizControl<LegendPos>(
    metadata,
    'legend_pos',
    'right',
  );

  // ---- Selection as a cross-filter ---------------------------------------
  // Resolved through selection.ts (named column, else the label column), so the
  // chrome's capability marker and this gate cannot disagree. A host with no
  // onFilterChange is read-only and advertises nothing.
  const selectionColumn = onFilterChange ? advancedVizSelectionColumn(metadata) : undefined;
  const selectionEnabled = Boolean(selectionColumn);

  const requiredCols = useMemo(() => {
    const cols = [config.x_col, config.y_col].filter(Boolean) as string[];
    for (const c of [config.label_col, config.color_col, config.size_col, selectionColumn]) {
      if (c && !cols.includes(c)) cols.push(c);
    }
    return cols;
  }, [config.x_col, config.y_col, config.label_col, config.color_col, config.size_col, selectionColumn]);

  // This component must not narrow itself by its own selection: a box select
  // would redraw the cloud as only the points it caught, and the user could
  // never widen it again. Every other component still narrows.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'scatter_selection'),
    [filters, metadata.index],
  );

  const [rows, setRows] = useState<Record<string, unknown[]> | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [estimated, setEstimated] = useState(false);

  useEffect(() => {
    if (!metadata.wf_id || !metadata.dc_id || requiredCols.length < 2) {
      setError('Scatter: missing data binding');
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
      vizKind: SCATTER_XY_VIZ_KIND,
      roles: { x: config.x_col, y: config.y_col },
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

  const points = useMemo(() => {
    if (!rows) return null;
    const xs = (rows[config.x_col] || []) as unknown[];
    const ys = (rows[config.y_col] || []) as unknown[];
    const labels = config.label_col ? ((rows[config.label_col] || []) as unknown[]) : null;
    const colours = config.color_col ? ((rows[config.color_col] || []) as unknown[]) : null;
    const sizes = config.size_col ? ((rows[config.size_col] || []) as unknown[]) : null;
    const keys = selectionColumn ? ((rows[selectionColumn] || []) as unknown[]) : null;

    const out: {
      x: number;
      y: number;
      label: string;
      colour: unknown;
      size: number | null;
      key: string;
    }[] = [];
    const n = Math.min(xs.length, ys.length);
    for (let i = 0; i < n; i++) {
      const x = num(xs[i]);
      const y = num(ys[i]);
      if (x === null || y === null) continue;
      const label = labels ? String(labels[i] ?? '') : '';
      out.push({
        x,
        y,
        label,
        colour: colours ? colours[i] : null,
        size: sizes ? num(sizes[i]) : null,
        key: keys ? String(keys[i] ?? '') : label,
      });
    }
    return out;
  }, [rows, config.x_col, config.y_col, config.label_col, config.color_col, config.size_col, selectionColumn]);

  const numericColour = useMemo(
    () => Boolean(config.color_col && points && looksNumeric(points.map((p) => p.colour))),
    [config.color_col, points],
  );

  const figure = useMemo(() => {
    if (!points) return null;
    if (points.length === 0) return null;

    const xTitle = config.x_title || config.x_col;
    const yTitle = config.y_title || config.y_col;

    // Plotly scales marker area, not diameter, so the tunable pair has to be
    // turned into one `sizeref`. Points at the smallest bound value keep
    // `minSize` via `sizemin`, which is what stops a long tail of invisible
    // dots when the size column spans orders of magnitude.
    const sizeVals = points.map((p) => p.size).filter((s): s is number => s !== null && s > 0);
    const sizeMax = sizeVals.length ? Math.max(...sizeVals) : 0;
    const sizeref = sizeMax > 0 ? (2 * sizeMax) / (maxSize * maxSize) : undefined;

    const markerCommon = {
      opacity,
      line: outline
        ? { width: 1, color: isDark ? 'rgba(0,0,0,0.55)' : 'rgba(70,70,70,0.55)' }
        : { width: 0 },
      ...(sizeref !== undefined
        ? { sizemode: 'area' as const, sizeref, sizemin: minSize }
        : {}),
    };

    const hover = (p: { label: string }) =>
      p.label ? `<b>${p.label}</b><br>` : '';
    const hoverTail = `${xTitle}: %{x}<br>${yTitle}: %{y}<extra></extra>`;

    const data: Record<string, unknown>[] = [];

    if (config.color_col && numericColour) {
      // One trace, colour as a continuous scale with a colorbar.
      data.push({
        type: 'scattergl' as const,
        mode: 'markers' as const,
        x: points.map((p) => p.x),
        y: points.map((p) => p.y),
        text: points.map((p) => p.label),
        customdata: points.map((p) => p.key),
        marker: {
          ...markerCommon,
          size: sizeref !== undefined ? points.map((p) => p.size ?? 0) : markerSize,
          color: points.map((p) => num(p.colour) ?? 0),
          colorscale: colourScale,
          showscale: true,
          colorbar: { thickness: 10, len: 0.75, title: { text: config.color_col, side: 'right' } },
        },
        hovertemplate: `%{text}<br>${config.color_col}: %{marker.color}<br>${hoverTail}`,
        showlegend: false,
        name: yTitle,
      });
    } else if (config.color_col) {
      // One trace per category, so the legend doubles as a category filter.
      const groups = new Map<string, typeof points>();
      for (const p of points) {
        const k = String(p.colour ?? '');
        const bucket = groups.get(k);
        if (bucket) bucket.push(p);
        else groups.set(k, [p]);
      }
      const names = Array.from(groups.keys()).sort();
      const colourMap = stableColorMap(names, palette);
      for (const name of names) {
        const group = groups.get(name) as typeof points;
        data.push({
          type: 'scattergl' as const,
          mode: 'markers' as const,
          name: name || '(blank)',
          x: group.map((p) => p.x),
          y: group.map((p) => p.y),
          text: group.map((p) => p.label),
          customdata: group.map((p) => p.key),
          marker: {
            ...markerCommon,
            color: colourMap.get(name),
            size: sizeref !== undefined ? group.map((p) => p.size ?? 0) : markerSize,
          },
          hovertemplate: `%{text}<br>${config.color_col}: ${name || '(blank)'}<br>${hoverTail}`,
        });
      }
    } else {
      data.push({
        type: 'scattergl' as const,
        mode: 'markers' as const,
        name: yTitle,
        x: points.map((p) => p.x),
        y: points.map((p) => p.y),
        text: points.map((p) => p.label),
        customdata: points.map((p) => p.key),
        marker: {
          ...markerCommon,
          color: palette[0],
          size: sizeref !== undefined ? points.map((p) => p.size ?? 0) : markerSize,
        },
        hovertemplate: `%{text}<br>${hoverTail}`,
        showlegend: false,
      });
    }

    // Labels for the most notable points. Ranked by the size column when one is
    // bound, because that is what the reader is being asked to look at;
    // otherwise by distance from the y origin, which is the volcano convention.
    const annotations: Record<string, unknown>[] = [];
    if (topN > 0 && config.label_col) {
      const ranked = [...points].sort((a, b) =>
        sizeMax > 0 ? (b.size ?? 0) - (a.size ?? 0) : Math.abs(b.y) - Math.abs(a.y),
      );
      for (const p of ranked.slice(0, topN)) {
        if (!p.label) continue;
        annotations.push({
          x: p.x,
          y: p.y,
          text: p.label,
          showarrow: false,
          yshift: 10,
          font: { size: 10 },
        });
      }
    }

    // Guide lines. The diagonal is drawn in paper-free data coordinates over
    // the shared range of both axes, so it stays the identity line under zoom.
    const shapes: Record<string, unknown>[] = [];
    const guide = { color: themeColors.zeroLineColor, width: 1, dash: 'dash' as const };
    if (refLine === 'diagonal') {
      const lo = Math.min(...points.map((p) => Math.min(p.x, p.y)));
      const hi = Math.max(...points.map((p) => Math.max(p.x, p.y)));
      shapes.push({ type: 'line', x0: lo, y0: lo, x1: hi, y1: hi, line: guide });
    } else if (refLine === 'horizontal' && config.reference_value !== null) {
      const v = config.reference_value ?? 0;
      shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: v, y1: v, line: guide });
    } else if (refLine === 'vertical' && config.reference_value !== null) {
      const v = config.reference_value ?? 0;
      shapes.push({ type: 'line', yref: 'paper', y0: 0, y1: 1, x0: v, x1: v, line: guide });
    }

    const layout: Record<string, unknown> = {
      ...plotlyThemeFragment(isDark, theme),
      margin: { l: 60, r: 16, t: 12, b: 52 },
      xaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        title: { text: xTitle, standoff: 8 },
        type: logX ? ('log' as const) : ('linear' as const),
        zeroline: false,
      },
      yaxis: {
        ...plotlyAxisOverrides(isDark, theme),
        title: { text: yTitle, standoff: 8 },
        type: logY ? ('log' as const) : ('linear' as const),
        zeroline: false,
      },
      shapes,
      annotations,
      showlegend: legendPos !== 'none' && data.length > 1,
      legend:
        legendPos === 'bottom'
          ? { orientation: 'h' as const, x: 0, y: -0.18, yanchor: 'top' as const }
          : { orientation: 'v' as const, x: 1.02, y: 1, font: { size: 10 } },
      hovermode: 'closest' as const,
      dragmode: selectionEnabled ? ('select' as const) : ('zoom' as const),
      autosize: true,
    };

    return { data, layout };
  }, [
    points,
    numericColour,
    config.x_col,
    config.y_col,
    config.label_col,
    config.color_col,
    config.x_title,
    config.y_title,
    config.reference_value,
    logX,
    logY,
    opacity,
    minSize,
    maxSize,
    markerSize,
    outline,
    topN,
    colourScale,
    refLine,
    legendPos,
    selectionEnabled,
    isDark,
    theme,
    palette,
    themeColors.zeroLineColor,
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
  const handleClick = useCallback(
    (event: any) => emitSelection(extractScatterSelection(event, 0)),
    [emitSelection],
  );
  const handleDeselect = useCallback(() => emitSelection([]), [emitSelection]);

  const counts = useMemo(
    () => (points ? { points: points.length } : undefined),
    [points],
  );

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
      <Select
        size="xs"
        label="Reference line"
        value={refLine}
        onChange={(v) => setRefLine((v as ReferenceLine) || 'none')}
        data={[
          { value: 'none', label: 'None' },
          { value: 'diagonal', label: 'Identity diagonal' },
          { value: 'horizontal', label: 'Horizontal at reference value' },
          { value: 'vertical', label: 'Vertical at reference value' },
        ]}
        allowDeselect={false}
        comboboxProps={{ withinPortal: true }}
      />
      {config.size_col ? (
        <Group gap="xs" grow>
          <NumberInput
            size="xs"
            label="Min size"
            value={minSize}
            onChange={(v) => setMinSize(Math.max(1, Number(v) || 4))}
            min={1}
            max={40}
          />
          <NumberInput
            size="xs"
            label="Max size"
            value={maxSize}
            onChange={(v) => setMaxSize(Math.max(2, Number(v) || 22))}
            min={2}
            max={80}
          />
        </Group>
      ) : (
        <NumberInput
          size="xs"
          label="Marker size"
          value={markerSize}
          onChange={(v) => setMarkerSize(Math.max(1, Number(v) || 7))}
          min={1}
          max={40}
        />
      )}
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Opacity
        </Text>
        <Slider
          size="xs"
          value={opacity}
          onChangeEnd={setOpacity}
          min={0.05}
          max={1}
          step={0.05}
          label={(v) => v.toFixed(2)}
        />
      </Stack>
      {config.color_col && numericColour ? (
        <Select
          size="xs"
          label="Colourscale"
          value={colourScale}
          onChange={(v) => v && setColourScale(v)}
          data={COLOUR_SCALES as unknown as string[]}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
      ) : null}
      {config.label_col ? (
        <NumberInput
          size="xs"
          label="Top-N labels"
          description={
            config.size_col ? 'Largest by the size column' : 'Furthest from zero on y'
          }
          value={topN}
          onChange={(v) => setTopN(Math.max(0, Number(v) || 0))}
          min={0}
          max={50}
        />
      ) : null}
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Markers
        </Text>
        <Switch
          size="xs"
          checked={outline}
          onChange={(e) => setOutline(e.currentTarget.checked)}
          label="Marker outline"
        />
      </Stack>
      <Stack gap={4}>
        <Text size="xs" fw={500}>
          Legend
        </Text>
        <Select
          size="xs"
          value={legendPos}
          onChange={(v) => setLegendPos((v as LegendPos) || 'right')}
          data={[
            { value: 'right', label: 'Right' },
            { value: 'bottom', label: 'Bottom' },
            { value: 'none', label: 'Hidden' },
          ]}
          allowDeselect={false}
          comboboxProps={{ withinPortal: true }}
        />
      </Stack>
    </Stack>
  );

  return (
    <AdvancedVizFrame
      estimated={estimated}
      title={metadata.title || 'Scatter'}
      subtitle={(metadata as any).description || (metadata as any).subtitle}
      counts={counts}
      controls={controls}
      loading={loading}
      error={error}
      emptyMessage={points && points.length === 0 ? 'No points' : undefined}
      dataRows={rows ?? undefined}
      dataColumns={requiredCols}
    >
      {figure ? (
        <ScatterXyPlot
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

export default ScatterXyRenderer;
