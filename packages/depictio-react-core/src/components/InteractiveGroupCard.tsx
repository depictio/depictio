import React from 'react';
import {
  ActionIcon,
  Badge,
  Collapse,
  Divider,
  Group,
  Paper,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import type { InteractiveFilter, StoredMetadata } from '../api';
import { countActiveFilters } from '../activeFilters';
import ComponentRenderer from './ComponentRenderer';

interface InteractiveGroupCardProps {
  groupName: string;
  members: StoredMetadata[];
  filters: InteractiveFilter[];
  onFilterChange?: (filter: InteractiveFilter) => void;
  /** Realtime refresh counter — forwarded so a grouped Timeline member
   *  re-fetches its datetime bounds as new rows stream in. */
  refreshTick?: number;
  /** Render the header as a toggle. Without it the card is always expanded. */
  collapsible?: boolean;
  /** Current open state. Only read when `collapsible`. */
  open?: boolean;
  onToggle?: () => void;
  /** Editor-only per-member actions (edit / duplicate / delete), injected into
   *  each member's chrome so grouped filters stay editable. */
  renderMemberActions?: (member: StoredMetadata) => React.ReactNode;
  /** Editor-only: render the grip that react-grid-layout drags the group by. */
  showDragHandle?: boolean;
}

/**
 * Visual container for interactive components sharing the same `group`.
 * Compact mode is forced on every member so they shed their own Paper and
 * tick marks, yielding a high-density "filter by x/y/z" stack inside one
 * Paper. Each member still emits its own filter and is read independently —
 * grouping is purely presentational, the AND-merging happens in the existing
 * filter pipeline.
 *
 * A collapsed group carries a badge with its active-filter count, so folding
 * one away never hides the fact that it is still narrowing the data. The
 * user's toggle always wins: forcing a group open because it holds a filter
 * turns the chevron into a dead click with nothing to explain it.
 */
const InteractiveGroupCard: React.FC<InteractiveGroupCardProps> = ({
  groupName,
  members,
  filters,
  onFilterChange,
  refreshTick,
  collapsible = false,
  open = true,
  onToggle,
  renderMemberActions,
  showDragHandle = false,
}) => {
  const activeCount = countActiveFilters(filters, members);
  const expanded = !collapsible || open;

  const resetGroup = () => {
    if (!onFilterChange) return;
    for (const m of members) {
      onFilterChange({ index: m.index, value: null });
    }
  };

  const heading = (
    <Group gap={6} wrap="nowrap" style={{ minWidth: 0, flex: 1 }}>
      {showDragHandle && (
        <Icon
          icon="mdi:drag"
          width={14}
          height={14}
          className="react-grid-dragHandle"
          style={{ flexShrink: 0, cursor: 'grab', color: 'var(--mantine-color-dimmed)' }}
        />
      )}
      {collapsible && (
        <Icon
          icon={expanded ? 'mdi:chevron-down' : 'mdi:chevron-right'}
          width={14}
          height={14}
          style={{ flexShrink: 0, color: 'var(--mantine-color-dimmed)' }}
        />
      )}
      <Text size="xs" fw={600} c="dimmed" tt="uppercase" truncate>
        {groupName}
      </Text>
      {activeCount > 0 && (
        <Badge size="xs" variant="light" circle>
          {activeCount}
        </Badge>
      )}
    </Group>
  );

  return (
    <Paper withBorder p="xs" radius="md" shadow="xs">
      <Group justify="space-between" wrap="nowrap" gap="xs" mb={expanded ? 6 : 0}>
        {collapsible && onToggle ? (
          <UnstyledButton
            onClick={onToggle}
            aria-expanded={expanded}
            style={{ flex: 1, minWidth: 0 }}
          >
            {heading}
          </UnstyledButton>
        ) : (
          heading
        )}
        {activeCount > 0 && onFilterChange && (
          <Tooltip label={`Reset ${groupName}`} withArrow openDelay={400}>
            <ActionIcon
              variant="subtle"
              color="orange"
              size="xs"
              aria-label={`Reset ${groupName}`}
              onClick={resetGroup}
            >
              <Icon icon="bx:reset" width={12} height={12} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>
      <Collapse in={expanded}>
        <Stack gap={6}>
          {members.map((m, i) => (
            <React.Fragment key={m.index}>
              {i > 0 && <Divider />}
              <ComponentRenderer
                metadata={m}
                filters={filters}
                onFilterChange={onFilterChange}
                refreshTick={refreshTick}
                extraActions={renderMemberActions?.(m)}
                compact
              />
            </React.Fragment>
          ))}
        </Stack>
      </Collapse>
    </Paper>
  );
};

export default InteractiveGroupCard;
