import React from 'react';
import { Box } from '@mantine/core';

/**
 * The height every compact filter control occupies.
 *
 * Mantine's `xs` input — the select and the date picker — is the tallest of the
 * controls the left panel stacks; a slider is 12px, a segmented control and a
 * checkbox land somewhere between. Left to their natural heights, a column of
 * compact filters gets a different row pitch per control type, so the panel
 * reads as a ragged pile rather than as one list, and swapping a filter's type
 * moves everything below it.
 */
export const COMPACT_CONTROL_HEIGHT = 30;

/**
 * Reserves that height for one control, centring anything shorter in it.
 *
 * A no-op outside compact mode: ungrouped filters own a Paper each and their
 * heights are already set by the grid.
 */
export const CompactControlSlot: React.FC<{
  compact?: boolean;
  children: React.ReactNode;
}> = ({ compact, children }) => {
  if (!compact) return <>{children}</>;
  return (
    <Box
      mih={COMPACT_CONTROL_HEIGHT}
      style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}
    >
      {children}
    </Box>
  );
};

export default CompactControlSlot;
