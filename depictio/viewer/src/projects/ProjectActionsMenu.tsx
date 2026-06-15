import React, { useState } from 'react';
import {
  ActionIcon,
  Button,
  Group,
  Menu,
  Modal,
  Stack,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import { exportProjectZip, exportProjectTemplate } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';

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

  // "Save as template" modal state.
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [templateExporting, setTemplateExporting] = useState(false);
  const [version, setVersion] = useState('1.0.0');
  const [description, setDescription] = useState('');

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

  const handleSaveAsTemplate = async () => {
    setTemplateExporting(true);
    try {
      await exportProjectTemplate(projectId, {
        version: version.trim() || '1.0.0',
        description: description.trim() || undefined,
      });
      notifications.show({
        color: 'teal',
        title: 'Template ready',
        message: 'Your template bundle is downloading.',
        autoClose: 2500,
      });
      setTemplateModalOpen(false);
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Template export failed',
        message: (err as Error).message,
      });
    } finally {
      setTemplateExporting(false);
    }
  };

  return (
    <>
      <Menu position="bottom-end" shadow="md" withinPortal width={190}>
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
          <Menu.Item
            leftSection={<Icon icon="mdi:pencil" width={14} />}
            disabled={!canMutate}
            onClick={() => onEdit(project)}
          >
            Edit
          </Menu.Item>
          <Menu.Item
            leftSection={<Icon icon="mdi:export" width={14} />}
            disabled={exporting}
            onClick={handleExport}
          >
            {exporting ? 'Exporting…' : 'Export'}
          </Menu.Item>
          <Menu.Item
            leftSection={<Icon icon="mdi:cube-outline" width={14} />}
            onClick={() => setTemplateModalOpen(true)}
          >
            Save as template
          </Menu.Item>
          <Menu.Divider />
          <Menu.Item
            color="red"
            leftSection={<Icon icon="tabler:trash" width={14} />}
            disabled={!canMutate}
            onClick={() => onDelete(project)}
          >
            Delete
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>

      <Modal
        opened={templateModalOpen}
        onClose={() => setTemplateModalOpen(false)}
        title="Save project as template"
        centered
        withinPortal
      >
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            Bundles this project's configuration and dashboards into a reusable
            template (a .zip). Data is not included — file paths are
            re-parameterized to {'{DATA_ROOT}'} so a colleague can run it against
            their own data.
          </Text>
          <TextInput
            label="Version"
            placeholder="1.0.0"
            value={version}
            onChange={(e) => setVersion(e.currentTarget.value)}
          />
          <Textarea
            label="Description"
            placeholder="What this template is for (optional)"
            autosize
            minRows={2}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
          />
          <Group justify="flex-end" mt="xs">
            <Button variant="default" onClick={() => setTemplateModalOpen(false)}>
              Cancel
            </Button>
            <Button
              leftSection={<Icon icon="mdi:cube-outline" width={16} />}
              loading={templateExporting}
              onClick={handleSaveAsTemplate}
            >
              Create template
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
};

export default ProjectActionsMenu;
