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
 *
 * The tab holds the state and the requests; the Preview and Create steps
 * render in `RunFolderSteps`, and the private bucket's rules live in
 * `privateBucket.ts`.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Box, Button, Group, Stack, Stepper, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  apiErrorCode,
  createProjectFromRun,
  defaultVersionFor,
  findRunPipeline,
  groupRunTemplates,
  inspectFolder,
  isLocalFolderPath,
  isPrivateBucketRefusal,
  isS3Location,
  runFoundNothing,
  runStorageFieldErrors,
  runStorageFromFields,
  runTemplateMatch,
  s3BucketOf,
  storageForLocation,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  FromRunReport,
  FromRunRequest,
  RunStorageBinding,
  TemplateInfo,
} from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../components/settings/SettingsSections';
import { useStepSettling } from '../hooks/useStepSettling';
import FolderBrowserModal from './browser/FolderBrowserModal';
import { DetectionCard } from './DetectionCard';
import type { DetectionState } from './DetectionCard';
import { closeSection, followBucket, NO_PRIVATE_BUCKET, openSection } from './privateBucket';
import type { OpenPrivateBucketOptions, PrivateBucketState } from './privateBucket';
import { PrivateBucketSection } from './PrivateBucketSection';
import { rememberRunFolder } from './recentFolders';
import type { RunCreatedContext } from './RunCreatedModal';
import { RunCreateStep, RunPreviewStep } from './RunFolderSteps';
import { TemplatePicker } from './TemplatePicker';
import { TemplateSettingsSection } from './TemplateSettings';

/** Stack id of the folder browser, which opens above the create dialog. */
const BROWSE_STACK_ID = 'run-folder-browser';

/** How long typing pauses before the folder is read. */
const INSPECT_DELAY_MS = 450;

/** A location the server can read: an s3:// location, plus, when it allows
 *  local folders, a path on its own disk. */
function isReadableRoot(location: string, localEnabled: boolean): boolean {
  return isS3Location(location) || (localEnabled && isLocalFolderPath(location));
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
  /** Why the caller may not give a private bucket's connection details
   *  (public mode, non-admin); null when they may. */
  privateBucketDisabledReason?: string | null;
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
  privateBucketDisabledReason = null,
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
  const [privateBucket, setPrivateBucket] = useState<PrivateBucketState>(NO_PRIVATE_BUCKET);
  /** The preview was refused for want of the bucket's connection details. */
  const [previewNeedsBucket, setPreviewNeedsBucket] = useState(false);
  /** Bumped when the folder should be read again with other connection
   *  details (a successful test, the section closed). */
  const [storageEpoch, setStorageEpoch] = useState(0);

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
    setPrivateBucket(NO_PRIVATE_BUCKET);
    setPreviewNeedsBucket(false);
  }, [opened]);

  const trimmedRoot = dataRoot.trim();
  // A location the server cannot read is refused here with the reason
  // spelled out rather than sent for a 422.
  const prefixInvalid =
    trimmedRoot.length > 0 && !isReadableRoot(trimmedRoot, localDataRootsEnabled);

  useEffect(() => {
    const timer = window.setTimeout(() => setInspectTarget(trimmedRoot), INSPECT_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [trimmedRoot]);

  // The private bucket's connection details, once they can be sent: bound to
  // their bucket, so a read of anything else never carries them.
  const rootBucket = s3BucketOf(trimmedRoot);
  const storageFieldErrors = useMemo(
    () => runStorageFieldErrors(privateBucket.fields),
    [privateBucket.fields],
  );
  const storageProblem = Object.values(storageFieldErrors)[0] ?? null;
  const storageBinding = useMemo<RunStorageBinding | null>(() => {
    if (privateBucketDisabledReason || !privateBucket.open || !privateBucket.bucket) return null;
    if (storageProblem) return null;
    const storage = runStorageFromFields(privateBucket.fields);
    return storage ? { bucket: privateBucket.bucket, storage } : null;
  }, [privateBucketDisabledReason, privateBucket, storageProblem]);
  /** Read by the detection effect, which re-runs on a new folder or a
   *  successful test, not on every keystroke in the connection details. */
  const storageBindingRef = useRef(storageBinding);
  storageBindingRef.current = storageBinding;
  const rootStorage = storageForLocation(trimmedRoot, storageBinding);
  // With a private bucket's details, its folders can be browsed even where
  // the server lists no S3 location of its own.
  const browseEnabled = localDataRootsEnabled || remoteBrowseEnabled || Boolean(rootStorage);

  /** Open the section for the bucket `location` names, if any. */
  const openPrivateBucket = useCallback(
    (location: string, options: OpenPrivateBucketOptions) => {
      const bucket = s3BucketOf(location);
      if (!bucket) return;
      setPrivateBucket((prev) => openSection(prev, bucket, options));
    },
    [],
  );

  const handlePrivateBucketToggle = (open: boolean) => {
    if (open) {
      openPrivateBucket(trimmedRoot, { byReader: true });
      return;
    }
    // Closing forgets the details; a folder read with them is read again
    // without them.
    if (storageBinding) setStorageEpoch((n) => n + 1);
    setPrivateBucket(closeSection);
  };

  // Another bucket in the field: the section follows it (`followBucket`).
  const targetBucket = s3BucketOf(inspectTarget);
  useEffect(() => {
    if (!targetBucket) return;
    setPrivateBucket((prev) => followBucket(prev, targetBucket));
  }, [targetBucket]);

  // Read the folder: what it holds, which pipeline made it, which template
  // fits. A newer folder cancels the request still in flight. A folder in a
  // private bucket is read with its connection details; a refusal opens the
  // section that asks for them.
  useEffect(() => {
    if (!opened) return undefined;
    const location = inspectTarget;
    if (!location || !isReadableRoot(location, localDataRootsEnabled)) {
      setDetection({ status: 'idle' });
      return undefined;
    }
    const controller = new AbortController();
    setDetection({ status: 'loading', location });
    const storage = storageForLocation(location, storageBindingRef.current);
    inspectFolder(location, { signal: controller.signal, storage })
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
        const code = apiErrorCode(err);
        setDetection({
          status: 'error',
          location,
          error: err.message || 'This folder could not be read.',
          code,
        });
        if (isPrivateBucketRefusal(code)) openPrivateBucket(location, { refused: true });
      });
    return () => controller.abort();
    // The connection details are read through a ref (see `storageEpoch`).
  }, [opened, inspectTarget, localDataRootsEnabled, storageEpoch, openPrivateBucket]);

  // What the card shows: the current folder's reading, "loading" while the
  // reader is still typing, nothing for an empty or unreadable field.
  const detectionView: DetectionState = useMemo(() => {
    if (!trimmedRoot || prefixInvalid) return { status: 'idle' };
    if (detection.status !== 'idle' && detection.location === trimmedRoot) return detection;
    return { status: 'loading', location: trimmedRoot };
  }, [detection, trimmedRoot, prefixInvalid]);

  // An unreadable folder in a private bucket: the way forward is the
  // section above the card, not the pipeline picker.
  let detectionErrorHint: string | null = null;
  let detectionErrorMessage: string | null = null;
  if (detectionView.status === 'error' && isPrivateBucketRefusal(detectionView.code)) {
    // Read without connection details, the server's reason points at the
    // storage settings of a project that does not exist yet.
    if (!rootStorage) {
      detectionErrorMessage =
        'The server cannot read this bucket on its own: it is not public, and not one this server is set up to read.';
    }
    if (privateBucketDisabledReason) {
      detectionErrorHint =
        'This bucket is not public, and reading a private bucket is not available to you here.';
    } else if (privateBucket.open) {
      detectionErrorHint =
        'This bucket is not public: give its connection details above, then test the connection.';
    } else {
      detectionErrorHint =
        'This bucket is not public: turn on \u201cThis bucket needs credentials\u201d above to give its connection details.';
    }
  }

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
      ...(rootStorage ? { storage: rootStorage } : {}),
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
    setPreviewNeedsBucket(false);
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
        const code = apiErrorCode(err);
        if (detecting && code === 'template_not_detected') {
          setNotDetected(err.message || 'The pipeline that produced this folder was not recognised.');
        } else {
          setPreviewError(err.message || 'Failed to preview the run folder.');
          if (isPrivateBucketRefusal(code) && s3BucketOf(trimmedRoot)) {
            setPreviewNeedsBucket(true);
            openPrivateBucket(trimmedRoot, { refused: true });
          }
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
  } else if (
    step === 0 &&
    !privateBucketDisabledReason &&
    privateBucket.open &&
    privateBucket.bucket === rootBucket &&
    storageProblem
  ) {
    disabledReason = `Private bucket: ${storageProblem}`;
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

  // One button reads Next, then Create Project on the last step: it ignores
  // clicks for a moment after each step change, so a double click on Next
  // stops on the Create step instead of creating straight away.
  const stepSettling = useStepSettling(step);

  const handleSubmit = async () => {
    if (disabledReason || stepSettling) return;
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
  const previewTitle = preview ? titleOf(preview.template_id) : null;
  // A preview refused for want of the bucket's details: back to the Source
  // step, with the section open.
  const giveBucketDetails =
    previewNeedsBucket && !privateBucketDisabledReason
      ? () => {
          openPrivateBucket(trimmedRoot, { refused: true, byReader: true });
          setStep(0);
        }
      : null;

  let rootError: string | undefined;
  if (prefixInvalid) {
    rootError = localDataRootsEnabled
      ? 'Enter a full folder path, a path starting with ~/, or an s3:// location.'
      : 'The run folder must be an s3:// location.';
  }

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
              error={rootError}
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

            {rootBucket && (
              <PrivateBucketSection
                location={trimmedRoot}
                bucket={privateBucket.bucket ?? rootBucket}
                open={privateBucket.open}
                refused={privateBucket.refused}
                onOpenChange={handlePrivateBucketToggle}
                fields={privateBucket.fields}
                onFieldsChange={(fields) => setPrivateBucket((prev) => ({ ...prev, fields }))}
                fieldErrors={storageFieldErrors}
                onRegionDetected={(region) =>
                  setPrivateBucket((prev) => ({ ...prev, fields: { ...prev.fields, region } }))
                }
                onConnected={() => setStorageEpoch((n) => n + 1)}
                disabledReason={privateBucketDisabledReason}
              />
            )}

            <DetectionCard
              state={detectionView}
              templateId={usedTemplateId}
              templateTitle={titleOf(usedTemplateId)}
              match={match}
              onUseDetected={
                detectedId ? () => setChoice({ templateId: detectedId, from: 'detected' }) : undefined
              }
              errorHint={detectionErrorHint}
              errorMessage={detectionErrorMessage}
            />

            <TemplatePicker
              groups={groups}
              pipeline={pipeline}
              templateId={choice.templateId}
              runVersion={detected?.version ?? null}
              closestTemplateId={detected?.match === 'closest' ? detectedId : null}
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
              onChange={(e) => {
                setProjectName(e.currentTarget.value);
                // A refusal of the previous name (taken already) no longer applies.
                setError(null);
              }}
              leftSection={<Icon icon="mdi:folder-outline" width={16} />}
              error={nameUsed ? 'A project with this name already exists.' : undefined}
              data-testid="run-project-name-input"
            />
            {extraVariables.length > 0 && (
              <TemplateSettingsSection
                variables={extraVariables}
                values={variables}
                onChange={(name, value) => setVariables((prev) => ({ ...prev, [name]: value }))}
              />
            )}
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="Preview" description="What each collection gets">
          <RunPreviewStep
            loading={previewLoading}
            detecting={!choice.templateId}
            notDetected={notDetected}
            onPickTemplate={() => setStep(0)}
            error={previewError}
            onGiveBucketDetails={giveBucketDetails}
            foundNothing={foundNothing}
            report={preview}
            templateTitle={previewTitle}
            detection={detected}
          />
        </Stepper.Step>

        <Stepper.Step label="Create" description="Confirm & ingest">
          <RunCreateStep
            report={preview}
            templateTitle={previewTitle}
            detection={detected}
            projectName={displayName}
            savesStorage={Boolean(rootStorage)}
          />
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
            aria-disabled={stepSettling || undefined}
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
            // The browser read it with the bucket's details: read it again
            // with them here, even when it is the folder already typed.
            if (storageForLocation(path, storageBinding)) setStorageEpoch((n) => n + 1);
            setBrowseOpened(false);
          }}
          initialLocation={trimmedRoot}
          localEnabled={localDataRootsEnabled}
          s3Enabled={remoteBrowseEnabled}
          privateBucket={rootStorage ? storageBinding : null}
          templates={templates}
        />
      )}
    </Stack>
  );
};

export default RunFolderTab;
