import React from 'react';
import { Group, Paper } from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../api';
import ComponentRenderer from './ComponentRenderer';

interface TopPanelProps {
  components: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Realtime refresh counter — forwarded so the Timeline scrubber re-fetches
   *  its datetime bounds (and range extends) as new rows stream in. */
  refreshTick?: number;
  /** Drop the bordered strip: for controls that bring their own card. */
  bare?: boolean;
}

/**
 * Slim, full-width container above the dashboard grid (right column only).
 * Hosts compact horizontal interactive controls — currently the Timeline
 * scrubber. Filters emitted from here flow through the same
 * `onFilterChange` path as left-sidebar components.
 */
const TopPanel: React.FC<TopPanelProps> = ({
  components,
  filters,
  onFilterChange,
  refreshTick,
  bare,
}) => {
  if (components.length === 0) return null;
  const row = (
    <Group gap="md" wrap="nowrap" align="center">
      {components.map((m) => (
        <div key={m.index} data-component-id={m.index} style={{ flex: 1, minWidth: 0 }}>
          <ComponentRenderer
            metadata={m}
            filters={filters}
            onFilterChange={onFilterChange}
            refreshTick={refreshTick}
          />
        </div>
      ))}
    </Group>
  );
  if (bare) return row;
  return (
    <Paper withBorder radius={0} p="xs" mb="xs">
      {row}
    </Paper>
  );
};

export default TopPanel;
