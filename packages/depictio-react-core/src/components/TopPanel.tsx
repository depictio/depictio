import React from 'react';
import { Group, Paper } from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../api';
import ComponentRenderer from './ComponentRenderer';

interface TopPanelProps {
  components: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * Slim, full-width container above the dashboard grid (right column only).
 * Hosts compact horizontal interactive controls — currently the Timeline
 * scrubber. Filters emitted from here flow through the same
 * `onFilterChange` path as left-sidebar components.
 */
const TopPanel: React.FC<TopPanelProps> = ({ components, filters, onFilterChange }) => {
  if (components.length === 0) return null;
  return (
    <Paper withBorder radius={0} p="xs" mb="xs">
      <Group gap="md" wrap="nowrap" align="center">
        {components.map((m) => (
          <div key={m.index} style={{ flex: 1, minWidth: 0 }}>
            <ComponentRenderer
              metadata={m}
              filters={filters}
              onFilterChange={onFilterChange}
            />
          </div>
        ))}
      </Group>
    </Paper>
  );
};

export default TopPanel;
