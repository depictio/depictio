/**
 * The pieces every way of putting data in a project shares: the drop zone,
 * which takes every kind of file a collection can hold (`fileKinds.ts`), the
 * screen holding it next to a folder field, what was found in the dropped
 * files, and their upload. Used when a
 * project is created (`fromRun/RunFolderTab.tsx`) and by "Add data" on a
 * project page (`detail/addData/AddDataModal.tsx`), so the two are one gesture.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Alert, Box, Checkbox, Divider, Flex, Group, Loader, Paper, ScrollArea, SegmentedControl, Stack, Text, ThemeIcon } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  createAssetDataCollection,
  createDataCollectionFromUpload,
  createMultiQCDataCollection,
  setTableCoordinates,
} from 'depictio-react-core';

import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useListingAccents } from '../../lib/useListingAccents';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';
import { DcTypeIcon, GEO_COLOR, GEO_ICON } from '../dcTypeIcon';
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
  /** Added, with something to say: the map coordinates were not marked. */
  note?: string | null;
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
  /** Tables whose detected coordinates the user unticked: not marked. */
  skipCoordinates: ReadonlySet<File> = new Set(),
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
    const { kind, table, coordinates } = guesses[i];
    try {
      let dataCollectionId: string | null;
      let note: string | null = null;
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
        // Marked through the route that checks the values: a refusal keeps the
        // table and says why it is not a Map source.
        if (dataCollectionId && coordinates && !skipCoordinates.has(file)) {
          await setTableCoordinates(dataCollectionId, coordinates.latColumn, coordinates.lonColumn).catch(
            (err: Error) => {
              note = `Added without map coordinates: ${err.message}`;
            },
          );
        }
      } else {
        throw new Error('Depictio cannot read this file.');
      }
      outcomes.push({ file, dataCollectionId, error: null, note });
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
  /** Tables whose detected map coordinates the user unticked. */
  skipCoordinates: ReadonlySet<File>;
  toggleCoordinates: (file: File, use: boolean) => void;
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
  const [skipCoordinates, setSkipCoordinates] = useState<Set<File>>(new Set());
  const toggleCoordinates = (file: File, use: boolean) =>
    setSkipCoordinates((prev) => {
      const next = new Set(prev);
      if (use) next.delete(file);
      else next.add(file);
      return next;
    });
  return { dropzone, files, rejected, guesses, skipCoordinates, toggleCoordinates };
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
  useCoordinates: boolean;
  onToggleCoordinates: (use: boolean) => void;
}> = ({ file, guess, index, submitting, onRemove, useCoordinates, onToggleCoordinates }) => (
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
          {guess?.coordinates && (
            <Checkbox
              mt={4}
              size="xs"
              color={GEO_COLOR}
              checked={useCoordinates}
              onChange={(e) => onToggleCoordinates(e.currentTarget.checked)}
              disabled={submitting}
              label={
                <Group gap={4} wrap="nowrap">
                  <Icon icon={GEO_ICON} width={12} color={`var(--mantine-color-${GEO_COLOR}-6)`} />
                  <Text size="xs">
                    Geomap: <code>{guess.coordinates.latColumn}</code> /{' '}
                    <code>{guess.coordinates.lonColumn}</code>
                  </Text>
                </Group>
              }
              data-testid={`files-item-${index}-coordinates`}
            />
          )}
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
                useCoordinates={!drop.skipCoordinates.has(f)}
                onToggleCoordinates={(use) => drop.toggleCoordinates(f, use)}
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
const SOURCE_BOX_HEIGHT = 236;

/** A column's head, centred over its box: what this way in is, and one line
 *  on what it does. Both lines keep one height, so the two boxes start level. */
const SourceHeader: React.FC<{ icon: string; label: string; description: string; testId: string }> = ({
  icon,
  label,
  description,
  testId,
}) => {
  const accent = useListingAccents('projects');
  return (
    <Stack gap={2} align="center" mb="xs" data-testid={testId}>
      <Group gap={6} wrap="nowrap">
        <Icon icon={icon} width={18} color={`var(--mantine-color-${accent.secondary}-6)`} />
        <Text fw={600} size="sm">
          {label}
        </Text>
      </Group>
      <Text size="xs" c="dimmed" ta="center" mih={34}>
        {description}
      </Text>
    </Stack>
  );
};

const DASHED_BOX = {
  border: '2px dashed var(--mantine-color-default-border)',
  borderRadius: 8,
} as const;

/** The one screen for giving Depictio data: files beside a folder, either or both. */
export const DataSourceFields: React.FC<{
  drop: DataDrop;
  submitting: boolean;
  /** The input of the folder or bucket. */
  folderField: React.ReactNode;
  /** One line under the folder box's title. */
  folderHint: string;
  /** Whatever reading the folder (or the URL) shows under it. */
  children?: React.ReactNode;
  /** What is decided about the data as a whole (how a folder is read):
   *  across both boxes, under them. */
  below?: React.ReactNode;
  /** With `onLocationModeChange`, the right-hand box also takes one file at
   *  a URL instead of a folder: `urlField` is its input. */
  locationMode?: LocationMode;
  onLocationModeChange?: (mode: LocationMode) => void;
  urlField?: React.ReactNode;
}> = ({
  drop,
  submitting,
  folderField,
  folderHint,
  children,
  below,
  locationMode = 'folder',
  onLocationModeChange,
  urlField,
}) => {
  const url = Boolean(onLocationModeChange) && locationMode === 'url';
  return (
    <Stack gap="md">
      <Flex direction={{ base: 'column', sm: 'row' }} gap="md" data-testid="data-source-fields">
        <Box style={{ flex: 1, minWidth: 0 }}>
          <SourceHeader
            icon="mdi:upload-outline"
            label="Upload"
            description="Files or whole folders from your computer, copied into Depictio"
            testId="data-source-upload-head"
          />
          <FilesDropArea drop={drop} submitting={submitting} />
        </Box>
        <Stack gap={6} align="center" visibleFrom="sm" data-testid="data-source-or">
          <Divider orientation="vertical" style={{ flex: 1, alignSelf: 'center' }} />
          <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
            and / or
          </Text>
          <Divider orientation="vertical" style={{ flex: 1, alignSelf: 'center' }} />
        </Stack>
        <Divider hiddenFrom="sm" label="and / or" labelPosition="center" />
        <Box style={{ flex: 1, minWidth: 0 }}>
          <SourceHeader
            icon="mdi:eye-outline"
            label="Read in place"
            description="A folder, a bucket or a file URL, read where it is: nothing is uploaded"
            testId="data-source-place-head"
          />
          <Stack gap="md">
            {/* The mode switch sits inside the box, so this box starts level with
                the drop zone beside it. */}
            <Stack
              gap="xs"
              p="md"
              mih={SOURCE_BOX_HEIGHT}
              style={DASHED_BOX}
              data-testid={url ? 'url-box' : 'folder-box'}
            >
              {onLocationModeChange && (
                <SegmentedControl
                  fullWidth
                  size="xs"
                  value={locationMode}
                  onChange={(v) => onLocationModeChange(v as LocationMode)}
                  disabled={submitting}
                  data={[
                    { value: 'folder', label: 'Folder or bucket' },
                    { value: 'url', label: 'One file URL' },
                  ]}
                  data-testid="location-mode"
                />
              )}
              {url ? (
                <Stack gap="xs" justify="center" style={{ flex: 1 }}>
                  <Stack gap={4} align="center">
                    <SourceBoxIcon icon="mdi:link-variant" />
                    <Text fw={500}>Read one table from its URL</Text>
                    <Text size="xs" c="dimmed" ta="center">
                      An https:// or s3:// file (CSV, TSV, Parquet, Feather, gzipped or not), fetched
                      by the server: nothing goes through your browser.
                    </Text>
                  </Stack>
                  {urlField}
                </Stack>
              ) : (
                <Stack gap="xs" justify="center" style={{ flex: 1 }}>
                  <Stack gap={4} align="center">
                    <SourceBoxIcon icon="mdi:folder-search-outline" />
                    <Text fw={500}>Point to a folder or bucket to read in place</Text>
                    <Text size="xs" c="dimmed" ta="center">
                      {folderHint}
                    </Text>
                  </Stack>
                  {folderField}
                </Stack>
              )}
            </Stack>
            {children}
          </Stack>
        </Box>
      </Flex>
      {below && <Box data-testid="data-source-below">{below}</Box>}
    </Stack>
  );
};

export type LocationMode = 'folder' | 'url';

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
            {outcome?.note && (
              <Text size="xs" c="orange" data-testid={`${testIdPrefix}-${i}-note`}>
                {outcome.note}
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
