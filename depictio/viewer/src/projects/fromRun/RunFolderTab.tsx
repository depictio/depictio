/**
 * The "A folder or bucket" flow of the create-project dialog: Source, What
 * Depictio found, Create.
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
import {
  Alert,
  Anchor,
  Box,
  Button,
  Group,
  Stack,
  Stepper,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  addTablesFromFolder,
  apiErrorCode,
  bareVersion,
  createProjectFromRun,
  defaultVersionFor,
  EMPTY_RUN_STORAGE_FIELDS,
  findRunPipeline,
  groupRunTemplates,
  inspectFolder,
  isLocalFolderPath,
  isPrivateBucketRefusal,
  isS3Location,
  runFoundNothing,
  runStorageFieldsBlank,
  runStorageFieldErrors,
  runStorageFromFields,
  runTemplateMatch,
  s3BucketOf,
  storageForLocation,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  CreateProjectInput,
  CreateProjectResult,
  FromRunReport,
  FromRunRequest,
  RunStorageBinding,
  TemplateInfo,
} from 'depictio-react-core';

import { GatedButton } from '../../components/settings/SettingsSections';
import { useStepSettling } from '../hooks/useStepSettling';
import { FolderTablesFound } from '../create/FolderTablesFound';
import { TableResults } from '../create/TableResults';
import type { TableResultRow } from '../create/TableResults';
import { baseName, classifyTableName, stemOf } from '../create/tableFiles';
import { plural } from './plural';
import { SourceSection } from '../create/SourceSection';
import { DataSourceFields, FilesFoundCard, uploadFiles, useDataDropzone } from '../create/FilesDropArea';
import type { TableUploadOutcome } from '../create/FilesDropArea';
import FolderBrowserModal from './browser/FolderBrowserModal';
import { DetectionCard } from './DetectionCard';
import type { DetectionState } from './DetectionCard';
import {
  closeSection,
  followBucket,
  NO_PRIVATE_BUCKET,
  offerSection,
  openSection,
} from './privateBucket';
import type { OpenPrivateBucketOptions, PrivateBucketState } from './privateBucket';
import { pipelineLabel } from './pipelineLabel';
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

/** The server has the bucket in its settings but no credentials for it: only
 *  its administrator can fix that, so the reader is never asked for keys. */
const SERVER_CREDENTIALS_MISSING = 's3_server_credentials_missing';

/** True when a read was refused for want of the reader's own connection
 *  details for the bucket. */
function needsOwnCredentials(code: string | null | undefined): boolean {
  return code !== SERVER_CREDENTIALS_MISSING && isPrivateBucketRefusal(code);
}

/** `base`, or `base 2`, `base 3`, ... the first not among `taken`. */
function uniqueName(base: string, taken: string[]): string {
  const used = new Set(taken.map((n) => n.toLowerCase()));
  if (!used.has(base.toLowerCase())) return base;
  for (let n = 2; ; n += 1) {
    const candidate = `${base} ${n}`;
    if (!used.has(candidate.toLowerCase())) return candidate;
  }
}

/** The template choice, and where it came from: detection may replace its
 *  own choice when the folder changes, never one the reader made. */
interface Choice {
  templateId: string | null;
  from: 'detected' | 'user' | null;
}

const NO_CHOICE: Choice = { templateId: null, from: null };

/** What the dialog's first screen asked; trimmed, empty when not given. */
export interface NewProjectInfo {
  name: string;
  description: string;
  isPublic: boolean;
}

interface RunFolderTabProps {
  /** Creates the project only; the dialog stays open (plain tables). */
  onCreateProject?: (
    input: CreateProjectInput,
    options?: { keepOpen?: boolean },
  ) => Promise<CreateProjectResult>;
  /** The project is complete: leave for its page. */
  onProjectReady?: (projectId: string, name: string, tableId?: string | null) => void;
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
  onCreateFromRun: (input: FromRunRequest, context: RunCreatedContext) => void;
  submitting: boolean;
  setSubmitting: (submitting: boolean) => void;
  /** Under the source fields: the rarer ways to start a project. */
  /** What the first screen of the dialog asked about the project. */
  projectInfo: NewProjectInfo;
}

const RunFolderTab: React.FC<RunFolderTabProps> = ({
  onCreateProject,
  onProjectReady,
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
  projectInfo,
}) => {
  const accent = useBrandAccents();
  const drop = useDataDropzone();
  const { dropzone, files: localFiles } = drop;
  const { clear: clearLocalFiles } = dropzone;
  const [step, setStep] = useState(0);
  const [dataRoot, setDataRoot] = useState('');
  /** The folder last read, `INSPECT_DELAY_MS` after typing stops (at once
   *  for a folder picked in the browser). */
  const [inspectTarget, setInspectTarget] = useState('');
  const [detection, setDetection] = useState<DetectionState>({ status: 'idle' });
  const [choice, setChoice] = useState<Choice>(NO_CHOICE);
  const projectName = projectInfo.name;
  const isPublic = projectInfo.isPublic;
  const [variables, setVariables] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<FromRunReport | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  /** The server's explanation when detection found no template (422
   *  `template_not_detected`): a "pick a template" state, not a failure. */
  const [notDetected, setNotDetected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** The pipeline and version pickers are shown under the folder field. */
  const [pipelinePickerOpen, setPipelinePickerOpen] = useState(false);
  const [browseOpened, setBrowseOpened] = useState(false);
  const [privateBucket, setPrivateBucket] = useState<PrivateBucketState>(NO_PRIVATE_BUCKET);
  /** The preview was refused for want of the bucket's connection details. */
  const [previewNeedsBucket, setPreviewNeedsBucket] = useState(false);
  /** Bumped when the folder should be read again with other connection
   *  details (a successful test, the section closed). */
  const [storageEpoch, setStorageEpoch] = useState(0);
  /** The details the folder browser reads its private bucket with: set when
   *  it opens and when a test in it connects, not on every keystroke, since
   *  new details start a fresh tree. */
  const [browseBinding, setBrowseBinding] = useState<RunStorageBinding | null>(null);
  /** Bumped by a test in the browser that connected. */
  const [browseEpoch, setBrowseEpoch] = useState(0);
  /** Plain tables: the files ticked, and what became of them. */
  const [tickedTables, setTickedTables] = useState<Set<string>>(new Set());
  const [tableRows, setTableRows] = useState<TableResultRow[]>([]);
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null);
  const [createdTableId, setCreatedTableId] = useState<string | null>(null);
  const [tableError, setTableError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) return;
    setStep(0);
    clearLocalFiles();
    setDataRoot('');
    setInspectTarget('');
    setPipelinePickerOpen(false);
    setTickedTables(new Set());
    setTableRows([]);
    setCreatedProjectId(null);
    setTableError(null);
    setDetection({ status: 'idle' });
    setChoice(NO_CHOICE);
    setVariables({});
    setPreview(null);
    setPreviewError(null);
    setNotDetected(null);
    setError(null);
    setBrowseOpened(false);
    setPrivateBucket(NO_PRIVATE_BUCKET);
    setPreviewNeedsBucket(false);
    setBrowseBinding(null);
    // `clearLocalFiles` is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const handlePrivateBucketToggle = (open: boolean, location: string) => {
    if (open) {
      openPrivateBucket(location, { byReader: true });
      return;
    }
    // Closing forgets the details; the folder in the field, read with them,
    // is read again without them.
    if (rootStorage) setStorageEpoch((n) => n + 1);
    setPrivateBucket(closeSection);
  };

  // The browser's details go with the section's: another bucket, or the
  // section closed, and the browser forgets them.
  useEffect(() => {
    setBrowseBinding((prev) =>
      prev && (!privateBucket.open || prev.bucket !== privateBucket.bucket) ? null : prev,
    );
  }, [privateBucket.open, privateBucket.bucket]);

  // A test in the browser connected: from now on it reads the bucket with
  // these details, the region the test found included.
  useEffect(() => {
    if (browseEpoch > 0) setBrowseBinding(storageBindingRef.current);
  }, [browseEpoch]);

  const openBrowser = () => {
    // The details of the field's bucket, or of the bucket last opened in the
    // browser while the field names none; never another bucket's.
    const own = storageBinding && (!rootBucket || storageBinding.bucket === rootBucket);
    setBrowseBinding(own ? storageBinding : null);
    setBrowseOpened(true);
  };

  const closeBrowser = () => {
    setBrowseOpened(false);
    // A bucket opened in the browser and left there: the section follows
    // the field again.
    if (rootBucket) setPrivateBucket((prev) => followBucket(prev, rootBucket));
  };

  /** The section for the bucket of `location`: under the field, or in the
   *  folder browser for a folder refused there. Both show the same details. */
  const renderPrivateBucket = (location: string, inBrowser: boolean) => {
    const bucket = s3BucketOf(location);
    if (!bucket) return null;
    // Under the field, the section shows its bucket until it follows the
    // field; in the browser, details typed for another bucket never show
    // under this one (its switch opens a section of its own).
    const mine = !inBrowser || privateBucket.bucket === bucket;
    // Under the field the section is for buckets the server cannot read on
    // its own: shown once a read was refused for want of the reader's
    // credentials, they asked for it, or details are already filled in.
    // Otherwise a small link offers it.
    if (
      !inBrowser &&
      !privateBucket.open &&
      !privateBucket.refused &&
      runStorageFieldsBlank(privateBucket.fields)
    ) {
      if (privateBucketDisabledReason) return null;
      return (
        <Anchor
          component="button"
          type="button"
          size="xs"
          c="dimmed"
          style={{ alignSelf: 'flex-start' }}
          onClick={() => handlePrivateBucketToggle(true, location)}
          data-testid="run-private-bucket-link"
        >
          Use my own credentials
        </Anchor>
      );
    }
    return (
      <PrivateBucketSection
        location={location}
        bucket={inBrowser ? bucket : privateBucket.bucket ?? bucket}
        open={mine && privateBucket.open}
        refused={mine ? privateBucket.refused : true}
        onOpenChange={(open) => handlePrivateBucketToggle(open, location)}
        fields={mine ? privateBucket.fields : EMPTY_RUN_STORAGE_FIELDS}
        onFieldsChange={(fields) => setPrivateBucket((prev) => ({ ...prev, fields }))}
        fieldErrors={mine ? storageFieldErrors : {}}
        onRegionDetected={(region) =>
          setPrivateBucket((prev) => ({ ...prev, fields: { ...prev.fields, region } }))
        }
        onConnected={() => {
          if (bucket === rootBucket) setStorageEpoch((n) => n + 1);
          if (inBrowser) setBrowseEpoch((n) => n + 1);
        }}
        disabledReason={privateBucketDisabledReason}
      />
    );
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
        if (needsOwnCredentials(code)) openPrivateBucket(location, { refused: true });
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
  const readFailed = detectionView.status === 'error';
  const readCode = detectionView.status === 'error' ? detectionView.code : null;
  if (readFailed && readCode === SERVER_CREDENTIALS_MISSING) {
    // The server's own message says what is missing; the reader has no keys
    // to type for this bucket.
    detectionErrorHint = 'Ask the administrator of this server.';
  } else if (readFailed && needsOwnCredentials(readCode)) {
    // Read without connection details, the server's reason is written for
    // every caller; this one is the run tab's.
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

  // A folder that cannot be read and that no connection details would open
  // (outside the allowed roots, missing, a server without keys): Next waits.
  const folderUnreadable = readFailed && !needsOwnCredentials(readCode);

  const inspection = detectionView.status === 'ready' ? detectionView.result : null;
  const detected = inspection?.detected ?? null;
  const detectedId = detected?.template_id ?? null;

  // A folder of plain tables: nothing in it names a pipeline, nothing was
  // picked. Listed from the inspection (direct children), classified by
  // extension; the project is created with the ticked ones.
  const filesOnly = localFiles.length > 0 && !trimmedRoot;
  const plainFolder = inspection !== null && !detected?.pipeline && !choice.templateId;
  const tablesMode = filesOnly || plainFolder;
  const folderFileNames = useMemo(() => inspection?.files.names ?? [], [inspection]);
  const tableNames = useMemo(
    () => folderFileNames.filter((n) => classifyTableName(n).table),
    [folderFileNames],
  );
  const inspectedLocation = inspection?.location ?? null;
  // Every table starts ticked, again for each folder read.
  useEffect(() => {
    setTickedTables(new Set(tableNames));
    // The folder decides, not the identity of the array.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspectedLocation, tableNames.join('\n')]);
  const tickedList = tableNames.filter((n) => tickedTables.has(n));
  const folderBase = baseName(trimmedRoot.replace(/\/+$/, '')) || 'tables';
  const singleFileStem = localFiles.length === 1 ? stemOf(localFiles[0].name) : '';
  /** What a project of tables is called by default. */
  const tablesBase = trimmedRoot ? folderBase : singleFileStem || 'uploads';
  const tableCount = (plainFolder ? tickedList.length : 0) + localFiles.length;

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
  const engineOf = (id: string | null | undefined): string | null =>
    (id ? templates.find((t) => t.template_id === id)?.engine : null) ?? null;
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

  /** Back to what detection found, or to plain tables when it found nothing. */
  const clearPipelineChoice = () =>
    setChoice(detectedId ? { templateId: detectedId, from: 'detected' } : NO_CHOICE);

  const handlePipelineChange = (key: string | null) => {
    if (!key) {
      clearPipelineChoice();
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
  // What the project is called when the field stays empty: the run folder's
  // name, made unique among the projects that exist.
  const defaultBase = usedTemplateId ? folderBase : null;
  const defaultName = defaultBase ? uniqueName(defaultBase, existingNames) : null;
  const effectiveName = trimmedName || defaultName || '';
  const nameUsed =
    effectiveName.length > 0 &&
    existingNames.some((n) => n.toLowerCase() === effectiveName.toLowerCase());

  const buildRequest = (dryRun: boolean): FromRunRequest => {
    const values: Record<string, string> = {};
    for (const v of extraVariables) {
      const value = (variables[v.name] ?? '').trim();
      if (value) values[v.name] = value;
    }
    return {
      dataRoot: trimmedRoot,
      templateId: choice.templateId,
      projectName: effectiveName || null,
      isPublic,
      description: projectInfo.description || null,
      ...(Object.keys(values).length > 0 ? { variables: values } : {}),
      dryRun,
      ...(rootStorage ? { storage: rootStorage } : {}),
    };
  };

  // Dry-run plan, re-fetched every time the Preview step is entered so a
  // Previous then Next round-trip picks up edited inputs.
  useEffect(() => {
    if (!opened || step !== 1 || !trimmedRoot || tablesMode) return undefined;
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
          if (needsOwnCredentials(code) && s3BucketOf(trimmedRoot)) {
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

  // Disabled with a visible reason rather than hidden (project convention).
  let disabledReason: string | null = null;
  const tablesName = trimmedName || uniqueName(tablesBase, existingNames);
  if (tablesMode && step === 1) {
    if (existingNames.some((n) => n.toLowerCase() === tablesName.toLowerCase())) {
      disabledReason = 'A project with this name already exists.';
    } else if (tableCount === 0) {
      disabledReason = 'Tick at least one table.';
    }
  } else if (filesOnly) {
    // Files are all it takes.
  } else if (step === 0 && !prefixInvalid && trimmedRoot && detectionView.status === 'loading') {
    disabledReason = 'Reading the folder.';
  } else if (trimmedRoot.length === 0) {
    disabledReason = browseEnabled
      ? 'Drop files, or enter or browse to a folder.'
      : 'Drop files, or enter the location of a folder.';
  } else if (prefixInvalid) {
    disabledReason = localDataRootsEnabled
      ? 'The run folder must be a folder path or an s3:// location.'
      : 'The run folder must be an s3:// location.';
  } else if (step === 0 && folderUnreadable) {
    disabledReason =
      (detectionView.status === 'error' && detectionView.error) || 'The run folder could not be read.';
  } else if (step >= 1 && nameUsed) {
    disabledReason = 'A project with this name already exists.';
  } else if (
    step === 0 &&
    !privateBucketDisabledReason &&
    privateBucket.open &&
    privateBucket.bucket === rootBucket &&
    storageProblem
  ) {
    disabledReason = `Private bucket: ${storageProblem}`;
  } else if (plainFolder && step === 0 && tableNames.length === 0 && localFiles.length === 0) {
    disabledReason = 'No pipeline recognised and no table files in this folder.';
  } else if (
    step === 1 &&
    (previewLoading || (!preview && !previewError && !notDetected))
  ) {
    // Between entering the step and the effect firing there is no preview
    // and no error yet: that is still "loading", not a failure.
    disabledReason = 'Reading the run folder.';
  } else if (step === 1 && notDetected) {
    disabledReason = 'The pipeline was not recognised: pick one first.';
  } else if (step === 1 && previewError) {
    disabledReason = 'The run folder could not be read.';
  } else if (foundNothing) {
    disabledReason = 'No data collection matched anything in this folder.';
  }

  // One button reads Next, then Create Project on the last step: it ignores
  // clicks for a moment after each step change, so a double click on Next
  // stops on the Create step instead of creating straight away.
  const stepSettling = useStepSettling(step);

  /** Create the project, then its tables: the folder's ticked ones and the
   *  dropped files. One that fails is reported on its row and the project stays. */
  const createTables = async () => {
    if (!onCreateProject) return;
    const folderTables = plainFolder && inspection ? tickedList : [];
    const location = inspection?.location ?? null;
    setStep(2);
    setSubmitting(true);
    setError(null);
    setTableError(null);
    setCreatedProjectId(null);
    const pending: TableResultRow[] = [
      ...folderTables.map((n) => ({ key: n, label: n, status: 'pending' as const })),
      ...localFiles.map((f, i) => ({
        key: `file-${i}`,
        label: baseName(f.name),
        status: 'pending' as const,
      })),
    ];
    setTableRows(pending);
    try {
      const result = await onCreateProject(
        {
          name: tablesName,
          // Legacy field: the type no longer changes what a project can do.
          project_type: 'basic',
          is_public: isPublic,
          description: projectInfo.description || null,
        } as CreateProjectInput,
        { keepOpen: true },
      );
      const projectId = result.project_id ?? null;
      if (!projectId) throw new Error(result.message || 'The project could not be created.');
      setCreatedProjectId(projectId);

      let folderRows: TableResultRow[] = [];
      let firstTableId: string | null = null;
      if (location && folderTables.length > 0) {
        const report = await addTablesFromFolder(projectId, {
          location,
          files: folderTables,
          dryRun: false,
          ...(rootStorage ? { storage: rootStorage } : {}),
        });
        folderRows = folderTables.map((n) => {
          const made = report.created.find((c) => c.path === n);
          if (made && made.status === 'ingested') {
            firstTableId = firstTableId ?? made.data_collection_id ?? null;
            return { key: n, label: n, status: 'created' };
          }
          return {
            key: n,
            label: n,
            status: 'failed',
            error: made?.error ?? 'This file was not turned into a table.',
          };
        });
        setTableRows([...folderRows, ...pending.slice(folderRows.length)]);
      }

      const toRow = (o: TableUploadOutcome, i: number): TableResultRow => ({
        key: `file-${i}`,
        label: baseName(o.file.name),
        status: o.error ? 'failed' : 'created',
        error: o.error,
      });
      const uploads = await uploadFiles(
        projectId,
        localFiles,
        folderTables.map(stemOf),
        (outcomes) =>
          setTableRows([
            ...folderRows,
            ...outcomes.map(toRow),
            ...pending.slice(folderRows.length + outcomes.length),
          ]),
      );
      firstTableId = firstTableId ?? uploads.find((u) => u.dataCollectionId)?.dataCollectionId ?? null;
      setCreatedTableId(firstTableId);
      const allCreated =
        folderRows.every((r) => r.status === 'created') && uploads.every((u) => !u.error);
      if (allCreated) onProjectReady?.(projectId, tablesName, firstTableId);
    } catch (err) {
      setTableError((err as Error).message || 'Failed to create the project.');
      setTableRows((prev) =>
        prev.map((r) => (r.status === 'pending' ? { ...r, status: 'failed' } : r)),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async () => {
    if (disabledReason || stepSettling) return;
    if (tablesMode && step === 1) {
      await createTables();
      return;
    }
    if (step === 0 && trimmedRoot) rememberRunFolder(trimmedRoot);
    if (step < 2) {
      setStep(step + 1);
      return;
    }
    // Hands over at once: the next screen waits for the project and says how it went.
    onCreateFromRun(buildRequest(false), {
      projectName: effectiveName,
      templateTitle: titleOf(choice.templateId ?? preview?.template_id),
      detection: detected,
      extraFiles: localFiles,
      takenTableNames: (preview?.data_collections ?? []).map((dc) => dc.data_collection_tag),
    });
  };

  const displayName = effectiveName || preview?.project_name || 'project';
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

  const plainTablesNote = plainFolder ? (
    <Alert
      color="blue"
      variant="light"
      icon={<Icon icon="mdi:information-outline" width={18} />}
      data-testid="folder-no-pipeline"
    >
      <Text size="sm">
        No pipeline recognised: these look like plain tables.
      </Text>
    </Alert>
  ) : null;

  const pickerBlock = (
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
  );

  // The pipeline is optional: shown once the folder was read (or a pipeline
  // was picked), as a line with a way to correct it.
  const chosenVersion = pipeline?.versions.find((v) => v.templateId === choice.templateId)?.version;
  let pipelineText: string | null = null;
  if (choice.from === 'user' && choice.templateId) {
    const name = pipeline?.pipeline ?? titleOf(choice.templateId);
    pipelineText = [name, chosenVersion ? bareVersion(chosenVersion) : null]
      .filter(Boolean)
      .join(' ');
  } else if (detected?.pipeline) {
    pipelineText = [detected.pipeline, detected.version ? bareVersion(detected.version) : null]
      .filter(Boolean)
      .join(' ');
  }
  const showPipelineLine = inspection !== null || choice.from === 'user';
  const pipelineLine = !showPipelineLine ? null : usedTemplateId ? (
    <Group gap="xs" wrap="wrap" data-testid="folder-pipeline-line">
      <Text size="sm" c="dimmed">
        Pipeline:
      </Text>
      <Text size="sm" fw={500}>
        {pipelineText ?? pipelineLabel(usedTemplateId) ?? usedTemplateId}
      </Text>
      <Text size="sm" c="dimmed">
        {'\u00b7'} {choice.from === 'user' ? 'Chosen' : 'Detected'}
      </Text>
      <Anchor
        component="button"
        type="button"
        size="sm"
        onClick={() => setPipelinePickerOpen((open) => !open)}
        data-testid="folder-change-pipeline"
      >
        {pipelinePickerOpen ? 'Hide' : 'Change'}
      </Anchor>
      {choice.from === 'user' && (
        <Anchor
          component="button"
          type="button"
          size="sm"
          onClick={() => {
            clearPipelineChoice();
            setPipelinePickerOpen(false);
          }}
          data-testid="folder-clear-pipeline"
        >
          Clear
        </Anchor>
      )}
    </Group>
  ) : (
    <Group gap="xs" wrap="wrap">
      <Anchor
        component="button"
        type="button"
        size="sm"
        onClick={() => setPipelinePickerOpen((open) => !open)}
        data-testid="folder-know-pipeline"
      >
        {pipelinePickerOpen ? 'Hide the pipeline picker' : 'I know the pipeline'}
      </Anchor>
    </Group>
  );

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
        <Stepper.Step
          label="Your data"
          description="Files, a folder, or both"
        >
          <Stack gap="md" pt="md">
          <DataSourceFields
            drop={drop}
            submitting={submitting}
            folderField={
            <TextInput
              aria-label="Folder or bucket"
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
                      onClick={openBrowser}
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
            }
            folderHint={
              localDataRootsEnabled
                ? 'A folder on this computer (a full path, or one starting with ~/) or an s3:// location.'
                : 'The s3:// location of a folder of results or tables.'
            }
          >
            {renderPrivateBucket(trimmedRoot, false)}

            {plainTablesNote}

            {pipelineLine}
            {pipelinePickerOpen && pickerBlock}

            {!tablesMode && trimmedRoot && (
            <DetectionCard
              state={detectionView}
              templateId={usedTemplateId}
              templateTitle={pipelineLabel(usedTemplateId)}
              templateEngine={engineOf(usedTemplateId)}
              match={match}
              storage={rootStorage}
              onUseDetected={
                detectedId ? () => setChoice({ templateId: detectedId, from: 'detected' }) : undefined
              }
              errorHint={detectionErrorHint}
              errorMessage={detectionErrorMessage}
            />
            )}

            {extraVariables.length > 0 && (
              <TemplateSettingsSection
                variables={extraVariables}
                values={variables}
                onChange={(name, value) => setVariables((prev) => ({ ...prev, [name]: value }))}
              />
            )}
          </DataSourceFields>
          </Stack>
        </Stepper.Step>

        <Stepper.Step label="What Depictio found" description="Facts and checks">
          {tablesMode ? (
            <Stack gap="md" pt="md">
              {plainTablesNote}
              {plainFolder && (
              <SourceSection
                icon="mdi:folder-outline"
                title="Folder"
                summary={`${plural(tableCount - localFiles.length, 'table')} ticked · ${inspection?.location ?? trimmedRoot}`}
                defaultOpen={localFiles.length === 0}
                testId="found-section-folder"
              >
              <FolderTablesFound
                location={inspection?.location ?? trimmedRoot}
                names={folderFileNames}
                moreCount={Math.max(0, (inspection?.files.count ?? 0) - folderFileNames.length)}
                ticked={tickedTables}
                onToggle={(name, checked) =>
                  setTickedTables((prev) => {
                    const next = new Set(prev);
                    if (checked) next.add(name);
                    else next.delete(name);
                    return next;
                  })
                }
              />
              </SourceSection>
              )}
              {localFiles.length > 0 && <FilesFoundCard drop={drop} defaultOpen={!plainFolder} />}
            </Stack>
          ) : (
          <Stack gap="md">
          <RunPreviewStep
            loading={previewLoading}
            detecting={!choice.templateId}
            notDetected={notDetected}
            onPickTemplate={() => {
              setPipelinePickerOpen(true);
              setStep(0);
            }}
            error={previewError}
            onGiveBucketDetails={giveBucketDetails}
            foundNothing={foundNothing}
            report={preview}
            templateTitle={previewTitle}
            templateEngine={engineOf(preview?.template_id)}
            detection={detected}
            storage={rootStorage}
            chosenFrom={choice.from}
            sectionsOpen={localFiles.length === 0}
          />
          {localFiles.length > 0 && <FilesFoundCard drop={drop} defaultOpen={false} />}
          </Stack>
          )}
        </Stepper.Step>

        <Stepper.Step label="Create" description="Confirm & ingest">
          {tablesMode ? (
            <TableResults
              projectName={tablesName}
              rows={tableRows}
              error={tableError}
              working={submitting}
              onOpen={
                createdProjectId && onProjectReady
                  ? () => onProjectReady(createdProjectId, tablesName, createdTableId)
                  : null
              }
            />
          ) : (
          <RunCreateStep
            report={preview}
            templateTitle={previewTitle}
            templateEngine={engineOf(preview?.template_id)}
            detection={detected}
            storage={rootStorage}
            projectName={displayName}
            savesStorage={Boolean(rootStorage)}
            dropped={localFiles.length > 0 ? <FilesFoundCard drop={drop} defaultOpen={false} /> : null}
          />
          )}
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

      {!(tablesMode && step === 2) && (
      <Group
        justify="space-between"
        align="flex-start"
        wrap="nowrap"
        py="sm"
        // Stays in view while the steps above scroll inside the dialog.
        style={{
          position: 'sticky',
          bottom: 0,
          zIndex: 3,
          background: 'var(--mantine-color-body)',
          borderTop: '1px solid var(--mantine-color-default-border)',
        }}
        data-testid="run-footer"
      >
        {step > 0 ? (
          <Button
            variant="default"
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={submitting}
            data-testid="run-previous"
          >
            Previous
          </Button>
        ) : (
          <span />
        )}
        <Stack gap={4} align="flex-end" style={{ minWidth: 0, flex: '1 1 auto' }} ml="md">
          <GatedButton
            aria-disabled={stepSettling || undefined}
            color={accent.secondary}
            onClick={handleSubmit}
            loading={submitting}
            reason={disabledReason}
            data-testid="create-from-run-submit"
          >
            {tablesMode && step === 1
              ? `Create project with ${plural(tableCount, localFiles.every((f) => drop.guesses.get(f)?.kind === 'table') ? 'table' : 'file')}`
              : step === 2
                ? 'Create Project'
                : 'Next'}
          </GatedButton>
          {disabledReason && (
            <Group
              gap={6}
              wrap="nowrap"
              align="flex-start"
              justify="flex-end"
              c="dimmed"
              data-testid="run-submit-disabled-reason"
            >
              <Icon
                icon="mdi:information-outline"
                width={16}
                style={{ flexShrink: 0, marginTop: 2 }}
              />
              <Text size="sm" c="dimmed" ta="right" style={{ wordBreak: 'break-word' }}>
                {disabledReason}
              </Text>
            </Group>
          )}
        </Stack>
      </Group>
      )}

      {browseEnabled && (
        <FolderBrowserModal
          stackId={BROWSE_STACK_ID}
          opened={opened && browseOpened}
          onClose={closeBrowser}
          onSelect={(path) => {
            // The section follows the folder picked, as it does the field.
            const bucket = s3BucketOf(path);
            if (bucket) setPrivateBucket((prev) => followBucket(prev, bucket));
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
          privateBucket={browseBinding}
          credentialsForm={(location) => renderPrivateBucket(location, true)}
          onCredentialsNeeded={(location) => {
            const bucket = s3BucketOf(location);
            if (bucket) setPrivateBucket((prev) => offerSection(prev, bucket));
          }}
          templates={templates}
        />
      )}
    </Stack>
  );
};

export default RunFolderTab;
