import React from 'react';
import { Paper, Stack, Title } from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../api';
import ComponentRenderer from './ComponentRenderer';

interface InteractiveGroupCardProps {
  groupName: string;
  members: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
}

/**
 * Visual container for interactive components sharing the same `group`.
 * Renders one Mantine Paper with each member stacked vertically. Each member
 * still emits its own filter and is read independently — grouping is purely
 * presentational, the AND-merging happens in the existing filter pipeline.
 */
const InteractiveGroupCard: React.FC<InteractiveGroupCardProps> = ({
  groupName,
  members,
  filters,
  onFilterChange,
}) => {
  return (
    <Paper withBorder p="xs" radius="md">
      <Stack gap="xs">
        <Title order={6}>{groupName}</Title>
        {members.map((m) => (
          <ComponentRenderer
            key={m.index}
            metadata={m}
            filters={filters}
            onFilterChange={onFilterChange}
          />
        ))}
      </Stack>
    </Paper>
  );
};

export default InteractiveGroupCard;
