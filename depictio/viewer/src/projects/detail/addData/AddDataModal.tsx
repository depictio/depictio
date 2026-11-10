/**
 * "Add data": the screen a new project starts from, on an existing project.
 * Files, a folder, or both. A folder that holds a new run of the project's
 * pipeline is added as a run; any other folder offers its tables.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Modal, Paper, Stack } from '@mantine/core';
import type { ProjectListEntry } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { plural } from '../../fromRun/plural';
import { DataSourceFields, FileUploadResults, uploadFiles, useDataDropzone } from '../../create/FilesDropArea';
import type { TableUploadOutcome } from '../../create/FilesDropArea';
import { LinkSuggestions } from '../../create/LinkSuggestions';
import { useAttachRun } from './useAttachRun';
import { useFolderTables } from './useFolderTables';
import { useLocationPicker } from './useLocationPicker';

interface AddDataModalProps {
  opened: boolean;
  projectId: string | null;
  project?: ProjectListEntry | null;
  /** Collection names already in the project, so new ones do not clash. */
  existingNames: string[];
  /** Only a project made from a pipeline, on the server's disk, takes a run. */
  takesRuns: boolean;
  /** "nf-core/rnaseq 3.14.0": the project's pipeline. */
  pipelineLabel: string | null;
  onClose: () => void;
  /** Data was added: reload the project. */
  onAdded: () => void;
  /** Leave for the single-collection dialog. */
  onSingleUrl: () => void;
}

export const AddDataModal: React.FC<AddDataModalProps> = ({
  opened,
  projectId,
  project,
  existingNames,
  takesRuns,
  pipelineLabel,
  onClose,
  onAdded,
  onSingleUrl,
}) => {
  const drop = useDataDropzone();
  const { dropzone, files, guesses } = drop;
  const { clear } = dropzone;
  const picker = useLocationPicker({
    opened,
    label: 'Folder or bucket',
    testIdPrefix: 'add-data-location',
  });
  const folder = useFolderTables({ opened, projectId, project, picker, onUseFiles: onSingleUrl });
  const run = useAttachRun({ enabled: takesRuns, opened, projectId, pipelineLabel, picker, onAdded });

  const [started, setStarted] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploads, setUploads] = useState<TableUploadOutcome[]>([]);

  useEffect(() => {
    if (opened) return;
    setStarted(false);
    setUploads([]);
    clear();
    // `clear` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const hasLocation = picker.trimmed.length > 0;
  const addsRun = takesRuns && hasLocation && run.isNewRun;
  const refusedRun = takesRuns && hasLocation && !run.loading && run.refusal && folder.tableCount === 0;

  let reason: string | null = null;
  if (!projectId) reason = 'The project is not loaded yet.';
  else if (files.length === 0 && !hasLocation) reason = 'Drop files, or enter a folder.';
  else if (hasLocation && takesRuns && run.loading) reason = 'Checking the folder.';
  else if (addsRun) reason = run.reason;
  else if (refusedRun) {
    reason = run.refusal?.known ? run.refusal.message : 'The folder could not be checked.';
  } else if (hasLocation) reason = folder.reason;

  const tables = files.length + (hasLocation && !addsRun ? folder.count : 0);
  // "Table" is the right word only while every file is one.
  const unit = files.every((f) => guesses.get(f)?.kind === 'table') ? 'table' : 'file';
  let submitLabel = 'Add data';
  if (addsRun && tables > 0) submitLabel = `Add run and ${plural(tables, unit)}`;
  else if (addsRun) submitLabel = 'Add run';
  else if (tables > 0) submitLabel = `Add ${plural(tables, unit)}`;

  const submit = async () => {
    if (reason || !projectId) return;
    setStarted(true);
    if (files.length > 0) {
      setUploading(true);
      await uploadFiles(projectId, files, [...existingNames, ...folder.tickedNames], setUploads);
      setUploading(false);
    }
    if (addsRun) await run.submit();
    else if (hasLocation) await folder.submit();
  };

  const busy = uploading || folder.submitting || run.submitting;
  const done = started && !busy && !run.following;
  const uploaded = uploads.filter((u) => !u.error).length;

  const finish = () => {
    // A run reloads the project itself when its ingestion ends.
    if (uploaded > 0 || folder.ingested > 0) onAdded();
    onClose();
  };
  const handleClose = () => {
    if (busy) return;
    if (done) finish();
    else onClose();
  };

  return (
    <>
      <Modal
        opened={opened}
        onClose={handleClose}
        title="Add data"
        size={1000}
        centered
        data-testid="add-data-modal"
      >
        <Stack gap="md">
          {!started && !run.showFollow ? (
            <>
              <DataSourceFields
                drop={drop}
                submitting={busy}
                folderField={picker.field}
                folderHint={
                  takesRuns
                    ? `A folder on the server, an s3:// location or the URL of one file. Another run of ${pipelineLabel ?? 'this pipeline'} is added as a run; any other folder offers its tables.`
                    : 'A folder on the server, an s3:// location, or the URL of one file. Its tables become collections.'
                }
              >
                {takesRuns && hasLocation && run.view}
                {!addsRun && !refusedRun && hasLocation && folder.view}
              </DataSourceFields>
              <Stack gap={6} align="flex-end">
                <Group gap="sm">
                  <Button variant="default" onClick={onClose} data-testid="add-data-cancel">
                    Cancel
                  </Button>
                  <GatedButton reason={reason} onClick={submit} data-testid="add-data-submit">
                    {submitLabel}
                  </GatedButton>
                </Group>
                <DisabledReason
                  reason={refusedRun ? null : reason}
                  icon="mdi:information-outline"
                  testId="add-data-reason"
                />
              </Stack>
            </>
          ) : (
            <>
              {files.length > 0 && (
                <Paper withBorder radius="md" p="md" data-testid="add-data-files-results">
                  <FileUploadResults files={files} uploads={uploads} testIdPrefix="add-data-file-result" />
                </Paper>
              )}
              {projectId && (
                <LinkSuggestions
                  projectId={projectId}
                  uploads={uploads}
                  ready={done}
                  testId="add-data-section-links"
                />
              )}
              {folder.resultView}
              {run.followView}
              {done && files.length > 0 && uploaded < files.length && (
                <Alert color="orange" variant="light" data-testid="add-data-files-summary">
                  {`${plural(uploaded, unit)} added, ${files.length - uploaded} failed.`}
                </Alert>
              )}
              <Group justify="flex-end">
                <Button onClick={finish} disabled={busy} data-testid="add-data-done">
                  {run.following ? 'Close' : 'Done'}
                </Button>
              </Group>
            </>
          )}
        </Stack>
      </Modal>
      {picker.browser}
    </>
  );
};

export default AddDataModal;
