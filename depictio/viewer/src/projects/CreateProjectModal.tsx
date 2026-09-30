import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  FileButton,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Stepper,
  Switch,
  Table,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  createProjectFromManifest,
  createProjectFromRun,
  listProjectTemplates,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  CreateProjectInput,
  CreateProjectResult,
  FromManifestReport,
  FromManifestRequest,
  FromRunReport,
  FromRunRequest,
  TemplateInfo,
} from 'depictio-react-core';

import {
  FromRunPreviewReport,
  fromRunFoundNothing,
  fromRunMatchTotals,
} from './FromRunReport';

type Tab = 'create' | 'import' | 'manifest' | 'run';
type ProjectType = 'basic' | 'advanced';

interface CreateProjectModalProps {
  opened: boolean;
  existingNames: string[];
  onClose: () => void;
  onCreate: (input: CreateProjectInput) => Promise<CreateProjectResult>;
  onImport: (file: File, overwrite: boolean) => Promise<void>;
  onCreateFromManifest: (input: FromManifestRequest) => Promise<FromManifestReport>;
  onCreateFromRun: (input: FromRunRequest) => Promise<FromRunReport>;
}



/** Visual treatment per manifest-ingestion status. Colors are Mantine palette
 *  names (theme tokens), not literals — mirrors IngestionReportPanel. */
const MANIFEST_STATUS_META: Record<string, { color: string; icon: string; label: string }> = {
  ingested: { color: 'green', icon: 'mdi:check-circle', label: 'Ingested' },
  planned: { color: 'blue', icon: 'mdi:clock-outline', label: 'Planned' },
  failed: { color: 'red', icon: 'mdi:alert-circle', label: 'Failed' },
};

const CreateProjectModal: React.FC<CreateProjectModalProps> = ({
  opened,
  existingNames,
  onClose,
  onCreate,
  onImport,
  onCreateFromManifest,
  onCreateFromRun,
}) => {
  const accent = useBrandAccents();
  const [tab, setTab] = useState<Tab>('create');
  const [activeStep, setActiveStep] = useState(0);
  const [projectType, setProjectType] = useState<ProjectType | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Import tab state
  const [importFile, setImportFile] = useState<File | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const importResetRef = useRef<() => void>(null);

  // From Manifest tab state
  const [manifestStep, setManifestStep] = useState(0);
  const [manifestUrl, setManifestUrl] = useState('');
  const [manifestTemplateId, setManifestTemplateId] = useState<string | null>(null);
  const [manifestProjectName, setManifestProjectName] = useState('');
  const [manifestVariables, setManifestVariables] = useState<Record<string, string>>({});
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [preview, setPreview] = useState<FromManifestReport | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // From a run folder tab state
  const [runStep, setRunStep] = useState(0);
  const [runDataRoot, setRunDataRoot] = useState('');
  const [runTemplateId, setRunTemplateId] = useState<string | null>(null);
  const [runProjectName, setRunProjectName] = useState('');
  const [runVariables, setRunVariables] = useState<Record<string, string>>({});
  const [runPreview, setRunPreview] = useState<FromRunReport | null>(null);
  const [runPreviewLoading, setRunPreviewLoading] = useState(false);
  const [runPreviewError, setRunPreviewError] = useState<string | null>(null);

  // Reset everything whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setTab('create');
    setActiveStep(0);
    setProjectType(null);
    setName('');
    setDescription('');
    setIsPublic(false);
    setImportFile(null);
    setOverwrite(false);
    setManifestStep(0);
    setManifestUrl('');
    setManifestTemplateId(null);
    setManifestProjectName('');
    setManifestVariables({});
    setPreview(null);
    setPreviewError(null);
    setRunStep(0);
    setRunDataRoot('');
    setRunTemplateId(null);
    setRunProjectName('');
    setRunVariables({});
    setRunPreview(null);
    setRunPreviewError(null);
    setError(null);
    setSubmitting(false);
    importResetRef.current?.();
  }, [opened]);

  // Every template the backend knows, fetched fresh per open so a newly
  // registered template shows up without a page reload. The From Manifest tab
  // narrows this to the manifest-capable ones; the From a run folder tab uses
  // the full list, since a run folder is scanned whatever the scan mode.
  useEffect(() => {
    if (!opened) return;
    let cancelled = false;
    setTemplatesError(null);
    listProjectTemplates()
      .then((all) => {
        if (!cancelled) setTemplates(all);
      })
      .catch((err: Error) => {
        if (!cancelled) setTemplatesError(err.message || 'Failed to load templates.');
      });
    return () => {
      cancelled = true;
    };
  }, [opened]);

  const manifestTemplates = useMemo(
    () => templates.filter((t) => t.manifest_capable),
    [templates],
  );

  // Step-1 card click also auto-advances (matches Dash UX).
  const handleSelectType = (type: ProjectType) => {
    if (type === 'advanced') return; // disabled card
    setProjectType(type);
    setActiveStep(1);
  };

  const trimmedName = name.trim();
  const nameAlreadyUsed = existingNames.some(
    (n) => n.toLowerCase() === trimmedName.toLowerCase(),
  );
  const canSubmit =
    !!projectType && trimmedName.length > 0 && !nameAlreadyUsed && !submitting;

  const handleCreate = async () => {
    if (!projectType || !trimmedName) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: trimmedName,
        project_type: projectType,
        is_public: isPublic,
        ...(description.trim() ? { description: description.trim() } : {}),
      } as CreateProjectInput);
    } catch (err) {
      setError((err as Error).message || 'Failed to create project.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleImport = async () => {
    if (!importFile) return;
    setSubmitting(true);
    setError(null);
    try {
      await onImport(importFile, overwrite);
    } catch (err) {
      setError((err as Error).message || 'Failed to import project.');
    } finally {
      setSubmitting(false);
    }
  };

  const selectedTemplate =
    manifestTemplates.find((t) => t.template_id === manifestTemplateId) ?? null;
  // MANIFEST_URL is injected server-side from the URL field — never render a
  // form input for it.
  const extraVariables = (selectedTemplate?.variables ?? []).filter(
    (v) => v.name !== 'MANIFEST_URL',
  );

  const trimmedManifestUrl = manifestUrl.trim();
  const trimmedManifestName = manifestProjectName.trim();
  const manifestNameUsed =
    trimmedManifestName.length > 0 &&
    existingNames.some((n) => n.toLowerCase() === trimmedManifestName.toLowerCase());
  const manifestSourceReady =
    trimmedManifestUrl.length > 0 && !!manifestTemplateId && !manifestNameUsed;

  const buildManifestRequest = (dryRun: boolean): FromManifestRequest => {
    const variables: Record<string, string> = {};
    for (const v of extraVariables) {
      const value = (manifestVariables[v.name] ?? '').trim();
      if (value) variables[v.name] = value;
    }
    return {
      manifest_url: trimmedManifestUrl,
      template_id: manifestTemplateId as string,
      project_name: trimmedManifestName || null,
      ...(Object.keys(variables).length > 0 ? { variables } : {}),
      dry_run: dryRun,
    };
  };

  // Dry-run plan, re-fetched every time the Preview step is entered so a
  // Previous → Next round-trip picks up edited inputs.
  useEffect(() => {
    if (!opened || tab !== 'manifest' || manifestStep !== 1) return;
    if (!trimmedManifestUrl || !manifestTemplateId) return;
    let cancelled = false;
    setPreview(null);
    setPreviewError(null);
    setPreviewLoading(true);
    createProjectFromManifest(buildManifestRequest(true))
      .then((r) => {
        if (!cancelled) setPreview(r);
      })
      .catch((err: Error) => {
        if (!cancelled) setPreviewError(err.message || 'Failed to preview manifest.');
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
  }, [opened, tab, manifestStep]);

  // Single primary action for the manifest stepper: Next / Next / Create.
  const handleManifestSubmit = async () => {
    if (!manifestSourceReady) return;
    if (manifestStep < 2) {
      setManifestStep(manifestStep + 1);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreateFromManifest(buildManifestRequest(false));
    } catch (err) {
      setError((err as Error).message || 'Failed to create project from manifest.');
    } finally {
      setSubmitting(false);
    }
  };

  const manifestSubmitDisabled =
    !manifestSourceReady ||
    submitting ||
    (manifestStep === 1 && (previewLoading || !!previewError || !preview));

  const manifestDisplayName =
    preview?.project_name || trimmedManifestName || selectedTemplate?.name || 'project';

  const runSelectedTemplate =
    templates.find((t) => t.template_id === runTemplateId) ?? null;
  // DATA_ROOT is injected server-side from the run folder field, so it never
  // gets a form input of its own.
  const runExtraVariables = (runSelectedTemplate?.variables ?? []).filter(
    (v) => v.name !== 'DATA_ROOT',
  );

  const trimmedRunDataRoot = runDataRoot.trim();
  // The endpoint reads the run folder over S3. A local path would be resolved
  // against the API container's filesystem, which is not what this tab is for,
  // so it is refused here with the reason spelled out rather than 400ing.
  const runPrefixInvalid =
    trimmedRunDataRoot.length > 0 && !trimmedRunDataRoot.startsWith('s3://');
  const trimmedRunName = runProjectName.trim();
  const runNameUsed =
    trimmedRunName.length > 0 &&
    existingNames.some((n) => n.toLowerCase() === trimmedRunName.toLowerCase());
  const runSourceReady =
    trimmedRunDataRoot.length > 0 &&
    !runPrefixInvalid &&
    !!runTemplateId &&
    !runNameUsed;

  const buildRunRequest = (dryRun: boolean): FromRunRequest => {
    const variables: Record<string, string> = {};
    for (const v of runExtraVariables) {
      const value = (runVariables[v.name] ?? '').trim();
      if (value) variables[v.name] = value;
    }
    return {
      dataRoot: trimmedRunDataRoot,
      templateId: runTemplateId as string,
      projectName: trimmedRunName || null,
      ...(Object.keys(variables).length > 0 ? { variables } : {}),
      dryRun,
    };
  };

  // Dry-run plan, re-fetched every time the Preview step is entered so a
  // Previous → Next round-trip picks up edited inputs.
  useEffect(() => {
    if (!opened || tab !== 'run' || runStep !== 1) return;
    if (!trimmedRunDataRoot || !runTemplateId) return;
    let cancelled = false;
    setRunPreview(null);
    setRunPreviewError(null);
    setRunPreviewLoading(true);
    createProjectFromRun(buildRunRequest(true))
      .then((r) => {
        if (!cancelled) setRunPreview(r);
      })
      .catch((err: Error) => {
        if (!cancelled) setRunPreviewError(err.message || 'Failed to preview the run folder.');
      })
      .finally(() => {
        if (!cancelled) setRunPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Inputs are frozen while on the Preview step, so entering it is the only
    // dependency that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, tab, runStep]);

  // Single primary action for the run stepper: Next / Next / Create.
  const handleRunSubmit = async () => {
    if (!runSourceReady) return;
    if (runStep < 2) {
      setRunStep(runStep + 1);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onCreateFromRun(buildRunRequest(false));
    } catch (err) {
      setError((err as Error).message || 'Failed to create project from run folder.');
    } finally {
      setSubmitting(false);
    }
  };

  // Nothing matched is the wrong-prefix case: creating would produce a project
  // with no data at all, so it is blocked. A partial match warns and allows.
  const runFoundNothing = runStep > 0 && !!runPreview && fromRunFoundNothing(runPreview);
  const runTotals = runPreview ? fromRunMatchTotals(runPreview) : null;
  // Disabled with a visible reason rather than hidden (project convention).
  let runDisabledReason: string | null = null;
  if (!runTemplateId) {
    runDisabledReason = 'Choose a template first';
  } else if (runPrefixInvalid) {
    runDisabledReason = 'The run folder must be an s3:// prefix';
  } else if (trimmedRunDataRoot.length === 0) {
    runDisabledReason = 'Enter the run folder prefix';
  } else if (runNameUsed) {
    runDisabledReason = 'A project with this name already exists';
  } else if (runStep === 1 && (runPreviewLoading || (!runPreview && !runPreviewError))) {
    // Between entering the step and the effect firing there is no preview
    // and no error yet: that is still "loading", not a failure.
    runDisabledReason = 'Reading the run folder';
  } else if (runStep === 1 && runPreviewError) {
    runDisabledReason = 'The run folder could not be read';
  } else if (runFoundNothing) {
    runDisabledReason = 'No data collection matched anything under this prefix';
  }
  const runSubmitDisabled = Boolean(runDisabledReason) || submitting;

  const runDisplayName =
    runPreview?.project_name || trimmedRunName || runSelectedTemplate?.name || 'project';

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      centered
      // The run preview is a five-column table plus full S3 paths, which the
      // other tabs' width would wrap into noise.
      size={tab === 'run' ? 'xl' : 'lg'}
      withCloseButton
      closeOnClickOutside={false}
      closeOnEscape={!submitting}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={null}
      padding="lg"
    >
      <Stack gap="md">
        {/* Title row — folder+ icon + Virgil "Projects" */}
        <Center>
          <Group gap="xs">
            <Icon
              icon="mdi:folder-plus-outline"
              width={28}
              color={`var(--mantine-color-${accent.secondary}-6)`}
            />
            <Title
              order={2}
              c={accent.secondary}
              style={{ fontFamily: 'Virgil', fontWeight: 400 }}
            >
              Projects
            </Title>
          </Group>
        </Center>

        {/* Pill-style tabs (Create New / Import) */}
        <Tabs
          value={tab}
          onChange={(v) => setTab((v as Tab) || 'create')}
          variant="pills"
          color={accent.secondary}
        >
          <Tabs.List justify="center">
            <Tabs.Tab
              value="create"
              leftSection={<Icon icon="mdi:plus" width={16} />}
            >
              Create New
            </Tabs.Tab>
            <Tabs.Tab
              value="import"
              leftSection={<Icon icon="mdi:import" width={16} />}
            >
              Import
            </Tabs.Tab>
            <Tabs.Tab
              value="manifest"
              leftSection={<Icon icon="mdi:link-variant" width={16} />}
            >
              From Manifest
            </Tabs.Tab>
            <Tabs.Tab
              value="run"
              leftSection={<Icon icon="mdi:folder-search-outline" width={16} />}
            >
              From a run folder
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="create" pt="md">
            <Stack gap="md">
              <Stepper
                active={activeStep}
                onStepClick={setActiveStep}
                color={accent.secondary}
                size="sm"
                allowNextStepsSelect={false}
              >
                <Stepper.Step
                  label="Project Type"
                  description="Choose basic or advanced"
                >
                  <Stack gap="md" pt="md">
                    <Text ta="center" fw={500}>
                      Choose your project type:
                    </Text>
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
                      <ProjectTypeCard
                        active={projectType === 'basic'}
                        type="basic"
                        title="Basic Project"
                        description="Perfect for simple data visualization and exploration. No workflows required — upload data collections directly through the UI. Best for individual datasets and quick analysis."
                        icon="mdi:view-dashboard-outline"
                        tag="UI Creation Only"
                        tagColor="cyan"
                        onClick={() => handleSelectType('basic')}
                      />
                      <ProjectTypeCard
                        active={false}
                        type="advanced"
                        title="Advanced Project"
                        description="Designed for complex bioinformatics runs, processing workflows, and data ingestion pipelines. Requires depictio-CLI for project design and workflow management. Best for bioinformatics and computational analysis."
                        icon="mdi:sitemap"
                        tag="Depictio-CLI Only"
                        tagColor="orange"
                        disabled
                      />
                    </SimpleGrid>
                  </Stack>
                </Stepper.Step>

                <Stepper.Step
                  label="Project Details"
                  description="Configure your project"
                >
                  <Stack gap="md" pt="md">
                    <TextInput
                      label="Project Name"
                      description="Give your project a descriptive name"
                      required
                      placeholder="Enter project name"
                      value={name}
                      onChange={(e) => setName(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                      error={
                        nameAlreadyUsed
                          ? 'A project with this name already exists.'
                          : undefined
                      }
                    />
                    <Textarea
                      label="Project Description (Optional)"
                      description="Describe what this project is about"
                      placeholder="Enter project description..."
                      value={description}
                      onChange={(e) => setDescription(e.currentTarget.value)}
                      autosize
                      minRows={2}
                      maxRows={5}
                    />
                    <Switch
                      label={
                        <span style={{ fontFamily: 'Virgil' }}>
                          Make this project public
                        </span>
                      }
                      description="Public projects are visible to all users"
                      checked={isPublic}
                      onChange={(e) => setIsPublic(e.currentTarget.checked)}
                      color={accent.secondary}
                    />
                  </Stack>
                </Stepper.Step>
              </Stepper>

              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}

              <Group justify="space-between">
                <Button
                  variant="default"
                  onClick={() => setActiveStep((s) => Math.max(0, s - 1))}
                  disabled={activeStep === 0 || submitting}
                >
                  Previous
                </Button>
                {activeStep === 0 ? (
                  <Button
                    color={accent.secondary}
                    onClick={() => setActiveStep(1)}
                    disabled={!projectType}
                  >
                    Next
                  </Button>
                ) : (
                  <Button
                    color={accent.secondary}
                    onClick={handleCreate}
                    loading={submitting}
                    disabled={!canSubmit}
                  >
                    Create Project
                  </Button>
                )}
              </Group>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="import" pt="md">
            <Stack gap="md">
              <Text size="sm" c="dimmed" ta="center">
                Upload a .zip bundle exported from another Depictio instance.
              </Text>
              <FileButton
                resetRef={importResetRef}
                accept=".zip,application/zip,application/x-zip-compressed"
                onChange={(f) => setImportFile(f)}
              >
                {(props) => (
                  <Box
                    {...props}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
                      if (e.key === 'Enter' || e.key === ' ') props.onClick();
                    }}
                    style={{
                      cursor: 'pointer',
                      border: `2px dashed var(--mantine-color-${accent.secondary}-6)`,
                      borderRadius: 12,
                      padding: 32,
                      textAlign: 'center' as const,
                      background: 'var(--mantine-color-default-hover)',
                    }}
                  >
                    <Stack gap="xs" align="center">
                      <Icon
                        icon="mdi:file-upload-outline"
                        width={36}
                        color={`var(--mantine-color-${accent.secondary}-6)`}
                      />
                      <Text fw={500}>
                        {importFile
                          ? importFile.name
                          : 'Drop .zip here or click to browse'}
                      </Text>
                      {importFile && (
                        <Text size="xs" c="dimmed">
                          {(importFile.size / 1024).toFixed(1)} KB
                        </Text>
                      )}
                    </Stack>
                  </Box>
                )}
              </FileButton>
              <Switch
                label={
                  <span style={{ fontFamily: 'Virgil' }}>
                    overwrite if project already exists
                  </span>
                }
                checked={overwrite}
                onChange={(e) => setOverwrite(e.currentTarget.checked)}
                color={accent.secondary}
              />
              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}
              <Button
                color={accent.secondary}
                onClick={handleImport}
                disabled={!importFile || submitting}
                loading={submitting}
                leftSection={<Icon icon="mdi:check" width={16} />}
                fullWidth
              >
                Import Project
              </Button>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="manifest" pt="md">
            <Stack gap="md">
              <Stepper
                active={manifestStep}
                onStepClick={setManifestStep}
                color={accent.secondary}
                size="sm"
                allowNextStepsSelect={false}
              >
                <Stepper.Step label="Source" description="Manifest & template">
                  <Stack gap="md" pt="md">
                    <TextInput
                      label="Manifest URL"
                      description="HTTP(S) link to a {id, type, url} Data Manifest"
                      required
                      placeholder="https://example.org/data/manifest.json"
                      value={manifestUrl}
                      onChange={(e) => setManifestUrl(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:link-variant" width={16} />}
                      data-testid="manifest-url-input"
                    />
                    <Select
                      label="Template"
                      description={
                        selectedTemplate?.description ||
                        'Choose a manifest-capable project template'
                      }
                      required
                      placeholder="Select a template"
                      data={manifestTemplates.map((t) => ({
                        value: t.template_id,
                        label: t.name,
                      }))}
                      value={manifestTemplateId}
                      onChange={setManifestTemplateId}
                      leftSection={
                        <Icon icon="mdi:file-document-outline" width={16} />
                      }
                      error={templatesError ?? undefined}
                      // Show the template_id under each name so near-identical
                      // templates stay distinguishable in the dropdown.
                      renderOption={({ option }) => (
                        <Stack gap={0}>
                          <Text size="sm">{option.label}</Text>
                          <Text size="xs" c="dimmed">
                            {option.value}
                          </Text>
                        </Stack>
                      )}
                      data-testid="manifest-template-select"
                    />
                    <TextInput
                      label="Project Name (Optional)"
                      description="Defaults to a name derived from the template"
                      placeholder="Enter project name"
                      value={manifestProjectName}
                      onChange={(e) => setManifestProjectName(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                      error={
                        manifestNameUsed
                          ? 'A project with this name already exists.'
                          : undefined
                      }
                      data-testid="manifest-project-name-input"
                    />
                    {extraVariables.map((v) => (
                      <TextInput
                        key={v.name}
                        label={`${v.name} (Optional)`}
                        description={v.description ?? undefined}
                        placeholder={v.default ?? ''}
                        value={manifestVariables[v.name] ?? ''}
                        onChange={(e) => {
                          const value = e.currentTarget.value;
                          setManifestVariables((prev) => ({
                            ...prev,
                            [v.name]: value,
                          }));
                        }}
                      />
                    ))}
                  </Stack>
                </Stepper.Step>

                <Stepper.Step label="Preview" description="Planned ingestion">
                  <Stack gap="md" pt="md">
                    {previewLoading && (
                      <Center mih={120}>
                        <Group gap="xs">
                          <Loader size="sm" color={accent.secondary} />
                          <Text size="sm" c="dimmed">
                            Reading the manifest and planning ingestion…
                          </Text>
                        </Group>
                      </Center>
                    )}
                    {previewError && (
                      <Alert color="red" variant="light">
                        {previewError}
                      </Alert>
                    )}
                    {preview && (
                      <ManifestPreviewReport report={preview} />
                    )}
                  </Stack>
                </Stepper.Step>

                <Stepper.Step label="Create" description="Confirm & create">
                  <Stack gap="md" pt="md">
                    <Paper withBorder radius="md" p="lg">
                      <Stack gap="sm" align="center">
                        <Icon
                          icon="mdi:rocket-launch-outline"
                          width={36}
                          color={`var(--mantine-color-${accent.secondary}-6)`}
                        />
                        <Text fw={500} ta="center">
                          Create “{manifestDisplayName}”
                        </Text>
                        <Text size="xs" c="dimmed" ta="center">
                          {preview
                            ? `${preview.manifest_entries} manifest entries → ` +
                              `${preview.ingestion.length} data collection${
                                preview.ingestion.length === 1 ? '' : 's'
                              }, ${preview.dashboards.length} dashboard${
                                preview.dashboards.length === 1 ? '' : 's'
                              }.`
                            : 'The manifest will be ingested and the template dashboards imported.'}
                        </Text>
                      </Stack>
                    </Paper>
                  </Stack>
                </Stepper.Step>
              </Stepper>

              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}

              <Group justify="space-between">
                <Button
                  variant="default"
                  onClick={() => setManifestStep((s) => Math.max(0, s - 1))}
                  disabled={manifestStep === 0 || submitting}
                >
                  Previous
                </Button>
                <Button
                  color={accent.secondary}
                  onClick={handleManifestSubmit}
                  loading={submitting}
                  disabled={manifestSubmitDisabled}
                  data-testid="create-from-manifest-submit"
                >
                  {manifestStep === 2 ? 'Create Project' : 'Next'}
                </Button>
              </Group>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="run" pt="md">
            <Stack gap="md">
              <Stepper
                active={runStep}
                onStepClick={setRunStep}
                color={accent.secondary}
                size="sm"
                allowNextStepsSelect={false}
              >
                <Stepper.Step label="Source" description="Run folder & template">
                  <Stack gap="md" pt="md">
                    <Select
                      label="Template"
                      description={
                        runSelectedTemplate?.description ||
                        'Choose the template matching the pipeline that produced this run'
                      }
                      required
                      placeholder="Select a template"
                      data={templates.map((t) => ({
                        value: t.template_id,
                        label: t.name,
                      }))}
                      value={runTemplateId}
                      onChange={setRunTemplateId}
                      leftSection={<Icon icon="mdi:file-document-outline" width={16} />}
                      error={templatesError ?? undefined}
                      searchable
                      // Show the template_id under each name so near-identical
                      // templates stay distinguishable in the dropdown.
                      renderOption={({ option }) => (
                        <Stack gap={0}>
                          <Text size="sm">{option.label}</Text>
                          <Text size="xs" c="dimmed">
                            {option.value}
                          </Text>
                        </Stack>
                      )}
                      data-testid="run-template-select"
                    />
                    <TextInput
                      label="Run folder"
                      description="S3 prefix of one pipeline run folder, the level the template's paths are relative to"
                      required
                      placeholder="s3://bucket/pipeline/run-id"
                      value={runDataRoot}
                      onChange={(e) => setRunDataRoot(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:folder-search-outline" width={16} />}
                      error={
                        runPrefixInvalid
                          ? 'The run folder must be an s3:// prefix.'
                          : undefined
                      }
                      data-testid="run-data-root-input"
                    />
                    <TextInput
                      label="Project Name (Optional)"
                      description="Defaults to a name derived from the template"
                      placeholder="Enter project name"
                      value={runProjectName}
                      onChange={(e) => setRunProjectName(e.currentTarget.value)}
                      leftSection={<Icon icon="mdi:folder-outline" width={16} />}
                      error={
                        runNameUsed
                          ? 'A project with this name already exists.'
                          : undefined
                      }
                      data-testid="run-project-name-input"
                    />
                    {runExtraVariables.map((v) => (
                      <TextInput
                        key={v.name}
                        label={`${v.name} (Optional)`}
                        description={v.description ?? undefined}
                        placeholder={v.default ?? ''}
                        value={runVariables[v.name] ?? ''}
                        onChange={(e) => {
                          const value = e.currentTarget.value;
                          setRunVariables((prev) => ({
                            ...prev,
                            [v.name]: value,
                          }));
                        }}
                      />
                    ))}
                  </Stack>
                </Stepper.Step>

                <Stepper.Step label="Preview" description="What each collection gets">
                  <Stack gap="md" pt="md">
                    {runPreviewLoading && (
                      <Center mih={120}>
                        <Group gap="xs">
                          <Loader size="sm" color={accent.secondary} />
                          <Text size="sm" c="dimmed">
                            Reading the run folder and resolving the template…
                          </Text>
                        </Group>
                      </Center>
                    )}
                    {runPreviewError && (
                      <Alert color="red" variant="light" data-testid="run-preview-error">
                        {runPreviewError}
                      </Alert>
                    )}
                    {runPreview && <FromRunPreviewReport report={runPreview} />}
                    {runFoundNothing && (
                      <Alert
                        color="red"
                        variant="light"
                        icon={<Icon icon="mdi:alert-circle" width={16} />}
                        data-testid="run-no-match-warning"
                      >
                        <Text size="sm">
                          No data collection matched anything under this prefix, so
                          there is nothing to ingest. The paths listed above are what
                          the server looked for: a run folder set one directory too
                          high, or too low, is the usual cause.
                        </Text>
                      </Alert>
                    )}
                    {!runFoundNothing &&
                      runTotals &&
                      runTotals.matched < runTotals.considered && (
                        <Alert
                          color="yellow"
                          variant="light"
                          icon={<Icon icon="mdi:information-outline" width={16} />}
                          data-testid="run-partial-warning"
                        >
                          <Text size="sm">
                            {runTotals.considered - runTotals.matched} of{' '}
                            {runTotals.considered} collections found no inputs. You can
                            still create the project; those collections stay empty
                            until their inputs exist.
                          </Text>
                        </Alert>
                      )}
                  </Stack>
                </Stepper.Step>

                <Stepper.Step label="Create" description="Confirm & ingest">
                  <Stack gap="md" pt="md">
                    <Paper withBorder radius="md" p="lg">
                      <Stack gap="sm" align="center">
                        <Icon
                          icon="mdi:rocket-launch-outline"
                          width={36}
                          color={`var(--mantine-color-${accent.secondary}-6)`}
                        />
                        <Text fw={500} ta="center">
                          Create “{runDisplayName}”
                        </Text>
                        <Text size="xs" c="dimmed" ta="center">
                          {runTotals
                            ? `${runTotals.matched} of ${runTotals.considered} data ` +
                              `collection${runTotals.considered === 1 ? '' : 's'} will ` +
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
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}

              <Group justify="space-between">
                <Button
                  variant="default"
                  onClick={() => setRunStep((s) => Math.max(0, s - 1))}
                  disabled={runStep === 0 || submitting}
                >
                  Previous
                </Button>
                <Group gap="xs" wrap="nowrap">
                  {runDisabledReason && (
                    <Text size="xs" c="dimmed" data-testid="run-submit-disabled-reason">
                      {runDisabledReason}
                    </Text>
                  )}
                  <Button
                    color={accent.secondary}
                    onClick={handleRunSubmit}
                    loading={submitting}
                    disabled={runSubmitDisabled}
                    title={runDisabledReason ?? undefined}
                    data-testid="create-from-run-submit"
                  >
                    {runStep === 2 ? 'Create Project' : 'Next'}
                  </Button>
                </Group>
              </Group>
            </Stack>
          </Tabs.Panel>
        </Tabs>
      </Stack>
    </Modal>
  );
};

/** True when a real (non dry-run) from-manifest report carries something the
 *  user should see before moving on: a manifest type no collection matched,
 *  an optional collection the template pruned, a collection or dashboard
 *  that failed. A clean report redirects straight to the dashboard. */
export function manifestReportNeedsReview(report: FromManifestReport): boolean {
  return (
    !report.success ||
    report.unmatched_manifest_types.length > 0 ||
    report.pruned_optional_dcs.length > 0 ||
    report.ingestion.some((dc) => dc.status === 'failed') ||
    report.dashboards.some((d) => !d.success)
  );
}

/** Per-DC rows plus the manifest types the template didn't match and the
 *  optional collections it pruned. Renders the dry-run plan on the Preview
 *  step and, unchanged, the real report after creation (where dashboards
 *  that failed to import are listed as well). */
export const ManifestPreviewReport: React.FC<{ report: FromManifestReport }> = ({ report }) => {
  const accent = useBrandAccents();
  const failedDashboards = report.dashboards.filter((d) => !d.success);
  return (
    <Stack gap="sm" data-testid="manifest-preview-report">
      <Group gap="xs" wrap="wrap">
        <Badge variant="light" color={accent.secondary} radius="sm">
          {report.project_name}
        </Badge>
        <Badge variant="light" color="gray" radius="sm">
          {report.manifest_entries} manifest entries
        </Badge>
        <Badge variant="light" color="gray" radius="sm">
          {report.dashboards.length} dashboard{report.dashboards.length === 1 ? '' : 's'}
        </Badge>
      </Group>
      <Table verticalSpacing="xs" striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Data collection</Table.Th>
            <Table.Th>Entries</Table.Th>
            <Table.Th>Status</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {report.ingestion.map((dc) => {
            const meta = MANIFEST_STATUS_META[dc.status] ?? MANIFEST_STATUS_META.planned;
            return (
              <Table.Tr key={dc.data_collection_tag}>
                <Table.Td>
                  <Text size="sm" fw={600}>
                    {dc.data_collection_tag}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{dc.entries}</Text>
                </Table.Td>
                <Table.Td>
                  <Group gap={6} wrap="nowrap">
                    <Badge
                      variant="light"
                      color={meta.color}
                      size="sm"
                      leftSection={<Icon icon={meta.icon} width={12} />}
                    >
                      {meta.label}
                    </Badge>
                    {dc.message && (
                      <Text size="xs" c="dimmed">
                        {dc.message}
                      </Text>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
      {report.unmatched_manifest_types.length > 0 && (
        <Group gap="xs" wrap="wrap">
          <Text size="xs" c="dimmed">
            Unmatched manifest types:
          </Text>
          {report.unmatched_manifest_types.map((t) => (
            <Badge key={t} variant="light" color="gray" size="sm" radius="sm">
              {t}
            </Badge>
          ))}
        </Group>
      )}
      {report.pruned_optional_dcs.length > 0 && (
        <Group gap="xs" wrap="wrap">
          <Text size="xs" c="dimmed">
            Skipped optional collections:
          </Text>
          {report.pruned_optional_dcs.map((t) => (
            <Badge key={t} variant="light" color="gray" size="sm" radius="sm">
              {t}
            </Badge>
          ))}
        </Group>
      )}
      {failedDashboards.length > 0 && (
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            Dashboards that failed to import:
          </Text>
          {failedDashboards.map((d) => (
            <Group key={d.path} gap="xs" wrap="nowrap">
              <Badge variant="light" color="red" size="sm" radius="sm">
                {d.title || d.path}
              </Badge>
              {d.error && (
                <Text size="xs" c="red">
                  {d.error}
                </Text>
              )}
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
};

/** Post-creation report for a from-manifest project that needs a look before
 *  the user lands on its dashboard (see `manifestReportNeedsReview`). The
 *  project already exists and the list behind the modal is refreshed; the
 *  user picks between opening the dashboard and staying on the list. */
export const ManifestCreatedModal: React.FC<{
  report: FromManifestReport | null;
  onClose: () => void;
}> = ({ report, onClose }) => {
  const accent = useBrandAccents();
  const dashboardId =
    report?.dashboards.find((d) => d.success && d.dashboard_id)?.dashboard_id ?? null;

  const summary: string[] = [];
  if (report) {
    const ingested = report.ingestion.filter((dc) => dc.status === 'ingested').length;
    const failed = report.ingestion.filter((dc) => dc.status === 'failed').length;
    summary.push(
      `${ingested} of ${report.ingestion.length} collection${
        report.ingestion.length === 1 ? '' : 's'
      } ingested${failed > 0 ? `, ${failed} failed` : ''}`,
    );
    if (report.unmatched_manifest_types.length > 0) {
      summary.push(
        `${report.unmatched_manifest_types.length} manifest type${
          report.unmatched_manifest_types.length === 1 ? '' : 's'
        } without a matching collection`,
      );
    }
    if (report.pruned_optional_dcs.length > 0) {
      summary.push(
        `${report.pruned_optional_dcs.length} optional collection${
          report.pruned_optional_dcs.length === 1 ? '' : 's'
        } skipped`,
      );
    }
    const failedDashboards = report.dashboards.filter((d) => !d.success).length;
    if (failedDashboards > 0) {
      summary.push(
        `${failedDashboards} dashboard${failedDashboards === 1 ? '' : 's'} failed to import`,
      );
    }
  }

  return (
    <Modal
      opened={Boolean(report)}
      onClose={onClose}
      centered
      size="lg"
      title={
        <Group gap="xs" wrap="nowrap">
          <Icon
            icon="mdi:clipboard-check-outline"
            width={20}
            color={`var(--mantine-color-${accent.secondary}-6)`}
          />
          <Text fw={600}>Project created with notes</Text>
        </Group>
      }
    >
      {report && (
        <Stack gap="md" data-testid="manifest-created-modal">
          <Alert
            color={report.success ? 'yellow' : 'orange'}
            variant="light"
            icon={<Icon icon="mdi:information-outline" width={16} />}
          >
            <Text size="sm">
              &ldquo;{report.project_name}&rdquo; was created: {summary.join('; ')}.
            </Text>
          </Alert>
          <ManifestPreviewReport report={report} />
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={onClose} data-testid="manifest-created-stay">
              Stay on projects
            </Button>
            <Button
              color={accent.secondary}
              leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
              disabled={!dashboardId}
              title={dashboardId ? undefined : 'No dashboard was imported for this project'}
              onClick={() => {
                if (dashboardId) window.location.assign(`/dashboard/${dashboardId}`);
              }}
              data-testid="manifest-created-open-dashboard"
            >
              Open dashboard
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
};

interface ProjectTypeCardProps {
  active: boolean;
  type: ProjectType;
  title: string;
  description: string;
  icon: string;
  tag: string;
  tagColor: string;
  disabled?: boolean;
  onClick?: () => void;
}

const ProjectTypeCard: React.FC<ProjectTypeCardProps> = ({
  active,
  type,
  title,
  description,
  icon,
  tag,
  tagColor,
  disabled,
  onClick,
}) => {
  // Project-type taxonomy, not a brand role — basic and advanced have to stay
  // told apart, so these keep their own hues.
  const typeAccent =
    type === 'basic' ? 'var(--mantine-color-teal-6)' : 'var(--mantine-color-orange-6)';
  return (
    <Paper
      withBorder
      radius="md"
      p="lg"
      onClick={disabled ? undefined : onClick}
      style={{
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        borderColor: active ? typeAccent : undefined,
        borderWidth: active ? 2 : 1,
        transition: 'border-color 120ms ease',
      }}
    >
      <Stack gap="sm" align="center">
        <Icon icon={icon} width={42} height={42} color={typeAccent} />
        <Title order={4} ta="center">
          {title}
        </Title>
        <Text size="xs" c="dimmed" ta="center" lh={1.4}>
          {description}
        </Text>
        <Badge color={tagColor} variant="light" radius="sm">
          {tag}
        </Badge>
      </Stack>
    </Paper>
  );
};

export default CreateProjectModal;
