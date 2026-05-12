import React from 'react';
import { Divider, Paper, Stack, Text } from '@mantine/core';

import type { InteractiveFilter, StoredMetadata } from '../api';
import ComponentRenderer from './ComponentRenderer';

interface InteractiveGroupCardProps {
  groupName: string;
  members: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Optional per-member chrome extras keyed by `metadata.index` — used by the
   *  viewer to inject a {@link GlobeToggle} into each interactive component's
   *  chrome row so users can promote that filter to global scope. */
  extraActionsByIndex?: Record<string, React.ReactNode>;
}

/**
 * Visual container for interactive components sharing the same `group`.
 * Compact mode is forced on every member so they shed their own Paper and
 * tick marks, yielding a high-density "filter by x/y/z" stack inside one
 * Paper. Each member still emits its own filter and is read independently —
 * grouping is purely presentational, the AND-merging happens in the existing
 * filter pipeline.
 */
const InteractiveGroupCard: React.FC<InteractiveGroupCardProps> = ({
  groupName,
  members,
  filters,
  onFilterChange,
  extraActionsByIndex,
}) => {
  return (
    <Paper withBorder p="xs" radius="md" shadow="xs">
      <Text size="xs" fw={600} c="dimmed" tt="uppercase" mb={6}>
        {groupName}
      </Text>
      <Stack gap={6}>
        {members.map((m, i) => (
          <React.Fragment key={m.index}>
            {i > 0 && <Divider />}
            <ComponentRenderer
              metadata={m}
              filters={filters}
              onFilterChange={onFilterChange}
              compact
              extraActions={extraActionsByIndex?.[m.index]}
            />
          </React.Fragment>
        ))}
      </Stack>
    </Paper>
  );
};

export default InteractiveGroupCard;
