import React from 'react';
import { Alert, Loader, Stack, Text } from '@mantine/core';

import ErrorBoundary from '../ErrorBoundary';

interface AdvancedVizFrameProps {
  /** Inner content (the viz itself). */
  children: React.ReactNode;
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
 * Shared wrapper for advanced-viz renderers. Provides:
 *  - error boundary
 *  - loading skeleton
 *  - empty-state messaging
 *  - a top-bar slot for builtin Tier-2 controls (sliders, search, top-N)
 *
 * Chrome (title, fullscreen, download, reset) is added by ComponentRenderer's
 * wrapWithChrome() one level above — same convention as figure/table.
 */
const AdvancedVizFrame: React.FC<AdvancedVizFrameProps> = ({
  children,
  controls,
  loading,
  error,
  emptyMessage,
}) => {
  return (
    <ErrorBoundary>
      <Stack gap="xs" style={{ width: '100%', height: '100%' }}>
        {controls ? (
          <div style={{ flex: '0 0 auto', padding: '4px 8px' }}>{controls}</div>
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
      </Stack>
    </ErrorBoundary>
  );
};

export default AdvancedVizFrame;
