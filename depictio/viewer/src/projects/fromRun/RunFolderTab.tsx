/**
 * The "From a run folder" tab of the create-project dialog: Source, Preview,
 * Create.
 *
 * Source takes the run folder (typed, or picked in the folder browser) and
 * reads it as soon as it is known: the detection card says which pipeline
 * and version made the run and which template Depictio would use. Detection
 * also fills the Pipeline and Template version fields, marked "Detected",
 * which the reader may change. Leaving them empty lets the server recognise
 * the pipeline itself when the plan is previewed.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Paper,
  Stack,
  Stepper,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  apiErrorCode,
  createProjectFromRun,
  defaultVersionFor,
  findRunPipeline,
  groupRunTemplates,
  inspectFolder,
  isS3Location,
  runCollectionTotals,
  runFoundNothing,
  runTemplateMatch,
  useBrandAccents,
} from 'depictio-react-core';
import type { FromRunReport, FromRunRequest, TemplateInfo } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';
import FolderBrowserModal from './browser/FolderBrowserModal';
import { DetectionCard } from './DetectionCard';
import type { DetectionState } from './DetectionCard';
import { rememberRunFolder } from './recentFolders';
import type { RunCreatedContext } from './RunCreatedModal';
import { RunPreview, RunSummaryCard, TemplateNotDetectedAlert } from './RunPreview';
import { TemplatePicker } from './TemplatePicker';

/** Stack id of the folder browser, which opens above the create dialog. */
const BROWSE_STACK_ID = 'run-folder-browser';

/** How long typing pauses before the folder is read. */
const INSPECT_DELAY_MS = 450;

/** A location the server reads from its own disk: absolute, or under the
 *  server user's home. */
function isLocalPath(location: string): boolean {
  return location.startsWith('/') || location.startsWith('~/') || location === '~';
}

/** The template choice, and where it came from: detection may replace its
 *  own choice when the folder changes, never one the reader made. */
interface Choice {
  templateId: string | null;
  from: 'detected' | 'user' | null;
}

const NO_CHOICE: Choice = { templateId: null, from: null };

interface RunFolderTabProps {
  /** The create dialog is open: every opening starts afresh. */
  opened: boolean;
  existingNames: string[];
  templates: TemplateInfo[];
  templatesError: string | null;
  /** The server reads run folders from its own disk (`depictio local`). */
  localDataRootsEnabled: boolean;
  /** The server may browse allowed S3 locations. */
  remoteBrowseEnabled: boolean;
  onCreateFromRun: (input: FromRunRequest, context: RunCreatedContext) => Promise<FromRunReport>;
  submitting: boolean;
  setSubmitting: (submitting: boolean) => void;
}

const RunFolderTab: React.FC<RunFolderTabProps> = ({
  opened,
  existingNames,
  templates,
  templatesError,
  localDataRootsEnabled,
  remoteBrowseEnabled,
  onCreateFromRun,
  submitting,
  setSubmitting,
}) => {
  const accent = useBrandAccents();
  const [step, setStep] = useState(0);
  const [dataRoot, setDataRoot] = useState('');
  /** The folder last read, `INSPECT_DELAY_MS` after typing stops (at once
   *  for a folder picked in the browser). */
  const [inspectTarget, setInspectTarget] = useState('');
  const [detection, setDetection] = useState<DetectionState>({ status: 'idle' });
  const [choice, setChoice] = useState<Choice>(NO_CHOICE);
  const [projectName, setProjectName] = useState('');
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<FromRunReport | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  /** The server's explanation when detection found no template (422
   *  `template_not_detected`): a "pick a template" state, not a failure. */
  const [notDetected, setNotDetected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [browseOpened, setBrowseOpened] = useState(false);

  const browseEnabled = localDataRootsEnabled || remoteBrowseEnabled;

  useEffect(() => {
    if (!opened) return;
    setStep(0);
    setDataRoot('');
    setInspectTarget('');
    setDetection({ status: 'idle' });
    setChoice(NO_CHOICE);
    setProjectName('');
    setVariables({});
    setPreview(null);
    setPreviewError(null);
    setNotDetected(null);
    setError(null);
    setBrowseOpened(false);
  }, [opened]);

  const trimmedRoot = dataRoot.trim();
  // The server reads an s3:// location, plus, when it allows local folders,
  // a path on its own disk. Anything else is refused here with the reason
  // spelled out rather than sent for a 422.
  const rootReadable = (location: string) =>
    isS3Location(location) || (localDataRootsEnabled && isLocalPath(location));
  const prefixInvalid = trimmedRoot.length > 0 && !rootReadable(trimmedRoot);

  useEffect(() => {
    const timer = window.setTimeout(() => setInspectTarget(trimmedRoot), INSPECT_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [trimmedRoot]);

  // Read the folder: what it holds, which pipeline made it, which template
  // fits. A newer folder cancels the request still in flight.
  useEffect(() => {
    if (!opened) return undefined;
    const location = inspectTarget;
    if (!location || !rootReadable(location)) {
      setDetection({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setDetection({ status: 'loading', location });
    inspectFolder(location, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setDetection({ status: 'ready', location, result });
        const detectedId = result.detected?.template_id ?? null;
        setChoice((prev) => {
          if (prev.from === 'user') return prev;
          if (detectedId) return { templateId: detectedId, from: 'detected' };
          return prev.from === 'detected' ? NO_CHOICE : prev;
        });
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return;
        setDetection({
          status: 'error',
          location,
          error: err.message || 'This folder could not be read.',
        });
      });
    return () => controller.abort();
    // `rootReadable` only reads `localDataRootsEnabled`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, inspectTarget, localDataRootsEnabled]);

  // What the card shows: the current folder's reading, "loading" while the
  // reader is still typing, nothing for an empty or unreadable field.
  const detectionView: DetectionState = useMemo(() => {
    if (!trimmedRoot || prefixInvalid) return { status: 'idle' };
    if (detection.status !== 'idle' && detection.location === trimmedRoot) return detection;
    return { status: 'loading', location: trimmedRoot };
  }, [detection, trimmedRoot, prefixInvalid]);

  const inspection = detectionView.status === 'ready' ? detectionView.result : null;
  const detected = inspection?.detected ?? null;
  const detectedId = detected?.template_id ?? null;

  const groups = useMemo(
    () =>
      groupRunTemplates(
        templates,
        [choice.templateId, detectedId].filter((id): id is string => Boolean(id)),
      ),
    [templates, choice.templateId, detectedId],
  );
  const pipeline = findRunPipeline(groups, choice.templateId);
  const detectedPipeline = findRunPipeline(groups, detectedId);
  const titleOf = (id: string | null | undefined): string | null =>
    (id && templates.find((t) => t.template_id === id)?.name) || null;

  const selectedTemplate = templates.find((t) => t.template_id === choice.templateId) ?? null;
  // DATA_ROOT is injected server-side from the run folder field, so it never
  // gets a form input of its own.
  const extraVariables = (selectedTemplate?.variables ?? []).filter((v) => v.name !== 'DATA_ROOT');

  // The card shows the template that would be used: the one chosen, else the
  // one detection picked.
  const usedTemplateId = choice.templateId ?? detectedId;
  const match = runTemplateMatch({
    runPipeline: detected?.pipeline,
    runVersion: detected?.version,
    templateId: usedTemplateId,
    detectedTemplateId: detectedId,
    detectedMatch: detected?.match ?? null,
  });

  const changeDataRoot = (value: string) => {
    setDataRoot(value);
    // A template detection picked belongs to the folder it was detected in.
    setChoice((prev) => (prev.from === 'detected' ? NO_CHOICE : prev));
  };

  const handlePipelineChange = (key: string | null) => {
    if (!key) {
      setChoice(NO_CHOICE);
      return;
    }
    const picked = groups.flatMap((g) => g.pipelines).find((p) => p.key === key);
    if (!picked) return;
    const templateId = defaultVersionFor(picked, {
      detectedTemplateId: detectedId,
      runVersion: detected?.version ?? null,
    });
    setChoice({ templateId, from: 'user' });
  };

  const trimmedName = projectName.trim();
  const nameUsed =
    trimmedName.length > 0 &&
    existingNames.some((n) => n.toLowerCase() === trimmedName.toLowerCase());

  const buildRequest = (dryRun: boolean): FromRunRequest => {
    const values: Record<string, string> = {};
    for (const v of extraVariables) {
      const value = (variables[v.name] ?? '').trim();
      if (value) values[v.name] = value;
    }
    return {
      dataRoot: trimmedRoot,
      templateId: choice.templateId,
      projectName: trimmedName || null,
      ...(Object.keys(values).length > 0 ? { variables: values } : {}),
      dryRun,
    };
  };

  // Dry-run plan, re-fetched every time the Preview step is entered so a
  // Previous then Next round-trip picks up edited inputs.
  useEffect(() => {
    if (!opened || step !== 1 || !trimmedRoot) return undefined;
    let cancelled = false;
    const detecting = choice.templateId === null;
    setPreview(null);
    setPreviewError(null);
    setNotDetected(null);
    setPreviewLoading(true);
    createProjectFromRun(buildRequest(true))
      .then((report) => {
        if (cancelled) return;
        setPreview(report);
        // Show the recognised template as the choice, still editable: going
        // back lists its variables, and Create uses exactly what was previewed.
        if (detecting && report.template_id) {
          setChoice({ templateId: report.template_id, from: 'detected' });
        }
      })
      .catch((err: Error) => {
        if (cancelled) return;
        if (detecting && apiErrorCode(err) === 'template_not_detected') {
          setNotDetected(err.message || 'The pipeline that produced this folder was not recognised.');
        } else {
          setPreviewError(err.message || 'Failed to preview the run folder.');
        }
      })
      .finally(() => {
        if (!cancelled) setPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Inputs are frozen while on the Preview step, so entering it is the only
    // dependency that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, step]);

  const foundNothing = step > 0 && !!preview && runFoundNothing(preview.data_collections);
  const totals = preview ? runCollectionTotals(preview.data_collections) : null;
  // The folder was read and nothing in it names a template: previewing would
  // only come back with "not recognised", so ask for the pipeline now.
  const noTemplateForFolder =
    step === 0 && !choice.templateId && inspection !== null && !detectedId;

  // Disabled with a visible reason rather than hidden (project convention).
  let disabledReason: string | null = null;
  if (trimmedRoot.length === 0) {
    disabledReason = browseEnabled
      ? 'Enter or browse to the run folder.'
      : 'Enter the location of the run folder.';
  } else if (prefixInvalid) {
    disabledReason = localDataRootsEnabled
      ? 'The run folder must be a folder path or an s3:// location.'
      : 'The run folder must be an s3:// location.';
  } else if (nameUsed) {
    disabledReason = 'A project with this name already exists.';
  } else if (noTemplateForFolder) {
    disabledReason = 'No template matches this folder: pick the pipeline below.';
  } else if (
    step === 1 &&
    (previewLoading || (!preview && !previewError && !notDetected))
  ) {
    // Between entering the step and the effect firing there is no preview
    // and no error yet: that is still "loading", not a failure.
    disabledReason = 'Reading the run folder.';
  } else if (step === 1 && notDetected) {
    disabledReason = 'The pipeline was not recognised: pick a template first.';
  } else if (step === 1 && previewError) {
    disabledReason = 'The run folder could not be read.';
  } else if (foundNothing) {
    disabledReason = 'No data collection matched anything in this folder.';
  }

  const handleSubmit = async () => {
    if (disabledReason) return;
    if (step === 0) rememberRunFolder(trimmedRoot);
    if (step < 2) {
      setStep(step + 1);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreateFromRun(buildRequest(false), {
        templateTitle: titleOf(choice.templateId ?? preview?.template_id),
        detection: detected,
      });
    } catch (err) {
      setError((err as Error).message || 'Failed to create project from run folder.');
    } finally {
      setSubmitting(false);
    }
  };

  const displayName =
    preview?.project_name || trimmedName || selectedTemplate?.name || 'project';

  return (
    <Stack gap="md">
      <Stepper
        active={step}
        onStepClick={setStep}
        color={accent.secondary}
        size="sm"
        allowNextStepsSelect={false}
      >
        <Stepper.Step label="Source" description="Run folder & template">
          <Stack gap="md" pt="md">
            <TextInput
              label="Run folder"
              description={
                localDataRootsEnabled
                  ? 'The output folder of one pipeline run: a folder on this computer (a full path, or one starting with ~/) or an s3:// location.'
                  : "The s3:// location of one pipeline run's output folder."
              }
              required
              placeholder={localDataRootsEnabled ? '~/results/run42' : 's3://bucket/results/run42/'}
              value={dataRoot}
              onChange={(e) => changeDataRoot(e.currentTarget.value)}
              leftSection={<Icon icon="mdi:folder-search-outline" width={16} />}
              error={
                prefixInvalid
                  ? localDataRootsEnabled
                    ? 'Enter a full folder path, a path starting with ~/, or an s3:// location.'
                    : 'The run folder must be an s3:// location.'
                  : undefined
              }
              spellCheck={false}
              // The Browse button sits beside the input itself, under the
              // label and above any error.
              inputContainer={(input) =>
                browseEnabled ? (
                  <Group gap="xs" wrap="nowrap" align="flex-start">
                    <Box style={{ flex: 1, minWidth: 0 }}>{input}</Box>
                    <Button
                      variant="default"
                      leftSection={<Icon icon="mdi:folder-open-outline" width={16} />}
                      onClick={() => setBrowseOpened(true)}
                      data-testid="run-browse-local"
                    >
                      Browse
                    </Button>
                  </Group>
                ) : (
                  input
                )
              }
              data-testid="run-data-root-input"
            />

            <DetectionCard
              state={detectionView}
              templateId={usedTemplateId}
              templateTitle={titleOf(usedTemplateId)}
              match={match}
              onUseDetected={
                detectedId ? () => setChoice({ templateId: detectedId, from: 'detected' }) : undefined
              }
            />

            <TemplatePicker
              groups={groups}
              pipeline={pipeline}
              templateId={choice.templateId}
              runVersion={detected?.version ?? null}
              pipelineDetected={Boolean(pipeline && detectedPipeline && pipeline.key === detectedPipeline.key)}
              versionDetected={Boolean(choice.templateId && choice.templateId === detectedId)}
              onPipelineChange={handlePipelineChange}
              onVersionChange={(templateId) => setChoice({ templateId, from: 'user' })}
              error={templatesError}
            />

            <TextInput
              label="Project Name (Optional)"
              description="Defaults to a name derived from the template"
              placeholder="Enter project name"
              value={projectName}
              onChange={(e) => setProjectName(e.currentTarget.value)}
              leftSection={<Icon icon="mdi:folder-outline" width={16} />}
              error={nameUsed ? 'A project with this name already exists.' : undefined}
              data-testid="run-project-name-input"
            />
            {extraVariables.map((v) => (
              <TextInput
                key={v.name}
                label={`${v.name} (Optional)`}
                description={v.description ?? undefined}
                placeholder={v.default ?? ''}
                value={variables[v.name] ?? ''}
                onChange={(e) => {
                  const value = e.currentTarget.value;
                  setVariables((prev) => ({ ...prev, [v.name]: value }));
                }}
              />
            ))}
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Preview" description="What each collection gets">
          <Stack gap="md" pt="md">
            <Box aria-live="polite" role="status">
              {previewLoading && (
                <Center mih={120}>
                  <Group gap="xs">
                    <Loader size="sm" color={accent.secondary} />
                    <Text size="sm" c="dimmed">
                      {choice.templateId
                        ? 'Reading the run folder and resolving the template...'
                        : 'Reading the run folder and recognising its pipeline...'}
                    </Text>
                  </Group>
                </Center>
              )}
            </Box>
            {notDetected && (
              <TemplateNotDetectedAlert message={notDetected} onPickTemplate={() => setStep(0)} />
            )}
            {previewError && (
              <Alert
                color="red"
                variant="light"
                icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
                data-testid="run-preview-error"
              >
                {previewError}
              </Alert>
            )}
            {foundNothing && (
              <Alert
                color="red"
                variant="light"
                icon={<Icon icon="mdi:alert-circle" width={16} />}
                title="Nothing to ingest in this folder"
                data-testid="run-no-match-warning"
              >
                <Text size="sm">
                  No data collection matched anything here. The paths under &ldquo;Not
                  found&rdquo; are what was looked for: a run folder set one level too high, or
                  too low, is the usual cause.
                </Text>
              </Alert>
            )}
            {preview && (
              <RunPreview
                report={preview}
                templateTitle={titleOf(preview.template_id)}
                detection={detected}
              />
            )}
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Create" description="Confirm & ingest">
          <Stack gap="md" pt="md">
            {preview && (
              <RunSummaryCard
                report={preview}
                templateTitle={titleOf(preview.template_id)}
                detection={detected}
              />
            )}
            <Paper withBorder radius="md" p="lg">
              <Stack gap="sm" align="center">
                <Icon
                  icon="mdi:rocket-launch-outline"
                  width={36}
                  color={`var(--mantine-color-${accent.secondary}-6)`}
                />
                <Text fw={500} ta="center">
                  Create &ldquo;{displayName}&rdquo;
                </Text>
                <Text size="xs" c="dimmed" ta="center">
                  {totals
                    ? `${totals.ready} of ${totals.considered} data ` +
                      `collection${totals.considered === 1 ? '' : 's'} will ` +
                      'be ingested in the background. You can watch the run ' +
                      'and open the dashboard from the next screen.'
                    : 'The run folder will be ingested and the template dashboards imported.'}
                </Text>
              </Stack>
            </Paper>
          </Stack>
        </Stepper.Step>
      </Stepper>

      {error && (
        <Alert
          color="red"
          variant="light"
          icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
          data-testid="run-create-error"
        >
          {error}
        </Alert>
      )}

      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Button
          variant="default"
          onClick={() => setStep((s) => Math.max(0, s - 1))}
          disabled={step === 0 || submitting}
          data-testid="run-previous"
        >
          Previous
        </Button>
        <Stack gap={4} align="flex-end" style={{ minWidth: 0 }}>
          <GatedButton
            color={accent.secondary}
            onClick={handleSubmit}
            loading={submitting}
            reason={disabledReason}
            data-testid="create-from-run-submit"
          >
            {step === 2 ? 'Create Project' : 'Next'}
          </GatedButton>
          <DisabledReason
            reason={disabledReason}
            icon="mdi:information-outline"
            testId="run-submit-disabled-reason"
          />
        </Stack>
      </Group>

      {browseEnabled && (
        <FolderBrowserModal
          stackId={BROWSE_STACK_ID}
          opened={opened && browseOpened}
          onClose={() => setBrowseOpened(false)}
          onSelect={(path) => {
            changeDataRoot(path);
            setInspectTarget(path);
            setBrowseOpened(false);
          }}
          initialLocation={trimmedRoot}
          localEnabled={localDataRootsEnabled}
          s3Enabled={remoteBrowseEnabled}
          templates={templates}
        />
      )}
    </Stack>
  );
};

export default RunFolderTab;
