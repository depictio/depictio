import React from 'react';
import { Alert, Loader, Paper, Stack, Text } from '@mantine/core';

import ErrorBoundary from '../ErrorBoundary';

interface AdvancedVizFrameProps {
  /** Inner content (the viz itself). */
  children: React.ReactNode;
  /** Title rendered at the top of the bordered container (matches FigureRenderer convention). */
  title?: string;
  /** Optional sub-title shown below the title. */
  subtitle?: string;
  /** Optional top-bar controls rendered above the chart (sliders, search, top-N). */
  controls?: React.ReactNode;
  /** Loading state for initial fetch. */
  loading?: boolean;
  /** Error to display in place of children. */
  error?: string | null;
  /** Empty-state message when data fetched but row_count === 0. */
  emptyMessage?: string;
}

/**
 * Shared wrapper for advanced-viz renderers. Mirrors the FigureRenderer
 * chrome: a single bordered Paper container holding (title, controls,
 * viz), with the renderer's own controls slot above the viz body. Error
 * boundary, loading skeleton, empty-state are handled here so each
 * renderer stays focused on the chart.
 *
 * The "Show data" drawer was removed — each dashboard tab already includes
 * a dedicated table component for the underlying data; duplicating that as
 * a drawer was confusing and the AG Grid inside the drawer mounted in the
 * wrong scroll context anyway.
 */
const AdvancedVizFrame: React.FC<AdvancedVizFrameProps> = ({
  children,
  title,
  subtitle,
  controls,
  loading,
  error,
  emptyMessage,
}) => {
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
        }}
      >
        {title ? (
          <Stack gap={2} mb="xs">
            <Text fw={600} size="sm">
              {title}
            </Text>
            {subtitle ? (
              <Text size="xs" c="dimmed">
                {subtitle}
              </Text>
            ) : null}
          </Stack>
        ) : null}
        {controls ? <div style={{ marginBottom: 6 }}>{controls}</div> : null}
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
