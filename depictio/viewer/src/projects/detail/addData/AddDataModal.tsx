/**
 * "Add data": the screen a new project starts from, on an existing project.
 * Files, a folder, or both. A folder that holds a new run of the project's
 * pipeline is added as a run; any other folder offers its tables.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Button, Center, Group, Modal, Paper, Stack, Text, Title } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBrandAccents } from 'depictio-react-core';
import type { ProjectListEntry } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { plural } from '../../fromRun/plural';
import { DataSourceFields, FileUploadResults, uploadFiles, useDataDropzone } from '../../create/FilesDropArea';
import type { LocationMode, TableUploadOutcome } from '../../create/FilesDropArea';
import { LinkSuggestions } from '../../create/LinkSuggestions';
import { useAttachRun } from './useAttachRun';
import { isSingleFileLocation, useFolderTables } from './useFolderTables';
import { useUrlTable } from './useUrlTable';
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
}) => {
  const accent = useBrandAccents();
  const drop = useDataDropzone();
  const { dropzone, files, guesses } = drop;
  const { clear } = dropzone;
  const picker = useLocationPicker({
    opened,
    label: 'Folder or bucket',
    testIdPrefix: 'add-data-location',
  });
  // The right-hand box reads a folder, or one file from its URL.
  const [mode, setMode] = useState<LocationMode>('folder');
  const urlTable = useUrlTable({ opened });
  const folder = useFolderTables({
    opened,
    projectId,
    project,
    picker,
    // A file URL typed as a folder moves over to the URL side, carried along.
    onUseFiles: (url) => {
      urlTable.setUrl(url);
      setMode('url');
    },
  });
  // One file is never a run, whatever the project's pipeline.
  const runsApply = takesRuns && mode === 'folder' && !isSingleFileLocation(picker.trimmed);
  const run = useAttachRun({ enabled: runsApply, opened, projectId, pipelineLabel, picker, onAdded });

  const [started, setStarted] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploads, setUploads] = useState<TableUploadOutcome[]>([]);

  useEffect(() => {
    if (opened) return;
    setStarted(false);
    setUploads([]);
    setMode('folder');
    clear();
    // `clear` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const hasLocation = mode === 'folder' && picker.trimmed.length > 0;
  const hasUrl = mode === 'url' && urlTable.hasUrl;
  const addsRun = runsApply && hasLocation && run.isNewRun;
  const refusedRun = runsApply && hasLocation && !run.loading && run.refusal && folder.tableCount === 0;
  // Not a run, but its tables can still come in: said as a note, not as a
  // refusal of the whole folder.
  const tablesInstead =
    runsApply && hasLocation && !run.loading && Boolean(run.refusal?.known) && folder.tableCount > 0;

  // Nothing picked yet: both panels already say what to do, so the line under
  // the button stays empty (the button keeps the reason on hover).
  const idle = files.length === 0 && !hasLocation && !hasUrl;
  let reason: string | null = null;
  if (!projectId) reason = 'The project is not loaded yet.';
  else if (idle) {
    reason = mode === 'url' ? 'Drop files, or enter the URL of one file.' : 'Drop files, or enter a folder.';
  } else if (hasUrl) reason = urlTable.reason;
  else if (hasLocation && runsApply && run.loading) reason = 'Checking the folder.';
  else if (addsRun) reason = run.reason;
  else if (refusedRun) {
    reason = run.refusal?.known ? run.refusal.message : 'The folder could not be checked.';
  } else if (hasLocation) reason = folder.reason;

  const tables = files.length + (hasLocation && !addsRun ? folder.count : 0) + (hasUrl ? 1 : 0);
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
      await uploadFiles(
        projectId,
        files,
        [...existingNames, ...folder.tickedNames],
        setUploads,
        drop.skipCoordinates,
      );
      setUploading(false);
    }
    if (hasUrl) await urlTable.submit(projectId);
    else if (addsRun) await run.submit();
    else if (hasLocation) await folder.submit();
  };

  const busy = uploading || folder.submitting || run.submitting || urlTable.submitting;
  const done = started && !busy && !run.following;
  const uploaded = uploads.filter((u) => !u.error).length;

  const finish = () => {
    // A run reloads the project itself when its ingestion ends.
    if (uploaded > 0 || folder.ingested > 0 || (urlTable.result && !urlTable.result.error)) onAdded();
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
        // Same header as New project: this is the screen a new project adds data from.
        title={null}
        withCloseButton
        size={1160}
        centered
        padding="xl"
        overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
        aria-label="Add data"
        data-testid="add-data-modal"
      >
        <Stack gap="md">
          <Stack gap={4} align="center">
            <Center>
              <Group gap="xs">
                <Icon
                  icon="mdi:database-plus-outline"
                  width={28}
                  color={`var(--mantine-color-${accent.secondary}-6)`}
                />
                <Title
                  order={2}
                  c={accent.secondary}
                  style={{ fontFamily: 'Virgil', fontWeight: 400 }}
                >
                  Add data
                </Title>
              </Group>
            </Center>
            <Text size="sm" c="dimmed" ta="center" data-testid="add-data-intro">
              {project?.name
                ? `Add data to “${project.name}”: Depictio works out what each file or folder is.`
                : 'Depictio works out what each file or folder is.'}
            </Text>
          </Stack>
          {!started && !run.showFollow ? (
            <>
              <DataSourceFields
                drop={drop}
                submitting={busy}
                folderField={picker.field}
                folderHint={
                  takesRuns
                    ? `A folder on the server or an s3:// prefix. Another run of ${pipelineLabel ?? 'this pipeline'} is added as a run; any other folder offers its tables.`
                    : 'A folder on the server or an s3:// prefix. Its tables become collections.'
                }
                locationMode={mode}
                onLocationModeChange={setMode}
                urlField={urlTable.field}
              >
                {tablesInstead ? (
                  <Alert
                    color={accent.secondary}
                    variant="light"
                    icon={<Icon icon="mdi:information-outline" width={18} />}
                    data-testid="attach-run-tables-instead"
                    data-code={run.refusal?.code ?? undefined}
                  >
                    This folder is not a run of {pipelineLabel ?? "the project's pipeline"}, so it is not added as
                    one. Its tables can be added as data collections below.
                  </Alert>
                ) : (
                  runsApply && hasLocation && run.view
                )}
                {!addsRun && !refusedRun && hasLocation && folder.view}
                {mode === 'url' && urlTable.preview}
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
                  reason={refusedRun || (idle && projectId) ? null : reason}
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
              {urlTable.result && (
                <Alert
                  color={urlTable.result.error ? 'red' : 'teal'}
                  variant="light"
                  data-testid="add-data-url-result"
                >
                  {urlTable.result.error ?? `"${urlTable.result.name}" was added from its URL.`}
                </Alert>
              )}
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
