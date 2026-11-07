/**
 * "Start from my data", Files: drop CSV, TSV or Parquet files, see what
 * Depictio found in them, then create the project and one table collection
 * per file. The project is created first; a file that fails is reported on
 * its own row and the project stays.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Paper,
  Stack,
  Stepper,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { createDataCollectionFromUpload, useBrandAccents } from 'depictio-react-core';
import type { CreateProjectInput, CreateProjectResult } from 'depictio-react-core';

import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';
import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';
import { FoundCard, SourceValue } from '../detail/FoundCard';
import { baseName, classifyTableName, columnsText, readColumns, stemOf } from './tableFiles';
import { TableResults } from './TableResults';
import type { TableResultRow } from './TableResults';

const MAX_FILE_BYTES = 50 * 1024 * 1024;

const sizeText = (bytes: number): string =>
  bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

export interface FilesFlowProps {
  opened: boolean;
  existingNames: string[];
  /** Creates the project only: the dialog stays open for the uploads. */
  onCreate: (
    input: CreateProjectInput,
    options?: { keepOpen?: boolean },
  ) => Promise<CreateProjectResult>;
  /** The project is complete: leave for its page. */
  onProjectReady: (projectId: string, name: string) => void;
  submitting: boolean;
  setSubmitting: (submitting: boolean) => void;
  onBack?: () => void;
}

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

/** Upload one file as a table collection of `projectId`. */
export function uploadTableFile(projectId: string, file: File, name: string) {
  const { fileFormat, separator } = formatOf(file);
  return createDataCollectionFromUpload({
    projectId,
    name,
    description: '',
    dataType: 'table',
    fileFormat,
    separator,
    compression: 'none',
    hasHeader: true,
    file,
  });
}

/** The drop zone of table files (CSV, TSV, Parquet), shared by the project
 *  creation flow and the "Add data > Files" dialog. `files` is sorted by name. */
type FolderDropzone = ReturnType<typeof useFolderDropzone>;

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

export const FilesFlow: React.FC<FilesFlowProps> = ({
  opened,
  existingNames,
  onCreate,
  onProjectReady,
  submitting,
  setSubmitting,
  onBack,
}) => {
  const accent = useBrandAccents();
  const { dropzone, files } = useTableDropzone();
  const { clear } = dropzone;
  const [step, setStep] = useState(0);
  const [projectName, setProjectName] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [columns, setColumns] = useState<Map<File, string[] | null>>(new Map());
  const [rows, setRows] = useState<TableResultRow[]>([]);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    setStep(0);
    setProjectName('');
    setIsPublic(false);
    setRows([]);
    setCreatedId(null);
    setError(null);
    clear();
    // `clear` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Read the header of each CSV or TSV file once.
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

  const names = useMemo(() => collectionNames(files), [files]);
  const trimmedName = projectName.trim();
  const nameUsed =
    trimmedName.length > 0 &&
    existingNames.some((n) => n.toLowerCase() === trimmedName.toLowerCase());
  const effectiveName = trimmedName || 'uploads';
  const effectiveNameUsed = existingNames.some(
    (n) => n.toLowerCase() === effectiveName.toLowerCase(),
  );

  let nextReason: string | null = null;
  if (files.length === 0) nextReason = 'Add at least one file.';
  let createReason: string | null = null;
  if (effectiveNameUsed) createReason = 'A project with this name already exists.';

  const createProjectWithTables = async () => {
    if (createReason || submitting) return;
    setStep(2);
    setSubmitting(true);
    setError(null);
    setCreatedId(null);
    const pending: TableResultRow[] = files.map((f, i) => ({
      key: `${i}`,
      label: baseName(f.name),
      status: 'pending',
    }));
    setRows(pending);
    let projectId: string | null = null;
    try {
      const result = await onCreate(
        {
          name: effectiveName,
          // Legacy field: the type no longer changes what a project can do.
          project_type: 'basic',
          is_public: isPublic,
        } as CreateProjectInput,
        { keepOpen: true },
      );
      projectId = result.project_id ?? null;
      if (!projectId) throw new Error(result.message || 'The project could not be created.');
      setCreatedId(projectId);
      const outcome = [...pending];
      for (let i = 0; i < files.length; i += 1) {
        const f = files[i];
        try {
          await uploadTableFile(projectId, f, names[i]);
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
      if (outcome.every((r) => r.status === 'created')) {
        onProjectReady(projectId, effectiveName);
      }
    } catch (err) {
      setError((err as Error).message || 'Failed to create the project.');
      setRows((prev) => prev.map((r) => (r.status === 'pending' ? { ...r, status: 'failed' } : r)));
    } finally {
      setSubmitting(false);
    }
  };

  const foundRows = [
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
  ];

  return (
    <Stack gap="md" data-testid="files-flow">
      <Stepper active={step} color={accent.secondary} size="sm" allowNextStepsSelect={false}>
        <Stepper.Step label="Source" description="Your files" />
        <Stepper.Step label="What Depictio found" description="Tables" />
        <Stepper.Step label="Create" description="Project and tables" />
      </Stepper>

      {step === 0 && (
        <Stack gap="md">
          <FilesDropArea dropzone={dropzone} files={files} submitting={submitting} />
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Button variant="default" onClick={() => onBack?.()} disabled={!onBack || submitting}>
              Back
            </Button>
            <Stack gap={4} align="flex-end">
              <GatedButton
                color={accent.secondary}
                reason={nextReason}
                onClick={() => setStep(1)}
                data-testid="files-next"
              >
                Next
              </GatedButton>
              <DisabledReason reason={nextReason} icon="mdi:information-outline" />
            </Stack>
          </Group>
        </Stack>
      )}

      {step === 1 && (
        <Stack gap="md">
          <FoundCard rows={foundRows} testId="files-found-card" />
          <TextInput
            label="Project name"
            placeholder="uploads"
            value={projectName}
            onChange={(e) => setProjectName(e.currentTarget.value)}
            leftSection={<Icon icon="mdi:folder-outline" width={16} />}
            error={nameUsed ? 'A project with this name already exists.' : undefined}
            data-testid="files-project-name-input"
          />
          <Switch
            label="Make this project public"
            description="Anyone who can reach this server can see a public project."
            checked={isPublic}
            onChange={(e) => setIsPublic(e.currentTarget.checked)}
            data-testid="files-public-switch"
          />
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Button variant="default" onClick={() => setStep(0)} disabled={submitting}>
              Previous
            </Button>
            <Stack gap={4} align="flex-end">
              <GatedButton
                color={accent.secondary}
                reason={createReason}
                loading={submitting}
                onClick={createProjectWithTables}
                data-testid="files-create-submit"
              >
                Create project with {files.length} {files.length === 1 ? 'table' : 'tables'}
              </GatedButton>
              <DisabledReason reason={createReason} icon="mdi:information-outline" />
            </Stack>
          </Group>
        </Stack>
      )}

      {step === 2 && (
        <TableResults
          projectName={effectiveName}
          rows={rows}
          error={error}
          working={submitting}
          onOpen={createdId ? () => onProjectReady(createdId, effectiveName) : null}
        />
      )}
    </Stack>
  );
};

export default FilesFlow;
