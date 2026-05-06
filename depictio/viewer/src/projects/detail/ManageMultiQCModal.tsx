import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  appendMultiQCFiles,
  clearMultiQCDC,
  replaceMultiQCFiles,
} from 'depictio-react-core';

import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';

const MAX_PER_FILE = 50 * 1024 * 1024;
const MAX_TOTAL = 500 * 1024 * 1024;

interface ManageMultiQCModalProps {
  opened: boolean;
  dcId: string;
  dcName: string;
  onClose: () => void;
  onSuccess: () => void;
}

type Mode = 'modify' | 'clear';

const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

const ManageMultiQCModal: React.FC<ManageMultiQCModalProps> = ({
  opened,
  dcId,
  dcName,
  onClose,
  onSuccess,
}) => {
  const [mode, setMode] = useState<Mode>('modify');
  const [replaceAll, setReplaceAll] = useState(false);
  const [confirmName, setConfirmName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    rootRef,
    inputRef,
    files,
    totalBytes,
    isDragOver,
    error: dropError,
    skipped,
    removeFile,
    clear,
    openPicker,
  } = useFolderDropzone({
    filterFilename: 'multiqc.parquet',
    maxPerFile: MAX_PER_FILE,
    maxTotal: MAX_TOTAL,
  });

  // Reset on open / close.
  useEffect(() => {
    if (!opened) return;
    setMode('modify');
    setReplaceAll(false);
    setConfirmName('');
    setError(null);
    setSubmitting(false);
    clear();
    // Don't include `clear` in deps — it's stable but linting complains
    // either way. Effect should fire only on `opened` changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  const submitLabel = useMemo(() => {
    if (mode === 'clear') return 'Clear all reports';
    if (replaceAll) return 'Replace all files';
    return 'Append files';
  }, [mode, replaceAll]);

  const canSubmit = useMemo(() => {
    if (submitting) return false;
    if (mode === 'modify') return files.length > 0;
    return confirmName.trim() === dcName;
  }, [submitting, mode, files, confirmName, dcName]);

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      if (mode === 'modify') {
        const fn = replaceAll ? replaceMultiQCFiles : appendMultiQCFiles;
        const result = await fn(dcId, files);
        notifications.show({
          color: 'green',
          title: replaceAll ? 'MultiQC DC replaced' : 'MultiQC DC updated',
          message: result.message || 'Done.',
          autoClose: 6000,
        });
      } else {
        await clearMultiQCDC(dcId, true);
        notifications.show({
          color: 'green',
          title: 'MultiQC DC cleared',
          message: `All reports for "${dcName}" deleted.`,
        });
      }
      onSuccess();
      onClose();
    } catch (err) {
      setError((err as Error).message || 'Failed to apply changes.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      opened={opened}
      onClose={submitting ? () => {} : onClose}
      title={`Manage data — ${dcName}`}
      size="lg"
      closeOnClickOutside={!submitting}
      closeOnEscape={!submitting}
    >
      <Stack gap="md">
        <SegmentedControl
          data={[
            { label: 'Modify', value: 'modify' },
            { label: 'Clear', value: 'clear' },
          ]}
          value={mode}
          onChange={(v) => setMode(v as Mode)}
          disabled={submitting}
        />

        {error && (
          <Alert color="red" icon={<Icon icon="mdi:alert-circle" width={18} />}>
            {error}
          </Alert>
        )}
        {dropError && (
          <Alert color="orange" icon={<Icon icon="mdi:alert" width={18} />}>
            {dropError}
          </Alert>
        )}

        {mode === 'modify' && (
          <Stack gap="md">
            <Group justify="space-between" align="flex-start">
              <Switch
                label="Replace all existing files"
                description="Wipes Mongo + S3 before reprocessing the new uploads."
                checked={replaceAll}
                onChange={(e) => setReplaceAll(e.currentTarget.checked)}
                disabled={submitting}
              />
              <Text size="xs" c="dimmed">
                Per-file 50 MB · Total 500 MB · Filter: multiqc.parquet
              </Text>
            </Group>

            <div ref={rootRef}>
              <UnstyledDropZone
                onClick={() => !submitting && openPicker()}
                disabled={submitting}
                active={isDragOver}
              >
                <Stack gap={4} align="center">
                  <Icon icon="mdi:folder-upload" width={32} />
                  <Text fw={500}>
                    Drop folder(s) containing multiqc_data/multiqc.parquet
                  </Text>
                  <Text size="xs" c="dimmed">
                    or click to choose a folder
                  </Text>
                </Stack>
              </UnstyledDropZone>
              {/* Hidden input enables click-to-pick a folder. */}
              <input
                ref={inputRef}
                type="file"
                multiple
                style={{ display: 'none' }}
                // @ts-expect-error — webkitdirectory is non-standard but
                // widely supported (Chromium, Firefox, Safari).
                webkitdirectory=""
              />
            </div>

            {files.length > 0 && (
              <Paper withBorder p="xs" radius="sm">
                <Group justify="space-between" mb={4}>
                  <Text size="sm" fw={500}>
                    {files.length} file{files.length === 1 ? '' : 's'} ·{' '}
                    {formatBytes(totalBytes)}
                  </Text>
                  <Button size="xs" variant="subtle" onClick={clear} disabled={submitting}>
                    Clear list
                  </Button>
                </Group>
                <ScrollArea h={Math.min(files.length * 32, 200)}>
                  <Stack gap={2}>
                    {files.map((f, i) => (
                      <Group
                        key={`${f.name}-${i}`}
                        justify="space-between"
                        wrap="nowrap"
                        gap="xs"
                      >
                        <Text size="xs" ff="monospace" lineClamp={1}>
                          {f.name}
                        </Text>
                        <Group gap={4} wrap="nowrap">
                          <Text size="xs" c="dimmed">
                            {formatBytes(f.size)}
                          </Text>
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            color="red"
                            onClick={() => removeFile(f)}
                            disabled={submitting}
                            aria-label="Remove file"
                          >
                            <Icon icon="mdi:close" width={14} />
                          </ActionIcon>
                        </Group>
                      </Group>
                    ))}
                  </Stack>
                </ScrollArea>
              </Paper>
            )}

            {skipped.length > 0 && (
              <Text size="xs" c="dimmed">
                Skipped {skipped.length} non-multiqc file
                {skipped.length === 1 ? '' : 's'}.
              </Text>
            )}
          </Stack>
        )}

        {mode === 'clear' && (
          <Stack gap="xs">
            <Alert color="red" icon={<Icon icon="mdi:alert-octagon" width={18} />}>
              This wipes every report (Mongo + S3) for this MultiQC DC. The
              data collection itself stays — you can refill it via Modify.
            </Alert>
            <TextInput
              label={`Type "${dcName}" to confirm`}
              value={confirmName}
              onChange={(e) => setConfirmName(e.currentTarget.value)}
              placeholder={dcName}
              disabled={submitting}
              autoComplete="off"
            />
          </Stack>
        )}

        {submitting && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              {mode === 'clear'
                ? 'Clearing reports…'
                : 'Processing — this can take up to a minute for large reports.'}
            </Text>
          </Group>
        )}

        <Group justify="space-between" mt="md">
          <Badge variant="light" size="sm">
            DC id: {dcId}
          </Badge>
          <Group gap="xs">
            <Button variant="default" onClick={onClose} disabled={submitting}>
              Cancel
            </Button>
            <Button
              color={mode === 'clear' ? 'red' : undefined}
              onClick={onSubmit}
              disabled={!canSubmit}
              loading={submitting}
            >
              {submitLabel}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
};

export default ManageMultiQCModal;
