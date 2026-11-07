import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ActionIcon, Alert, Button, Group, Loader, Modal, Paper, ScrollArea, SegmentedControl, Select, SimpleGrid, Stack, Switch, Table, Tabs, Text, TextInput, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';
import { checkMultiQCUniformity, createDataCollectionFromUpload, createDataCollectionFromUrl, createMultiQCDataCollection, useBrandAccents } from 'depictio-react-core';
import type {  } from 'depictio-react-core';
import { detectCoordinatesColumns } from './extendedTableCategories';
import { DcTypeIcon, GEO_COLOR, GEO_ICON } from '../dcTypeIcon';
import { UnstyledDropZone } from '../../components/UnstyledDropZone';
import { useFolderDropzone } from '../../hooks/useFolderDropzone';

const FORMAT_OPTIONS = [
  { value: 'csv', label: 'CSV' },
  { value: 'tsv', label: 'TSV' },
  { value: 'parquet', label: 'Parquet' },
  { value: 'feather', label: 'Feather' },
];

const SEPARATOR_OPTIONS = [
  { value: ',', label: 'Comma (,)' },
  { value: '\t', label: 'Tab (\\t)' },
  { value: ';', label: 'Semicolon (;)' },
  { value: '|', label: 'Pipe (|)' },
  { value: 'custom', label: 'Custom…' },
];

const COMPRESSION_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'gzip', label: 'gzip' },
  { value: 'zip', label: 'zip' },
  { value: 'bz2', label: 'bz2' },
];

type MultiQCMismatchKind = 'modules' | 'plots' | 'version' | 'samples';
type MultiQCMismatch = {
  code: 'multiqc_report_mismatch';
  kind: MultiQCMismatchKind;
  summary: string;
  details: Record<string, unknown>;
};

/** Try to recover the structured 422 detail the server raised from a
 *  `multiqc_report_mismatch`. `throwHttpDetailError` JSON-stringifies the
 *  detail into the Error message, so we parse it back out here. */
function tryParseMultiQCMismatch(message: string): MultiQCMismatch | null {
  try {
    const parsed = JSON.parse(message);
    if (parsed && parsed.code === 'multiqc_report_mismatch') {
      return parsed as MultiQCMismatch;
    }
  } catch {
    /* not JSON; not a structured mismatch */
  }
  return null;
}

const MULTIQC_CHECKS: ReadonlyArray<{
  kind: MultiQCMismatchKind;
  label: string;
  desc: string;
}> = [
  {
    kind: 'modules',
    label: 'Modules',
    desc: 'All reports include the same MultiQC modules.',
  },
  {
    kind: 'plots',
    label: 'Plot keys',
    desc: 'All reports expose the same set of plots.',
  },
  {
    kind: 'version',
    label: 'MultiQC version',
    desc: 'All reports share the same major.minor version.',
  },
  {
    kind: 'samples',
    label: 'Sample uniqueness',
    desc: 'No sample name appears in more than one report.',
  },
];

const MultiQCMismatchDetails: React.FC<{ mismatch: MultiQCMismatch }> = ({
  mismatch,
}) => {
  const d = mismatch.details || {};
  const list = (xs: unknown): string[] => (Array.isArray(xs) ? (xs as string[]) : []);
  const added = list(d.added_in_compared);
  const removed = list(d.removed_in_compared);
  const dupes =
    mismatch.kind === 'samples' && d.duplicate_samples
      ? (d.duplicate_samples as Record<string, string[]>)
      : {};
  const dupeEntries = Object.entries(dupes);
  return (
    <Paper
      withBorder
      p={8}
      radius="xs"
      ml={26}
      bg="var(--mantine-color-red-0)"
    >
      <Text size="xs" c="red" mb={4}>
        {mismatch.summary}
      </Text>
      {(mismatch.kind === 'modules' || mismatch.kind === 'plots') && (
        <Stack gap={2}>
          {added.length > 0 && (
            <Text size="xs" c="dimmed">
              Added in <code>{String(d.compared_report ?? '?')}</code>:{' '}
              {added.join(', ')}
            </Text>
          )}
          {removed.length > 0 && (
            <Text size="xs" c="dimmed">
              Missing in <code>{String(d.compared_report ?? '?')}</code>:{' '}
              {removed.join(', ')}
            </Text>
          )}
        </Stack>
      )}
      {mismatch.kind === 'version' && (
        <Text size="xs" c="dimmed">
          <code>{String(d.baseline_report ?? '?')}</code> ={' '}
          {String(d.baseline_version ?? '?')} ·{' '}
          <code>{String(d.compared_report ?? '?')}</code> ={' '}
          {String(d.compared_version ?? '?')}
        </Text>
      )}
      {mismatch.kind === 'samples' && dupeEntries.length > 0 && (
        <Stack gap={2}>
          {dupeEntries.slice(0, 5).map(([sample, reports]) => (
            <Text key={sample} size="xs" c="dimmed">
              <code>{sample}</code> in {reports.join(', ')}
            </Text>
          ))}
          {dupeEntries.length > 5 && (
            <Text size="xs" c="dimmed">
              …and {dupeEntries.length - 5} more
            </Text>
          )}
        </Stack>
      )}
    </Paper>
  );
};

const MultiQCUniformityChecklist: React.FC<{
  fileCount: number;
  submitting: boolean;
  validating: boolean;
  lastCheckPassed: boolean;
  mismatch: MultiQCMismatch | null;
  onCheck: () => void;
}> = ({ fileCount, submitting, validating, lastCheckPassed, mismatch, onCheck }) => {
  const accent = useBrandAccents();
  const hasMultiple = fileCount >= 2;
  const busy = submitting || validating;
  const statusText = !hasMultiple
    ? 'activated with 2+ reports'
    : submitting
      ? 'running on Create…'
      : validating
        ? 'checking…'
        : mismatch
          ? 'failed'
          : lastCheckPassed
            ? 'all uniform'
            : 'not checked yet';
  return (
    <Paper withBorder p="sm" radius="sm">
      <Group justify="space-between" mb={6} wrap="nowrap">
        <Group gap={6} wrap="nowrap">
          <Icon
            icon="mdi:clipboard-check-outline"
            width={16}
            color="var(--mantine-color-teal-6)"
          />
          <Text size="sm" fw={500}>
            Uniformity checks
          </Text>
        </Group>
        <Group gap={8} wrap="nowrap">
          <Text size="xs" c="dimmed">
            {statusText}
          </Text>
          <Button
            size="compact-xs"
            variant="light"
            color={accent.secondary}
            onClick={onCheck}
            disabled={!hasMultiple || busy}
            loading={validating}
            leftSection={<Icon icon="mdi:check-decagram-outline" width={14} />}
          >
            Check now
          </Button>
        </Group>
      </Group>
      <Stack gap={4}>
        {MULTIQC_CHECKS.map((c) => {
          // 1) red X if this row is the failing kind in mismatch
          // 2) animated dots while validating or submitting
          // 3) green check if the last check passed (and no mismatch since)
          // 4) gray pending dot otherwise (never checked, files just staged)
          const failed = mismatch?.kind === c.kind;
          const iconName = failed
            ? 'mdi:close-circle'
            : busy && hasMultiple
              ? 'mdi:dots-horizontal-circle-outline'
              : lastCheckPassed && hasMultiple
                ? 'mdi:check-circle'
                : 'mdi:circle-outline';
          const iconColor = failed
            ? 'var(--mantine-color-red-6)'
            : busy && hasMultiple
              ? 'var(--mantine-color-teal-6)'
              : lastCheckPassed && hasMultiple
                ? 'var(--mantine-color-teal-6)'
                : 'var(--mantine-color-gray-5)';
          return (
            <Stack gap={2} key={c.kind}>
              <Group gap="xs" wrap="nowrap" align="flex-start">
                <Icon icon={iconName} width={18} color={iconColor} />
                <Text
                  size="sm"
                  c={failed ? 'red' : undefined}
                  fw={failed ? 500 : 400}
                  style={{ minWidth: 140 }}
                >
                  {c.label}
                </Text>
                <Text size="xs" c="dimmed" style={{ flex: 1 }}>
                  {c.desc}
                </Text>
              </Group>
              {failed && mismatch && <MultiQCMismatchDetails mismatch={mismatch} />}
            </Stack>
          );
        })}
      </Stack>
    </Paper>
  );
};

/** Guess the file format from extension. Lets the user override afterwards. */
function guessFormat(name: string | undefined): string | null {
  if (!name) return null;
  const lower = name.toLowerCase();
  if (lower.endsWith('.csv')) return 'csv';
  if (lower.endsWith('.tsv') || lower.endsWith('.tab')) return 'tsv';
  if (lower.endsWith('.parquet') || lower.endsWith('.pq')) return 'parquet';
  if (lower.endsWith('.feather') || lower.endsWith('.arrow')) return 'feather';
  return null;
}

/** Single-file dropzone + selected-file chip for the Table tab of the
 *  create-DC modal. */
const TableFileDropZone: React.FC<{
  dropzone: ReturnType<typeof useFolderDropzone>;
  file: File | null;
  submitting: boolean;
  icon: string;
  title: string;
  onRemove: () => void;
}> = ({ dropzone, file, submitting, icon, title, onRemove }) => (
  <>
    <Text size="sm" fw={500}>
      File <span style={{ color: 'var(--mantine-color-red-6)' }}>*</span>
    </Text>
    <div ref={dropzone.rootRef}>
      <UnstyledDropZone
        onClick={() => !submitting && dropzone.openPicker()}
        disabled={submitting}
        active={dropzone.isDragOver}
      >
        <Stack gap={4} align="center">
          <Icon icon={icon} width={28} />
          <Text fw={500}>{title}</Text>
          <Text size="xs" c="dimmed">
            or click to pick · max 50 MB
          </Text>
        </Stack>
      </UnstyledDropZone>
      <input
        ref={dropzone.inputRef}
        type="file"
        accept=".csv,.tsv,.tab,.parquet,.pq,.feather,.arrow"
        style={{ display: 'none' }}
        onChange={dropzone.onInputChange}
      />
    </div>
    {dropzone.error && (
      <Alert
        color="orange"
        variant="light"
        icon={<Icon icon="mdi:alert" width={16} />}
      >
        {dropzone.error}
      </Alert>
    )}
    {file && (
      <Paper withBorder p="xs" radius="sm">
        <Group justify="space-between" wrap="nowrap" gap="xs">
          <Group gap="xs" wrap="nowrap">
            <Icon icon="mdi:file-outline" width={16} />
            <Text size="sm" ff="monospace" lineClamp={1}>
              {file.name}
            </Text>
          </Group>
          <Group gap={4} wrap="nowrap">
            <Text size="xs" c="dimmed">
              {(file.size / (1024 * 1024)).toFixed(1)} MB
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
    )}
  </>
);

/** Two-column lat/lon picker for the coordinates DC fallback. CSV/TSV gets
 *  Selects bound to the parsed header; non-delimited formats (Parquet) fall
 *  back to free-text TextInputs since we can't peek the header client-side. */
const CoordColumnPickers: React.FC<{
  isDelimited: boolean;
  csvColumns: string[];
  parsingHeader: boolean;
  latColumn: string | null;
  lonColumn: string | null;
  onLatChange: (col: string | null) => void;
  onLonChange: (col: string | null) => void;
  disabled: boolean;
}> = ({
  isDelimited,
  csvColumns,
  parsingHeader,
  latColumn,
  lonColumn,
  onLatChange,
  onLonChange,
  disabled,
}) => {
  if (!isDelimited) {
    return (
      <SimpleGrid cols={2} spacing="sm">
        <TextInput
          label="Latitude column"
          placeholder="e.g. latitude"
          value={latColumn ?? ''}
          onChange={(e) => onLatChange(e.currentTarget.value || null)}
          disabled={disabled}
          required
        />
        <TextInput
          label="Longitude column"
          placeholder="e.g. longitude"
          value={lonColumn ?? ''}
          onChange={(e) => onLonChange(e.currentTarget.value || null)}
          disabled={disabled}
          required
        />
      </SimpleGrid>
    );
  }
  let placeholder: string;
  if (parsingHeader) placeholder = 'Reading header…';
  else if (csvColumns.length) placeholder = 'Pick column';
  else placeholder = 'No columns found';
  const colsDisabled = disabled || parsingHeader || csvColumns.length === 0;
  return (
    <SimpleGrid cols={2} spacing="sm">
      <Select
        label="Latitude column"
        placeholder={placeholder}
        data={csvColumns}
        value={latColumn}
        onChange={onLatChange}
        disabled={colsDisabled}
        required
        leftSection={parsingHeader ? <Loader size="xs" /> : undefined}
        searchable
        nothingFoundMessage="No matching columns"
      />
      <Select
        label="Longitude column"
        placeholder={placeholder}
        data={csvColumns}
        value={lonColumn}
        onChange={onLonChange}
        disabled={colsDisabled}
        required
        searchable
        nothingFoundMessage="No matching columns"
      />
    </SimpleGrid>
  );
};

const CreateDataCollectionModal: React.FC<{
  opened: boolean;
  projectId: string | null;
  onClose: () => void;
  onSuccess: () => void;
  /** The kind the dialog opens on. */
  initialType?: 'table' | 'multiqc';
  /** Heading of the dialog; defaults to "Create a Data Collection". */
  title?: string;
}> = ({ opened, projectId, onClose, onSuccess, initialType = 'table', title }) => {
  const accent = useBrandAccents();
  const [dcType, setDcType] = useState<'table' | 'multiqc'>(initialType);
  useEffect(() => {
    if (opened) setDcType(initialType);
  }, [opened, initialType]);
  // Where the table comes from. 'upload' pushes bytes through the browser;
  // 'url' hands the server a location to fetch itself, which is the only
  // workable route for files too large to upload or buckets the browser
  // cannot reach.
  const [tableSource, setTableSource] = useState<'upload' | 'url'>('upload');
  const [remoteUrl, setRemoteUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [fileFormat, setFileFormat] = useState<string>('csv');
  const [separator, setSeparator] = useState<string>(',');
  const [customSeparator, setCustomSeparator] = useState('');
  const [compression, setCompression] = useState<string>('none');
  const [hasHeader, setHasHeader] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [validating, setValidating] = useState(false);
  const [lastCheckPassed, setLastCheckPassed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState<MultiQCMismatch | null>(null);
  // Header columns parsed client-side from the dropped CSV/TSV file. Used both
  // to surface coordinates auto-detection (see detectCoordinatesColumns) and
  // to back the lat/lon Select dropdowns when the user opts into a coordinates
  // table on the Table tab.
  const [csvColumns, setCsvColumns] = useState<string[]>([]);
  const [parsingHeader, setParsingHeader] = useState(false);
  const [latColumn, setLatColumn] = useState<string | null>(null);
  const [lonColumn, setLonColumn] = useState<string | null>(null);
  // True when the user wants the table persisted as a coordinates DC
  // (DCTableCoordinatesConfig). Auto-flips on when detection succeeds; can be
  // toggled manually for non-delimited formats where we can't peek the header.
  const [coordsConfirmed, setCoordsConfirmed] = useState(false);

  // MultiQC folder dropzone — owned by the modal so close-and-reopen clears it.
  const multiqcDropzone = useFolderDropzone({
    filterFilename: 'multiqc.parquet',
    maxPerFile: 50 * 1024 * 1024,
    maxTotal: 500 * 1024 * 1024,
  });

  // Single-file dropzone for the table DC flow. Same drag-anywhere UX as the
  // MultiQC dropzone — we just take the first file and pipe it into `file`.
  const tableDropzone = useFolderDropzone({
    maxPerFile: 50 * 1024 * 1024,
  });
  // Sync the first dropped/picked file into the existing `file` state so the
  // rest of the table flow (auto-fill, submit) keeps working unchanged.
  useEffect(() => {
    if (dcType !== 'table') return;
    const first = tableDropzone.files[0];
    if (!first) return;
    if (file && first === file) return;
    setFile(first);
  }, [dcType, tableDropzone.files, file]);

  // Parse the dropped file's header (CSV/TSV only) so the coordinates
  // detection + lat/lon Select dropdowns can populate. Reads the first ~64KB
  // client-side — enough for any reasonable single-line header without paying
  // the cost of the whole file. Parquet/feather headers aren't accessible
  // without a wasm parser; for those the user opts in manually and the API
  // validates column names server-side via `_validate_coord_columns_in_file`.
  useEffect(() => {
    if (dcType !== 'table' || !file || !hasHeader) {
      setCsvColumns([]);
      return;
    }
    const fmt = fileFormat.toLowerCase();
    if (fmt !== 'csv' && fmt !== 'tsv') {
      setCsvColumns([]);
      return;
    }
    let cancelled = false;
    setParsingHeader(true);
    const sep = separator === 'custom' ? customSeparator || ',' : separator;
    file
      .slice(0, 65536)
      .text()
      .then((text) => {
        if (cancelled) return;
        const firstLine = text.split(/\r?\n/).find((l) => l.length > 0) ?? '';
        const cols = firstLine.split(sep).map((c) => c.trim()).filter(Boolean);
        setCsvColumns(cols);
      })
      .catch(() => {
        if (!cancelled) setCsvColumns([]);
      })
      .finally(() => {
        if (!cancelled) setParsingHeader(false);
      });
    return () => {
      cancelled = true;
    };
  }, [dcType, file, fileFormat, separator, customSeparator, hasHeader]);

  // Detect an extended category from the parsed header. When coordinates land,
  // pre-fill lat/lon and flip the coordsConfirmed switch on. The auto-fill is
  // gated by a per-file ref so a user who explicitly toggles the switch off
  // doesn't immediately have it flipped back on by this effect.
  const coordsGuess = useMemo(
    () => detectCoordinatesColumns(csvColumns),
    [csvColumns],
  );

  // Prefill lat/lon pickers on header detection — a SUGGESTION only. The
  // "Save as a coordinates table" switch stays off until the user flips it:
  // silently opting a table in used to turn every metadata table carrying
  // latitude/longitude columns into a "Coordinates" table, hiding its
  // Metadata nature. Gated by a per-file ref so it fires once per file.
  const prefilledForFileRef = useRef<File | null>(null);
  useEffect(() => {
    if (!file) {
      prefilledForFileRef.current = null;
      return;
    }
    if (!coordsGuess) return;
    if (prefilledForFileRef.current === file) return;
    prefilledForFileRef.current = file;
    setLatColumn(coordsGuess.latColumn);
    setLonColumn(coordsGuess.lonColumn);
  }, [file, coordsGuess]);

  // The name last filled in from a picked file or a typed URL. While the name
  // field still holds it, a newer file or URL replaces it; once the user
  // edits the name, it is theirs and stays.
  const autoNameRef = useRef('');
  const autoFillName = (next: string) => {
    if (name.trim() && name !== autoNameRef.current) return;
    autoNameRef.current = next;
    setName(next);
  };

  // Reset everything when the modal closes — otherwise re-opening shows stale
  // state from the previous attempt.
  useEffect(() => {
    if (!opened) {
      setDcType('table');
      setFile(null);
      setName('');
      autoNameRef.current = '';
      setDescription('');
      setFileFormat('csv');
      setSeparator(',');
      setCustomSeparator('');
      setCompression('none');
      setHasHeader(true);
      setError(null);
      setSubmitting(false);
      setCsvColumns([]);
      setLatColumn(null);
      setLonColumn(null);
      setCoordsConfirmed(false);
      setParsingHeader(false);
      setTableSource('upload');
      setRemoteUrl('');
      multiqcDropzone.clear();
      tableDropzone.clear();
    }
    // multiqcDropzone is recreated on each render but its `clear` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened]);

  // Auto-fill format + name from picked filename. Don't clobber a name the
  // user already typed (see autoFillName); do clobber the format because
  // picking a new file means a new format. Runs per file only: re-running on
  // every keystroke of the name field would reset a separator or format the
  // user picked since.
  useEffect(() => {
    if (!file) return;
    const guessed = guessFormat(file.name);
    if (guessed) {
      setFileFormat(guessed);
      setSeparator(guessed === 'tsv' ? '\t' : ',');
    }
    autoFillName(file.name.replace(/\.[^.]+$/, ''));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  // Same auto-fill for the remote-URL source: the last path segment plays the
  // role the picked filename plays above. It follows the URL as it is typed
  // ("https://e" first gives "e") until the user edits the name.
  useEffect(() => {
    if (tableSource !== 'url') return;
    const basename = remoteUrl.trim().split('?')[0].split('/').pop();
    if (!basename) return;
    const guessed = guessFormat(basename);
    if (guessed) {
      setFileFormat(guessed);
      setSeparator(guessed === 'tsv' ? '\t' : ',');
    }
    autoFillName(basename.replace(/\.[^.]+$/, ''));
    // `name` is intentionally read but not depended on: re-running on every
    // keystroke of the name field would fight the user's own edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remoteUrl, tableSource]);

  // Clear any prior uniformity mismatch (and stale pass state) when the user
  // changes the dropped file set — both refer to a different set of reports.
  useEffect(() => {
    setMismatch(null);
    setLastCheckPassed(false);
  }, [multiqcDropzone.files, dcType]);

  // Auto-fill name when the user drops MultiQC files, so the Create button
  // doesn't sit silently disabled. Picks the deepest shared parent directory
  // across all dropped files so multi-run drops get a representative name.
  useEffect(() => {
    if (dcType !== 'multiqc') return;
    if (name.trim()) return;
    if (multiqcDropzone.files.length === 0) return;

    const splitPaths = multiqcDropzone.files.map((f) =>
      f.name.replace(/\\/g, '/').split('/').filter(Boolean),
    );
    // Drop the trailing filename segment so we compare directories only.
    const dirPaths = splitPaths.map((p) => p.slice(0, -1));
    const common: string[] = [];
    const minLen = Math.min(...dirPaths.map((p) => p.length));
    for (let i = 0; i < minLen; i++) {
      const seg = dirPaths[0][i];
      if (dirPaths.every((p) => p[i] === seg)) common.push(seg);
      else break;
    }
    // The deepest shared dir is usually wrapper-ish (e.g. `multiqc_data`)
    // when only one run was dropped; prefer its parent for >1 run so the
    // wrapper folder (`mysamples`) wins over the per-run `multiqc_data`.
    const deepest =
      common.length > 0 && common[common.length - 1] === 'multiqc_data'
        ? common[common.length - 2]
        : common[common.length - 1];
    setName(deepest || 'multiqc_reports');
  }, [dcType, multiqcDropzone.files, name]);

  const handleCheckUniformity = async () => {
    if (multiqcDropzone.files.length < 2) return;
    setValidating(true);
    setError(null);
    setMismatch(null);
    setLastCheckPassed(false);
    try {
      await checkMultiQCUniformity(multiqcDropzone.files);
      setLastCheckPassed(true);
    } catch (err) {
      const raw = (err as Error).message || 'Uniformity check failed.';
      const parsed = tryParseMultiQCMismatch(raw);
      if (parsed) {
        setMismatch(parsed);
        setError(parsed.summary);
      } else {
        setError(raw);
      }
    } finally {
      setValidating(false);
    }
  };

  const handleSubmit = async () => {
    if (!projectId) {
      setError('Project ID missing from URL.');
      return;
    }
    if (!name.trim()) {
      setError('Data collection name is required.');
      return;
    }

    setSubmitting(true);
    setError(null);
    setMismatch(null);
    try {
      if (dcType === 'multiqc') {
        if (multiqcDropzone.files.length === 0) {
          setError('Drop one or more folders containing multiqc.parquet.');
          setSubmitting(false);
          return;
        }
        const result = await createMultiQCDataCollection({
          projectId,
          name: name.trim(),
          description: description.trim(),
          files: multiqcDropzone.files,
        });
        notifications.show({
          color: 'teal',
          title: 'MultiQC data collection created',
          message: result.message || `"${name.trim()}" is ready.`,
          autoClose: 4000,
        });
      } else if (tableSource === 'url') {
        const url = remoteUrl.trim();
        if (!url) {
          setError('Enter the URL of the file.');
          setSubmitting(false);
          return;
        }
        if (!/^(https?|s3):\/\//i.test(url)) {
          // http:// passes here; whether the server accepts it depends on
          // DEPICTIO_REMOTE_ALLOW_HTTP.
          setError(
            'The URL must start with https://, s3:// or http:// ' +
              '(plain http:// is only accepted when the server allows it).',
          );
          setSubmitting(false);
          return;
        }
        if (separator === 'custom' && !customSeparator) {
          setError('Custom separator cannot be empty.');
          setSubmitting(false);
          return;
        }
        const result = await createDataCollectionFromUrl({
          projectId,
          name: name.trim(),
          description: description.trim(),
          dataType: 'table',
          fileFormat,
          separator,
          customSeparator: separator === 'custom' ? customSeparator : null,
          compression,
          hasHeader,
          url,
        });
        notifications.show({
          color: 'teal',
          title: 'Data collection created',
          message: result.message || `"${name.trim()}" is ready.`,
          autoClose: 2500,
        });
      } else {
        if (!file) {
          setError('Pick a file to upload.');
          setSubmitting(false);
          return;
        }
        if (separator === 'custom' && !customSeparator) {
          setError('Custom separator cannot be empty.');
          setSubmitting(false);
          return;
        }
        if (coordsConfirmed) {
          if (!latColumn || !lonColumn) {
            setError('Pick the latitude and longitude columns.');
            setSubmitting(false);
            return;
          }
          if (latColumn === lonColumn) {
            setError('Latitude and longitude columns must differ.');
            setSubmitting(false);
            return;
          }
        }
        const result = await createDataCollectionFromUpload({
          projectId,
          name: name.trim(),
          description: description.trim(),
          dataType: 'table',
          fileFormat,
          separator,
          customSeparator: separator === 'custom' ? customSeparator : null,
          compression,
          hasHeader,
          file,
          latColumn: coordsConfirmed ? latColumn : null,
          lonColumn: coordsConfirmed ? lonColumn : null,
        });
        notifications.show({
          color: 'teal',
          title: 'Data collection created',
          message: result.message || `"${name.trim()}" is ready.`,
          autoClose: 2500,
        });
      }
      onSuccess();
    } catch (err) {
      const rawMessage = (err as Error).message || 'Upload failed.';
      const parsed = tryParseMultiQCMismatch(rawMessage);
      if (parsed) {
        setMismatch(parsed);
        setError(parsed.summary);
      } else {
        setError(rawMessage);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const isDelimited = fileFormat === 'csv' || fileFormat === 'tsv';

  /** True while the chosen source still lacks an input the Create button needs. */
  const isMissingInput = (): boolean => {
    if (!name.trim()) return true;
    if (dcType === 'multiqc') return multiqcDropzone.files.length === 0;
    if (tableSource === 'url') return !remoteUrl.trim();
    return !file || (coordsConfirmed && (!latColumn || !lonColumn));
  };

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={null}
      centered
      size="lg"
      closeOnClickOutside={!submitting}
      withCloseButton={!submitting}
    >
      <Stack gap="md" data-testid="create-dc-modal">
        <Group justify="center" gap="sm">
          <Icon
            icon="mdi:database-plus-outline"
            width={32}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Title order={3} c={accent.secondary} m={0}>
            {title ?? 'Create a Data Collection'}
          </Title>
        </Group>

        <Tabs
          value={dcType}
          onChange={(v) => v && setDcType(v as 'table' | 'multiqc')}
          variant="default"
        >
          <Tabs.List grow>
            {/* Same glyphs the manager and the ingestion report use, so the
                type you pick here is the type you recognise later. */}
            <Tabs.Tab
              value="table"
              leftSection={<DcTypeIcon type="table" size={18} withTooltip={false} />}
              disabled={submitting}
            >
              Table (CSV / TSV / Parquet)
            </Tabs.Tab>
            <Tabs.Tab
              value="multiqc"
              leftSection={<DcTypeIcon type="multiqc" size={18} withTooltip={false} />}
              disabled={submitting}
            >
              MultiQC report(s)
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="table" pt="md">
            <Stack gap="xs">
              <SegmentedControl
                fullWidth
                value={tableSource}
                onChange={(value) => setTableSource(value as 'upload' | 'url')}
                disabled={submitting}
                data={[
                  { label: 'Upload a file', value: 'upload' },
                  { label: 'Remote URL', value: 'url' },
                ]}
              />
              {tableSource === 'url' ? (
                <TextInput
                  label="File URL"
                  placeholder="https://example.org/data.csv or s3://bucket/key.csv"
                  description="Fetched by the server, so the file never travels through your browser. Private buckets use this project's storage credentials; a bucket the administrator marked public is read without any."
                  value={remoteUrl}
                  onChange={(e) => setRemoteUrl(e.currentTarget.value)}
                  disabled={submitting}
                />
              ) : (
                <TableFileDropZone
                  dropzone={tableDropzone}
                  file={file}
                  submitting={submitting}
                  icon="mdi:file-upload-outline"
                  title="Drop a CSV, TSV, Parquet, or Feather file"
                  onRemove={() => {
                    setFile(null);
                    setCsvColumns([]);
                    setLatColumn(null);
                    setLonColumn(null);
                    setCoordsConfirmed(false);
                    tableDropzone.clear();
                  }}
                />
              )}
              {/* The URL source sends no coordinates, so a file picked before
                  switching to it must not keep offering them. */}
              {tableSource === 'upload' && file && (
                <Paper p="sm" withBorder radius="sm" bg="var(--mantine-color-default-hover)">
                  <Stack gap="xs">
                    {coordsGuess && !coordsConfirmed && (
                      <Alert
                        color={GEO_COLOR}
                        variant="light"
                        icon={<Icon icon={GEO_ICON} />}
                        data-testid="coords-detected-alert"
                      >
                        Geographic columns detected ({coordsGuess.latColumn} /{' '}
                        {coordsGuess.lonColumn}). Turn on the switch below to make this
                        table available to Map components.
                      </Alert>
                    )}
                    <Switch
                      label="Save as a coordinates table"
                      description="Adds latitude / longitude column metadata so the data collection can power Map components."
                      checked={coordsConfirmed}
                      disabled={submitting}
                      onChange={(e) => {
                        const next = e.currentTarget.checked;
                        setCoordsConfirmed(next);
                        if (!next) {
                          setLatColumn(null);
                          setLonColumn(null);
                        } else if (coordsGuess) {
                          setLatColumn((prev) => prev ?? coordsGuess.latColumn);
                          setLonColumn((prev) => prev ?? coordsGuess.lonColumn);
                        }
                      }}
                    />
                    {coordsConfirmed && (
                      <CoordColumnPickers
                        isDelimited={fileFormat === 'csv' || fileFormat === 'tsv'}
                        csvColumns={csvColumns}
                        parsingHeader={parsingHeader}
                        latColumn={latColumn}
                        lonColumn={lonColumn}
                        onLatChange={setLatColumn}
                        onLonChange={setLonColumn}
                        disabled={submitting}
                      />
                    )}
                  </Stack>
                </Paper>
              )}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="multiqc" pt="md">
            <Stack gap="xs">
            <Text size="sm" fw={500}>
              MultiQC reports
            </Text>
            <div ref={multiqcDropzone.rootRef}>
              <UnstyledDropZone
                onClick={() => !submitting && multiqcDropzone.openPicker()}
                disabled={submitting}
                active={multiqcDropzone.isDragOver}
              >
                <Stack gap={4} align="center">
                  <Icon icon="mdi:folder-upload" width={28} />
                  <Text fw={500}>
                    Drop a multiqc.parquet file or a folder of runs
                  </Text>
                  <Text size="xs" c="dimmed">
                    Only multiqc.parquet files are kept · run folder name is preserved
                  </Text>
                </Stack>
              </UnstyledDropZone>
              <input
                ref={multiqcDropzone.inputRef}
                type="file"
                multiple
                style={{ display: 'none' }}
                // Click-to-pick must open a *folder* picker so the run-folder
                // structure (<run>/multiqc_data/multiqc.parquet) reaches the
                // hook via webkitRelativePath — parity with drag-drop. Without
                // it, click-selected files carry no path and the upload silently
                // does nothing (#847). `accept` is dropped because browsers
                // ignore it for directory selection; the hook's
                // filterFilename:'multiqc.parquet' does the real filtering.
                // @ts-expect-error — webkitdirectory is non-standard but widely supported.
                webkitdirectory=""
                onChange={multiqcDropzone.onInputChange}
              />
            </div>
            {multiqcDropzone.error && (
              <Alert
                color="orange"
                variant="light"
                icon={<Icon icon="mdi:alert" width={16} />}
              >
                {multiqcDropzone.error}
              </Alert>
            )}
            {multiqcDropzone.files.length > 0 && (
              <Paper withBorder p="xs" radius="sm">
                <Group justify="space-between" mb={6}>
                  <Text size="sm" fw={500}>
                    {multiqcDropzone.files.length} file
                    {multiqcDropzone.files.length === 1 ? '' : 's'} ·{' '}
                    {(multiqcDropzone.totalBytes / (1024 * 1024)).toFixed(1)} MB
                  </Text>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={multiqcDropzone.clear}
                    disabled={submitting}
                  >
                    Clear list
                  </Button>
                </Group>
                <ScrollArea h={Math.min(multiqcDropzone.files.length * 28 + 8, 200)}>
                  <Stack gap={2}>
                    {multiqcDropzone.files.map((f, i) => (
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
                            {(f.size / (1024 * 1024)).toFixed(1)} MB
                          </Text>
                          <ActionIcon
                            size="xs"
                            variant="subtle"
                            color="red"
                            onClick={() => multiqcDropzone.removeFile(f)}
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
                {multiqcDropzone.skipped.length > 0 && (
                  <Text size="xs" c="dimmed" mt={6}>
                    Skipped {multiqcDropzone.skipped.length} non-multiqc file
                    {multiqcDropzone.skipped.length === 1 ? '' : 's'}.
                  </Text>
                )}
              </Paper>
            )}
            {multiqcDropzone.files.length > 0 && (
              <MultiQCUniformityChecklist
                fileCount={multiqcDropzone.files.length}
                submitting={submitting}
                validating={validating}
                lastCheckPassed={lastCheckPassed}
                mismatch={mismatch}
                onCheck={handleCheckUniformity}
              />
            )}
            </Stack>
          </Tabs.Panel>
        </Tabs>

        <TextInput
          label="Name"
          placeholder={
            dcType === 'multiqc' ? 'e.g. multiqc_qc' : 'e.g. samples_metadata'
          }
          required
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
          disabled={submitting}
        />

        <Textarea
          label="Description"
          placeholder="What does this data collection contain? (optional)"
          value={description}
          onChange={(e) => setDescription(e.currentTarget.value)}
          autosize
          minRows={2}
          maxRows={4}
          disabled={submitting}
        />

        {dcType === 'table' && (
          <>
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <Select
                label="Format"
                data={FORMAT_OPTIONS}
                value={fileFormat}
                onChange={(v) => v && setFileFormat(v)}
                allowDeselect={false}
                disabled={submitting}
              />
              {isDelimited && (
                <Select
                  label="Separator"
                  data={SEPARATOR_OPTIONS}
                  value={separator}
                  onChange={(v) => v && setSeparator(v)}
                  allowDeselect={false}
                  disabled={submitting}
                />
              )}
            </SimpleGrid>

            {isDelimited && separator === 'custom' && (
              <TextInput
                label="Custom separator"
                placeholder="e.g. ::"
                value={customSeparator}
                onChange={(e) => setCustomSeparator(e.currentTarget.value)}
                required
                disabled={submitting}
              />
            )}

            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
              <Select
                label="Compression"
                data={COMPRESSION_OPTIONS}
                value={compression}
                onChange={(v) => v && setCompression(v)}
                allowDeselect={false}
                disabled={submitting}
              />
              {isDelimited && (
                <Switch
                  mt="lg"
                  label="File has header row"
                  checked={hasHeader}
                  onChange={(e) => setHasHeader(e.currentTarget.checked)}
                  disabled={submitting}
                />
              )}
            </SimpleGrid>
          </>
        )}

        {error && (
          <Alert
            color="red"
            variant="light"
            icon={<Icon icon="mdi:alert-circle-outline" width={18} />}
          >
            {error}
          </Alert>
        )}

        <Alert
          color="blue"
          variant="light"
          icon={<Icon icon="mdi:information-outline" width={18} />}
        >
          <Text size="xs">
            {dcType === 'table' && tableSource === 'url'
              ? 'The server fetches the URL itself and aggregates it to a Delta table. The address is screened before any request is made, so private and internal addresses are refused. '
              : 'The file will be scanned and aggregated to a Delta table on the server. '}
            Larger files take longer: keep this dialog open until you see the
            success notification.
          </Text>
        </Alert>

        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            color={accent.secondary}
            onClick={handleSubmit}
            loading={submitting}
            disabled={isMissingInput()}
            leftSection={<Icon icon="mdi:cloud-upload-outline" width={16} />}
          >
            Create
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
};

export default CreateDataCollectionModal;
