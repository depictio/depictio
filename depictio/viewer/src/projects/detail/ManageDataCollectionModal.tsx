import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Code,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { notifications } from '@mantine/notifications';

import {
  appendMultiQCFiles,
  appendTableFiles,
  clearMultiQCDC,
  clearTableDC,
  fetchMultiQCByDataCollection,
  replaceMultiQCFiles,
  replaceTableFiles,
  type MultiQCReportSummary,
} from 'depictio-react-core';

import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';

const MAX_PER_FILE = 50 * 1024 * 1024;
const MAX_TOTAL = 500 * 1024 * 1024;

export type ManageDcType = 'multiqc' | 'table';
type Tab = 'modify' | 'clear';

interface ManageDataCollectionModalProps {
  opened: boolean;
  dcId: string;
  dcName: string;
  /** Drives backend dispatch (MultiQC vs Table endpoints) and the dropzone
   *  filter. Pass the DC's `config.type`. */
  dcType: ManageDcType;
  /** For Table DCs: the configured file format (csv/tsv/parquet/...). Used
   *  to set an extension filter on the dropzone so the user doesn't accidentally
   *  upload an incompatible file. Ignored for MultiQC. */
  tableFormat?: string | null;
  onClose: () => void;
  onSuccess: () => void;
}

const formatBytes = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

/** Derive the run-folder name from a multiqc report's stored
 *  `original_file_path`. Mirrors `_extract_multiqc_folder_name` in
 *  `depictio/api/v1/endpoints/datacollections_endpoints/utils.py` so the React
 *  Clear-tab folder list matches what the Dash modal shows for the same DC. */
function extractFolderName(originalPath: string | undefined, idx: number): string {
  if (!originalPath) return `report_${idx}`;
  const parts = originalPath.replace(/\\/g, '/').split('/').filter(Boolean);
  if (parts.length >= 3 && parts[parts.length - 2] === 'multiqc_data') {
    return parts[parts.length - 3];
  }
  if (parts.length >= 2) return parts[parts.length - 2];
  return `report_${idx}`;
}

const ManageDataCollectionModal: React.FC<ManageDataCollectionModalProps> = ({
  opened,
  dcId,
  dcName,
  dcType,
  tableFormat,
  onClose,
  onSuccess,
}) => {
  const [tab, setTab] = useState<Tab>('modify');
  const [replaceAll, setReplaceAll] = useState(false);
  const [confirmName, setConfirmName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Clear-tab summary state — fetched lazily on first switch to the Clear tab.
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summary, setSummary] = useState<{
    folders: string[];
    totalBytes: number;
  } | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const dropzoneOptions = useMemo(() => {
    if (dcType === 'multiqc') {
      return {
        filterFilename: 'multiqc.parquet',
        maxPerFile: MAX_PER_FILE,
        maxTotal: MAX_TOTAL,
      };
    }
    const fmt = (tableFormat || '').toLowerCase();
    // Map the DC's configured format to the set of accepted browser
    // extensions. Permissive (e.g. csv accepts both `.csv` and `.tsv`) —
    // backend re-parses anyway.
    const exts = fmt
      ? {
          csv: ['csv', 'txt'],
          tsv: ['tsv', 'txt'],
          parquet: ['parquet'],
          feather: ['feather', 'arrow', 'ipc'],
          xls: ['xls'],
          xlsx: ['xlsx'],
        }[fmt]
      : undefined;
    return {
      filterExtensions: exts,
      maxPerFile: MAX_PER_FILE,
      maxTotal: MAX_TOTAL,
    };
  }, [dcType, tableFormat]);

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
  } = useFolderDropzone(dropzoneOptions);

  // Reset on open / close.
  useEffect(() => {
    if (!opened) return;
    setTab('modify');
    setReplaceAll(false);
    setConfirmName('');
    setError(null);
    setSubmitting(false);
    setSummary(null);
    setSummaryError(null);
    setSummaryLoading(false);
    clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Dropzone filter changes (different DC type) must drop stale files —
  // otherwise switching from a CSV DC to a parquet DC would carry CSVs over.
  useEffect(() => {
    clear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dcType, tableFormat]);

  // Lazy-fetch the Clear-tab folder summary the first time the user opens
  // that tab. MultiQC only — table DCs don't expose a per-folder breakdown.
  useEffect(() => {
    if (!opened || tab !== 'clear' || dcType !== 'multiqc') return;
    if (summary || summaryLoading || summaryError) return;
    setSummaryLoading(true);
    fetchMultiQCByDataCollection(dcId, 200)
      .then((res) => {
        const reports: MultiQCReportSummary[] = res.reports || [];
        const folders = reports.map((r, i) =>
          extractFolderName(r.report?.original_file_path, i),
        );
        const totalBytes = reports.reduce(
          (acc, r) => acc + (r.report?.file_size_bytes || 0),
          0,
        );
        setSummary({ folders, totalBytes });
      })
      .catch((err) => {
        setSummaryError((err as Error).message || 'Failed to load folder list.');
      })
      .finally(() => setSummaryLoading(false));
  }, [opened, tab, dcType, dcId, summary, summaryLoading, summaryError]);

  const submitLabel = useMemo(() => {
    if (tab === 'clear') return 'Clear data collection';
    return replaceAll ? 'Replace all data' : 'Append folders';
  }, [tab, replaceAll]);

  const submitColor: string | undefined = useMemo(() => {
    if (tab === 'clear') return 'red';
    if (replaceAll) return 'red';
    return undefined;
  }, [tab, replaceAll]);

  const submitIcon = tab === 'clear' ? 'mdi:database-remove' : 'mdi:cloud-upload-outline';

  const canSubmit = useMemo(() => {
    if (submitting) return false;
    if (tab === 'clear') return confirmName.trim() === dcName;
    return files.length > 0;
  }, [submitting, tab, files, confirmName, dcName]);

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      if (tab === 'clear') {
        if (dcType === 'multiqc') {
          await clearMultiQCDC(dcId, true);
        } else {
          await clearTableDC(dcId);
        }
        notifications.show({
          color: 'green',
          title: 'Data collection cleared',
          message: `All data for "${dcName}" deleted.`,
        });
      } else if (replaceAll) {
        const fn = dcType === 'multiqc' ? replaceMultiQCFiles : replaceTableFiles;
        const result = await fn(dcId, files);
        notifications.show({
          color: 'green',
          title: 'Data collection replaced',
          message: result.message || 'Replace complete.',
          autoClose: 6000,
        });
      } else {
        const fn = dcType === 'multiqc' ? appendMultiQCFiles : appendTableFiles;
        const result = await fn(dcId, files);
        notifications.show({
          color: 'green',
          title: 'Data collection updated',
          message: result.message || 'Append complete.',
          autoClose: 6000,
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
      withCloseButton
      title={null}
      size="lg"
      centered
      closeOnClickOutside={!submitting}
      closeOnEscape={!submitting}
      padding="lg"
    >
      <Stack gap="md">
        {/* Header — generic title, matches Dash. DC name surfaces inside the
            Clear tab's typed-name input rather than in the title. */}
        <Group justify="center" gap="sm">
          <Icon
            icon="mdi:database-cog"
            width={32}
            color="var(--mantine-color-teal-6)"
          />
          <Title order={3} c="teal" m={0}>
            Manage Data Collection
          </Title>
        </Group>

        <Tabs
          value={tab}
          onChange={(v) => v && setTab(v as Tab)}
          variant="default"
        >
          <Tabs.List grow>
            <Tabs.Tab value="modify" disabled={submitting}>
              Modify data
            </Tabs.Tab>
            <Tabs.Tab value="clear" disabled={submitting}>
              Clear contents
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="modify" pt="md">
            <Stack gap="md">
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

              <Switch
                label="Replace existing data"
                description="When OFF, new folders are appended. When ON, the entire DC is wiped and re-ingested."
                checked={replaceAll}
                onChange={(e) => setReplaceAll(e.currentTarget.checked)}
                disabled={submitting}
                color="red"
              />

              <Stack gap={4}>
                <Text size="sm" fw={600}>
                  File Upload
                </Text>
                <Text size="xs" c="dimmed">
                  Upload your data file(s) (max 5MB for tables; for MultiQC: drop folders
                  containing multiqc.parquet, 50MB per file, 500MB total)
                </Text>
              </Stack>

              <div ref={rootRef}>
                <UnstyledDropZone
                  onClick={() => !submitting && openPicker()}
                  disabled={submitting}
                  active={isDragOver}
                >
                  <Stack gap={4} align="center">
                    <Icon icon="mdi:cloud-upload-outline" width={32} />
                    <Text fw={500}>Drag and drop file(s) or folder(s) here, or click to select</Text>
                    <Text size="xs" c="dimmed">
                      Tables: 1 file, max 5MB | MultiQC: drop folder(s); only multiqc.parquet is extracted
                    </Text>
                  </Stack>
                </UnstyledDropZone>
                <input ref={inputRef} type="file" multiple style={{ display: 'none' }} />
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
                  Skipped {skipped.length} file{skipped.length === 1 ? '' : 's'} not matching the
                  expected format.
                </Text>
              )}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="clear" pt="md">
            <Stack gap="sm">
              {error && (
                <Alert color="red" icon={<Icon icon="mdi:alert-circle" width={18} />}>
                  {error}
                </Alert>
              )}

              <Alert color="red" variant="light" icon={<Icon icon="mdi:alert" width={18} />}>
                This will permanently delete all reports and ingested data. The DC itself, its
                name, and any links pointing to it will be preserved. This action cannot be undone.
              </Alert>

              {dcType === 'multiqc' && (
                <>
                  {summaryLoading && (
                    <Group gap="xs">
                      <Loader size="xs" />
                      <Text size="sm" c="dimmed">
                        Loading folder list…
                      </Text>
                    </Group>
                  )}
                  {summary && !summaryLoading && (
                    <>
                      <Text size="sm" fw={500}>
                        {summary.folders.length} folder{summary.folders.length === 1 ? '' : 's'} ·{' '}
                        {formatBytes(summary.totalBytes)}
                      </Text>
                      {summary.folders.length > 0 && (
                        <Code block style={{ maxHeight: 180, overflow: 'auto' }}>
                          {summary.folders.join('\n')}
                        </Code>
                      )}
                    </>
                  )}
                  {summaryError && !summaryLoading && (
                    <Text size="xs" c="dimmed">
                      Folder list unavailable ({summaryError}).
                    </Text>
                  )}
                </>
              )}

              <TextInput
                label="Type the data collection name to confirm:"
                value={confirmName}
                onChange={(e) => setConfirmName(e.currentTarget.value)}
                placeholder="data collection name"
                disabled={submitting}
                autoComplete="off"
                required
                description={
                  <Text component="span" size="xs" c="dimmed">
                    Expected: <Text component="span" ff="monospace">{dcName}</Text>
                  </Text>
                }
              />
            </Stack>
          </Tabs.Panel>
        </Tabs>

        {submitting && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              {tab === 'clear'
                ? 'Clearing…'
                : 'Processing — this can take up to a minute for large uploads.'}
            </Text>
          </Group>
        )}

        <Group justify="flex-end" mt="md" gap="xs">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color={submitColor}
            onClick={onSubmit}
            disabled={!canSubmit}
            loading={submitting}
            leftSection={<Icon icon={submitIcon} width={16} />}
          >
            {submitLabel}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default ManageDataCollectionModal;
