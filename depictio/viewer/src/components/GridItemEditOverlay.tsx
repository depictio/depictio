import React from 'react';
import { ActionIcon, Menu } from '@mantine/core';
import { Icon } from '@iconify/react';

/**
 * The Dash editor (component add/edit pages) lives on a separate port from the
 * FastAPI-served React SPA. In dev: 5122 (Dash) vs 8122 (FastAPI). Build the
 * absolute URL so cross-port navigation works. In prod (single-origin reverse
 * proxy) the env var is empty and we fall back to current origin.
 */
function dashOrigin(): string {
  const env = (import.meta as unknown as { env?: Record<string, string> }).env;
  if (env?.VITE_DASH_ORIGIN) return env.VITE_DASH_ORIGIN.replace(/\/$/, '');
  if (
    typeof window !== 'undefined' &&
    window.location.hostname &&
    window.location.port === '8122'
  ) {
    return `${window.location.protocol}//${window.location.hostname}:5122`;
  }
  return '';
}

/**
 * Edit menu rendered as a chrome action icon (passed via the
 * `extraActions` slot on `ComponentChrome`). Sits inside the same hover
 * cluster as metadata/fullscreen/download/reset — single z-index, single
 * hover state, no overlap with the input widget. Provides a Mantine Menu
 * with Edit / Duplicate / Delete actions:
 *
 *   - Edit:      navigates to the Dash stepper at /dashboard-edit/{id}/component/edit/{componentId}
 *   - Duplicate: fires `onDuplicate` — parent clones metadata + layout, POSTs /save
 *   - Delete:    fires `onDelete` — parent is responsible for the actual API call
 *
 * Hidden via the `editMode` prop so the same renderer tree can be reused for
 * read-only mode.
 */
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
}

const GridItemEditOverlay: React.FC<GridItemEditOverlayProps> = ({
  dashboardId,
  componentId,
  editMode,
  onDelete,
  onDuplicate,
}) => {
  if (!editMode) return null;

  const handleEdit = () => {
    window.location.assign(
      `${dashOrigin()}/dashboard-edit/${dashboardId}/component/edit/${componentId}`,
    );
  };

  const handleDuplicate = () => {
    onDuplicate?.(componentId);
  };

  const handleDelete = () => {
    onDelete(componentId);
  };

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
        {onDuplicate && (
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
