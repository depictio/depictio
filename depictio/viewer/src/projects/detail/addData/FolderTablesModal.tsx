/**
 * "From a folder or bucket": pick the tables of a folder, an s3:// location
 * or (a single file) a URL, one collection per file.
 *
 * The location is read as a dry run (`addTablesFromFolder`), which lists the
 * files: tables are ticked, other files are disabled with the reason. The
 * button then sends the ticked paths for real and the per-file results are
 * shown in the dialog until Done, which closes it and reloads the project.
 * Tables already in the project are listed, unticked and disabled.
 *
 * A single https:// URL, or an s3:// path that names one table file,
 * is not a folder: the dialog says so and offers the single-table dialog, whose
 * "From a URL" source (`createDataCollectionFromUrl`) takes it. It does not
 * call that endpoint itself, since the format and separator need choosing.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Badge, Button, Checkbox, Group, Loader, Modal, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { addTablesFromFolder, apiErrorCode } from 'depictio-react-core';
import type { FolderTableFile, FolderTablesReport, ProjectListEntry } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { projectSourceFileNames } from '../../layout';
import { fileSize } from '../../fromRun/fileSize';
import { plural } from '../../fromRun/plural';
import { refusalText, useLocationPicker } from './useLocationPicker';

/** The collection of this project a file is already read as, if any. The
 *  server sets it on a listing. */
function existingOf(f: FolderTableFile): FolderTableFile['existing'] {
  return f.existing ?? null;
}

const ALREADY_IN_PROJECT = 'Already in this project';
const SAME_NAME_IN_PROJECT = 'A file with this name is already in this project';
const baseName = (path: string): string => (path.split('/').pop() ?? path).toLowerCase();
/** A file that can be added: a table the project does not hold yet. */
const addable = (f: FolderTableFile): boolean => f.table && !existingOf(f);

const TABLE_FILE = /\.(csv|tsv|txt|parquet|feather)(\.(gz|bz2|zip))?$/i;

/** A location that names one file rather than a folder. */
export function isSingleFileLocation(location: string): boolean {
  if (/^https?:\/\//i.test(location)) return true;
  return /^s3:\/\//i.test(location) && TABLE_FILE.test(location) && !location.endsWith('/');
}

interface FolderTablesModalProps {
  opened: boolean;
  projectId: string | null;
  /** The project, to spot files named like a collection it already holds. */
  project?: ProjectListEntry | null;
  onClose: () => void;
  /** Tables were added: reload the project. */
  onAdded: () => void;
  /** Hand a single file URL over to the single-table dialog (From a URL). */
  onUseFiles: () => void;
}

export const FolderTablesModal: React.FC<FolderTablesModalProps> = ({
  opened,
  projectId,
  project,
  onClose,
  onAdded,
  onUseFiles,
}) => {
  const knownNames = useMemo(() => projectSourceFileNames(project), [project]);
  /** A new file named like a collection made from another source. */
  const sameName = (f: FolderTableFile): boolean =>
    addable(f) && knownNames.has(baseName(f.path));
  const picker = useLocationPicker({
    opened,
    label: 'Folder or bucket',
    description:
      'A folder on the server, an s3:// location, or the URL of one file. Its tables become collections.',
    testIdPrefix: 'folder-tables-location',
  });
  const { target, invalid, epoch, storageFor, noteRefusal } = picker;

  const [report, setReport] = useState<FolderTablesReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<FolderTablesReport | null>(null);

  const singleFile = target.length > 0 && isSingleFileLocation(target);

  useEffect(() => {
    if (!opened) {
      setReport(null);
      setReadError(null);
      setResult(null);
      setSubmitError(null);
      setTicked(new Set());
    }
  }, [opened]);

  // Read the location whenever it settles; a newer one cancels the request.
  useEffect(() => {
    setResult(null);
    setSubmitError(null);
    if (!opened || !projectId || !target || picker.invalid || singleFile) {
      setReport(null);
      setReadError(null);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setReadError(null);
    addTablesFromFolder(
      projectId,
      { location: target, dryRun: true, storage: storageFor(target) },
      { signal: controller.signal },
    )
      .then((r) => {
        if (controller.signal.aborted) return;
        setReport(r);
        setTicked(new Set(r.files.filter((f) => addable(f) && !sameName(f)).map((f) => f.path)));
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setReport(null);
        const code = apiErrorCode(err);
        setReadError(refusalText(err.message || 'This location could not be read.', code));
        noteRefusal(target, code);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // `storageFor` and `noteRefusal` are stable; `epoch` re-reads with new details.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, projectId, target, epoch, invalid, singleFile]);

  const tableCount = useMemo(() => report?.files.filter((f) => f.table).length ?? 0, [report]);
  const newCount = useMemo(() => report?.files.filter(addable).length ?? 0, [report]);
  const count = ticked.size;

  let reason: string | null = null;
  if (!picker.trimmed) reason = 'Enter or browse to a folder.';
  else if (picker.invalid) reason = 'Enter a folder path or an s3:// location.';
  else if (singleFile) reason = 'This is one file, not a folder: add it as one table from its URL.';
  else if (picker.storageProblem) reason = `Private bucket: ${picker.storageProblem}`;
  else if (loading || (!report && !readError)) reason = 'Reading the location.';
  else if (readError) reason = 'The location could not be read.';
  else if (tableCount === 0) reason = 'No table file was found in this location.';
  else if (newCount === 0) reason = 'Every table of this location is already in this project.';
  else if (count === 0) reason = 'Tick at least one table.';

  const toggle = (path: string, on: boolean) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(path);
      else next.delete(path);
      return next;
    });

  const submit = async () => {
    if (reason || !projectId || !report) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const done = await addTablesFromFolder(projectId, {
        location: target,
        files: report.files.filter((f) => ticked.has(f.path)).map((f) => f.path),
        dryRun: false,
        storage: storageFor(target),
      });
      setResult(done);
    } catch (err) {
      setSubmitError((err as Error).message || 'Failed to add the tables.');
    } finally {
      setSubmitting(false);
    }
  };

  const nameOf = (path: string) => report?.files.find((f) => f.path === path)?.name ?? path;
  const countOf = (status: string) =>
    result?.created.filter((c) => (c.status as string) === status).length ?? 0;
  const failed = countOf('failed');
  const skipped = countOf('skipped');
  const ingested = countOf('ingested');
  const finish = () => {
    if (ingested > 0) onAdded();
    onClose();
  };

  return (
    <>
      <Modal
        opened={opened}
        onClose={result ? finish : onClose}
        title="From a folder or bucket"
        size="lg"
        centered
        data-testid="folder-tables-modal"
      >
        <Stack gap="md">
          {picker.field}

          {singleFile && (
            <Alert color="blue" icon={<Icon icon="mdi:information-outline" width={18} />} data-testid="folder-tables-single-file">
              <Stack gap="xs" align="flex-start">
                <Text size="sm">
                  This points at a single file, not a folder. Add it as one table from its URL.
                </Text>
                <Button size="xs" variant="light" onClick={onUseFiles} data-testid="folder-tables-use-files">
                  Add this file
                </Button>
              </Stack>
            </Alert>
          )}

          {loading && (
            <Group gap="xs" data-testid="folder-tables-loading">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                Reading the location
              </Text>
            </Group>
          )}

          {readError && !loading && (
            <Alert color="red" data-testid="folder-tables-read-error">
              {readError}
            </Alert>
          )}

          {report && !loading && !result && (
            <Paper withBorder radius="md" p="sm" data-testid="folder-tables-files">
              <Stack gap={6}>
                {report.files.length === 0 && (
                  <Text size="sm" c="dimmed">
                    This location holds no file.
                  </Text>
                )}
                {report.files.map((f) => {
                  const existing = existingOf(f);
                  return (
                  <Checkbox
                    key={f.path}
                    checked={!existing && ticked.has(f.path)}
                    disabled={!f.table || Boolean(existing)}
                    data-existing={existing ? 'true' : undefined}
                    data-same-name={!existing && sameName(f) ? 'true' : undefined}
                    onChange={(e) => toggle(f.path, e.currentTarget.checked)}
                    data-testid={`folder-tables-file-${f.path}`}
                    label={
                      <Group gap={8} wrap="wrap">
                        <Text size="sm" span>
                          {f.path}
                        </Text>
                        <Text size="xs" c="dimmed" span>
                          {!existing && sameName(f)
                            ? `${[f.format?.toUpperCase(), fileSize(f.size)].filter(Boolean).join(', ')}. ${SAME_NAME_IN_PROJECT}`
                            : existing
                            ? existing.data_collection_tag
                              ? `${ALREADY_IN_PROJECT} (${existing.data_collection_tag})`
                              : ALREADY_IN_PROJECT
                            : f.table
                              ? [f.format?.toUpperCase(), fileSize(f.size)].filter(Boolean).join(', ')
                              : f.reason || 'not a table'}
                        </Text>
                      </Group>
                    }
                  />
                  );
                })}
                {tableCount > 0 && newCount === 0 && (
                  <Text size="sm" data-testid="folder-tables-nothing-new">
                    Nothing new to add: every table of this location is already in this project.
                  </Text>
                )}
                {report.truncated && (
                  <Text size="xs" c="dimmed">
                    Only the first files are listed.
                  </Text>
                )}
              </Stack>
            </Paper>
          )}

          {result && (
            <Stack gap={6} data-testid="folder-tables-results">
              {result.created.map((c) => {
                const status = c.status as string;
                const ok = status === 'ingested';
                const color = ok ? 'green' : status === 'skipped' ? 'gray' : 'red';
                const label = ok ? 'Ingested' : status === 'skipped' ? ALREADY_IN_PROJECT : 'Failed';
                return (
                <Group key={c.path} gap="xs" wrap="nowrap" align="flex-start" data-testid={`folder-tables-result-${c.path}`} data-status={status}>
                  <Icon
                    icon={ok ? 'mdi:check-circle-outline' : status === 'skipped' ? 'mdi:minus-circle-outline' : 'mdi:alert-circle-outline'}
                    width={18}
                    style={{ flexShrink: 0, marginTop: 2, color: `var(--mantine-color-${color}-6)` }}
                  />
                  <Stack gap={0}>
                    <Group gap={6}>
                      <Text size="sm">{c.data_collection_tag ?? nameOf(c.path)}</Text>
                      <Badge size="xs" variant="light" color={color}>
                        {label}
                      </Badge>
                    </Group>
                    {c.error && status !== 'skipped' && (
                      <Text size="xs" c="red">
                        {c.error}
                      </Text>
                    )}
                  </Stack>
                </Group>
                );
              })}
              <Text size="sm" data-testid="folder-tables-summary">
                {[
                  ingested > 0 || (failed === 0 && skipped === 0) ? `${plural(ingested, 'table')} added` : null,
                  skipped > 0 ? `${skipped} already in this project` : null,
                  failed > 0 ? `${failed} failed` : null,
                ]
                  .filter(Boolean)
                  .join(', ')}
                .
              </Text>
            </Stack>
          )}

          {submitError && (
            <Alert color="red" data-testid="folder-tables-submit-error">
              {submitError}
            </Alert>
          )}

          <Stack gap={6} align="flex-end">
            <Group gap="sm">
              {result ? (
                <Button onClick={finish} data-testid="folder-tables-done">
                  Done
                </Button>
              ) : (
                <Button variant="default" onClick={onClose} data-testid="folder-tables-cancel">
                  Cancel
                </Button>
              )}
              {!result && (
                <GatedButton
                  reason={reason}
                  loading={submitting}
                  onClick={submit}
                  data-testid="add-tables-submit"
                >
                  {count > 0 ? `Add ${plural(count, 'table')}` : 'Add tables'}
                </GatedButton>
              )}
            </Group>
            {!result && <DisabledReason reason={reason} testId="add-tables-reason" />}
          </Stack>
        </Stack>
      </Modal>
      {picker.browser}
    </>
  );
};

export default FolderTablesModal;
