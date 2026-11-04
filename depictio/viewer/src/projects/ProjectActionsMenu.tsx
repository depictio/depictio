import React, { useState } from 'react';
import { ActionIcon, Menu, Tooltip } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { exportProjectZip } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';

import MigrateProjectModal from './MigrateProjectModal';
import { usePushTargets } from './usePushTargets';
import { useMigrationUi } from '../hooks/useMigrationUi';

export interface ProjectActionsMenuProps {
  project: ProjectListEntry;
  /** True when the current user is an Owner of this project, OR an admin.
   *  Edit/Delete are disabled otherwise. */
  canMutate: boolean;
  onEdit: (project: ProjectListEntry) => void;
  onDelete: (project: ProjectListEntry) => void;
  /** Visual size of the trigger button. Table rows use sm, modal headers md. */
  triggerSize?: 'sm' | 'md';
}

const ProjectActionsMenu: React.FC<ProjectActionsMenuProps> = ({
  project,
  canMutate,
  onEdit,
  onDelete,
  triggerSize = 'sm',
}) => {
  const projectId = (project._id ?? project.id) as string;
  const [exporting, setExporting] = useState(false);
  const [pushOpen, setPushOpen] = useState(false);
  // Owners and admins only; hidden when this instance has no push target or
  // hides migration.
  const migrationUi = useMigrationUi();
  const pushTargets = usePushTargets(canMutate && migrationUi);
  const canPush = canMutate && migrationUi && pushTargets.length > 0;
  const locked = !!project.published_lock;
  const mutable = canMutate && !locked;
  const lockTip = (node: React.ReactElement) =>
    locked ? (
      <Tooltip label="Read-only: editing is locked" position="left" withinPortal>
        <div>{node}</div>
      </Tooltip>
    ) : (
      node
    );

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportProjectZip(projectId);
      notifications.show({
        color: 'teal',
        title: 'Export started',
        message: `depictio_export_${projectId}.zip is downloading.`,
        autoClose: 2500,
      });
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Export failed',
        message: (err as Error).message,
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
    <Menu position="bottom-end" shadow="md" withinPortal width={230}>
      <Menu.Target>
        <ActionIcon
          variant="subtle"
          color="gray"
          size={triggerSize}
          aria-label="Project actions"
          onClick={(e) => e.stopPropagation()}
        >
          <Icon icon="tabler:dots-vertical" width={18} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        {lockTip(
          <Menu.Item
          leftSection={<Icon icon="mdi:pencil" width={14} />}
          disabled={!mutable}
          onClick={() => onEdit(project)}
        >
          Edit
        </Menu.Item>
        )}
        <Menu.Item
          leftSection={<Icon icon="mdi:export" width={14} />}
          disabled={exporting}
          onClick={handleExport}
        >
          {exporting ? 'Exporting…' : 'Export'}
        </Menu.Item>
        {canPush && (
          <Menu.Item
            leftSection={<Icon icon="mdi:transfer-up" width={14} />}
            onClick={() => setPushOpen(true)}
            data-testid="project-push-menu-item"
          >
            Migrate to another instance…
          </Menu.Item>
        )}
        <Menu.Divider />
        {lockTip(
          <Menu.Item
          color="red"
          leftSection={<Icon icon="tabler:trash" width={14} />}
          disabled={!mutable}
          onClick={() => onDelete(project)}
        >
          Delete
        </Menu.Item>
        )}
      </Menu.Dropdown>
    </Menu>
    {canPush && (
      // The modal is portalled, but React events still bubble to the table row.
      <div onClick={(e) => e.stopPropagation()}>
        <MigrateProjectModal
          opened={pushOpen}
          onClose={() => setPushOpen(false)}
          projectId={projectId}
          projectName={project.name}
        />
      </div>
    )}
    </>
  );
};

export default ProjectActionsMenu;
