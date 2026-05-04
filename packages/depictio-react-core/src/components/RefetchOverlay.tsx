import React from 'react';
import { Loader, Box } from '@mantine/core';

interface RefetchOverlayProps {
  visible: boolean;
}

/**
 * Subtle in-flight indicator overlaid on top of an already-rendered
 * component (figure / map / table / image grid). Replaces the previous
 * "unmount + full Loader" flicker pattern: the existing content stays
 * mounted while the next fetch is in flight; the overlay just dims and
 * shows a small spinner in the corner.
 *
 * Pointer-events are off so the user can keep scrolling / interacting with
 * the underlying content during refetch.
 */
const RefetchOverlay: React.FC<RefetchOverlayProps> = ({ visible }) => {
  if (!visible) return null;
  return (
    <Box
      aria-hidden
      style={{
        position: 'absolute',
        inset: 0,
        background: 'rgba(255, 255, 255, 0.35)',
        backdropFilter: 'saturate(0.85)',
        pointerEvents: 'none',
        zIndex: 1,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'flex-end',
        padding: 8,
      }}
    >
      <Loader size="xs" />
    </Box>
  );
};

export default RefetchOverlay;
