/** One section in the manager's list: what it looks like, and what it holds. */
import React from 'react';
import { ActionIcon, Badge, Group, Paper, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';
import { SectionIcon } from 'depictio-react-core';
import type { FilterSectionSpec } from 'depictio-react-core';

export interface SectionRowProps {
  spec: FilterSectionSpec;
  memberCount: number;
  canMoveUp: boolean;
  canMoveDown: boolean;
  /** True when the other namespace declares a section with the same name. */
  sharedName: boolean;
  onMove: (dir: 'up' | 'down') => void;
  onEdit: () => void;
  onDelete: () => void;
}

const SectionRow: React.FC<SectionRowProps> = ({
  spec,
  memberCount,
  canMoveUp,
  canMoveDown,
  sharedName,
  onMove,
  onEdit,
  onDelete,
}) => (
  <Paper withBorder radius="md" p="xs">
    <Group gap="sm" wrap="nowrap">
      <SectionIcon spec={spec} size={18} fallbackIcon="mdi:shape-outline" />

      <div style={{ flex: 1, minWidth: 0 }}>
        <Group gap="xs" wrap="nowrap">
          <Text size="sm" fw={600} truncate>
            {spec.name}
          </Text>
          {spec.collapsed && (
            <Tooltip label="Starts collapsed for first-time visitors" withArrow>
              <Badge size="xs" variant="default">
                folded
              </Badge>
            </Tooltip>
          )}
          {spec.persistent && (
            <Tooltip
              label="Shown on every tab of this dashboard; filter values set in it survive tab switches"
              withArrow
              multiline
              w={260}
            >
              <Badge size="xs" variant="light">
                every tab
              </Badge>
            </Tooltip>
          )}
          {sharedName && (
            <Tooltip
              label="The other tab has a section with this name. They are separate — renaming one leaves the other alone."
              withArrow
              multiline
              w={260}
            >
              <Badge size="xs" variant="light" color="gray">
                name reused
              </Badge>
            </Tooltip>
          )}
        </Group>
        <Text size="xs" c="dimmed" truncate>
          {memberCount} component{memberCount === 1 ? '' : 's'}
          {spec.description ? ` · ${spec.description}` : ''}
        </Text>
      </div>

      <Group gap={2} wrap="nowrap">
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          aria-label={`Move ${spec.name} up`}
          disabled={!canMoveUp}
          onClick={() => onMove('up')}
        >
          <Icon icon="mdi:chevron-up" width={16} />
        </ActionIcon>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          aria-label={`Move ${spec.name} down`}
          disabled={!canMoveDown}
          onClick={() => onMove('down')}
        >
          <Icon icon="mdi:chevron-down" width={16} />
        </ActionIcon>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="sm"
          aria-label={`Edit ${spec.name}`}
          onClick={onEdit}
        >
          <Icon icon="mdi:pencil" width={16} />
        </ActionIcon>
        <ActionIcon
          variant="subtle"
          color="red"
          size="sm"
          aria-label={`Delete ${spec.name}`}
          onClick={onDelete}
        >
          <Icon icon="mdi:trash-can-outline" width={16} />
        </ActionIcon>
      </Group>
    </Group>
  </Paper>
);

export default SectionRow;
