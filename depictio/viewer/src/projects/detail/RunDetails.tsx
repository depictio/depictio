/**
 * One run of a project, unfolded: its folder, the files each collection holds
 * from it, and its scans. A scan is picked on the right; each file then says
 * what that scan did to it (new, changed, failed to read, unchanged), and the
 * list can be narrowed to what the scan brought. A changed file says what it
 * was before (size, date) and, for a MultiQC report, which samples and modules
 * came in or went. Any file opens onto its first rows, read from the run
 * folder.
 *
 * The files are read only once the run is unfolded
 * (`GET /projects/project-runs/{id}/files`).
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Box,
  Collapse,
  CopyButton,
  Grid,
  Group,
  Loader,
  Paper,
  Stack,
  Switch,
  Text,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import { fetchProjectRunFiles, relativeToRunFolder } from 'depictio-react-core';
import type { ProjectRun, RunFile, RunFiles, RunReportChange } from 'depictio-react-core';

import { FactBadge, StatusBadge } from '../badges';
import { DcTypeIcon } from '../dcTypeIcon';
import { FilePreviewPanel, FilePreviewToggle, RunFileScope } from '../fromRun/FilePreview';
import { fileSize } from '../fromRun/fileSize';
import { formatTimestamp } from './DcViewerParts';

/** Run times are written with the server's local clock. */
export const when = (value: string | null | undefined) => formatTimestamp(value, { utc: false }) ?? '—';

type FileState = 'new' | 'changed' | 'failed' | 'unchanged';

const FILE_STATE: Record<FileState, { label: string; color: string; hint: string }> = {
  new: { label: 'New', color: 'blue', hint: 'This scan brought the file.' },
  changed: { label: 'Changed', color: 'yellow', hint: 'This scan found the file changed and read it again.' },
  failed: { label: 'Failed', color: 'red', hint: 'This scan could not read the file.' },
  unchanged: { label: 'Unchanged', color: 'gray', hint: 'Brought by an earlier scan, not changed since.' },
};

/** What scan `scan` did to `file`; null when the file came later. */
function stateIn(file: RunFile, scan: number): FileState | null {
  if (file.failed_in.includes(scan)) return 'failed';
  if (file.added_in === scan) return 'new';
  if (file.changed_in.includes(scan)) return 'changed';
  if (file.added_in !== null && file.added_in > scan) return null;
  return 'unchanged';
}

const names = (items: string[], max = 3) =>
  items.slice(0, max).join(', ') + (items.length > max ? `, +${items.length - max}` : '');

const counted = (sign: string, items: string[], one: string, many: string) =>
  items.length ? `${sign}${items.length} ${items.length === 1 ? one : many} (${names(items)})` : null;

function reportChangeParts(change: RunReportChange): string[] {
  return [
    counted('+', change.samples_added, 'sample', 'samples'),
    counted('−', change.samples_removed, 'sample', 'samples'),
    counted('+', change.modules_added, 'module', 'modules'),
    counted('−', change.modules_removed, 'module', 'modules'),
  ].filter((p): p is string => p !== null);
}

/** What scan `scan` changed in `file`, in words: size and date before → after,
 *  then the samples and modules its report gained or lost. */
function changeLine(file: RunFile, scan: number): string | null {
  const parts: string[] = [];
  const change = file.changes.find((c) => c.scan === scan);
  const [sizeBefore, sizeAfter] = change?.size ?? [null, null];
  if (sizeBefore !== sizeAfter && (sizeBefore !== null || sizeAfter !== null)) {
    parts.push(`${fileSize(sizeBefore) ?? '?'} → ${fileSize(sizeAfter) ?? '?'}`);
  }
  const [modBefore, modAfter] = change?.modified ?? [null, null];
  if (modBefore && modAfter && modBefore !== modAfter) {
    parts.push(`modified ${when(modBefore)} → ${when(modAfter)}`);
  }
  // A report keeps only its last overwrite's change: the newest scan that changed it.
  const lastChanged = Math.max(-1, ...file.changed_in);
  if (file.report_change && lastChanged === scan) parts.push(...reportChangeParts(file.report_change));
  return parts.length ? parts.join(' · ') : null;
}

const SectionLabel: React.FC<{ icon: string; children: React.ReactNode; right?: React.ReactNode }> = ({
  icon,
  children,
  right,
}) => (
  <Group justify="space-between" wrap="nowrap" mb={8} gap="sm">
    <Group gap={6} wrap="nowrap">
      <Icon icon={icon} width={14} style={{ opacity: 0.6 }} />
      <Text size="xs" c="dimmed" fw={600} tt="uppercase">
        {children}
      </Text>
    </Group>
    {right}
  </Group>
);

const FileRow: React.FC<{
  file: RunFile;
  state: FileState;
  scan: number | null;
  runFolder: string | null;
}> = ({ file, state, scan, runFolder }) => {
  const [open, setOpen] = useState(false);
  const relative = runFolder ? relativeToRunFolder(runFolder, file.location) : null;
  const s = FILE_STATE[state];
  const detail = scan !== null && state === 'changed' ? changeLine(file, scan) : null;
  return (
    <Box
      py={6}
      style={{ borderTop: '1px solid var(--mantine-color-default-border)' }}
      data-testid="run-file"
      data-state={state}
      data-filename={file.filename}
    >
      <Group gap="sm" wrap="nowrap" justify="space-between">
        <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
          <Tooltip label={s.hint} withArrow>
            <StatusBadge color={s.color} size="xs" w={92} data-testid="run-file-state">
              {s.label}
            </StatusBadge>
          </Tooltip>
          <Tooltip label={file.location} withArrow multiline maw={520} openDelay={400}>
            <Text size="sm" ff="monospace" truncate="start" style={{ minWidth: 0 }}>
              {relative || file.filename}
            </Text>
          </Tooltip>
        </Group>
        <Group gap="sm" wrap="nowrap">
          <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
            {[fileSize(file.size), file.modified ? when(file.modified) : null].filter(Boolean).join(' · ')}
          </Text>
          {runFolder && (
            <FilePreviewToggle open={open} onToggle={() => setOpen((o) => !o)} testId="run-file-preview-toggle" />
          )}
        </Group>
      </Group>
      {detail && (
        <Text size="xs" c="dimmed" pl={100} pt={2} data-testid="run-file-change">
          {detail}
        </Text>
      )}
      {runFolder && (
        <Collapse in={open}>
          {open && (
            <Box pt={6} pl={100}>
              <FilePreviewPanel location={file.location} />
            </Box>
          )}
        </Collapse>
      )}
    </Box>
  );
};

const CollectionFiles: React.FC<{
  tag: string;
  type: string;
  dcId?: string;
  total: number;
  rows: { file: RunFile; state: FileState }[];
  scan: number | null;
  runFolder: string | null;
  onOpenDc?: (dcId: string) => void;
}> = ({ tag, type, dcId, total, rows, scan, runFolder, onOpenDc }) => {
  const name = (
    <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
      <DcTypeIcon type={type} size={16} withTooltip={false} />
      <Text size="sm" fw={600} truncate="end">
        {tag}
      </Text>
    </Group>
  );
  return (
    <Paper withBorder radius="sm" px="sm" py={6} data-testid={`run-collection-${tag}`}>
      <Group justify="space-between" wrap="nowrap" gap="sm" py={2}>
        {dcId && onOpenDc ? (
          <Tooltip label="Open this collection" withArrow>
            <UnstyledButton onClick={() => onOpenDc(dcId)} style={{ minWidth: 0 }}>
              {name}
            </UnstyledButton>
          </Tooltip>
        ) : (
          name
        )}
        {total === 0 ? (
          <StatusBadge color="orange" size="xs">
            Nothing found
          </StatusBadge>
        ) : (
          <FactBadge size="xs">{total === 1 ? '1 file' : `${total} files`}</FactBadge>
        )}
      </Group>
      {rows.map(({ file, state }) => (
        <FileRow key={file.id} file={file} state={state} scan={scan} runFolder={runFolder} />
      ))}
      {total > 0 && rows.length === 0 && (
        <Text size="xs" c="dimmed" py={4}>
          This scan changed none of its files.
        </Text>
      )}
    </Paper>
  );
};

export const RunDetails: React.FC<{
  projectId: string;
  run: ProjectRun;
  dcIdByTag: Record<string, string>;
  dcTypeByTag: Record<string, string>;
  onOpenDc?: (dcId: string) => void;
  /** What the run produced (changes-since only). */
  produced?: React.ReactNode;
}> = ({ projectId, run, dcIdByTag, dcTypeByTag, onOpenDc, produced }) => {
  const [data, setData] = useState<RunFiles | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<number | null>(null);
  const [onlyChanged, setOnlyChanged] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchProjectRunFiles(projectId, run.run_tag)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message || 'The files of this run could not be loaded.');
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, run.run_tag, run.scans.length]);

  const scans = data?.scans ?? [];
  const selected = scan ?? (scans.length > 0 ? scans.length - 1 : null);
  const picked = selected !== null ? scans[selected] : undefined;
  const brought = picked ? picked.new + picked.changed + picked.failed : 0;
  // On by default when the scan changed something: that is what one looks for.
  const narrow = (onlyChanged ?? brought > 0) && brought > 0;

  const groups = useMemo(() => {
    const byTag = new Map<string, { file: RunFile; state: FileState }[]>();
    const totals = new Map<string, number>();
    for (const file of data?.files ?? []) {
      const tag = file.dc_tag ?? 'unknown';
      const state = selected === null ? 'unchanged' : stateIn(file, selected);
      if (state === null) continue;
      totals.set(tag, (totals.get(tag) ?? 0) + 1);
      if (narrow && state === 'unchanged') continue;
      const list = byTag.get(tag) ?? [];
      list.push({ file, state });
      byTag.set(tag, list);
    }
    // Every collection that reads per run, with nothing found first: that is
    // why a run is incomplete.
    const tags = new Set([...Object.keys(run.dc_files), ...totals.keys()]);
    return [...tags]
      .map((tag) => ({ tag, total: totals.get(tag) ?? 0, rows: byTag.get(tag) ?? [] }))
      .filter((g) => !narrow || g.rows.length > 0 || g.total === 0)
      .sort((a, b) => Number(a.total > 0) - Number(b.total > 0) || a.tag.localeCompare(b.tag));
  }, [data, selected, narrow, run.dc_files]);

  const folder = run.run_location;
  const body = (
    <Grid gutter="lg">
      <Grid.Col span={{ base: 12, md: 8 }}>
        <SectionLabel
          icon="mdi:file-multiple-outline"
          right={
            brought > 0 ? (
              <Switch
                size="xs"
                checked={narrow}
                onChange={(e) => setOnlyChanged(e.currentTarget.checked)}
                label="Only what this scan changed"
                data-testid="run-files-only-changed"
              />
            ) : undefined
          }
        >
          Files
        </SectionLabel>
        {error ? (
          <Alert color="red" variant="light">
            {error}
          </Alert>
        ) : !data ? (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">
              Reading the files of this run
            </Text>
          </Group>
        ) : groups.length === 0 ? (
          <Text size="sm" c="dimmed">
            No collection reads files per run.
          </Text>
        ) : (
          <Stack gap="xs" data-testid="run-files">
            {groups.map((g) => (
              <CollectionFiles
                key={g.tag}
                tag={g.tag}
                type={dcTypeByTag[g.tag] ?? 'table'}
                dcId={dcIdByTag[g.tag]}
                total={g.total}
                rows={g.rows}
                scan={selected}
                runFolder={folder}
                onOpenDc={onOpenDc}
              />
            ))}
            {data.truncated && (
              <Text size="xs" c="dimmed">
                Only the first {data.files.length.toLocaleString()} files are listed.
              </Text>
            )}
          </Stack>
        )}
      </Grid.Col>
      <Grid.Col span={{ base: 12, md: 4 }}>
        <SectionLabel icon="mdi:history">Scans</SectionLabel>
        {scans.length === 0 ? (
          <Text size="sm" c="dimmed">
            {data ? 'Never scanned.' : ''}
          </Text>
        ) : (
          <Stack gap={4} data-testid="run-scans">
            {scans
              .map((s, i) => ({ s, i }))
              .reverse()
              .map(({ s, i }) => {
                const active = i === selected;
                return (
                  <UnstyledButton
                    key={`${s.scan_time}-${i}`}
                    onClick={() => setScan(i)}
                    px="sm"
                    py={6}
                    aria-pressed={active}
                    data-testid="run-scan"
                    data-active={active || undefined}
                    style={{
                      borderRadius: 'var(--mantine-radius-sm)',
                      border: `1px solid ${active ? 'var(--mantine-primary-color-filled)' : 'var(--mantine-color-default-border)'}`,
                      background: active ? 'var(--mantine-primary-color-light)' : undefined,
                    }}
                  >
                    <Group justify="space-between" wrap="nowrap" gap="xs">
                      <Text size="sm" fw={active ? 600 : 400} style={{ whiteSpace: 'nowrap' }}>
                        {when(s.scan_time)}
                      </Text>
                      {i === scans.length - 1 && (
                        <Text size="xs" c="dimmed">
                          latest
                        </Text>
                      )}
                    </Group>
                    <Group gap={4} mt={4} wrap="wrap">
                      {s.new > 0 && (
                        <StatusBadge size="xs" color={FILE_STATE.new.color}>
                          {s.new} new
                        </StatusBadge>
                      )}
                      {s.changed > 0 && (
                        <StatusBadge size="xs" color={FILE_STATE.changed.color}>
                          {s.changed} changed
                        </StatusBadge>
                      )}
                      {s.failed > 0 && (
                        <StatusBadge size="xs" color={FILE_STATE.failed.color}>
                          {s.failed} failed
                        </StatusBadge>
                      )}
                      {s.new + s.changed + s.failed === 0 && (
                        <Text size="xs" c="dimmed">
                          Nothing changed
                        </Text>
                      )}
                    </Group>
                  </UnstyledButton>
                );
              })}
          </Stack>
        )}
      </Grid.Col>
    </Grid>
  );

  return (
    <Paper withBorder radius="md" p="md" my="xs" data-testid={`run-details-${run.run_tag}`}>
      <Stack gap="md">
        {folder && (
          <Group gap={6} wrap="nowrap" align="flex-start">
            <Icon icon="mdi:folder-outline" width={16} style={{ opacity: 0.6, flexShrink: 0, marginTop: 2 }} />
            <Text size="sm" ff="monospace" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
              {folder}
            </Text>
            <CopyButton value={folder} timeout={1500}>
              {({ copied, copy }) => (
                <Tooltip label={copied ? 'Copied' : 'Copy the folder path'} withArrow>
                  <ActionIcon
                    size="sm"
                    variant="subtle"
                    color="gray"
                    onClick={copy}
                    aria-label="Copy the folder path"
                    data-testid={`run-copy-path-${run.run_tag}`}
                  >
                    <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={14} />
                  </ActionIcon>
                </Tooltip>
              )}
            </CopyButton>
          </Group>
        )}
        {folder ? <RunFileScope dataRoot={folder}>{body}</RunFileScope> : body}
        {produced}
      </Stack>
    </Paper>
  );
};

export default RunDetails;
