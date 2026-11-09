/**
 * Another output folder of the project's pipeline.
 *
 * The folder is checked as a dry run (`attachRun`) once typing pauses, and the
 * answer is shown as a "What Depictio found" card. The server refuses what it
 * cannot add with a code (`not_a_pipeline_project`, `other_pipeline`,
 * `already_attached`, `cannot_attach`, `run_name_clash`). The real call returns
 * an ingestion run, followed with `getManifestRefreshRun`.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Group, Loader, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { apiErrorCode, attachRun, isS3Location } from 'depictio-react-core';
import type { AttachRunReport, ManifestRefreshReport } from 'depictio-react-core';

import { plural } from '../../fromRun/plural';
import { formatElapsed, manifestRunOutcome, summarizeManifestRun, useElapsedMs, useManifestRunPoll } from '../../manifestRun';
import type { ManifestRunOutcome } from '../../manifestRun';
import { FoundCard, RunChips, SourceValue } from '../FoundCard';
import type { FoundRow } from '../FoundCard';
import { refusalText, SERVER_CREDENTIALS_MISSING } from './useLocationPicker';
import type { LocationPicker } from './useLocationPicker';

/** Refusals the server explains with a message worth showing as is. */
const REFUSAL_CODES = new Set([
  'not_a_pipeline_project',
  'other_pipeline',
  'already_attached',
  'cannot_attach',
  'run_name_clash',
  SERVER_CREDENTIALS_MISSING,
]);

interface Options {
  /** False on a project with no pipeline to add a run of: nothing is read. */
  enabled: boolean;
  opened: boolean;
  projectId: string | null;
  /** "nf-core/rnaseq 3.14.0": the project's pipeline, for the card. */
  pipelineLabel: string | null;
  picker: LocationPicker;
  /** A run was added (its ingestion ended): reload the project. */
  onAdded: () => void;
}

interface Refusal {
  code: string | null;
  message: string;
  /** A refusal the server explains (yellow), not a failure to read (red). */
  known: boolean;
}

function foundRows(report: AttachRunReport, location: string, pipelineLabel: string | null): FoundRow[] {
  const detectedLabel = report.detected?.pipeline
    ? `${report.detected.pipeline}${report.detected.version ? ` ${report.detected.version}` : ''}`
    : pipelineLabel;
  const same = report.match === 'exact';
  const pipelineRow: FoundRow = {
    key: 'pipeline',
    label: 'Pipeline',
    value: <Text size="sm">{detectedLabel ?? 'Not recognised'}</Text>,
    status: same ? 'ok' : 'differs',
    hint: same
      ? 'same as this project'
      : report.match === 'other_pipeline'
        ? 'another pipeline than this project'
        : 'versions differ',
  };
  const collected = report.data_collections.filter(
    (c) => c.status === 'ok' && c.matched > 0,
  ).length;
  const kept = report.data_collections.filter((c) => c.status === 'kept').length;
  return [
    pipelineRow,
    {
      key: 'runs',
      label: 'Runs',
      value:
        report.new_runs.length > 0 ? (
          <Stack gap={4}>
            <Text size="sm">{plural(report.new_runs.length, 'new run')}</Text>
            <RunChips names={report.new_runs} />
          </Stack>
        ) : (
          <Text size="sm">No new run</Text>
        ),
      hint:
        report.existing_runs.length > 0
          ? `${report.existing_runs.length} already in the project`
          : undefined,
    },
    {
      key: 'source',
      label: 'Source',
      value: <SourceValue kind={isS3Location(location) ? 's3' : 'folder'} location={report.data_root || location} />,
    },
    {
      key: 'contents',
      label: 'Contents',
      value: (
        <Stack gap={2}>
          <Text size="sm">
            {collected === 1
              ? '1 collection will get its files'
              : `${collected} collections will get its files`}
          </Text>
          {kept > 0 && (
            <Text size="xs" c="dimmed">
              {kept === 1
                ? '1 collection keeps its file from the first run'
                : `${kept} collections keep their file from the first run`}
            </Text>
          )}
        </Stack>
      ),
    },
  ];
}

export function useAttachRun({ enabled, opened, projectId, pipelineLabel, picker, onAdded }: Options) {
  const { target, epoch, storageFor, noteRefusal } = picker;
  const [report, setReport] = useState<AttachRunReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [progress, setProgress] = useState<ManifestRefreshReport | null>(null);
  const [followError, setFollowError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [added, setAdded] = useState(false);

  const following = runId !== null;
  const busy = submitting || following;

  // Check the folder whenever it settles. Not while a run is being followed:
  // the dialog then shows that run, whatever the field holds.
  useEffect(() => {
    if (busy || added) return undefined;
    setSubmitError(null);
    if (!enabled || !opened || !projectId || !target || picker.invalid) {
      setReport(null);
      setRefusal(null);
      setLoading(false);
      return undefined;
    }
    const controller = new AbortController();
    setLoading(true);
    setRefusal(null);
    setReport(null);
    attachRun(
      projectId,
      { dataRoot: target, dryRun: true, storage: storageFor(target) },
      { signal: controller.signal },
    )
      .then((r) => {
        if (!controller.signal.aborted) setReport(r);
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        const code = apiErrorCode(err);
        setRefusal({
          code,
          message: refusalText(err.message || 'This folder could not be checked.', code),
          known: code !== null && REFUSAL_CODES.has(code),
        });
        noteRefusal(target, code);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, opened, projectId, target, epoch, picker.invalid, busy, added]);

  // Every opening starts afresh, unless a run is still being followed.
  useEffect(() => {
    if (opened || following) return;
    setReport(null);
    setRefusal(null);
    setProgress(null);
    setFollowError(null);
    setSubmitError(null);
    setStartedAt(null);
    setFinishedAt(null);
    setAdded(false);
  }, [opened, following]);

  const finish = useCallback(() => {
    setAdded(true);
    onAdded();
  }, [onAdded]);

  useManifestRunPoll({
    runId,
    startedAt,
    onReport: setProgress,
    onStop: (pollError) => {
      if (pollError) setFollowError(pollError);
      setRunId(null);
      setFinishedAt(Date.now());
      finish();
    },
    pollErrorMessage: (err) =>
      `Lost track of the ingestion run: ${err.message}. The workers keep going; the project's Ingestion tab shows the outcome.`,
    timeoutMessage:
      "Stopped following after 30 minutes. Ingestion may still be running; the project's Ingestion tab shows the outcome.",
  });
  const elapsed = useElapsedMs(following, startedAt, finishedAt);

  let reason: string | null = null;
  if (picker.invalid) reason = 'Enter a folder path or an s3:// location.';
  else if (picker.storageProblem) reason = `Private bucket: ${picker.storageProblem}`;
  else if (loading || (!report && !refusal)) reason = 'Checking the run folder.';
  else if (refusal) reason = refusal.known ? refusal.message : 'The run folder could not be checked.';
  else if (report && report.new_runs.length === 0)
    reason = 'This folder holds no run that is not in the project yet.';

  const submit = async () => {
    if (!projectId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const done = await attachRun(projectId, {
        dataRoot: target,
        dryRun: false,
        storage: storageFor(target),
      });
      if (done.run_id) {
        setProgress(null);
        setFollowError(null);
        setFinishedAt(null);
        setStartedAt(Date.now());
        setRunId(done.run_id);
      } else {
        finish();
      }
    } catch (err) {
      setSubmitError((err as Error).message || 'Failed to add the run.');
    } finally {
      setSubmitting(false);
    }
  };

  let outcome: ManifestRunOutcome | null = null;
  if (added && finishedAt != null) outcome = manifestRunOutcome(progress);
  const summary = progress ? summarizeManifestRun(progress) : null;
  const showFollow = following || added;

  const isNewRun = Boolean(report && report.new_runs.length > 0);

  /** What the folder is, before anything is added. */
  const view = (
    <>
          {loading && (
            <Group gap="xs" data-testid="attach-run-loading">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                Checking the run folder
              </Text>
            </Group>
          )}

          {refusal && !loading && (
            <Alert
              color={refusal.known ? 'yellow' : 'red'}
              icon={<Icon icon="mdi:alert-outline" width={18} />}
              data-testid="attach-run-refusal"
              data-code={refusal.code ?? undefined}
            >
              {refusal.message}
            </Alert>
          )}

          {report && !loading && (
            <>
              <FoundCard rows={foundRows(report, picker.trimmed, pipelineLabel)} testId="attach-run-found" />
              {report.warnings.length > 0 && (
                <Alert color="yellow" icon={<Icon icon="mdi:alert-outline" width={18} />} data-testid="attach-run-warnings">
                  <Stack gap={2}>
                    {report.warnings.map((w) => (
                      <Text key={w} size="sm">
                        {w}
                      </Text>
                    ))}
                  </Stack>
                </Alert>
              )}
            </>
          )}

    </>
  );

  /** The run being followed, once it was sent. */
  const followView = (
    <>
          {showFollow && (
            <Stack gap="xs" data-testid="attach-run-progress" data-state={following ? 'running' : (outcome ?? 'done')}>
              <Group gap="xs">
                {following ? (
                  <Loader size="xs" />
                ) : (
                  <Icon
                    icon={outcome === 'failed' ? 'mdi:alert-circle-outline' : 'mdi:check-circle-outline'}
                    width={18}
                  />
                )}
                <Text size="sm" fw={500}>
                  {following
                    ? `Refreshing the project's collections with the new run (${formatElapsed(elapsed)})`
                    : outcome === 'failed'
                      ? 'The run was added, ingestion finished with errors'
                      : outcome === 'stopped'
                        ? 'The run was added, ingestion is still going'
                        : 'The run was added'}
                </Text>
              </Group>
              {summary && (
                <Text size="xs" c="dimmed" data-testid="attach-run-progress-summary">
                  Every collection of the project is checked; only those with files in the new run
                  change. Checked so far: {summary}.
                </Text>
              )}
              {followError && (
                <Alert color="yellow" data-testid="attach-run-follow-error">
                  {followError}
                </Alert>
              )}
            </Stack>
          )}

          {submitError && (
            <Alert color="red" data-testid="attach-run-submit-error">
              {submitError}
            </Alert>
          )}

    </>
  );

  return {
    reason,
    refusal,
    loading,
    isNewRun,
    submitting,
    following,
    added,
    showFollow,
    submit,
    view,
    followView,
  };
}
