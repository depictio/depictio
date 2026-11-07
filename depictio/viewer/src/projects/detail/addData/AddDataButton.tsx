import React, { useState } from 'react';
import { Button, Menu, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { ProjectListEntry } from 'depictio-react-core';
import CreateDataCollectionModal from '../CreateDataCollectionModal';
import { projectLayout, projectPipeline, projectRunFolders } from '../../layout';
import FilesModal from './FilesModal';
import AttachRunModal from './AttachRunModal';
import FolderTablesModal from './FolderTablesModal';

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
  project,
  canMutate,
  onAdded,
  onOpen,
  disabledReason = 'Owner permission required',
  size = 'xs',
  color,
}) => {
  const [filesOpened, setFilesOpened] = useState(false);
  // The single-collection dialog: MultiQC reports, and one table from a URL.
  const [singleType, setSingleType] = useState<'table' | 'multiqc' | null>(null);
  const [folderOpened, setFolderOpened] = useState(false);
  const [runOpened, setRunOpened] = useState(false);

  // "Add a run" only makes sense for a project made from a pipeline: one with
  // real workflows and the origin the server checks a new run against.
  // The server only takes another run for a project made from a folder on its
  // own disk: not one read from an s3:// location.
  const runFolderIsS3 = /^s3:\/\//i.test(projectRunFolders(project)[0] ?? '');
  const isPipelineProject =
    Boolean(project?.template_origin) &&
    projectLayout(project).realWorkflows.length > 0 &&
    !runFolderIsS3;
  const pipeline = isPipelineProject ? projectPipeline(project) : null;
  const pipelineName = pipeline?.name ?? 'this pipeline';

  const existingNames = (
    Array.isArray(project?.workflows) ? (project?.workflows as Array<Record<string, unknown>>) : []
  ).flatMap((wf) =>
    Array.isArray(wf.data_collections)
      ? (wf.data_collections as Array<{ data_collection_tag?: unknown }>)
          .map((dc) => dc.data_collection_tag)
          .filter((t): t is string => typeof t === 'string')
      : [],
  );

  const items: AddDataItem[] = [
    {
      key: 'files',
      label: 'Files',
      description: 'Upload one or several tables (CSV, TSV, Parquet).',
      icon: 'mdi:file-upload-outline',
      testId: 'add-data-files',
      onSelect: () => {
        onOpen?.();
        setFilesOpened(true);
      },
    },
    {
      key: 'folder',
      label: 'From a folder or bucket',
      description: 'Pick tables in a folder, an s3:// location or a URL.',
      icon: 'mdi:folder-outline',
      testId: 'add-data-folder',
      onSelect: () => {
        onOpen?.();
        setFolderOpened(true);
      },
    },
    {
      key: 'multiqc',
      label: 'MultiQC report',
      description: 'Upload a multiqc.parquet file or a folder of runs.',
      icon: 'mdi:chart-box-outline',
      testId: 'add-data-multiqc',
      onSelect: () => {
        onOpen?.();
        setSingleType('multiqc');
      },
    },
    ...(isPipelineProject
      ? [
          {
            key: 'run',
            label: 'Add a run',
            description: `Another output folder of ${pipelineName}. Checked against this project's pipeline before it is added.`,
            icon: 'mdi:flag-outline',
            testId: 'add-data-run',
            onSelect: () => {
              onOpen?.();
              setRunOpened(true);
            },
          } as AddDataItem,
        ]
      : []),
  ];

  return (
    <>
      <Menu
        position="bottom-end"
        withinPortal
        middlewares={{ flip: true, shift: true }}
        disabled={!canMutate} shadow="md" width={320}>
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
        <Menu.Dropdown style={{ maxHeight: 'calc(100vh - 96px)', overflowY: 'auto' }}>
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
      <FilesModal
        opened={filesOpened}
        projectId={projectId}
        existingNames={existingNames}
        onClose={() => setFilesOpened(false)}
        onAdded={onAdded}
      />
      <CreateDataCollectionModal
        opened={singleType !== null}
        projectId={projectId}
        initialType={singleType ?? 'table'}
        title={singleType === 'multiqc' ? 'Add a MultiQC report' : undefined}
        onClose={() => setSingleType(null)}
        onSuccess={() => {
          setSingleType(null);
          onAdded();
        }}
      />
      <FolderTablesModal
        opened={folderOpened}
        projectId={projectId}
        project={project}
        onClose={() => setFolderOpened(false)}
        onAdded={onAdded}
        onUseFiles={() => {
          setFolderOpened(false);
          setSingleType('table');
        }}
      />
      {isPipelineProject && (
        <AttachRunModal
          opened={runOpened}
          projectId={projectId}
          projectName={project?.name ?? null}
          pipelineLabel={pipeline ? `${pipeline.name}${pipeline.version ? ` ${pipeline.version}` : ''}` : null}
          onClose={() => setRunOpened(false)}
          onAdded={onAdded}
        />
      )}
    </>
  );
};

export default AddDataButton;
