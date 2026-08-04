import React from 'react';
import { ActionIcon, Button, Checkbox, Divider, Group, Menu, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { ColumnDef } from '../lib/useTableColumns';

export interface ColumnPickerProps<K extends string> {
  columns: ColumnDef<K>[];
  isVisible: (key: K) => boolean;
  onToggle: (key: K) => void;
  onReset: () => void;
  isCustomized: boolean;
  /** Count of visible columns, shown on the trigger for quick feedback. */
  visibleCount?: number;
}

/**
 * Dropdown that lets the user choose which table columns to display.
 *
 * `alwaysVisible` columns are listed but rendered as disabled checkboxes so
 * it's clear *why* they can't be turned off, rather than silently omitting them.
 */
function ColumnPicker<K extends string>({
  columns,
  isVisible,
  onToggle,
  onReset,
  isCustomized,
  visibleCount,
}: ColumnPickerProps<K>) {
  return (
    <Menu shadow="md" width={260} closeOnItemClick={false} withinPortal position="bottom-end">
      <Menu.Target>
        <Tooltip label="Choose columns" withinPortal>
          <ActionIcon
            variant={isCustomized ? 'light' : 'subtle'}
            color={isCustomized ? 'orange' : 'gray'}
            aria-label="Choose columns"
          >
            <Icon icon="mdi:view-column-outline" width={16} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>
          <Group justify="space-between" wrap="nowrap">
            <span>Columns</span>
            {visibleCount !== undefined && (
              <Text size="xs" c="dimmed">
                {visibleCount}/{columns.length}
              </Text>
            )}
          </Group>
        </Menu.Label>
        <div style={{ maxHeight: 340, overflowY: 'auto' }}>
          {columns.map((col) => (
            <Menu.Item
              key={col.key}
              onClick={() => onToggle(col.key)}
              disabled={col.alwaysVisible}
            >
              <Checkbox
                size="xs"
                checked={isVisible(col.key)}
                disabled={col.alwaysVisible}
                onChange={() => onToggle(col.key)}
                onClick={(e) => e.stopPropagation()}
                label={col.description ?? col.label}
                styles={{ label: { cursor: 'pointer' } }}
              />
            </Menu.Item>
          ))}
        </div>
        <Divider my={4} />
        <Menu.Item component="div">
          <Button
            variant="subtle"
            size="compact-xs"
            fullWidth
            disabled={!isCustomized}
            onClick={onReset}
            leftSection={<Icon icon="mdi:restore" width={13} />}
          >
            Reset to defaults
          </Button>
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

export default ColumnPicker;
