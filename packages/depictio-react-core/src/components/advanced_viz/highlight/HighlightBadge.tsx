import React from 'react';
import { Badge, CloseButton } from '@mantine/core';

/**
 * "N highlighted" in the tile's badge row, with the way to let go of them. The
 * highlight is a view state (see highlightModel), so this is the only place it
 * can be cleared without touching the table or the plot again.
 */
const HighlightBadge: React.FC<{ count: number; onClear: () => void }> = ({ count, onClear }) =>
  count > 0 ? (
    <Badge
      size="xs"
      variant="light"
      radius="sm"
      data-testid="highlight-badge"
      rightSection={
        <CloseButton size="xs" aria-label="Clear the highlighted points" onClick={onClear} />
      }
    >
      {count.toLocaleString()} highlighted
    </Badge>
  ) : null;

export default HighlightBadge;
