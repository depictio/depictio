import React from 'react';
import { ActionIcon, Menu } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * Overlay shown in the top-right corner of each grid cell while in edit mode.
 * Provides a Mantine Menu with Edit / Duplicate / Delete actions:
 *
 *   - Edit:      navigates to the Dash stepper at /dashboard-edit/{id}/component/edit/{componentId}
 *   - Duplicate: stub for now (TODO)
 *   - Delete:    fires `onDelete` — parent is responsible for the actual API call
 *
 * Render inside any positioned (relative) parent grid cell. Hidden via the
 * `editMode` prop so the same renderer tree can be reused for read-only mode.
 */
interface GridItemEditOverlayProps {
  dashboardId: string;
  componentId: string;
  editMode: boolean;
  onDelete: (componentId: string) => void;
}

const GridItemEditOverlay: React.FC<GridItemEditOverlayProps> = ({
  dashboardId,
  componentId,
  editMode,
  onDelete,
}) => {
  if (!editMode) return null;

  const handleEdit = () => {
    window.location.assign(
      `/dashboard-edit/${dashboardId}/component/edit/${componentId}`,
    );
  };

  const handleDuplicate = () => {
    // TODO: implement duplicate (probably: clone metadata with new uuid, POST /save).
    console.warn('[GridItemEditOverlay] Duplicate not yet implemented');
  };

  const handleDelete = () => {
    onDelete(componentId);
  };

  return (
    <div
      style={{
        position: 'absolute',
        top: 4,
        right: 4,
        zIndex: 5,
      }}
    >
      <Menu position="bottom-end" withinPortal shadow="md" width={160}>
        <Menu.Target>
          <ActionIcon variant="subtle" size="sm" aria-label="Component actions">
            <Icon icon="tabler:dots-vertical" width={16} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item
            leftSection={<Icon icon="tabler:edit" width={14} />}
            onClick={handleEdit}
          >
            Edit
          </Menu.Item>
          <Menu.Item
            leftSection={<Icon icon="tabler:copy" width={14} />}
            onClick={handleDuplicate}
          >
            Duplicate
          </Menu.Item>
          <Menu.Divider />
          <Menu.Item
            color="red"
            leftSection={<Icon icon="tabler:trash" width={14} />}
            onClick={handleDelete}
          >
            Delete
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </div>
  );
};

export default GridItemEditOverlay;
