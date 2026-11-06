import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Stepper,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { createProjectFromManifest, listProjectTemplates, Z_LAYERS } from 'depictio-react-core';
import { useListingAccents } from '../lib/useListingAccents';
import type {
  CreateProjectInput,
  CreateProjectResult,
  FromManifestReport,
  FromManifestRequest,
  FromRunReport,
  FromRunRequest,
  TemplateInfo,
  TemplateVariable,
} from 'depictio-react-core';

import IngestionResultTable from './IngestionResultTable';
import { useStepSettling } from './hooks/useStepSettling';
import { DisabledReason, GatedButton } from '../components/settings/SettingsSections';
import { RunFolderTab } from './fromRun';
import type { RunCreatedContext } from './fromRun';

/** Where a new project starts from; null is the chooser. */
type Tab = 'create' | 'manifest' | 'run';

/** A required template variable with a declared default is filled in
 *  server-side, so only the ones without a default must be typed here. */
const mustBeTyped = (v: TemplateVariable): boolean => v.required && !v.default;

/** Stack id of the create dialog: the run tab's folder browser opens above
 *  it, in the same `Modal.Stack`. */
const CREATE_STACK_ID = 'create-project';

/** "1 dashboard", "2 dashboards". */
const plural = (n: number, one: string, many = `${one}s`): string =>
  `${n} ${n === 1 ? one : many}`;

interface CreateProjectModalProps {
  opened: boolean;
  existingNames: string[];
  onClose: () => void;
  onCreate: (input: CreateProjectInput) => Promise<CreateProjectResult>;
  onCreateFromManifest: (input: FromManifestRequest) => Promise<FromManifestReport>;
  onCreateFromRun: (input: FromRunRequest, context: RunCreatedContext) => Promise<FromRunReport>;
  /** The server reads run folders from its own disk (`depictio local`): the
   *  run tab then takes a local path and offers a folder browser. */
  localDataRootsEnabled?: boolean;
  /** The server may browse allowed S3 locations: the folder browser then
   *  offers an S3 side. */
  remoteBrowseEnabled?: boolean;
  /** Why the run tab may not take a private bucket's connection details
   *  (public mode, non-admin); null when it may. */
  privateBucketDisabledReason?: string | null;
}

const CreateProjectModal: React.FC<CreateProjectModalProps> = ({
  opened,
  existingNames,
  onClose,
  onCreate,
  onCreateFromManifest,
  onCreateFromRun,
  localDataRootsEnabled = false,
  remoteBrowseEnabled = false,
  privateBucketDisabledReason = null,
}) => {
  const accent = useListingAccents('projects');
  const [tab, setTab] = useState<Tab | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  // Reset everything whenever the modal opens.
  useEffect(() => {
    if (!opened) return;
    setTab(null);
    setName('');
    setDescription('');
    setIsPublic(false);
    setManifestStep(0);
    setManifestUrl('');
    setManifestTemplateId(null);
    setManifestProjectName('');
    setManifestVariables({});
    setPreview(null);
    setPreviewError(null);
    setError(null);
    setSubmitting(false);
  }, [opened]);

  // Every template the backend knows, fetched fresh per open so a newly
  // registered template shows up without a page reload. The From Manifest tab
  // narrows this to the manifest-capable ones, the From a run folder tab to
  // the run-folder-capable ones (grouped per pipeline).
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

  const isNameTaken = (candidate: string) =>
    existingNames.some((n) => n.toLowerCase() === candidate.toLowerCase());

  const trimmedName = name.trim();
  const nameAlreadyUsed = isNameTaken(trimmedName);
  const canSubmit = trimmedName.length > 0 && !nameAlreadyUsed && !submitting;

  const handleCreate = async () => {
    if (!trimmedName) return;
    setSubmitting(true);
    setError(null);
    try {
      await onCreate({
        name: trimmedName,
        // Legacy field: the type no longer changes what a project can do.
        project_type: 'basic',
        is_public: isPublic,
        ...(description.trim() ? { description: description.trim() } : {}),
      } as CreateProjectInput);
    } catch (err) {
      setError((err as Error).message || 'Failed to create project.');
    } finally {
      setSubmitting(false);
    }
  };

  const selectedTemplate =
    manifestTemplates.find((t) => t.template_id === manifestTemplateId) ?? null;
  // MANIFEST_URL is injected server-side from the URL field: never render a
  // form input for it.
  const extraVariables = (selectedTemplate?.variables ?? []).filter(
    (v) => v.name !== 'MANIFEST_URL',
  );
  const missingVariables = extraVariables
    .filter((v) => mustBeTyped(v) && !(manifestVariables[v.name] ?? '').trim())
    .map((v) => v.name);
  const missingVariablesReason =
    missingVariables.length > 0
      ? `Enter a value for ${missingVariables.join(', ')} to continue.`
      : null;

  const trimmedManifestUrl = manifestUrl.trim();
  const trimmedManifestName = manifestProjectName.trim();
  const manifestNameUsed = trimmedManifestName.length > 0 && isNameTaken(trimmedManifestName);
  const manifestSourceReady =
    trimmedManifestUrl.length > 0 &&
    !!manifestTemplateId &&
    !manifestNameUsed &&
    missingVariables.length === 0;

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
  // It ignores clicks for a moment after each step change, so a double click
  // on Next stops on the Create step instead of creating straight away.
  const manifestStepSettling = useStepSettling(manifestStep);
  const handleManifestSubmit = async () => {
    if (!manifestSourceReady || manifestStepSettling) return;
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

  // Escape and the close button both land here; neither may drop a request
  // that is still being sent.
  const handleModalClose = () => {
    if (!submitting) onClose();
  };

  const createDialog = (
    <Modal
      stackId={CREATE_STACK_ID}
      className="depictio-form-modal"
      opened={opened}
      onClose={handleModalClose}
      centered
      // The run tab shows a detection card, a two-column summary and the
      // grouped plan, which the other tabs' width would wrap into noise.
      size={tab === 'run' ? 1160 : 980}
      withCloseButton
      closeOnClickOutside={false}
      closeOnEscape={!submitting}
      overlayProps={{ blur: 3, backgroundOpacity: 0.55 }}
      title={null}
      padding="xl"
    >
      <Stack gap="md">
        {/* Title row: folder+ icon + Virgil "Projects" */}
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

        {tab === null ? (
          <Stack gap="md" data-testid="create-project-chooser">
            <Text ta="center" fw={500} size="lg">
              Start a project from:
            </Text>
            <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="lg">
              <SourceCard
                icon="mdi:folder-plus-outline"
                title="An empty project"
                description="Name it, then add data collections from the project page: drop a folder or files, or link a bucket."
                onClick={() => setTab('create')}
                testId="create-source-empty"
              />
              <SourceCard
                icon="mdi:link-variant"
                title="A data manifest"
                description="Point to a manifest URL and pick a template: the data collections and dashboards are built from it."
                onClick={() => setTab('manifest')}
                testId="create-source-manifest"
              />
              <SourceCard
                icon="mdi:folder-search-outline"
                title="A run folder"
                description="Point to a pipeline run folder: Depictio detects what it holds and plans the project."
                onClick={() => setTab('run')}
                testId="create-source-run"
              />
            </SimpleGrid>
          </Stack>
        ) : (
        <Tabs value={tab} variant="unstyled" color={accent.secondary}>
          <Button
            variant="subtle"
            color="gray"
            size="compact-sm"
            leftSection={<Icon icon="mdi:arrow-left" width={16} />}
            onClick={() => setTab(null)}
            disabled={submitting}
            data-testid="create-source-back"
          >
            Start from
          </Button>

          <Tabs.Panel value="create" pt="md">
            <Stack gap="md">
                  <Stack gap="lg" pt="md">
                    <TextInput
                      size="md"
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
                      size="md"
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
                      size="md"
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

              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}

              <Group justify="flex-end">
                <Button
                  size="md"
                  color={accent.secondary}
                  onClick={handleCreate}
                  loading={submitting}
                  disabled={!canSubmit}
                  data-testid="create-project-submit"
                >
                  Create project
                </Button>
              </Group>
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
                      comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
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
                        label={mustBeTyped(v) ? v.name : `${v.name} (Optional)`}
                        required={mustBeTyped(v)}
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
                      <Alert
                        color="red"
                        variant="light"
                        icon={<Icon icon="mdi:alert-circle-outline" width={16} />}
                      >
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
                    <Paper withBorder radius="md" p="lg" data-testid="manifest-create-step">
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
                            ? `${plural(preview.manifest_entries, 'manifest entry', 'manifest entries')} → ` +
                              `${plural(preview.ingestion.length, 'data collection')}, ` +
                              `${plural(preview.dashboards.length, 'dashboard')}.`
                            : 'The manifest will be ingested and the template dashboards imported.'}
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
                >
                  {error}
                </Alert>
              )}

              <Group justify="space-between">
                <Button
                  variant="default"
                  onClick={() =>
                    manifestStep === 0 ? setTab(null) : setManifestStep((s) => s - 1)
                  }
                  disabled={submitting}
                >
                  {manifestStep === 0 ? 'Back' : 'Previous'}
                </Button>
                <Button
                  color={accent.secondary}
                  onClick={handleManifestSubmit}
                  loading={submitting}
                  disabled={manifestSubmitDisabled}
                  aria-disabled={manifestStepSettling || undefined}
                  data-testid="create-from-manifest-submit"
                >
                  {manifestStep === 2 ? 'Create Project' : 'Next'}
                </Button>
              </Group>
              {manifestStep === 0 && <DisabledReason reason={missingVariablesReason} />}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="run" pt="md">
            <RunFolderTab
              opened={opened}
              existingNames={existingNames}
              templates={templates}
              templatesError={templatesError}
              localDataRootsEnabled={localDataRootsEnabled}
              remoteBrowseEnabled={remoteBrowseEnabled}
              privateBucketDisabledReason={privateBucketDisabledReason}
              onCreateFromRun={onCreateFromRun}
              submitting={submitting}
              setSubmitting={setSubmitting}
              onBack={() => setTab(null)}
            />
          </Tabs.Panel>
        </Tabs>
        )}
      </Stack>
    </Modal>
  );

  // One stack, so the run tab's folder browser gets the higher layer and
  // Escape closes only the top one.
  return <Modal.Stack>{createDialog}</Modal.Stack>;
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

/** A dimmed label followed by one grey badge per tag; nothing when empty. */
const TagList: React.FC<{ label: string; tags: string[] }> = ({ label, tags }) =>
  tags.length > 0 ? (
    <Group gap="xs" wrap="wrap">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      {tags.map((t) => (
        <Badge key={t} variant="light" color="gray" size="sm" radius="sm">
          {t}
        </Badge>
      ))}
    </Group>
  ) : null;

/** Per-DC rows plus the manifest types the template didn't match and the
 *  optional collections it pruned. Renders the dry-run plan on the Preview
 *  step and, unchanged, the real report after creation (where dashboards
 *  that failed to import are listed as well). */
export const ManifestPreviewReport: React.FC<{ report: FromManifestReport }> = ({ report }) => {
  const accent = useListingAccents('projects');
  const failedDashboards = report.dashboards.filter((d) => !d.success);
  return (
    <Stack gap="sm" data-testid="manifest-preview-report">
      <Group gap="xs" wrap="wrap">
        <Badge variant="light" color={accent.secondary} radius="sm">
          {report.project_name}
        </Badge>
        {report.manifest_entries > 0 && (
          <Badge variant="light" color="gray" radius="sm">
            {plural(report.manifest_entries, 'manifest entry', 'manifest entries')}
          </Badge>
        )}
        {report.dashboards.length > 0 && (
          <Badge variant="light" color="gray" radius="sm">
            {plural(report.dashboards.length, 'dashboard')}
          </Badge>
        )}
      </Group>
      {(report.manifest_entries === 0 || report.dashboards.length === 0) && (
        <Text size="xs" c="dimmed">
          {report.manifest_entries === 0 ? 'The manifest lists no entry. ' : ''}
          {report.dashboards.length === 0 ? 'The template has no dashboard to import.' : ''}
        </Text>
      )}
      <IngestionResultTable
        rows={report.ingestion}
        rowTestIdPrefix="manifest-preview"
        emptyText="The template matched no data collection in this manifest."
      />
      <TagList label="Unmatched manifest types:" tags={report.unmatched_manifest_types} />
      <TagList label="Skipped optional collections:" tags={report.pruned_optional_dcs} />
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

/** "3 of 4 collections ingested, 1 failed; 2 manifest types without a matching
 *  collection", one clause per kind of note the report carries. */
function summarizeCreated(report: FromManifestReport): string {
  const ingested = report.ingestion.filter((dc) => dc.status === 'ingested').length;
  const failed = report.ingestion.filter((dc) => dc.status === 'failed').length;
  const failedDashboards = report.dashboards.filter((d) => !d.success).length;
  const clauses = [
    `${ingested} of ${plural(report.ingestion.length, 'collection')} ingested` +
      (failed > 0 ? `, ${failed} failed` : ''),
  ];
  if (report.unmatched_manifest_types.length > 0) {
    clauses.push(
      `${plural(report.unmatched_manifest_types.length, 'manifest type')} without a matching collection`,
    );
  }
  if (report.pruned_optional_dcs.length > 0) {
    clauses.push(`${plural(report.pruned_optional_dcs.length, 'optional collection')} skipped`);
  }
  if (failedDashboards > 0) {
    clauses.push(`${plural(failedDashboards, 'dashboard')} failed to import`);
  }
  return clauses.join('; ');
}

/** Post-creation report for a from-manifest project that needs a look before
 *  the user lands on its dashboard (see `manifestReportNeedsReview`). The
 *  project already exists and the list behind the modal is refreshed; the
 *  user picks between opening the dashboard and staying on the list. */
export const ManifestCreatedModal: React.FC<{
  report: FromManifestReport | null;
  onClose: () => void;
}> = ({ report, onClose }) => {
  const accent = useListingAccents('projects');
  const dashboardId =
    report?.dashboards.find((d) => d.success && d.dashboard_id)?.dashboard_id ?? null;
  const openDashboardReason = dashboardId ? null : 'No dashboard was imported for this project.';

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
              &ldquo;{report.project_name}&rdquo; was created: {summarizeCreated(report)}.
            </Text>
          </Alert>
          <ManifestPreviewReport report={report} />
          <Stack gap={6} align="flex-end">
            <Group justify="flex-end" gap="xs">
              <Button variant="default" onClick={onClose} data-testid="manifest-created-stay">
                Stay on projects
              </Button>
              <GatedButton
                color={accent.secondary}
                leftSection={<Icon icon="mdi:view-dashboard-outline" width={16} />}
                reason={openDashboardReason}
                onClick={() => {
                  if (dashboardId) window.location.assign(`/dashboard/${dashboardId}`);
                }}
                data-testid="manifest-created-open-dashboard"
              >
                Open dashboard
              </GatedButton>
            </Group>
            <DisabledReason reason={openDashboardReason} />
          </Stack>
        </Stack>
      )}
    </Modal>
  );
};

interface SourceCardProps {
  icon: string;
  title: string;
  description: string;
  onClick: () => void;
  testId: string;
}

const SourceCard: React.FC<SourceCardProps> = ({ icon, title, description, onClick, testId }) => (
  <Paper
    withBorder
    radius="md"
    p="xl"
    role="button"
    tabIndex={0}
    onClick={onClick}
    onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Enter' || e.key === ' ') onClick();
    }}
    style={{ cursor: 'pointer' }}
    data-testid={testId}
  >
    <Stack gap="sm" align="center">
      <Icon icon={icon} width={48} height={48} color="var(--mantine-primary-color-filled)" />
      <Title order={3} ta="center">
        {title}
      </Title>
      <Text size="md" c="dimmed" ta="center" lh={1.5}>
        {description}
      </Text>
    </Stack>
  </Paper>
);

export default CreateProjectModal;
