import React, { useContext, useEffect, useMemo } from 'react';
import { Alert, Badge, Group, Loader, Paper, Stack, Text, Tooltip } from '@mantine/core';

import ErrorBoundary from '../ErrorBoundary';
import LoadAllButton from '../chrome/LoadAllButton';
import {
  AdvancedVizDataPopover,
  AdvancedVizExtrasContext,
  AdvancedVizSettingsPopover,
  type TierAnnotation,
} from './AdvancedVizExtras';

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

  // Only surface the reduction affordances once the frame is actually reduced
  // (or fully loaded) — an unsampled small frame has nothing to expand.
  const showReduction = Boolean(reduction && (reduction.sampled || reduction.full));

  // Render the popovers as a single React node and publish it. ComponentRenderer
  // reads it via useState and threads it through wrapWithChrome's extraActions
  // slot. The popovers themselves portal their dropdown content so even if the
  // chrome row fades out on mouseleave, an OPEN popover stays visible.
  const extras = useMemo(() => {
    const nodes: React.ReactNode[] = [];
    if (controls) {
      nodes.push(<AdvancedVizSettingsPopover key="settings" controls={controls} />);
    }
    if (dataRows) {
      nodes.push(
        <AdvancedVizDataPopover
          key="data"
          dataRows={dataRows}
          dataColumns={dataColumns}
          tierAnnotation={tierAnnotation}
        />,
      );
    }
    // Reuse the exact figure/table Load-All ActionIcon so the toggle looks and
    // sits identically across component types.
    if (reduction && showReduction) {
      nodes.push(
        <LoadAllButton
          key="load-all"
          state={{
            reduced: !reduction.full,
            full: reduction.full,
            loading: reduction.loading,
            toggle: reduction.onToggle,
            noun: 'points',
          }}
        />,
      );
    }
    return nodes.length ? <>{nodes}</> : null;
  }, [controls, dataRows, dataColumns, tierAnnotation, reduction, showReduction]);

  useEffect(() => {
    if (!publish) return;
    publish(extras);
    return () => publish(null);
  }, [publish, extras]);

  return (
    <ErrorBoundary>
      <Paper
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
        {title || subtitle || (counts && Object.keys(counts).length > 0) || showReduction || estimated ? (
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
          </Stack>
        ) : null}
        <div style={{ flex: '1 1 auto', minHeight: 0, position: 'relative' }}>
          {loading ? (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Loader size="sm" />
            </div>
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
          )}
        </div>
      </Paper>
    </ErrorBoundary>
  );
};

export default AdvancedVizFrame;
