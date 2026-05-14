import React from 'react';
import { ActionIcon, Menu } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { DashboardListEntry } from 'depictio-react-core';

export interface DashboardActionsMenuProps {
  dashboard: DashboardListEntry;
  isOwner: boolean;
  onView: (d: DashboardListEntry) => void;
  onEdit: (d: DashboardListEntry) => void;
  onDelete: (d: DashboardListEntry) => void;
  onDuplicate: (d: DashboardListEntry) => void;
  onExport: (d: DashboardListEntry) => void;
  /** Visual size of the trigger button. List/Table use compact, Card uses md. */
  triggerSize?: 'sm' | 'md';
}

const DashboardActionsMenu: React.FC<DashboardActionsMenuProps> = ({
  dashboard,
  isOwner,
  onView,
  onEdit,
  onDelete,
  onDuplicate,
  onExport,
  triggerSize = 'md',
}) => (
  <Menu position="bottom-end" shadow="md" withinPortal width={170}>
    <Menu.Target>
      <ActionIcon
        variant="subtle"
        color="gray"
        size={triggerSize}
        aria-label="Dashboard actions"
        onClick={(e) => e.stopPropagation()}
      >
        <Icon icon="tabler:dots-vertical" width={18} />
      </ActionIcon>
    </Menu.Target>
    <Menu.Dropdown>
      <Menu.Item
        leftSection={<Icon icon="mdi:eye" width={14} />}
        onClick={() => onView(dashboard)}
      >
        Open
      </Menu.Item>
      <Menu.Item
        leftSection={<Icon icon="tabler:edit" width={14} />}
        disabled={!isOwner}
        onClick={() => onEdit(dashboard)}
      >
        Edit
      </Menu.Item>
      <Menu.Item
        leftSection={<Icon icon="mdi:content-duplicate" width={14} />}
        onClick={() => onDuplicate(dashboard)}
      >
        Duplicate
      </Menu.Item>
      <Menu.Item
        leftSection={<Icon icon="mdi:download" width={14} />}
        onClick={() => onExport(dashboard)}
      >
        Export JSON
      </Menu.Item>
      <Menu.Divider />
      <Menu.Item
        color="red"
        leftSection={<Icon icon="tabler:trash" width={14} />}
        disabled={!isOwner}
        onClick={() => onDelete(dashboard)}
      >
        Delete
      </Menu.Item>
    </Menu.Dropdown>
  </Menu>
);

export default DashboardActionsMenu;
