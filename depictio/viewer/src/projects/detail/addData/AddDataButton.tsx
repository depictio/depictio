import React, { useState } from 'react';
import { Button } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { ProjectListEntry } from 'depictio-react-core';
import CreateDataCollectionModal from '../CreateDataCollectionModal';
import { projectLayout, projectPipeline, projectRunFolders } from '../../layout';
import AddDataModal from './AddDataModal';

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

/** The one entry point for putting data into a project: `AddDataModal`, the
 *  same screen a new project starts from. */
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
  const [opened, setOpened] = useState(false);
  // The single-collection dialog: MultiQC reports, and one table from a URL.
  const [singleType, setSingleType] = useState<'table' | 'multiqc' | null>(null);
  const openSingle = (type: 'table' | 'multiqc') => {
    setOpened(false);
    setSingleType(type);
  };

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

  const existingNames = (
    Array.isArray(project?.workflows) ? (project?.workflows as Array<Record<string, unknown>>) : []
  ).flatMap((wf) =>
    Array.isArray(wf.data_collections)
      ? (wf.data_collections as Array<{ data_collection_tag?: unknown }>)
          .map((dc) => dc.data_collection_tag)
          .filter((t): t is string => typeof t === 'string')
      : [],
  );

  return (
    <>
      <Button
        data-testid="add-data-btn"
        size={size}
        color={color}
        leftSection={<Icon icon="mdi:plus" width={16} />}
        disabled={!canMutate}
        title={canMutate ? 'Add data to this project' : disabledReason}
        onClick={() => {
          onOpen?.();
          setOpened(true);
        }}
      >
        Add data
      </Button>
      <AddDataModal
        opened={opened}
        projectId={projectId}
        project={project}
        existingNames={existingNames}
        takesRuns={isPipelineProject}
        pipelineLabel={pipeline ? `${pipeline.name}${pipeline.version ? ` ${pipeline.version}` : ''}` : null}
        onClose={() => setOpened(false)}
        onAdded={onAdded}
        onMultiqc={() => openSingle('multiqc')}
        onSingleUrl={() => openSingle('table')}
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
    </>
  );
};

export default AddDataButton;
