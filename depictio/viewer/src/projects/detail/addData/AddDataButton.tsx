import React, { useState } from 'react';
import { Button, Menu, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { ProjectListEntry } from 'depictio-react-core';
import CreateDataCollectionModal from '../CreateDataCollectionModal';

export interface AddDataItem {
  key: string;
  label: string;
  description: string;
  icon: string;
  testId: string;
  /** Called when the item is picked; opens whatever dialog it owns. */
  onSelect: () => void;
}

interface AddDataButtonProps {
  projectId: string | null;
  project?: ProjectListEntry | null;
  canMutate: boolean;
  /** Called after data was added, to reload the project. */
  onAdded: () => void;
  /** Called when a dialog opens (the page expands the collections list). */
  onOpen?: () => void;
  /** Reason shown when the button is disabled. */
  disabledReason?: string;
  size?: 'xs' | 'sm' | 'md';
  color?: string;
}

/** The one entry point for putting data into a project. Each way of adding
 *  data is an item below; a new one is one more entry in `items`. */
export const AddDataButton: React.FC<AddDataButtonProps> = ({
  projectId,
  canMutate,
  onAdded,
  onOpen,
  disabledReason = 'Owner permission required',
  size = 'xs',
  color,
}) => {
  const [filesOpened, setFilesOpened] = useState(false);

  const items: AddDataItem[] = [
    {
      key: 'files',
      label: 'Files',
      description: 'Upload a table (CSV, TSV, Parquet) or a MultiQC report.',
      icon: 'mdi:file-upload-outline',
      testId: 'add-data-files',
      onSelect: () => {
        onOpen?.();
        setFilesOpened(true);
      },
    },
  ];

  return (
    <>
      <Menu position="bottom-end" withinPortal disabled={!canMutate} shadow="md" width={320}>
        <Menu.Target>
          <Button
            data-testid="add-data-btn"
            size={size}
            color={color}
            leftSection={<Icon icon="mdi:plus" width={16} />}
            rightSection={<Icon icon="mdi:chevron-down" width={16} />}
            disabled={!canMutate}
            title={canMutate ? 'Add data to this project' : disabledReason}
          >
            Add data
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          {items.map((item) => (
            <Menu.Item
              key={item.key}
              data-testid={item.testId}
              leftSection={<Icon icon={item.icon} width={18} />}
              onClick={item.onSelect}
            >
              <Text size="sm" fw={500}>
                {item.label}
              </Text>
              <Text size="xs" c="dimmed" style={{ whiteSpace: 'normal' }}>
                {item.description}
              </Text>
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>
      <CreateDataCollectionModal
        opened={filesOpened}
        projectId={projectId}
        onClose={() => setFilesOpened(false)}
        onSuccess={() => {
          setFilesOpened(false);
          onAdded();
        }}
      />
    </>
  );
};

export default AddDataButton;
