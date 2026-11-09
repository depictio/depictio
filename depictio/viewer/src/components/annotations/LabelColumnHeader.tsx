import React from 'react';
import { ActionIcon, Group, Menu, Text, Tooltip } from '@mantine/core';
import { Icon } from '@iconify/react';

/** What a label column's header can do; the panel supplies it per column. */
export interface LabelColumnActions {
  name: string;
  active: boolean;
  local: boolean;
  /** Why this column cannot drive the comparison, or null. */
  compareBlocked: string | null;
  /** Offered for a local column of an account that stores annotations. */
  canKeepOnAccount: boolean;
  /** Why this column cannot be written to the table, or null. */
  saveBlocked: string | null;
  onCompare: () => void;
  onRename: () => void;
  onKeepOnAccount: () => void;
  onSaveToTable: () => void;
  onDelete: () => void;
}

/**
 * AG Grid header of a label column: a tag icon (a screen for a label kept in
 * this browser), the name, a dot on the compared column, and a menu holding
 * every action on the column. The grid is the whole UI; nothing about a
 * column lives anywhere else.
 */
const LabelColumnHeader: React.FC<{ actions: LabelColumnActions }> = ({ actions: a }) => (
  <Group gap={6} wrap="nowrap" style={{ width: '100%', minWidth: 0 }} data-testid="label-header">
    <Tooltip
      withinPortal
      label={a.local ? 'Labels from a file, kept in this browser only' : 'Session labels'}
    >
      <Icon
        icon={a.local ? 'mdi:monitor' : 'mdi:tag-outline'}
        width={14}
        style={{ flexShrink: 0, color: 'var(--mantine-color-dimmed)' }}
      />
    </Tooltip>
    <Text size="sm" fw={600} truncate style={{ minWidth: 0 }}>
      {a.name}
    </Text>
    {a.active && (
      <Tooltip withinPortal label="Compared in the charts">
        <span
          aria-label="Compared"
          data-testid="label-compared"
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            flexShrink: 0,
            background: 'var(--mantine-primary-color-filled)',
          }}
        />
      </Tooltip>
    )}
    <Menu withinPortal position="bottom-end" shadow="md">
      <Menu.Target>
        <ActionIcon
          size="xs"
          variant="subtle"
          color="gray"
          ml="auto"
          aria-label={`${a.name} column menu`}
          data-testid={`label-menu-${a.name}`}
        >
          <Icon icon="mdi:chevron-down" width={14} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item
          leftSection={<Icon icon="mdi:chart-scatter-plot" width={14} />}
          disabled={!a.active && Boolean(a.compareBlocked)}
          onClick={a.onCompare}
        >
          {a.active ? 'Stop comparing' : 'Compare in the charts'}
          {!a.active && a.compareBlocked && (
            <Text size="xs" c="dimmed" maw={240}>
              {a.compareBlocked}
            </Text>
          )}
        </Menu.Item>
        <Menu.Item leftSection={<Icon icon="mdi:pencil-outline" width={14} />} onClick={a.onRename}>
          Rename
        </Menu.Item>
        {a.canKeepOnAccount && (
          <Menu.Item
            leftSection={<Icon icon="mdi:cloud-upload-outline" width={14} />}
            onClick={a.onKeepOnAccount}
          >
            Keep on my account
            <Text size="xs" c="dimmed" maw={240}>
              Its labels are sent to the server.
            </Text>
          </Menu.Item>
        )}
        <Menu.Item
          leftSection={<Icon icon="mdi:table-column-plus-after" width={14} />}
          disabled={Boolean(a.saveBlocked)}
          onClick={a.onSaveToTable}
        >
          Save to table
          {a.saveBlocked && (
            <Text size="xs" c="dimmed" maw={240}>
              {a.saveBlocked}
            </Text>
          )}
        </Menu.Item>
        <Menu.Divider />
        <Menu.Item
          color="red"
          leftSection={<Icon icon="mdi:trash-can-outline" width={14} />}
          onClick={a.onDelete}
        >
          Delete
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  </Group>
);

export default LabelColumnHeader;
