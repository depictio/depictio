import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Box,
  Button,
  NumberInput,
  Paper,
  Select,
  Slider,
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
// The same settings popover every advanced_viz renderer uses, imported from the
// leaf module rather than through AdvancedVizDispatch. That distinction is the
// whole chunking story: `AdvancedVizExtras` imports no renderer, so a map picks
// up the popover without dragging the ~17 plotly-heavy advanced_viz renderers
// onto its chunk. The import lives HERE and not in ComponentRenderer on
// purpose, because ComponentRenderer is eager and the map branch must not put
// any of this on the dashboard's boot path.
import { AdvancedVizSettingsPopover } from './advanced_viz/AdvancedVizExtras';

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
  /** Receives the display-settings popover, for a host that has an action row
   *  to hang it in. Same shape as TableRenderer's `onLoadAllState`: the
   *  settings belong to the figure they restyle, so they are built here and
   *  the host only has to find them a slot. Null while the figure is still in
   *  flight, and on the map types none of the controls would reach. */
  onSettingsNode?: (node: React.ReactNode) => void;
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
  onSettingsNode,
  presentation,
}) => {
  const plotRef = useRef<HTMLDivElement | null>(null);
  const [figure, setFigure] = useState<{ data?: unknown[]; layout?: Record<string, unknown> } | null>(null);
  const [fitSpec, setFitSpec] = useState<MapFitSpec | null>(null);
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
        setFitSpec(parseMapFit(res.metadata));
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

  // ---------------------------------------------------------------------
  // Re-fitting the viewport to the box we actually got.
  //
  // `render_map` frames the data against a guessed 600x400 viewport, because
  // the server has no idea who is rendering. A grid tile is close enough to
  // that; the docked panel is neither as wide nor anywhere near as tall, so
  // the server's zoom comes back about a level too tight and the outer points
  // fall off the edges. So the server also ships the bounding box it fitted
  // (`metadata.fit`) and we redo the same arithmetic against the measured
  // container. It is the box and not the figure's own traces because a
  // choropleth's geometry is server-side GeoJSON that never reaches us.
  const [boxSize, setBoxSize] = useState<{ width: number; height: number } | null>(null);
  const [appliedFit, setAppliedFit] = useState<AppliedFit | null>(null);
  // True once the viewer has panned or zoomed by hand, which is what stops a
  // resize or a filter change from dragging the map back out from under them.
  // Deliberately never cleared while the plot stays mounted: that is already
  // how the rest of the viewport behaves, because Plotly stores a direct GUI
  // edit and `map.uirevision` holds it against every later figure.
  const userMovedRef = useRef(false);
  const appliedFitRef = useRef<AppliedFit | null>(null);
  const fitRevRef = useRef(0);

  useEffect(() => {
    const el = plotRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      // Rounded, and only stored when it actually changed: a sub-pixel
      // reflow must not turn into a state update, let alone one that resizes
      // the plot again.
      const width = Math.round(rect.width);
      const height = Math.round(rect.height);
      if (width < 1 || height < 1) return;
      setBoxSize((prev) =>
        prev && prev.width === width && prev.height === height ? prev : { width, height },
      );
    });
    ro.observe(el);
    return () => ro.disconnect();
    // The observed div only exists once there is a figure to draw, so the
    // observer has to be (re)attached when that flips.
  }, [isInitialLoad]);

  useEffect(() => {
    if (userMovedRef.current || !fitSpec || !boxSize) return;
    // Plotly's margins come off the container before the map subplot gets what
    // is left, so the fit has to be against the drawing area rather than the
    // div. On a titled grid tile that is a 30px strip, which on a short panel
    // would be a real slice of the height.
    const margin = (figure?.layout?.margin as Record<string, unknown>) || {};
    const width = boxSize.width - numberOr(margin.l, 0) - numberOr(margin.r, 0);
    const height =
      boxSize.height - (bare ? 0 : numberOr(margin.t, 30)) - numberOr(margin.b, 0);
    if (width < 1 || height < 1) return;
    const next = computeMapFit(fitSpec, width, height);
    // The last fit is mirrored in a ref rather than read out of state, so the
    // comparison happens once here instead of inside a state updater React is
    // free to call more than once.
    if (appliedFitRef.current && sameFit(appliedFitRef.current, next)) return;
    fitRevRef.current += 1;
    const applied: AppliedFit = { ...next, revision: `fit-${fitRevRef.current}` };
    appliedFitRef.current = applied;
    setAppliedFit(applied);
  }, [fitSpec, boxSize, figure, bare]);

  /** Plotly reports every user pan / zoom / rotate through relayout, keyed
   *  under the map subplot. Our own re-fits go through props and reach the map
   *  as a `Plotly.react`, which emits `plotly_react` and never this, so
   *  anything arriving here is the viewer's own doing. */
  const handleRelayout = useCallback((event: unknown) => {
    if (!event || typeof event !== 'object') return;
    const moved = Object.keys(event).some((key) => /^map(box)?[._]/.test(key));
    if (moved) userMovedRef.current = true;
  }, []);

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

  // ---------------------------------------------------------------------
  // On-the-fly display settings.
  //
  // Deliberately cosmetic and deliberately client-side: every one of these
  // restyles the figure the server has ALREADY returned, so none of them
  // refetches. That is what makes them instant, and it is also their limit.
  // Anything that would change which rows are drawn belongs in the component's
  // authored config, not here.
  //
  // `null` means "whatever the server drew". The controls display the figure's
  // own value until one is touched, so a control can never claim a value the
  // map is not showing. That matters for the basemap in particular: the server
  // swaps `map_style` by colour scheme (carto-positron ⇄ carto-darkmatter), so
  // the authored value is not reliably what is on screen.
  const [sizeOverride, setSizeOverride] = useState<number | null>(null);
  const [opacityOverride, setOpacityOverride] = useState<number | null>(null);
  const [styleOverride, setStyleOverride] = useState<string | null>(null);

  /** What the server actually drew, read back off the figure. */
  const shown = useMemo(() => {
    const traces = (figure?.data as any[]) || [];
    const typeOf = (t: any) => String(t?.type || '');
    // `startsWith` rather than equality so the legacy `*mapbox` trace names are
    // covered too; both carry the same marker / radius properties.
    const point = traces.find((t) => typeOf(t).startsWith('scattermap'));
    const density = traces.find((t) => typeOf(t).startsWith('densitymap'));
    const region = traces.find((t) => typeOf(t).startsWith('choroplethmap'));
    const rawSize = point?.marker?.size;
    const mapLayout =
      ((figure?.layout?.map || figure?.layout?.mapbox) as Record<string, unknown>) || {};
    return {
      hasPoints: Boolean(point),
      hasDensity: Boolean(density),
      // True when marker size encodes a column: sizes are then per-point and
      // the scale is carried by `sizeref`, so writing a scalar would erase the
      // encoding. The size control rescales `sizeref` in that case.
      sizeEncoded: Array.isArray(rawSize),
      sizeref: numberOr(point?.marker?.sizeref, null),
      // With no size column the server writes `size_max` straight onto
      // `marker.size` (see _render_scatter_map), so a scalar here IS the
      // authored maximum. With one, `size_max` only reaches the figure through
      // `sizeref` and has to come from the metadata.
      size: numberOr(rawSize, numberOr(metadata.size_max, DEFAULT_SIZE_MAX)),
      radius: numberOr(density?.radius, DEFAULT_DENSITY_RADIUS),
      opacity: numberOr(
        point?.marker?.opacity ?? region?.marker?.opacity ?? density?.opacity,
        1,
      ),
      style: typeof mapLayout.style === 'string' ? (mapLayout.style as string) : null,
    };
  }, [figure, metadata.size_max]);

  /** Restyle one trace, returning it UNTOUCHED when nothing is overridden. The
   *  identity matters: a fresh object makes Plotly redraw the whole layer, the
   *  same reason `selectedKey` stands in for `selectedValues` below. */
  const applyDisplay = useCallback(
    (trace: any) => {
      const type = String(trace?.type || '');
      if (type.startsWith('densitymap')) {
        if (sizeOverride == null && opacityOverride == null) return trace;
        return {
          ...trace,
          // A density layer has no markers; its `radius` is the equivalent
          // knob, which is why the control relabels itself for one.
          ...(sizeOverride != null ? { radius: sizeOverride } : {}),
          ...(opacityOverride != null ? { opacity: opacityOverride } : {}),
        };
      }
      const isPoint = type.startsWith('scattermap');
      if (!isPoint && !type.startsWith('choroplethmap')) return trace;
      const marker: Record<string, unknown> = {};
      if (opacityOverride != null) marker.opacity = opacityOverride;
      if (isPoint && sizeOverride != null) {
        if (!shown.sizeEncoded) {
          marker.size = sizeOverride;
        } else if (shown.sizeref != null) {
          // Plotly Express derives `sizeref` as max(value) / size_max², so a
          // new maximum is a pure rescale of what the server computed and
          // needs no knowledge of the data range. The per-point sizes stay as
          // they are, which is what keeps the encoding intact.
          marker.sizeref = shown.sizeref * (shown.size / sizeOverride) ** 2;
        }
      }
      if (Object.keys(marker).length === 0) return trace;
      return { ...trace, marker: { ...(trace?.marker || {}), ...marker } };
    },
    [sizeOverride, opacityOverride, shown],
  );

  const settingsControls = useMemo<React.ReactNode>(() => {
    // Nothing to restyle before the first figure lands, and a choropleth has
    // neither points nor a density layer to size.
    if (!figure) return null;
    const canSize = shown.hasPoints || shown.hasDensity;
    const touched = sizeOverride != null || opacityOverride != null || styleOverride != null;
    return (
      <Stack gap="xs">
        <Select
          size="xs"
          label="Basemap"
          value={styleOverride ?? shown.style}
          onChange={(v) => v && setStyleOverride(v)}
          data={MAP_STYLE_OPTIONS}
          allowDeselect={false}
        />
        {canSize && (
          <NumberInput
            size="xs"
            label={shown.hasPoints ? 'Point size' : 'Radius'}
            description={shown.sizeEncoded ? 'Largest marker; the encoding is kept' : undefined}
            value={sizeOverride ?? (shown.hasPoints ? shown.size : shown.radius)}
            onChange={(v) => setSizeOverride(Math.max(1, Number(v) || 1))}
            min={1}
            max={60}
          />
        )}
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Opacity
          </Text>
          <Slider
            size="xs"
            min={0.1}
            max={1}
            step={0.1}
            value={opacityOverride ?? shown.opacity}
            onChange={setOpacityOverride}
            marks={OPACITY_MARKS}
            mb="xs"
          />
        </Stack>
        <Button
          size="compact-xs"
          variant="subtle"
          color="gray"
          disabled={!touched}
          onClick={() => {
            setSizeOverride(null);
            setOpacityOverride(null);
            setStyleOverride(null);
          }}
        >
          Reset
        </Button>
        <Text size="xs" c="dimmed">
          Display only. Not saved with the dashboard.
        </Text>
      </Stack>
    );
  }, [figure, shown, sizeOverride, opacityOverride, styleOverride]);

  // Keyed because the host flattens `extraActions` through
  // `React.Children.toArray`, which keys an unkeyed child by position: the
  // settings action appears only once the figure lands, and the actions in
  // front of it come and go with the selection, so a positional key would
  // remount the popover (closing it) whenever either happened.
  const settingsNode = useMemo<React.ReactNode>(
    () =>
      settingsControls ? (
        <AdvancedVizSettingsPopover key="map-settings" controls={settingsControls} />
      ) : null,
    [settingsControls],
  );

  // Two effects rather than one with a cleanup: a cleanup keyed on the node
  // would publish null between every control change, and the host re-rendering
  // without the popover would close it mid-adjustment.
  useEffect(() => {
    onSettingsNode?.(settingsNode);
  }, [onSettingsNode, settingsNode]);
  useEffect(() => () => onSettingsNode?.(null), [onSettingsNode]);

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

    // Everything that lives on the map subplot itself. `render_map` builds
    // with the MapLibre constructors (px.scatter_map / density_map /
    // choropleth_map), so the style lives at `layout.map.style`; the legacy
    // `layout.mapbox` key is only honoured for figures that already carry one.
    // Spread over the server's own subplot object so whatever we do not touch
    // — `center`, `zoom`, its `uirevision` — survives, which is what keeps the
    // viewer's pan and zoom across a style change.
    const subplotKey = figure?.layout?.mapbox ? 'mapbox' : 'map';
    const subplot: Record<string, unknown> = {};
    if (styleOverride) subplot.style = styleOverride;
    if (appliedFit) {
      subplot.center = appliedFit.center;
      subplot.zoom = appliedFit.zoom;
      // The subplot carries its OWN `uirevision` (the server pins it to
      // "preserve") and does not inherit the one above, so without moving it
      // Plotly would treat the fit as a value to reconcile against a stashed
      // GUI edit and drop it on an already-mounted map. It changes only when
      // the fit itself does, so a refetch that lands on the same framing still
      // leaves the viewer's own pan and zoom alone.
      subplot.uirevision = appliedFit.revision;
    }
    if (Object.keys(subplot).length > 0) {
      base[subplotKey] = { ...((base[subplotKey] as Record<string, unknown>) || {}), ...subplot };
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
    styleOverride,
    appliedFit,
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
    // Cosmetics first, selection second: the selection branch rebuilds traces
    // anyway, and running the restyle over the raw list keeps each concern
    // reading a plain trace rather than the other one's output.
    const traces = ((figure?.data as any[]) || []).map(applyDisplay);
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
  }, [figure, selectionEnabled, selectionColumnIndex, selectedKey, applyDisplay]);

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
            onRelayout={handleRelayout}
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

/** Basemaps offered on the fly: the same three the map builder offers
 *  (MAP_STYLES in depictio/models/components/constants.py). Deliberately not a
 *  wider list: a viewer should not be able to reach a style the author could
 *  not have chosen, and the rest of Plotly's MapLibre styles need a MapTiler
 *  token this deployment does not carry. */
const MAP_STYLE_OPTIONS = [
  { value: 'open-street-map', label: 'OpenStreetMap' },
  { value: 'carto-positron', label: 'Carto Light' },
  { value: 'carto-darkmatter', label: 'Carto Dark' },
];

/** Same marks the map builder puts on its opacity slider. */
const OPACITY_MARKS = [
  { value: 0.2, label: '0.2' },
  { value: 0.5, label: '0.5' },
  { value: 0.8, label: '0.8' },
  { value: 1.0, label: '1.0' },
];

/** `size_max` default in depictio/api/v1/services/map/render.py. */
const DEFAULT_SIZE_MAX = 15;
/** Plotly Express' own density radius, used when the component authors none. */
const DEFAULT_DENSITY_RADIUS = 30;

/** Narrow an untyped figure / metadata field to a finite number. */
function numberOr<T>(value: unknown, fallback: T): number | T {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

/** MapLibre's world is one 512px tile at zoom 0. */
const WORLD_TILE_PX = 512;

/**
 * What the server framed, as forwarded in `metadata.fit`: the bounding box of
 * everything it plotted plus the constants it fitted with. The constants ride
 * along on purpose, so the two ends of this cannot drift apart when one of
 * them is tuned — see `_fit_payload` in
 * depictio/api/v1/services/map/render.py.
 */
interface MapFitSpec {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
  padding: number;
  maxZoom: number;
  singlePointZoom: number;
}

/** A fit we have handed Plotly, and the revision that made it stick. */
interface AppliedFit {
  center: { lat: number; lon: number };
  zoom: number;
  revision: string;
}

function parseMapFit(metadata: unknown): MapFitSpec | null {
  const fit = (metadata as { fit?: unknown } | undefined)?.fit;
  if (!fit || typeof fit !== 'object') return null;
  const raw = fit as Record<string, unknown>;
  const num = (key: string): number | null => {
    const value = raw[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  };
  const minLat = num('min_lat');
  const maxLat = num('max_lat');
  const minLon = num('min_lon');
  const maxLon = num('max_lon');
  if (minLat == null || maxLat == null || minLon == null || maxLon == null) return null;
  return {
    minLat,
    maxLat,
    minLon,
    maxLon,
    padding: num('padding') ?? 0.5,
    maxZoom: num('max_zoom') ?? 12,
    singlePointZoom: num('single_point_zoom') ?? 9,
  };
}

/** Web-Mercator ordinate of a latitude, halved and clamped to the projection's
 *  usable range. Same function as `_lat_rad` server-side and `latRad` in
 *  CoordinatesMapPreview. */
function mercatorY(lat: number): number {
  const sin = Math.sin((lat * Math.PI) / 180);
  const y = Math.log((1 + sin) / (1 - sin)) / 2;
  return Math.max(Math.min(y, Math.PI), -Math.PI) / 2;
}

/** Inverse of `mercatorY`. */
function latFromMercatorY(y: number): number {
  return (Math.asin(Math.tanh(y * 2)) * 180) / Math.PI;
}

/**
 * Center and zoom that frame `spec` inside a `widthPx` x `heightPx` drawing
 * area. The same fit the server does, run again against the box we measured
 * rather than the 600x400 it has to assume.
 *
 * The center is the middle of the *projected* latitude span: Mercator stretches
 * towards the poles, so the mean of two latitudes is not the latitude halfway
 * down the viewport, and the gap grows as the box gets shorter.
 *
 * The zoom keeps its fraction where the server floors it. Flooring is the
 * server hedging against a viewport it guessed at; with a measured one there
 * is nothing to hedge, and a floor here would throw away most of a level.
 */
function computeMapFit(
  spec: MapFitSpec,
  widthPx: number,
  heightPx: number,
): { center: { lat: number; lon: number }; zoom: number } {
  const center = {
    lat: latFromMercatorY((mercatorY(spec.minLat) + mercatorY(spec.maxLat)) / 2),
    lon: (spec.minLon + spec.maxLon) / 2,
  };
  if (spec.minLat === spec.maxLat && spec.minLon === spec.maxLon) {
    return { center, zoom: spec.singlePointZoom };
  }
  const latFraction = (mercatorY(spec.maxLat) - mercatorY(spec.minLat)) / Math.PI;
  let lonDiff = spec.maxLon - spec.minLon;
  if (lonDiff < 0) lonDiff += 360;
  const lonFraction = lonDiff / 360;
  const latZoom = Math.log2(heightPx / WORLD_TILE_PX / (latFraction || Number.EPSILON));
  const lonZoom = Math.log2(widthPx / WORLD_TILE_PX / (lonFraction || Number.EPSILON));
  let zoom = Math.min(latZoom, lonZoom) - spec.padding;
  if (!Number.isFinite(zoom)) zoom = spec.singlePointZoom;
  return { center, zoom: Math.max(1, Math.min(zoom, spec.maxZoom)) };
}

/** Whether a recomputed fit is close enough to the applied one to leave alone.
 *  Below these thresholds the map would not move a pixel, and re-applying
 *  would cost a `uirevision` bump for nothing. */
function sameFit(a: AppliedFit, b: { center: { lat: number; lon: number }; zoom: number }): boolean {
  return (
    Math.abs(a.zoom - b.zoom) < 0.01 &&
    Math.abs(a.center.lat - b.center.lat) < 1e-6 &&
    Math.abs(a.center.lon - b.center.lon) < 1e-6
  );
}

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
