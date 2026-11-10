/**
 * The pieces every way of putting data in a project shares: the drop zone,
 * which takes every kind of file a collection can hold (`fileKinds.ts`), the
 * screen holding it next to a folder field, what was found in the dropped
 * files, and their upload. Used when a
 * project is created (`fromRun/RunFolderTab.tsx`) and by "Add data" on a
 * project page (`detail/addData/AddDataModal.tsx`), so the two are one gesture.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Alert, Box, Divider, Flex, Group, Input, Loader, Paper, ScrollArea, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  createAssetDataCollection,
  createDataCollectionFromUpload,
  createMultiQCDataCollection,
} from 'depictio-react-core';

import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useListingAccents } from '../../lib/useListingAccents';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';
import { DcTypeIcon } from '../dcTypeIcon';
import { FoundCard, SourceValue } from '../detail/FoundCard';
import { ACCEPTED_EXTENSIONS, identifyFile, kindsText } from './fileKinds';
import type { FileGuess, FileKind } from './fileKinds';
import { plural } from '../fromRun/plural';
import { SourceSection } from './SourceSection';
import { baseName, columnsText, readColumns, stemOf } from './tableFiles';

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

export interface TableUploadOutcome {
  file: File;
  /** The new collection; null when the upload failed. */
  dataCollectionId: string | null;
  error: string | null;
}

/** A report's file must be named `multiqc.parquet` for the server to take it. */
function asMultiqcFile(file: File): File {
  if (baseName(file.name) === 'multiqc.parquet') return file;
  const slash = file.name.replace(/\\/g, '/').lastIndexOf('/');
  return new File([file], `${slash >= 0 ? file.name.slice(0, slash + 1) : ''}multiqc.parquet`);
}

/** Upload `files` to `projectId`, each as the kind it was identified as, in
 *  order. A file that fails is reported on its own and the others still go.
 *  MultiQC reports make one collection, and so do images: they are read
 *  together. */
export async function uploadFiles(
  projectId: string,
  files: File[],
  taken: string[] = [],
  onProgress?: (outcomes: TableUploadOutcome[]) => void,
): Promise<TableUploadOutcome[]> {
  const guesses = await Promise.all(files.map(identifyFile));
  const members = (kind: FileKind) => files.filter((_, i) => guesses[i].kind === kind);
  const names = collectionNames(files, taken);
  // Against the names of the files that keep one: a report's own stem is free.
  const kept = names.filter((_, i) => guesses[i].kind !== 'multiqc' && guesses[i].kind !== 'image');
  const groupName = (stem: string): string => collectionNames([new File([], stem)], [...taken, ...kept])[0];

  const groups = new Map<FileKind, Promise<string | null>>();
  const uploadGroup = (kind: FileKind): Promise<string | null> => {
    let group = groups.get(kind);
    if (!group) {
      group = (
        kind === 'multiqc'
          ? createMultiQCDataCollection({
              projectId,
              name: groupName('multiqc'),
              description: '',
              files: members('multiqc').map(asMultiqcFile),
            })
          : createAssetDataCollection({ projectId, name: groupName('images'), kind: 'image', files: members('image') })
      ).then((r) => r.data_collection_id ?? null);
      groups.set(kind, group);
    }
    return group;
  };

  const outcomes: TableUploadOutcome[] = [];
  for (let i = 0; i < files.length; i += 1) {
    const file = files[i];
    const { kind, table } = guesses[i];
    try {
      let dataCollectionId: string | null;
      if (kind === 'multiqc' || kind === 'image') {
        dataCollectionId = await uploadGroup(kind);
      } else if (kind === 'geojson' || kind === 'phylogeny') {
        const made = await createAssetDataCollection({ projectId, name: names[i], kind, files: [file] });
        dataCollectionId = made.data_collection_id ?? null;
      } else if (table) {
        const made = await createDataCollectionFromUpload({
          projectId,
          name: names[i],
          description: '',
          dataType: 'table',
          fileFormat: table.fileFormat,
          separator: table.separator,
          compression: table.compression,
          hasHeader: true,
          file,
        });
        dataCollectionId = made.data_collection_id ?? null;
      } else {
        throw new Error('Depictio cannot read this file.');
      }
      outcomes.push({ file, dataCollectionId, error: null });
    } catch (err) {
      outcomes.push({ file, dataCollectionId: null, error: (err as Error).message || 'Upload failed.' });
    }
    onProgress?.([...outcomes]);
  }
  return outcomes;
}

type FolderDropzone = ReturnType<typeof useFolderDropzone>;

/** Dropped files, sorted by name and sorted out: `files` can be added,
 *  `rejected` cannot. */
export interface DataDrop {
  dropzone: FolderDropzone;
  files: File[];
  rejected: File[];
  guesses: Map<File, FileGuess>;
}

/** System files a dropped folder brings along. */
const isHidden = (file: File): boolean => baseName(file.name).startsWith('.');

/** The drop zone's state: every file is identified once it arrives. */
export function useDataDropzone(): DataDrop {
  const dropzone = useFolderDropzone({ maxPerFile: MAX_FILE_BYTES });
  const [guesses, setGuesses] = useState<Map<File, FileGuess>>(new Map());
  const sorted = useMemo(
    () => sortFilesByName(dropzone.files.filter((f) => !isHidden(f))),
    [dropzone.files],
  );

  useEffect(() => {
    let cancelled = false;
    const missing = sorted.filter((f) => !guesses.has(f));
    if (missing.length === 0) return undefined;
    Promise.all(missing.map(async (f) => [f, await identifyFile(f)] as const)).then((read) => {
      if (cancelled) return;
      setGuesses((prev) => new Map([...prev, ...read]));
    });
    return () => {
      cancelled = true;
    };
  }, [sorted, guesses]);

  const files = useMemo(
    () => sorted.filter((f) => guesses.has(f) && guesses.get(f)?.kind !== 'unknown'),
    [sorted, guesses],
  );
  const rejected = useMemo(() => sorted.filter((f) => guesses.get(f)?.kind === 'unknown'), [sorted, guesses]);
  return { dropzone, files, rejected, guesses };
}

/** The icon heading the drop zone and the folder box, in the project colour. */
const SourceBoxIcon: React.FC<{ icon: string }> = ({ icon }) => {
  const accent = useListingAccents('projects');
  return <Icon icon={icon} width={28} color={`var(--mantine-color-${accent.secondary}-6)`} />;
};

const FileRow: React.FC<{
  file: File;
  guess: FileGuess | undefined;
  index: number;
  submitting: boolean;
  onRemove: () => void;
}> = ({ file, guess, index, submitting, onRemove }) => (
  <Paper withBorder p="xs" radius="sm" data-testid={`files-item-${index}`} data-kind={guess?.kind}>
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
        <DcTypeIcon type={guess?.kind} withTooltip={false} />
        <Stack gap={0} style={{ minWidth: 0 }}>
          <Text size="sm" lineClamp={1}>
            {baseName(file.name)}
          </Text>
          <Text size="xs" c="dimmed">
            {guess?.label}
          </Text>
        </Stack>
      </Group>
      <Group gap={4} wrap="nowrap">
        <Text size="xs" c="dimmed">
          {sizeText(file.size)}
        </Text>
        <ActionIcon
          size="xs"
          variant="subtle"
          color="red"
          onClick={onRemove}
          disabled={submitting}
          aria-label="Remove file"
        >
          <Icon icon="mdi:close" width={14} />
        </ActionIcon>
      </Group>
    </Group>
  </Paper>
);

/** The drop zone, its warnings and the list of dropped files. */
export const FilesDropArea: React.FC<{ drop: DataDrop; submitting: boolean }> = ({ drop, submitting }) => {
  const { dropzone, files, rejected, guesses } = drop;
  const count = (kind: FileKind) => files.filter((f) => guesses.get(f)?.kind === kind).length;
  return (
    <Stack gap="md">
      <div ref={dropzone.rootRef}>
        <UnstyledDropZone
          onClick={() => !submitting && dropzone.openPicker()}
          disabled={submitting}
          active={dropzone.isDragOver}
          style={{ minHeight: SOURCE_BOX_HEIGHT, padding: '16px 20px' }}
          data-testid="files-dropzone"
        >
          <Stack gap={4} align="center">
            <SourceBoxIcon icon="mdi:tray-arrow-up" />
            <Text fw={500}>Drop files or folders here</Text>
            <Text size="xs" c="dimmed" ta="center">
              Tables, MultiQC reports, phylogenetic trees, GeoJSON maps and images, recognised
              automatically
            </Text>
            <Text size="xs" c="dimmed">
              or click to browse · max 50 MB each
            </Text>
          </Stack>
        </UnstyledDropZone>
        <input
          ref={dropzone.inputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.map((e) => `.${e}`).join(',')}
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
      {files.length > 0 && (
        <ScrollArea.Autosize mah={320} type="auto" offsetScrollbars>
          <Stack gap="xs">
            {files.map((f, i) => (
              <FileRow
                key={`${f.name}-${i}`}
                file={f}
                guess={guesses.get(f)}
                index={i}
                submitting={submitting}
                onRemove={() => dropzone.removeFile(f)}
              />
            ))}
          </Stack>
        </ScrollArea.Autosize>
      )}
      {count('multiqc') > 1 && (
        <Text size="xs" c="dimmed" data-testid="files-multiqc-together">
          The {count('multiqc')} MultiQC reports become one collection.
        </Text>
      )}
      {count('image') > 1 && (
        <Text size="xs" c="dimmed" data-testid="files-images-together">
          The {count('image')} images become one collection.
        </Text>
      )}
      {rejected.length > 0 && (
        <Stack gap={2} data-testid="files-skipped">
          <Text size="xs" fw={600}>
            Will not be added
          </Text>
          {rejected.map((f, i) => (
            <Text size="xs" c="dimmed" key={`${f.name}-${i}`}>
              {baseName(f.name)}: {guesses.get(f)?.label}
            </Text>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

/** Two boxes of one height, so the two ways in read as equals. */
const SOURCE_BOX_HEIGHT = 200;

/** The one screen for giving Depictio data: files beside a folder, either or both. */
export const DataSourceFields: React.FC<{
  drop: DataDrop;
  submitting: boolean;
  /** The input of the folder or bucket. */
  folderField: React.ReactNode;
  /** One line under the folder box's title. */
  folderHint: string;
  /** Whatever reading the folder shows under it. */
  children?: React.ReactNode;
}> = ({ drop, submitting, folderField, folderHint, children }) => (
  <Flex direction={{ base: 'column', sm: 'row' }} gap="md" data-testid="data-source-fields">
    <Input.Wrapper label="Files" description="From your computer" style={{ flex: 1, minWidth: 0 }}>
      <Box mt={4}>
        <FilesDropArea drop={drop} submitting={submitting} />
      </Box>
    </Input.Wrapper>
    <Stack gap={6} align="center" visibleFrom="sm" data-testid="data-source-or">
      <Divider orientation="vertical" style={{ flex: 1, alignSelf: 'center' }} />
      <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
        and / or
      </Text>
      <Divider orientation="vertical" style={{ flex: 1, alignSelf: 'center' }} />
    </Stack>
    <Divider hiddenFrom="sm" label="and / or" labelPosition="center" />
    <Input.Wrapper
      label="Folder or bucket"
      description="Read where it is, nothing to upload"
      style={{ flex: 1, minWidth: 0 }}
    >
      <Stack gap="md" mt={4}>
        <Stack
          gap="xs"
          justify="center"
          p="md"
          mih={SOURCE_BOX_HEIGHT}
          style={{
            border: '2px dashed var(--mantine-color-default-border)',
            borderRadius: 8,
          }}
          data-testid="folder-box"
        >
          <Stack gap={4} align="center">
            <SourceBoxIcon icon="mdi:folder-search-outline" />
            <Text fw={500}>Point to a folder or bucket</Text>
            <Text size="xs" c="dimmed" ta="center">
              {folderHint}
            </Text>
          </Stack>
          {folderField}
        </Stack>
        {children}
      </Stack>
    </Input.Wrapper>
  </Flex>
);

/** Each dropped file and how its upload went: pending until `uploads` holds it. */
export const FileUploadResults: React.FC<{
  files: File[];
  uploads: TableUploadOutcome[];
  testIdPrefix: string;
}> = ({ files, uploads, testIdPrefix }) => (
  <Stack gap="xs">
    {files.map((f, i) => {
      const outcome = uploads[i];
      return (
        <Group
          key={`${f.name}-${i}`}
          gap="xs"
          wrap="nowrap"
          align="flex-start"
          data-testid={`${testIdPrefix}-${i}`}
          data-status={!outcome ? 'pending' : outcome.error ? 'failed' : 'created'}
        >
          {!outcome ? (
            <Loader size={14} mt={3} />
          ) : (
            <ThemeIcon variant="light" size="sm" radius="xl" color={outcome.error ? 'red' : 'green'}>
              <Icon icon={outcome.error ? 'mdi:alert-circle' : 'mdi:check'} width={12} />
            </ThemeIcon>
          )}
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Text size="sm" ff="monospace" style={{ wordBreak: 'break-all' }}>
              {baseName(f.name)}
            </Text>
            {outcome?.error && (
              <Text size="xs" c="red">
                {outcome.error}
              </Text>
            )}
          </Stack>
        </Group>
      );
    })}
  </Stack>
);

/** The dropped files, as one source: what each one is, and the columns of
 *  the tables, read once each. */
export const FilesFoundCard: React.FC<{ drop: DataDrop; defaultOpen?: boolean }> = ({
  drop,
  defaultOpen = true,
}) => {
  const { files, guesses } = drop;
  const [columns, setColumns] = useState<Map<File, string[] | null>>(new Map());

  useEffect(() => {
    let cancelled = false;
    const missing = files.filter((f) => !columns.has(f));
    if (missing.length === 0) return undefined;
    Promise.all(missing.map(async (f) => [f, await readColumns(f)] as const)).then((read) => {
      if (cancelled) return;
      setColumns((prev) => new Map([...prev, ...read]));
    });
    return () => {
      cancelled = true;
    };
  }, [files, columns]);

  const known = files.flatMap((f) => guesses.get(f) ?? []);
  return (
    <SourceSection
      icon="mdi:tray-arrow-up"
      title="Files you dropped"
      summary={`${plural(known.length, 'file')}: ${kindsText(known)}`}
      defaultOpen={defaultOpen}
      testId="found-section-files"
    >
      <FoundCard
        embedded
        testId="files-found-card"
        rows={[
          { key: 'source', label: 'Source', value: <SourceValue kind="upload" /> },
          {
            key: 'contents',
            label: 'Contents',
            value: (
              <Stack gap={4}>
                <Text size="sm" data-testid="files-found-count">
                  {kindsText(known)}
                </Text>
                {files.map((f, i) => {
                  const cols = columns.get(f);
                  const guess = guesses.get(f);
                  return (
                    <Group gap={6} wrap="nowrap" key={`${f.name}-${i}`}>
                      <DcTypeIcon type={guess?.kind} size={14} withTooltip={false} />
                      <Text size="sm" c="dimmed" data-testid={`files-found-${i}`}>
                        {baseName(f.name)} ({cols ? columnsText(cols.length) : guess?.label})
                      </Text>
                    </Group>
                  );
                })}
              </Stack>
            ),
          },
        ]}
      />
    </SourceSection>
  );
};
