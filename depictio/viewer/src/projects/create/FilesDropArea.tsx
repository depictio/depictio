/**
 * The pieces every way of putting data in a project shares: the drop zone of
 * table files (CSV, TSV, Parquet), the screen holding it next to a folder
 * field, what was found in the dropped files, and their upload. Used when a
 * project is created (`fromRun/RunFolderTab.tsx`) and by "Add data" on a
 * project page (`detail/addData/AddDataModal.tsx`), so the two are one gesture.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Alert, Divider, Group, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { createDataCollectionFromUpload } from 'depictio-react-core';

import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';
import { FoundCard, SourceValue } from '../detail/FoundCard';
import { baseName, classifyTableName, columnsText, readColumns, stemOf } from './tableFiles';

const MAX_FILE_BYTES = 50 * 1024 * 1024;

const sizeText = (bytes: number): string =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

/** Files in one stable order (by name, then size) wherever they are listed. */
export function sortFilesByName(files: File[]): File[] {
  return [...files].sort(
    (a, b) =>
      baseName(a.name).localeCompare(baseName(b.name), undefined, { numeric: true, sensitivity: 'base' }) ||
      a.size - b.size,
  );
}

/** A collection name per file: the file's stem, made unique (also against
 *  `taken`, the names already in the project). */
export function collectionNames(files: File[], taken: string[] = []): string[] {
  const used = new Set(taken.map((t) => t.toLowerCase()));
  const seen = new Map<string, number>();
  return files.map((f) => {
    const stem = stemOf(f.name) || 'table';
    let n = seen.get(stem) ?? 0;
    let candidate: string;
    do {
      n += 1;
      candidate = n === 1 ? stem : `${stem}_${n}`;
    } while (used.has(candidate.toLowerCase()));
    seen.set(stem, n);
    used.add(candidate.toLowerCase());
    return candidate;
  });
}

export function formatOf(file: File): { fileFormat: string; separator: string } {
  const lower = file.name.toLowerCase();
  if (lower.endsWith('.tsv') || lower.endsWith('.tab')) return { fileFormat: 'tsv', separator: '\t' };
  if (lower.endsWith('.parquet') || lower.endsWith('.pq')) return { fileFormat: 'parquet', separator: ',' };
  return { fileFormat: 'csv', separator: ',' };
}

export interface TableUploadOutcome {
  file: File;
  /** The new collection; null when the upload failed. */
  dataCollectionId: string | null;
  error: string | null;
}

/** Upload each file as a table of `projectId`, one at a time. A file that
 *  fails is reported on its own and the others still go. */
export async function uploadTableFiles(
  projectId: string,
  files: File[],
  taken: string[] = [],
  onProgress?: (outcomes: TableUploadOutcome[]) => void,
): Promise<TableUploadOutcome[]> {
  const names = collectionNames(files, taken);
  const outcomes: TableUploadOutcome[] = [];
  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    const { fileFormat, separator } = formatOf(file);
    try {
      const result = await createDataCollectionFromUpload({
        projectId,
        name: names[i],
        description: '',
        dataType: 'table',
        fileFormat,
        separator,
        compression: 'none',
        hasHeader: true,
        file,
      });
      outcomes.push({ file, dataCollectionId: result.data_collection_id ?? null, error: null });
    } catch (err) {
      outcomes.push({ file, dataCollectionId: null, error: (err as Error).message || 'Upload failed.' });
    }
    onProgress?.([...outcomes]);
  }
  return outcomes;
}

type FolderDropzone = ReturnType<typeof useFolderDropzone>;

/** The drop zone's state; `files` is sorted by name. */
export function useTableDropzone(): { dropzone: FolderDropzone; files: File[] } {
  const dropzone = useFolderDropzone({
    filterExtensions: ['csv', 'tsv', 'tab', 'parquet', 'pq'],
    maxPerFile: MAX_FILE_BYTES,
  });
  const files = useMemo(() => sortFilesByName(dropzone.files), [dropzone.files]);
  return { dropzone, files };
}

/** The drop zone, its warnings and the list of dropped files. */
export const FilesDropArea: React.FC<{
  dropzone: FolderDropzone;
  files: File[];
  submitting: boolean;
}> = ({ dropzone, files, submitting }) => (
  <Stack gap="md">
    <div ref={dropzone.rootRef}>
      <UnstyledDropZone
        onClick={() => !submitting && dropzone.openPicker()}
        disabled={submitting}
        active={dropzone.isDragOver}
        data-testid="files-dropzone"
      >
        <Stack gap={4} align="center">
          <Icon icon="mdi:tray-arrow-up" width={28} />
          <Text fw={500}>Drop CSV, TSV or Parquet files</Text>
          <Text size="xs" c="dimmed">
            or click to browse · max 50 MB each
          </Text>
        </Stack>
      </UnstyledDropZone>
      <input
        ref={dropzone.inputRef}
        type="file"
        multiple
        accept=".csv,.tsv,.tab,.parquet,.pq"
        style={{ display: 'none' }}
        onChange={dropzone.onInputChange}
        data-testid="files-input"
      />
    </div>
    {dropzone.error && (
      <Alert color="orange" variant="light" icon={<Icon icon="mdi:alert" width={16} />}>
        {dropzone.error}
      </Alert>
    )}
    {dropzone.skipped.length > 0 && (
      <Text size="xs" c="dimmed" data-testid="files-skipped">
        Skipped {dropzone.skipped.length} file{dropzone.skipped.length === 1 ? '' : 's'} that are
        not CSV, TSV or Parquet.
      </Text>
    )}
    {files.map((f, i) => (
      <Paper withBorder p="xs" radius="sm" key={`${f.name}-${i}`} data-testid={`files-item-${i}`}>
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <Icon icon="mdi:file-outline" width={16} />
            <Text size="sm" lineClamp={1}>
              {baseName(f.name)}
            </Text>
          </Group>
          <Group gap={4} wrap="nowrap">
            <Text size="xs" c="dimmed">
              {sizeText(f.size)}
            </Text>
            <ActionIcon
              size="xs"
              variant="subtle"
              color="red"
              onClick={() => dropzone.removeFile(f)}
              disabled={submitting}
              aria-label="Remove file"
            >
              <Icon icon="mdi:close" width={14} />
            </ActionIcon>
          </Group>
        </Group>
      </Paper>
    ))}
  </Stack>
);

/** The one screen for giving Depictio data: files, a folder, or both. */
export const DataSourceFields: React.FC<{
  dropzone: FolderDropzone;
  files: File[];
  submitting: boolean;
  /** The folder field, with whatever reading the folder shows under it. */
  children: React.ReactNode;
}> = ({ dropzone, files, submitting, children }) => (
  <Stack gap="md" data-testid="data-source-fields">
    <FilesDropArea dropzone={dropzone} files={files} submitting={submitting} />
    <Divider label="and / or a folder" labelPosition="center" />
    {children}
  </Stack>
);

/** "What Depictio found" for dropped files: their columns, read once each. */
export const FilesFoundCard: React.FC<{ files: File[] }> = ({ files }) => {
  const [columns, setColumns] = useState<Map<File, string[] | null>>(new Map());

  useEffect(() => {
    let cancelled = false;
    const missing = files.filter((f) => !columns.has(f));
    if (missing.length === 0) return undefined;
    Promise.all(missing.map(async (f) => [f, await readColumns(f)] as const)).then((read) => {
      if (cancelled) return;
      setColumns((prev) => {
        const next = new Map(prev);
        for (const [f, cols] of read) next.set(f, cols);
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [files, columns]);

  return (
    <FoundCard
      testId="files-found-card"
      rows={[
        {
          key: 'source',
          label: 'Source',
          value: <SourceValue kind="upload" location={files.map((f) => f.name).join(', ') || undefined} />,
        },
        {
          key: 'contents',
          label: 'Contents',
          value: (
            <Stack gap={2}>
              <Text size="sm" data-testid="files-found-count">
                {files.length} {files.length === 1 ? 'table' : 'tables'}
              </Text>
              {files.map((f, i) => {
                const cols = columns.get(f);
                const format = classifyTableName(f.name).format;
                return (
                  <Text size="sm" c="dimmed" key={`${f.name}-${i}`} data-testid={`files-found-${i}`}>
                    {baseName(f.name)} ({cols ? columnsText(cols.length) : (format ?? 'table')})
                  </Text>
                );
              })}
            </Stack>
          ),
        },
      ]}
    />
  );
};
