import React from 'react';
import { ActionIcon, Menu } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * Edit menu rendered as a chrome action icon (passed via the
 * `extraActions` slot on `ComponentChrome`). Sits inside the same hover
 * cluster as metadata/fullscreen/download/reset — single z-index, single
 * hover state, no overlap with the input widget. Provides a Mantine Menu
 * with Edit / Duplicate / Delete actions:
 *
 *   - Edit:      navigates to the React edit page at
 *                /dashboard-edit/{id}/component/edit/{componentId}
 *   - History:   fires `onOpenHistory` — opens this component across versions
 *   - Duplicate: fires `onDuplicate` — parent clones metadata + layout, POSTs /save
 *   - Delete:    fires `onDelete` — parent is responsible for the actual API call
 *
 * History lives in this menu rather than as its own hover icon because it is
 * an editing affordance: it can restore the component, and it is offered only
 * where the caller can write. A second always-visible icon would also compete
 * with the chrome cluster this one deliberately joins.
 *
 * Hidden via the `editMode` prop so the same renderer tree can be reused for
 * read-only mode.
 */
const DUPLICATABLE_COMPONENT_TYPES = new Set(['card', 'interactive', 'figure']);

interface GridItemEditOverlayProps {
  dashboardId: string;
  componentId: string;
  editMode: boolean;
  onDelete: (componentId: string) => void;
  /**
   * Optional duplicate handler. When omitted, the menu item is hidden so the
   * overlay degrades cleanly in callers that haven't wired the action yet.
   */
  onDuplicate?: (componentId: string) => void;
  /**
   * Component type from `stored_metadata`. Duplicate is only meaningful for
   * card/interactive/figure — other types (table/multiqc/text) hide the item.
   */
  componentType?: string;
  /**
   * Optional component-history handler. Hidden when absent, or when the
   * dashboard has no recorded versions — an action that can only ever open an
   * empty pane is worse than no action.
   */
  onOpenHistory?: (componentId: string) => void;
}

const GridItemEditOverlay: React.FC<GridItemEditOverlayProps> = ({
  dashboardId,
  componentId,
  editMode,
  onDelete,
  onDuplicate,
  componentType,
  onOpenHistory,
}) => {
  if (!editMode) return null;

  const handleEdit = () => {
    window.location.assign(
      `/dashboard-edit/${dashboardId}/component/edit/${componentId}`,
    );
  };

  const handleDuplicate = () => {
    onDuplicate?.(componentId);
  };

  const handleDelete = () => {
    onDelete(componentId);
  };

  const showDuplicate =
    !!onDuplicate &&
    !!componentType &&
    DUPLICATABLE_COMPONENT_TYPES.has(componentType);

  return (
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
        {onOpenHistory && (
          <Menu.Item
            leftSection={<Icon icon="mdi:history" width={14} />}
            onClick={() => onOpenHistory(componentId)}
            data-testid="component-history-action"
          >
            History
          </Menu.Item>
        )}
        {showDuplicate && (
          <Menu.Item
            leftSection={<Icon icon="tabler:copy" width={14} />}
            onClick={handleDuplicate}
          >
            Duplicate
          </Menu.Item>
        )}
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
  );
};

export default GridItemEditOverlay;
