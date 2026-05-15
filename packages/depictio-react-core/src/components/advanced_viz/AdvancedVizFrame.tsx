import React, { useContext, useEffect, useMemo } from 'react';
import { Alert, Badge, Group, Loader, Paper, Stack, Text } from '@mantine/core';

import ErrorBoundary from '../ErrorBoundary';
import {
  AdvancedVizDataPopover,
  AdvancedVizExtrasContext,
  AdvancedVizSettingsPopover,
  type TierAnnotation,
} from './AdvancedVizExtras';

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
}

/** Subtle Mantine theme colour for each canonical tier name (no hardcoded
 *  literals — respects `feedback_mantine_defaults_no_custom_colors`). */
const TIER_COLORS: Record<string, string> = {
  UP: 'pink',
  DN: 'blue',
  HIT: 'teal',
  ABOVE: 'teal',
  BELOW: 'gray',
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
}) => {
  const publish = useContext(AdvancedVizExtrasContext);

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
    return nodes.length ? <>{nodes}</> : null;
  }, [controls, dataRows, dataColumns, tierAnnotation]);

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
        {title || subtitle || (counts && Object.keys(counts).length > 0) ? (
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
                {Object.entries(counts).map(([label, n]) => (
                  <Badge
                    key={label}
                    size="xs"
                    radius="sm"
                    variant="light"
                    color={TIER_COLORS[label] ?? 'gray'}
                  >
                    {label}: {n.toLocaleString()}
                  </Badge>
                ))}
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
