import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Paper,
  Text,
  Stack,
  rgba,
  useMantineColorScheme,
  useMantineTheme,
} from '@mantine/core';
import Plot from 'react-plotly.js';

import { renderMap, InteractiveFilter, StoredMetadata } from '../api';
import {
  extractScatterSelection,
  filtersExcludingOwn,
  isMapSelectionEnabled,
  mapSelectionFilter,
  mapSelectionValues,
} from '../selection';
import RefetchOverlay from './RefetchOverlay';
import ComponentSkeleton from './ComponentSkeleton';
import { useReportLoadStatus } from './DashboardLoadingProvider';
import { collapseMapAttribution } from './map/collapseMapAttribution';

interface MapRendererProps {
  dashboardId: string;
  metadata: StoredMetadata;
  filters: InteractiveFilter[];
  /** Receives a filter entry with ``source="map_selection"`` whenever the
   *  user lassos / clicks points on the map. ``value: []`` clears. */
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Counter to force refetch on realtime updates even when filters are unchanged. */
  refreshTick?: number;
  /** Called with whether this map's figure has a legend or colour bar to show
   *  at all, so a host can offer the toggle only when it would do something. */
  onLegendPresence?: (present: boolean) => void;
  /** Overrides for hosts that supply their own chrome. The floating panel draws
   *  its own bordered card and header, so it asks for `bare` to avoid a card
   *  inside a card. */
  presentation?: {
    /** Render into a plain box instead of a bordered Paper, and skip the title.
     *  Also what moves the legend / colour bar onto the map: it marks the hosts
     *  that are short of width. */
    bare?: boolean;
    /** Show the figure's legend / colour bar. Defaults to true. It overlays the
     *  map either way — this is for hosts narrow enough that a long category
     *  list covers the tiles it is meant to explain. */
    showLegend?: boolean;
  };
}

/**
 * Renders a Plotly map component (px.scatter_map / density_map / choropleth_map).
 * Mirrors FigureRenderer: server returns a Plotly figure dict via
 * ``POST /dashboards/render_map/{id}/{component_id}``, React renders via
 * react-plotly.js. No Leaflet — Depictio's map module is Plotly-based.
 *
 * Selection wiring matches the scatter-figure path (lasso / click → emit a
 * filter with ``source="map_selection"``). Skipped for ``choropleth_map`` —
 * choropleth shapes are non-point geometries that Plotly's selection events
 * don't cover, mirroring Dash's behavior.
 */
const MapRenderer: React.FC<MapRendererProps> = ({
  dashboardId,
  metadata,
  filters,
  onFilterChange,
  refreshTick,
  onLegendPresence,
  presentation,
}) => {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const [figure, setFigure] = useState<{ data?: unknown[]; layout?: Record<string, unknown> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { colorScheme } = useMantineColorScheme();
  const mantineTheme = useMantineTheme();
  const theme: 'light' | 'dark' = colorScheme === 'dark' ? 'dark' : 'light';

  const selectionEnabled = isMapSelectionEnabled(metadata, !!onFilterChange);
  const selectionColumn =
    typeof metadata.selection_column === 'string'
      ? (metadata.selection_column as string)
      : undefined;
  const selectionColumnIndex =
    typeof metadata.selection_column_index === 'number'
      ? (metadata.selection_column_index as number)
      : 0;

  // Strip our own ``map_selection`` filter before fetching — see the matching
  // comment in FigureRenderer / TableRenderer.
  const filtersForFetch = useMemo(
    () => filtersExcludingOwn(filters, metadata.index, 'map_selection'),
    [filters, metadata.index],
  );

  // What this map currently has selected. Plotly tracks that internally while
  // the user is lassoing, but not across a remount — and a floating map
  // remounts on every tab switch while its selection keeps filtering the rest
  // of the dashboard. Reading it back from the filter list is what keeps the
  // highlight and the actual filtering in agreement.
  const selectedValues = useMemo(
    () => mapSelectionValues(filters, metadata.index),
    [filters, metadata.index],
  );
  const selectedKey = selectedValues.join('\u0000');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    renderMap(dashboardId, metadata.index, filtersForFetch, theme)
      .then((res) => {
        if (cancelled) return;
        // Keep the previous map mounted while the next response is in
        // flight; Plotly diffs props so swapping data/layout in place
        // avoids the full tile-layer teardown the old loader pattern caused.
        setFigure(res.figure);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message || String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, metadata.index, JSON.stringify(filtersForFetch), theme, refreshTick]);

  // Fold the basemap credit down to its ⓘ once the plot has a container to
  // look in. Deliberately an effect and not one of Plotly's `onInitialized` /
  // `onAfterPlot` callbacks: react-plotly.js only fires those once
  // `Plotly.react` resolves, and a map subplot resolves from
  // `resolveOnRender` — a `render` handler that waits for `map.loaded()`. If
  // the last frame maplibre draws happens while that is still false, no further
  // render comes and the promise stays pending for the life of the plot. That
  // was observed on a slow basemap, which is exactly when the credit is late
  // enough to matter. The helper waits for the control to appear on its own.
  useEffect(() => {
    if (!figure) return;
    collapseMapAttribution(plotRef.current);
  }, [figure]);

  const isInitialLoad = figure === null;
  const showInitialLoader = isInitialLoad && loading;
  const showRefetchOverlay = !isInitialLoad && loading;

  // Report load status to the dashboard registry (maps fetch on mount, no
  // viewport gate — so no deferred state).
  useReportLoadStatus(
    metadata.index,
    figure != null ? 'ready' : error ? 'error' : 'loading',
  );

  const emitSelection = (values: string[]) => {
    if (!onFilterChange) return;
    onFilterChange(mapSelectionFilter(metadata, values));
  };

  /** Lasso/box release and plain click both mean the same thing to a map: the
   *  points Plotly hands back are the new selection. */
  const handlePointSelection = (event: any) => {
    if (!selectionEnabled || !selectionColumn) return;
    emitSelection(extractScatterSelection(event, selectionColumnIndex));
  };

  const handleDeselect = () => {
    if (!selectionEnabled) return;
    emitSelection([]);
  };

  const bare = Boolean(presentation?.bare);
  const showLegend = presentation?.showLegend ?? true;

  // Does this figure have anything to legend? Plotly only draws a legend for
  // more than one named trace, and a colour bar only for a colour axis — read
  // off the raw figure, not the layout below, so the answer does not flip when
  // the viewer folds the legend away.
  const legendPresent = useMemo(() => {
    if (!figure) return false;
    if (figure.layout?.coloraxis) return true;
    const traces = (figure.data as any[]) || [];
    return traces.filter((t) => t?.showlegend !== false && t?.name).length > 1;
  }, [figure]);

  useEffect(() => {
    onLegendPresence?.(legendPresent);
  }, [legendPresent, onLegendPresence]);

  /** A plate to sit the legend on: it now floats over the basemap, and the
   *  tiles underneath are far too busy to read text off directly. */
  const overlayPlate = useMemo(() => {
    const surface = theme === 'dark' ? mantineTheme.colors.dark[7] : mantineTheme.white;
    const border = theme === 'dark' ? mantineTheme.colors.dark[4] : mantineTheme.colors.gray[3];
    return { bgcolor: rgba(surface, 0.85), bordercolor: rgba(border, 0.9) };
  }, [theme, mantineTheme]);

  const layout = useMemo<Record<string, unknown>>(() => {
    const base: Record<string, unknown> = {
      ...((figure?.layout as Record<string, unknown>) || {}),
      autosize: true,
      margin: {
        l: 0,
        r: 0,
        t: 30,
        b: 0,
        ...((figure?.layout?.margin as Record<string, unknown>) || {}),
        // A bare host already shows the title in its own header, so the figure
        // gives that strip back to the map instead of repeating it. This has to
        // land AFTER the server's margin: `render_map` reserves 30px whenever
        // the component has a title, which on a docked map was a fifth of the
        // height held open for a title Plotly is never asked to draw.
        ...(bare ? { t: 0 } : {}),
      },
    };
    if (bare) base.title = undefined;
    if (selectionEnabled && !base.dragmode) {
      // Respect a YAML-level ``selection_mode`` ('lasso' | 'select' | 'pan').
      // Default 'lasso' matches the Dash map component default.
      const mode =
        typeof metadata.selection_mode === 'string' ? metadata.selection_mode : 'lasso';
      base.dragmode = mode;
    }
    // Bump uirevision per refreshTick so realtime updates produce a unique
    // value and force Plotly to repaint. Filter changes don't increment
    // refreshTick, so user pan/zoom/bearing still survives those.
    base.uirevision = `tick-${refreshTick ?? 0}`;
    // Selection persistence rides on its own revision axis; left unset it
    // inherits `uirevision`, which deliberately does NOT change when a filter
    // reset empties the selection. Keying it on the selection itself makes
    // Plotly treat each incoming `selectedpoints` as the new starting point
    // rather than something to reconcile against a stashed GUI edit.
    base.selectionrevision = selectedKey || 'none';

    // Float the legend over the map instead of beside it — bare hosts only.
    //
    // Plotly's default vertical legend sits at x=1.02 — outside the plot area —
    // and `expandMargin` (components/legend/draw.js) turns that into a right
    // margin the map has to give up. On a dock only as wide as the filter panel
    // that ate most of the tiles. Anchoring the legend *inside* the paper takes
    // it off the margin calculation entirely: `doAutoMargin` only grows a
    // margin when a pushed edge would land outside the plot, which an inside
    // anchor never does unless the legend is wider than the whole map.
    // Top *left*, not right: Plotly parks its modebar in the top-right corner
    // of the plot area, and with a zero top margin the two land on top of each
    // other. Bottom-right belongs to the basemap credit.
    //
    // A grid tile is not short of width, so it keeps Plotly's own placement at
    // full size: the 10px plate is a trade the panel makes and a full-width map
    // has no reason to.
    if (bare) {
      const srcLegend = (figure?.layout?.legend as Record<string, unknown>) || {};
      base.legend = {
        ...srcLegend,
        x: 0,
        xanchor: 'left',
        y: 1,
        yanchor: 'top',
        bgcolor: overlayPlate.bgcolor,
        bordercolor: overlayPlate.bordercolor,
        borderwidth: 1,
        font: { size: 10, ...((srcLegend.font as Record<string, unknown>) || {}) },
        // Marker size follows the data by default, so a size-encoded map ends up
        // with legend swatches of wildly different sizes.
        itemsizing: 'constant',
      };
    }
    if (!showLegend) base.showlegend = false;

    // Same treatment for a continuous colour bar, which is what a density map
    // or a numeric `color_column` gets *instead of* a legend — the two never
    // appear together, so it can share the left edge. It goes left rather than
    // right for its own reason: tick labels are drawn on the bar's outer side,
    // and at the right edge they would fall off the paper and be clipped.
    // Plotly Express always routes map colour through `layout.coloraxis`, so
    // there is no per-trace colour bar to chase here.
    const coloraxis = figure?.layout?.coloraxis as Record<string, unknown> | undefined;
    if (coloraxis && (bare || !showLegend)) {
      const cb = (coloraxis.colorbar as Record<string, unknown>) || {};
      base.coloraxis = {
        ...coloraxis,
        ...(showLegend ? {} : { showscale: false }),
        ...(bare
          ? {
              colorbar: {
                ...cb,
                x: 0,
                xanchor: 'left',
                y: 0.5,
                yanchor: 'middle',
                len: 0.82,
                thickness: 10,
                outlinewidth: 0,
                bgcolor: overlayPlate.bgcolor,
                bordercolor: overlayPlate.bordercolor,
                borderwidth: 1,
                tickfont: { size: 9, ...((cb.tickfont as Record<string, unknown>) || {}) },
              },
            }
          : {}),
      };
    }
    return base;
  }, [
    figure,
    selectionEnabled,
    metadata.selection_mode,
    refreshTick,
    bare,
    selectedKey,
    showLegend,
    overlayPlate,
  ]);

  // Repaint the selection: dim every point the active filter excludes. Plotly
  // matches ``selectedpoints`` by position within each trace, and the server
  // puts the selectable value at ``selection_column_index`` of each point's
  // ``customdata`` — the same place ``extractScatterSelection`` reads it from
  // when the user draws the selection in the first place.
  //
  // Every trace is rebuilt into a FRESH object carrying an explicit
  // ``selectedpoints``, including when nothing is selected. That is not
  // defensive style, it is the fix for a real bug: react-plotly.js hands
  // ``props.data`` straight to ``Plotly.react`` without copying, and Plotly's
  // ``updateSelectedState`` writes the lasso result back onto ``trace._input``
  // — which *is* the object inside ``figure``, i.e. inside React state. So a
  // lassoed trace is permanently stamped with ``selectedpoints``, and handing
  // it back untouched after a reset re-asserts the selection the user just
  // cleared. ``null`` is Plotly's "no selection at all" value and turns the
  // selected/unselected styling off entirely.
  const data = useMemo<any[]>(() => {
    const traces = (figure?.data as any[]) || [];
    if (!selectionEnabled) return traces;
    const wanted = new Set(selectedValues);
    return traces.map((trace) => {
      const points =
        wanted.size === 0
          ? null
          : customdataMatches(trace?.customdata, selectionColumnIndex, wanted);
      if (!points) {
        const { unselected: _unselected, ...rest } = trace ?? {};
        return { ...rest, selectedpoints: null };
      }
      return {
        ...trace,
        selectedpoints: points,
        unselected: { marker: { opacity: UNSELECTED_OPACITY } },
      };
    });
    // `selectedKey` stands in for `selectedValues`, which is a fresh array on
    // every render; without it Plotly would be handed new trace objects each
    // time and redraw the map for nothing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [figure, selectionEnabled, selectionColumnIndex, selectedKey]);

  const Shell = bare ? Box : Paper;
  // `Box` takes no Paper props; keep the bordered card for the grid path only.
  const shellProps = bare ? {} : { p: 'sm' as const, withBorder: true, radius: 'md' as const };

  return (
    <Shell
      {...shellProps}
      style={{
        flex: 1,
        minHeight: 0,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {metadata.title && !bare && (
        <Text fw={600} size="sm" mb="xs">
          {metadata.title}
        </Text>
      )}
      {showInitialLoader && <ComponentSkeleton variant="block" />}
      {error && isInitialLoad && (
        <Stack style={{ flex: 1 }} justify="center" align="center">
          <Text size="sm" c="red" className="dashboard-error">Map failed: {error}</Text>
        </Stack>
      )}
      {figure && (
        <div ref={plotRef} style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <Plot
            data={data}
            layout={layout}
            revision={refreshTick ?? 0}
            config={{
              displaylogo: false,
              responsive: true,
              scrollZoom: true,
              // `'hover'` is Plotly's own default and the one that suits a map:
              // the toolbar sits *over* the tiles, so pinning it on costs a
              // corner of the map to buttons nobody is reaching for.
              displayModeBar: 'hover',
            }}
            style={{ width: '100%', height: '100%' }}
            useResizeHandler
            onSelected={selectionEnabled ? handlePointSelection : undefined}
            onClick={selectionEnabled ? handlePointSelection : undefined}
            onDeselect={selectionEnabled ? handleDeselect : undefined}
          />
          <RefetchOverlay visible={showRefetchOverlay} />
        </div>
      )}
    </Shell>
  );
};

/** Opacity applied to points outside the selection. Matches Plotly's own
 *  default dimming closely enough to read as "these are filtered out". */
const UNSELECTED_OPACITY = 0.2;

/**
 * Positions within a trace whose ``customdata`` value is in ``wanted``.
 *
 * Returns ``null`` for a trace that carries no per-point customdata (a density
 * layer, say). The caller turns that into ``selectedpoints: null`` — "this
 * trace has no selection" — rather than an empty array, which Plotly reads as
 * "nothing here is selected" and dims the whole layer. Those are also exactly
 * the traces that used to stay dimmed forever: Plotly stamps
 * ``selectedpoints`` onto every trace a lasso searched, customdata or not.
 */
function customdataMatches(
  customdata: unknown,
  columnIndex: number,
  wanted: Set<string>,
): number[] | null {
  if (!Array.isArray(customdata)) return null;
  const points: number[] = [];
  customdata.forEach((row, i) => {
    if (row == null || typeof row !== 'object') return;
    const raw = (row as Record<number, unknown>)[columnIndex];
    if (raw != null && wanted.has(String(raw))) points.push(i);
  });
  return points;
}

export default MapRenderer;
