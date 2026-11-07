/**
 * "Add data > Files": drop one or several CSV, TSV or Parquet files and add
 * each as a table of this project. Same drop zone and per-file results as the
 * project creation flow (`create/FilesFlow.tsx`); the project already exists,
 * so a file that fails is reported on its own row and the others stay.
 */
import React, { useEffect, useState } from 'react';
import { Alert, Button, Group, Loader, Modal, Paper, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { plural } from '../../fromRun/plural';
import { baseName } from '../../create/tableFiles';
import { collectionNames, FilesDropArea, uploadTableFile, useTableDropzone } from '../../create/FilesFlow';

interface FilesModalProps {
  opened: boolean;
  projectId: string | null;
  /** Collection names already in the project, so new ones do not clash. */
  existingNames: string[];
  onClose: () => void;
  /** Tables were added: reload the project. */
  onAdded: () => void;
}

interface Row {
  key: string;
  label: string;
  status: 'pending' | 'created' | 'failed';
  error?: string | null;
}

export const FilesModal: React.FC<FilesModalProps> = ({
  opened,
  projectId,
  existingNames,
  onClose,
  onAdded,
}) => {
  const { dropzone, files } = useTableDropzone();
  const { clear } = dropzone;
  const [rows, setRows] = useState<Row[] | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (opened) return;
    setRows(null);
    setSubmitting(false);
    clear();
    // `clear` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  let reason: string | null = null;
  if (!projectId) reason = 'The project is not loaded yet.';
  else if (files.length === 0) reason = 'Add at least one file.';

  const submit = async () => {
    if (reason || !projectId || submitting) return;
    setSubmitting(true);
    const names = collectionNames(files, existingNames);
    const outcome: Row[] = files.map((f, i) => ({
      key: `${i}`,
      label: baseName(f.name),
      status: 'pending',
    }));
    setRows([...outcome]);
    for (let i = 0; i < files.length; i += 1) {
      try {
        await uploadTableFile(projectId, files[i], names[i]);
        outcome[i] = { ...outcome[i], status: 'created' };
      } catch (err) {
        outcome[i] = {
          ...outcome[i],
          status: 'failed',
          error: (err as Error).message || 'Upload failed.',
        };
      }
      setRows([...outcome]);
    }
    setSubmitting(false);
  };

  const done = rows !== null && !submitting;
  const added = rows?.filter((r) => r.status === 'created').length ?? 0;
  const failed = rows?.filter((r) => r.status === 'failed').length ?? 0;

  const finish = () => {
    if (added > 0) onAdded();
    onClose();
  };

  return (
    <Modal
      opened={opened}
      onClose={submitting ? () => undefined : done ? finish : onClose}
      title="Add files"
      size="lg"
      centered
      data-testid="files-modal"
    >
      <Stack gap="md">
        {rows === null ? (
          <>
            <FilesDropArea dropzone={dropzone} files={files} submitting={submitting} />
            <Stack gap={6} align="flex-end">
              <Group gap="sm">
                <Button variant="default" onClick={onClose} data-testid="files-modal-cancel">
                  Cancel
                </Button>
                <GatedButton reason={reason} onClick={submit} data-testid="files-modal-submit">
                  {files.length > 0 ? `Add ${plural(files.length, 'table')}` : 'Add tables'}
                </GatedButton>
              </Group>
              <DisabledReason reason={reason} icon="mdi:information-outline" testId="files-modal-reason" />
            </Stack>
          </>
        ) : (
          <>
            <Paper withBorder radius="md" p="md" data-testid="files-modal-results">
              <Stack gap="xs">
                {rows.map((row) => (
                  <Group
                    key={row.key}
                    gap="xs"
                    wrap="nowrap"
                    align="flex-start"
                    data-testid={`files-modal-result-${row.key}`}
                    data-status={row.status}
                  >
                    {row.status === 'pending' ? (
                      <Loader size={14} mt={3} />
                    ) : (
                      <ThemeIcon
                        variant="light"
                        size="sm"
                        radius="xl"
                        color={row.status === 'created' ? 'green' : 'red'}
                      >
                        <Icon
                          icon={row.status === 'created' ? 'mdi:check' : 'mdi:alert-circle'}
                          width={12}
                        />
                      </ThemeIcon>
                    )}
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>
                        {row.label}
                      </Text>
                      {row.error && (
                        <Text size="xs" c="red">
                          {row.error}
                        </Text>
                      )}
                    </Stack>
                  </Group>
                ))}
              </Stack>
            </Paper>
            {done && (
              <Alert
                color={failed > 0 ? 'orange' : 'green'}
                variant="light"
                data-testid="files-modal-summary"
              >
                {failed === 0
                  ? `${plural(added, 'table')} added.`
                  : `${plural(added, 'table')} added, ${failed} failed.`}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button onClick={finish} disabled={!done} data-testid="files-modal-done">
                Done
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </Modal>
  );
};

export default FilesModal;
