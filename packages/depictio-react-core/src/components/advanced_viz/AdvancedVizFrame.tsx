import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Badge, Group, Paper, Stack, Text, Tooltip } from '@mantine/core';

import ErrorBoundary from '../ErrorBoundary';
import ComponentSkeleton from '../ComponentSkeleton';
import { GroupStatusBadgeContext } from '../GroupStatusBadge';
import { ComponentIndexContext, useReportLoadStatus } from '../DashboardLoadingProvider';
import { GRID_ROW_GAP_PX, GRID_ROW_PX, publishContentDemand } from '../autofit';
import {
  AdvancedVizExtrasContext,
  type AdvancedVizExtrasPayload,
  type TierAnnotation,
} from './AdvancedVizExtras';
import {
  InlineControlsRail,
  InlineControlsStrip,
  RAIL_WIDTH_PX,
  inlineLayoutFor,
  selectionEcho,
  useControlsPlacement,
  useRegionEcho,
} from './AdvancedVizInlineControls';
import { frameTiers } from './frameTiers';
import { usePlotSlotResize } from './plotSlotResize';

/**
 * Server-side downsampling state, mirroring the scatter-figure reduction badge
 * + Load-All toggle. When `sampled` (or `full`) is set, the frame shows an
 * "N / M pts" badge and publishes a Load-All ActionIcon into the chrome row.
 */
export interface AdvancedVizReduction {
  /** Rows currently shown (post-sampling). */
  displayed: number;
  /** Rows before sampling. */
  total: number;
  /** Server randomly downsampled the returned frame. */
  sampled: boolean;
  /** Full frame currently loaded (Load-All engaged). */
  full: boolean;
  /** A full-load refetch is in flight. */
  loading: boolean;
  /** Flip between the sampled and full views. */
  onToggle: () => void;
}

interface AdvancedVizFrameProps {
  /** Inner content (the viz itself). */
  children: React.ReactNode;
  /** Title rendered at the top of the bordered container. */
  title?: string;
  /** Optional sub-title shown below the title (dim, smaller). */
  subtitle?: string;
  /**
   * Tier-2 controls (sliders / dropdowns / toggles). NOT rendered inline:
   * the frame publishes them via AdvancedVizExtrasContext so the Settings
   * ActionIcon ends up in ComponentChrome's hover-revealed action row,
   * alongside metadata / fullscreen / reset (same styling, same position).
   */
  controls?: React.ReactNode;
  /**
   * The encoding tier: the controls that decide *what* is plotted (axes,
   * colour-by, normalise, rank, view switch, gene picker, run button), as
   * opposed to the cosmetic tier in `controls` (opacity, point size, labels).
   *
   * Pass a fragment of individual compact controls, not a pre-arranged Stack:
   * the frame lays the same node out as a strip under the title (`header`), as
   * a column in the rail (`rail`), or hands it to the settings popover ahead of
   * the cosmetic tier (`popover`, the default). Sizes are the renderer's to
   * set, `size="xs"` and an explicit `w`, since Mantine sizes cannot cascade
   * from a wrapper.
   */
  primaryControls?: React.ReactNode;
  /**
   * How many grid rows this tile's content actually needs, published to the
   * autofit channel so a viz with three bars stops occupying five rows. The
   * frame adds the inline controls area's own height when it draws one below
   * the plot.
   */
  contentDemand?: { rows: number };
  /**
   * What this tile is currently showing, as one dim line under the title
   * (`412 / 5,000 rows`, `chr7:55,000,000-56,000,000`, `A (412) vs B (388)`).
   * Renderers that know better than the frame set it; otherwise the frame
   * derives it from `reduction` and from any region filter that reached the
   * tile.
   */
  echo?: string;
  /** Loading state for initial fetch. */
  loading?: boolean;
  /** Error to display in place of children. */
  error?: string | null;
  /** Empty-state message when data fetched but row_count === 0. */
  emptyMessage?: string;
  /**
   * Optional column-oriented row data. Published via the same context so a
   * "Show data" ActionIcon appears in the chrome row with a 50-row preview
   * Popover.
   */
  dataRows?: Record<string, unknown[]>;
  /** Column ordering for the data popover. */
  dataColumns?: string[];
  /**
   * Threshold-aware per-row annotation aligned with `dataRows` (volcano UP/DN/NS,
   * manhattan HIT/MISS, etc.). When set, the data popover prepends a `__tier`
   * column, sorts selected rows to the top, and tints them.
   */
  tierAnnotation?: TierAnnotation;
  /**
   * Tier-level counts rendered as small Badges under the title (e.g.
   * `{ UP: 12, DN: 7, NS: 481 }` for volcano). Order is preserved from the
   * dict's iteration order, so renderers should pass an ordered object.
   */
  counts?: Record<string, number>;
  /**
   * Server-side downsampling state. When present and reduced/full, the frame
   * renders an "N / M pts" badge and a Load-All toggle in the chrome row,
   * matching the scatter-figure UX.
   */
  reduction?: AdvancedVizReduction;
  /**
   * The rows behind this viz were sampled even though it aggregates them, so
   * the values on screen are estimates rather than totals. Set from the
   * server's `sampling.degraded` — see `advanced_viz_no_sample_max_rows`. The
   * frame renders a warning badge; it is deliberately separate from
   * `reduction`, since the renderers that most need to say this are the ones
   * with no Load-All toggle to hang it off.
   */
  estimated?: boolean;
}

/** Subtle Mantine theme colour for each canonical tier name (no hardcoded
 *  literals — respects `feedback_mantine_defaults_no_custom_colors`).
 *
 *  ``BELOW`` is orange (not gray) so that when a renderer flips the
 *  highlight to the below-threshold population, its chip and table tint
 *  actually pop. Renderers that don't want this can pin a different colour
 *  via ``selectedOrder`` semantics — chips outside ``selectedOrder`` always
 *  fall back to gray regardless of their natural colour.
 *
 *  Exported so per-viz renderers (e.g. ManhattanRenderer) can paint their
 *  Plotly markers with the same Mantine palette names — the chip, table
 *  tint, and dot colours all stay in sync without each renderer
 *  reinventing the mapping. */
export const TIER_COLORS: Record<string, string> = {
  UP: 'pink',
  DN: 'blue',
  HIT: 'teal',
  ABOVE: 'teal',
  BELOW: 'orange',
  NS: 'gray',
  MISS: 'gray',
};

/**
 * Shared wrapper for advanced-viz renderers.
 *
 * Renders a bordered Mantine Paper with the viz title + subtitle at the top
 * and the viz body below. The Settings + Show-data ActionIcons live in the
 * chrome action row (ComponentChrome's `extraActions`) — the frame just
 * publishes their content via context so they get the same styling and
 * hover behaviour as the standard chrome icons.
 */
const AdvancedVizFrame: React.FC<AdvancedVizFrameProps> = ({
  children,
  title,
  subtitle,
  controls,
  primaryControls,
  contentDemand,
  echo,
  loading,
  error,
  emptyMessage,
  dataRows,
  dataColumns,
  tierAnnotation,
  counts,
  reduction,
  estimated,
}) => {
  const publish = useContext(AdvancedVizExtrasContext);
  // "not grouped", when the dispatch found the analysis groups cannot reach
  // this component. Null otherwise, and with no provider.
  const groupBadge = useContext(GroupStatusBadgeContext);

  // Report this panel's load status to the dashboard registry (drives the
  // header progress bar). Index arrives via context from AdvancedVizDispatch so
  // we don't thread it through all ~20 per-viz renderers. No-ops with no
  // provider (catalog preview / editor).
  const componentIndex = useContext(ComponentIndexContext);
  useReportLoadStatus(
    componentIndex ?? '',
    componentIndex ? (loading ? 'loading' : error ? 'error' : 'ready') : null,
  );

  // Only surface the reduction affordances once the frame is actually reduced
  // (or fully loaded) — an unsampled small frame has nothing to expand.
  const showReduction = Boolean(reduction && (reduction.sampled || reduction.full));

  // Depend on `reduction`'s *primitive* fields, not the object identity. Several
  // renderers build `reduction={{ …, onToggle: () => … }}` inline, i.e. a fresh
  // object with a fresh callback every render; depending on the object would
  // recompute `extras` every render, re-fire the publish effect below, and —
  // because `publish` setStates in ComponentRenderer, which re-renders this
  // subtree — loop until React aborts with "Maximum update depth exceeded".
  // Reading the primitives keeps `extras` stable across renders that didn't
  // change anything, and the ref lets the Load-All toggle call the latest
  // `onToggle` without its identity churn invalidating the memo.
  const redPresent = Boolean(reduction);
  const redFull = reduction?.full ?? false;
  const redLoading = reduction?.loading ?? false;
  const redDisplayed = reduction?.displayed ?? 0;
  const redTotal = reduction?.total ?? 0;
  const onToggleRef = useRef(reduction?.onToggle);
  onToggleRef.current = reduction?.onToggle;
  const stableToggle = useCallback(() => onToggleRef.current?.(), []);

  // Where this tile's controls are drawn. Resolved once by the dispatch (which
  // holds the config and the dashboard default) and read here and there, so
  // the strip and the popover cannot disagree about which tier lives where.
  const { placement } = useControlsPlacement();
  const regionEcho = useRegionEcho();

  // A renderer with only a cosmetic tier still gets a strip under `header`:
  // its controls are promoted, which also leaves the popover empty.
  const tiers = useMemo(
    () => frameTiers(placement, primaryControls, controls),
    [placement, primaryControls, controls],
  );
  const stripControls = tiers.primary;
  const cosmeticControls = tiers.cosmetic;

  // Publish what this renderer has, not how to draw it. AdvancedVizDispatch
  // turns the payload back into the popovers; the inspector turns the same
  // fields into docked tabs. Publishing finished popovers, as this once did,
  // left the inspector with nothing it could re-present.
  const extras = useMemo<AdvancedVizExtrasPayload | null>(() => {
    const payload: AdvancedVizExtrasPayload = {};
    if (cosmeticControls) payload.controls = cosmeticControls;
    if (stripControls) payload.primaryControls = stripControls;
    if (dataRows) {
      payload.data = { rows: dataRows, columns: dataColumns, tierAnnotation };
    }
    if (redPresent && showReduction) {
      payload.reduction = {
        reduced: !redFull,
        full: redFull,
        loading: redLoading,
        toggle: stableToggle,
        noun: 'points',
      };
    }
    return Object.keys(payload).length ? payload : null;
  }, [
    cosmeticControls,
    stripControls,
    dataRows,
    dataColumns,
    tierAnnotation,
    redPresent,
    redFull,
    redLoading,
    stableToggle,
    showReduction,
  ]);

  useEffect(() => {
    if (!publish) return;
    publish(extras);
    return () => publish(null);
  }, [publish, extras]);

  // The rail moves beside the plot only on a tile wide enough for both. Width
  // rather than the grid's `w`: the frame never sees the layout item, and a
  // dashboard renders at several breakpoints anyway.
  const frameRef = useRef<HTMLDivElement | null>(null);
  const [frameWidth, setFrameWidth] = useState<number | null>(null);
  useEffect(() => {
    const node = frameRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    const measure = () =>
      setFrameWidth((prev) => {
        const next = node.clientWidth;
        // Sub-pixel churn would re-render the whole subtree on every reflow.
        return prev !== null && Math.abs(prev - next) < 1 ? prev : next;
      });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const hasInlineControls = Boolean(stripControls || cosmeticControls);
  const inlineLayout = inlineLayoutFor(placement, frameWidth, hasInlineControls);

  // An inline area under the plot is content the tile has to make room for:
  // without this, turning the strip on squeezes the figure instead of growing
  // the tile. A side rail takes width, not height, so it adds nothing.
  const inlineRef = useRef<HTMLDivElement | null>(null);
  const [inlineHeight, setInlineHeight] = useState(0);
  useEffect(() => {
    const node = inlineRef.current;
    if (!node || typeof ResizeObserver === 'undefined') {
      setInlineHeight(0);
      return;
    }
    const measure = () =>
      setInlineHeight((prev) => {
        const next = Math.round(node.getBoundingClientRect().height);
        return Math.abs(prev - next) < 2 ? prev : next;
      });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [inlineLayout]);

  // The strip, the rail and the badge rows all take room from the plot slot
  // without the window moving, which is the only resize Plotly listens to.
  const plotSlotRef = useRef<HTMLDivElement | null>(null);
  usePlotSlotResize(plotSlotRef);

  const demandRows = contentDemand?.rows;
  useEffect(() => {
    if (!componentIndex || demandRows === undefined) return;
    const stacked = inlineLayout === 'header' || inlineLayout === 'rail-below';
    const extraRows =
      stacked && inlineHeight > 0
        ? Math.ceil(inlineHeight / (GRID_ROW_PX + GRID_ROW_GAP_PX))
        : 0;
    publishContentDemand(String(componentIndex), { rows: demandRows + extraRows });
  }, [componentIndex, demandRows, inlineLayout, inlineHeight]);

  // One dim line saying what is on screen. Derived from the reduction the
  // renderer already publishes unless it passed something better.
  // The rows the renderer handed the data popover, as the count to echo when
  // nothing was sampled, which is most tiles, most of the time.
  const dataRowCount = dataRows ? (Object.values(dataRows)[0]?.length ?? 0) : 0;
  const echoText = useMemo(
    () =>
      selectionEcho({
        echo,
        reduction: redPresent ? { displayed: redDisplayed, total: redTotal, full: redFull } : null,
        rows: dataRowCount,
        region: regionEcho,
      }),
    [echo, redPresent, redDisplayed, redTotal, redFull, dataRowCount, regionEcho],
  );

  // Once the plot has drawn, a refetch keeps it mounted under the skeleton
  // instead of swapping it out. Unmounting purges Plotly, and a purged GL plot
  // leaves its WebGL contexts alive until GC, so every filter change on a busy
  // tab used to churn contexts until Chrome evicted a live plot's (a blank
  // UMAP after creating a group). It also removes the flash between renders.
  const hasDrawnRef = useRef(false);
  if (!loading && !error && !emptyMessage) hasDrawnRef.current = true;
  const skeleton = (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', zIndex: 1 }}>
      <ComponentSkeleton variant="block" />
    </div>
  );
  const body = loading ? (
    hasDrawnRef.current ? (
      <>
        {children}
        {skeleton}
      </>
    ) : (
      skeleton
    )
  ) : error ? (
    <Alert color="red" title="Failed to render" variant="light">
      <Text size="xs">{error}</Text>
    </Alert>
  ) : emptyMessage ? (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        color: 'var(--mantine-color-dimmed)',
        fontSize: '0.85rem',
      }}
    >
      {emptyMessage}
    </div>
  ) : (
    children
  );

  return (
    <ErrorBoundary>
      <Paper
        ref={frameRef}
        p="sm"
        withBorder
        radius="md"
        style={{
          flex: 1,
          minHeight: 0,
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          borderWidth: 1.5,
        }}
      >
        {title ||
        subtitle ||
        echoText ||
        inlineLayout === 'header' ||
        (counts && Object.keys(counts).length > 0) ||
        showReduction ||
        estimated ||
        groupBadge ? (
          <Stack gap={2} mb="xs">
            {title ? (
              <Text fw={600} size="sm" lineClamp={1}>
                {title}
              </Text>
            ) : null}
            {subtitle ? (
              <Text size="xs" c="dimmed" lineClamp={2}>
                {subtitle}
              </Text>
            ) : null}
            {echoText ? (
              <Text size="xs" c="dimmed" lineClamp={1} data-testid="advanced-viz-echo">
                {echoText}
              </Text>
            ) : null}
            {counts && Object.keys(counts).length > 0 ? (
              <Group gap={4} wrap="nowrap" mt={2}>
                {Object.entries(counts).map(([label, n]) => {
                  // When ``tierAnnotation.selectedOrder`` is provided, that's
                  // the source of truth for which tier is "highlighted" — chips
                  // for selected tiers get the canonical hit colour, the rest
                  // dim to gray. This keeps the chips, plot markers, and data
                  // table consistent when the user flips highlight above/below.
                  // Without selectedOrder (no threshold set), fall back to the
                  // per-tier palette.
                  const selected = tierAnnotation?.selectedOrder;
                  const respectSelection = Array.isArray(selected) && selected.length > 0;
                  const isSelected = respectSelection
                    ? selected.includes(label)
                    : true;
                  const color = respectSelection
                    ? isSelected
                      ? TIER_COLORS[label] ?? 'teal'
                      : 'gray'
                    : TIER_COLORS[label] ?? 'gray';
                  return (
                    <Badge
                      key={label}
                      size="xs"
                      radius="sm"
                      variant={isSelected ? 'light' : 'outline'}
                      color={color}
                    >
                      {label}: {n.toLocaleString()}
                    </Badge>
                  );
                })}
              </Group>
            ) : null}
            {reduction && showReduction ? (
              <Group gap={4} wrap="nowrap" mt={2}>
                <Badge variant="light" color="gray" size="xs" radius="sm">
                  {reduction.full
                    ? `${reduction.displayed.toLocaleString()} pts (all)`
                    : `${reduction.displayed.toLocaleString()} / ${reduction.total.toLocaleString()} pts`}
                </Badge>
              </Group>
            ) : null}
            {estimated ? (
              // "10,000 / 5,000,000 pts" on a chart that sums its rows reads as
              // a display cap. It isn't: the values themselves are off by the
              // sampling stride, and that has to be said outright.
              <Group gap={4} wrap="nowrap" mt={2}>
                <Tooltip
                  label="This chart derives its values from the rows it receives, and the collection was too large to send whole — what is shown is an estimate."
                  multiline
                  w={260}
                  withArrow
                >
                  <Badge variant="light" color="orange" size="xs" radius="sm">
                    estimated
                  </Badge>
                </Tooltip>
              </Group>
            ) : null}
            {groupBadge ? (
              <Group gap={4} wrap="nowrap" mt={2}>
                {groupBadge}
              </Group>
            ) : null}
            {inlineLayout === 'header' ? (
              <div ref={inlineRef} style={{ marginTop: 4 }}>
                <InlineControlsStrip>{stripControls}</InlineControlsStrip>
              </div>
            ) : null}
          </Stack>
        ) : null}
        <div
          style={{
            flex: '1 1 auto',
            minHeight: 0,
            display: 'flex',
            flexDirection: inlineLayout === 'rail-side' ? 'row' : 'column',
            gap: inlineLayout === 'rail-side' || inlineLayout === 'rail-below' ? 8 : 0,
          }}
        >
          <div
            ref={plotSlotRef}
            style={{ flex: '1 1 auto', minHeight: 0, minWidth: 0, position: 'relative' }}
          >
            {body}
          </div>
          {inlineLayout === 'rail-side' || inlineLayout === 'rail-below' ? (
            <div
              ref={inlineLayout === 'rail-below' ? inlineRef : undefined}
              style={
                inlineLayout === 'rail-side'
                  ? { flex: `0 0 ${RAIL_WIDTH_PX}px`, minHeight: 0, display: 'flex' }
                  : { flex: '0 0 auto' }
              }
            >
              <InlineControlsRail layout={inlineLayout}>
                {stripControls}
                {cosmeticControls}
              </InlineControlsRail>
            </div>
          ) : null}
        </div>
      </Paper>
    </ErrorBoundary>
  );
};

export default AdvancedVizFrame;
