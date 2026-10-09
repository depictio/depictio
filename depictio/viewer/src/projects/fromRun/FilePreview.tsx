/**
 * A file of a run folder, written relative to the folder, that opens onto
 * its first rows: a table for a CSV, TSV or parquet file, the first lines for
 * a text file, and why not for a report or a binary file. The server reads
 * the start of the file only (`previewRunFile`), with the checks of a dry
 * run, and the answer is kept per file while the page lives.
 *
 * The run folder, and the connection details of the private bucket it may be
 * in, come from `RunFileScope`, set once around a plan.
 */
import React, { createContext, useContext, useEffect, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Code,
  Collapse,
  Group,
  Loader,
  ScrollArea,
  Stack,
  Table,
  Text,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { previewRunFile, relativeToRunFolder, Z_LAYERS } from 'depictio-react-core';
import type { RunFilePreview, RunStorageIn } from 'depictio-react-core';

import { fileSize } from './fileSize';
import { FolderPath } from './FolderPath';
import { plural } from './plural';

interface RunFileScopeValue {
  dataRoot: string;
  storage: RunStorageIn | null;
}

const RunFileScopeContext = createContext<RunFileScopeValue | null>(null);

/** The run folder the files below are read from. */
export const RunFileScope: React.FC<{
  dataRoot: string;
  storage?: RunStorageIn | null;
  children: React.ReactNode;
}> = ({ dataRoot, storage = null, children }) => (
  <RunFileScopeContext.Provider value={{ dataRoot, storage }}>{children}</RunFileScopeContext.Provider>
);

export function useRunFileScope(): RunFileScopeValue | null {
  return useContext(RunFileScopeContext);
}

const previews = new Map<string, RunFilePreview>();

type PreviewState =
  | { status: 'loading' }
  | { status: 'error'; error: string }
  | { status: 'ready'; preview: RunFilePreview };

function usePreview(scope: RunFileScopeValue, location: string): PreviewState {
  const key = `${scope.dataRoot}\n${location}`;
  const [state, setState] = useState<PreviewState>(() => {
    const known = previews.get(key);
    return known ? { status: 'ready', preview: known } : { status: 'loading' };
  });
  useEffect(() => {
    const known = previews.get(key);
    if (known) {
      setState({ status: 'ready', preview: known });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: 'loading' });
    previewRunFile(
      { dataRoot: scope.dataRoot, location, storage: scope.storage },
      { signal: controller.signal },
    )
      .then((preview) => {
        previews.set(key, preview);
        if (!controller.signal.aborted) setState({ status: 'ready', preview });
      })
      .catch((err: Error) => {
        if (!controller.signal.aborted) {
          setState({ status: 'error', error: err.message || 'The file could not be read.' });
        }
      });
    return () => controller.abort();
    // `storage` belongs to the run folder; the key decides.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

/** "First 20 rows of 1 240 · 14 of 30 columns · 12.3 KB". */
function tableFooter(preview: RunFilePreview): string {
  const parts: string[] = [];
  const shown = preview.rows.length;
  if (preview.rows_total !== null && preview.rows_total > shown) {
    parts.push(`First ${shown} rows of ${preview.rows_total.toLocaleString()}`);
  } else if (preview.rows_total === null && preview.truncated) {
    parts.push(`First ${plural(shown, 'row')}`);
  } else {
    parts.push(plural(shown, 'row'));
  }
  if (preview.columns_total > preview.columns.length) {
    parts.push(`${preview.columns.length} of ${preview.columns_total} columns`);
  }
  const size = fileSize(preview.size);
  if (size) parts.push(size);
  return parts.join(' · ');
}

const PreviewBody: React.FC<{ preview: RunFilePreview }> = ({ preview }) => {
  if (preview.format === 'none') {
    return (
      <Text size="xs" c="dimmed" data-testid="file-preview-none">
        {preview.reason || 'This file cannot be previewed.'}
        {fileSize(preview.size) ? ` (${fileSize(preview.size)})` : ''}
      </Text>
    );
  }
  if (preview.format === 'text') {
    return (
      <Stack gap={4}>
        <ScrollArea.Autosize mah={220} type="auto" offsetScrollbars>
          <Code block fz="xs" data-testid="file-preview-text">
            {preview.text ?? ''}
          </Code>
        </ScrollArea.Autosize>
        <Text size="xs" c="dimmed">
          {[preview.truncated ? 'The first lines' : 'The whole file', fileSize(preview.size)]
            .filter(Boolean)
            .join(' · ')}
        </Text>
      </Stack>
    );
  }
  return (
    <Stack gap={4}>
      <ScrollArea.Autosize mah={260} type="auto" offsetScrollbars>
        <Table
          // Explicit: a table inside a fixed-layout table (the checks, the
          // plan) inherits its layout otherwise, and its columns overlap.
          layout="auto"
          striped
          withTableBorder
          withColumnBorders
          verticalSpacing={2}
          horizontalSpacing={6}
          fz="xs"
          data-testid="file-preview-table"
          style={{ whiteSpace: 'nowrap', width: 'max-content', minWidth: '100%' }}
        >
          <Table.Thead>
            <Table.Tr>
              {preview.columns.map((column, index) => (
                // Column names repeat in some reports; the position keeps keys unique.
                // eslint-disable-next-line react/no-array-index-key
                <Table.Th key={`${index}-${column}`} ff="monospace">
                  {column}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {preview.rows.map((row, r) => (
              // eslint-disable-next-line react/no-array-index-key
              <Table.Tr key={r}>
                {row.map((cell, c) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <Table.Td key={c} ff="monospace" c={cell === null ? 'dimmed' : undefined}>
                    {cell ?? 'null'}
                  </Table.Td>
                ))}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea.Autosize>
      <Text size="xs" c="dimmed" data-testid="file-preview-footer">
        {tableFooter(preview)}
      </Text>
    </Stack>
  );
};

/** The first rows of `location`, read below the folder of the `RunFileScope`
 *  around it; nothing without one. */
export const FilePreviewPanel: React.FC<{ location: string }> = ({ location }) => {
  const scope = useRunFileScope();
  return scope ? <PreviewPanel scope={scope} location={location} /> : null;
};

const PreviewPanel: React.FC<{ scope: RunFileScopeValue; location: string }> = ({
  scope,
  location,
}) => {
  const state = usePreview(scope, location);
  return (
    <Stack
      gap={4}
      py={4}
      // The panel is as wide as where it is shown, whatever the width of the
      // table in it: a wide table scrolls inside it instead of widening the
      // list or the plan around it.
      style={{ contain: 'inline-size', minWidth: 0 }}
      data-testid="file-preview"
      data-state={state.status}
      aria-live="polite"
    >
      {state.status === 'loading' && (
        <Group gap="xs" wrap="nowrap">
          <Loader size="xs" />
          <Text size="xs" c="dimmed">
            Reading the start of the file...
          </Text>
        </Group>
      )}
      {state.status === 'error' && (
        <Alert
          color="yellow"
          variant="light"
          p="xs"
          icon={<Icon icon="mdi:alert-outline" width={14} />}
          data-testid="file-preview-error"
        >
          <Text size="xs">{state.error}</Text>
        </Alert>
      )}
      {state.status === 'ready' && <PreviewBody preview={state.preview} />}
    </Stack>
  );
};

/** The eye that opens a file onto its first rows, and closes it again. */
export const FilePreviewToggle: React.FC<{
  open: boolean;
  onToggle: () => void;
  /** What is previewed, when the file is not named beside the eye. */
  label?: string;
  testId?: string;
}> = ({ open, onToggle, label, testId = 'file-preview-toggle' }) => {
  const words = open ? 'Hide the preview' : label ?? 'Preview the first rows';
  return (
    <Tooltip label={words} withArrow multiline maw={320} zIndex={Z_LAYERS.tooltip}>
      <ActionIcon
        size="sm"
        variant={open ? 'light' : 'subtle'}
        color={open ? undefined : 'gray'}
        onClick={(event) => {
          // A row that opens on a click of its own keeps still.
          event.stopPropagation();
          onToggle();
        }}
        aria-expanded={open}
        aria-label={words}
        data-testid={testId}
      >
        <Icon icon={open ? 'mdi:eye-off-outline' : 'mdi:eye-outline'} width={14} />
      </ActionIcon>
    </Tooltip>
  );
};

interface RunFilePathProps {
  location: string;
  /** Longest shortened form, in characters. */
  maxLength?: number;
  testId?: string;
}

/** A file of the run folder: its path relative to the folder, the real path
 *  a hover and a click away, and its first rows one click away. Without a
 *  `RunFileScope` around it, the path alone. */
export const RunFilePath: React.FC<RunFilePathProps> = ({ location, maxLength = 88, testId }) => {
  const scope = useRunFileScope();
  const [open, setOpen] = useState(false);
  const relative = scope ? relativeToRunFolder(scope.dataRoot, location) : null;
  const label = relative === null || relative === '' ? undefined : relative;
  return (
    <Stack gap={0} style={{ minWidth: 0 }} data-testid={testId} data-location={location}>
      <Group gap={2} wrap="nowrap" style={{ minWidth: 0 }}>
        <FolderPath location={location} label={label} maxLength={maxLength} />
        {scope && <FilePreviewToggle open={open} onToggle={() => setOpen((o) => !o)} />}
      </Group>
      {scope && (
        <Collapse in={open}>
          {/* Mounted while open; the answer is kept per file, so opening it
              again asks nothing. */}
          {open && <PreviewPanel scope={scope} location={location} />}
        </Collapse>
      )}
    </Stack>
  );
};
