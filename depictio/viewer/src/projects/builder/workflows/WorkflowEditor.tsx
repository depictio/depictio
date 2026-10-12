/**
 * The selected workflow: name, engine, versions, catalog, repository (with a
 * metadata fetch) and structure (flat, or one level of run folders). Edits
 * go straight to the draft; a name another workflow uses is shown, not
 * refused, so typing through a clash is never blocked.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Collapse,
  Group,
  Loader,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { Icon } from '@iconify/react';

import {
  builderMetadata,
  builderRunsRegex,
  BUILDER_CATALOGS,
  isWorkflowNameTaken,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  BuilderCatalogName,
  BuilderRootSpec,
  BuilderRunsRegex,
  BuilderState,
  BuilderWorkflowPatch,
  BuilderWorkflowState,
} from 'depictio-react-core';

import { OptionalBlock, SectionHead } from '../Requirement';
import { RepoMetadata } from './RepoMetadata';
import { RunsPanel } from './RunsPanel';
import { CATALOG_OPTIONS, ENGINE_OPTIONS, engineLabel, WorkflowLogo } from './WorkflowLogo';

const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

interface WorkflowEditorProps {
  state: BuilderState;
  workflow: BuilderWorkflowState;
  /** The data root whose first-level folders the runs regex is read from. */
  root: BuilderRootSpec;
  /** Bumped to open the editor and bring it into view (the guide's first step). */
  focusRequest?: number;
  onChange: (patch: BuilderWorkflowPatch) => void;
}

export const WorkflowEditor: React.FC<WorkflowEditorProps> = ({ state, workflow, root, focusRequest = 0, onChange }) => {
  const accent = useBrandAccents();
  // Folded for the lone default workflow: a single-workflow project never
  // has to look at it.
  // Open until a collection exists: a new workflow is what the reader has to
  // look at first. Folded once it has collections, to leave room for them.
  const [open, setOpen] = useState(state.workflows.length > 1 || workflow.data_collections.length === 0);
  const [fetching, setFetching] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusRequest) return;
    setOpen(true);
    rootRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [focusRequest]);
  const [detecting, setDetecting] = useState(false);
  // What the last reading of the folders found, shown under the field.
  const [detected, setDetected] = useState<BuilderRunsRegex | null>(null);
  const repoUrl = (workflow.repository_url ?? '').trim();
  const nameClash = isWorkflowNameTaken(state, workflow.name, workflow.id);
  const nameEmpty = !workflow.name.trim();

  const fetchMeta = useCallback(async () => {
    if (!repoUrl) return;
    setFetching(true);
    try {
      const meta = await builderMetadata(repoUrl);
      const patch: BuilderWorkflowPatch = { repository_url: meta.repository_url || repoUrl, meta };
      // A fetched name only replaces the default one, and never makes a clash.
      if (meta.name && !isWorkflowNameTaken(state, meta.name, workflow.id)) patch.name = meta.name;
      if (meta.engine) patch.engine = meta.engine.toLowerCase();
      if (meta.version) patch.version = meta.version;
      if (meta.catalog && BUILDER_CATALOGS.includes(meta.catalog.name as BuilderCatalogName)) {
        patch.catalog = { name: meta.catalog.name as BuilderCatalogName, url: meta.catalog.url };
      }
      onChange(patch);
      notifications.show(
        meta.sources.length
          ? { color: accent.secondary, title: 'Metadata fetched', message: `From ${meta.sources.join(', ')}`, autoClose: 2500 }
          : { color: 'yellow', title: 'No metadata found', message: 'Fill the workflow fields yourself.', autoClose: 2500 },
      );
    } catch (err) {
      notifications.show({
        color: 'red',
        title: 'Metadata fetch failed',
        message: (err as Error).message,
        autoClose: 4000,
      });
    } finally {
      setFetching(false);
    }
  }, [repoUrl, onChange, state, workflow.id, accent.secondary]);

  // The regex that fits the root's run folders, read off their names. Fills
  // the field only when `fill` (the reader asked, or it was empty).
  const detectRuns = useCallback(
    async (fill: boolean) => {
      setDetecting(true);
      try {
        const found = await builderRunsRegex(root);
        setDetected(found);
        if (found.regex && fill) onChange({ runs_regex: found.regex });
        if (!found.regex) {
          notifications.show({
            color: 'yellow',
            title: 'No common shape',
            message: 'The folders of the data root do not look alike: write the regex yourself.',
            autoClose: 3500,
          });
        }
      } catch (err) {
        notifications.show({
          color: 'red',
          title: 'Could not read the folders',
          message: (err as Error).message,
          autoClose: 4000,
        });
      } finally {
        setDetecting(false);
      }
    },
    [root, onChange],
  );

  const engineData = ENGINE_OPTIONS.some((o) => o.value === workflow.engine)
    ? ENGINE_OPTIONS
    : [{ value: workflow.engine, label: engineLabel(workflow.engine) }, ...ENGINE_OPTIONS];

  return (
    <Paper ref={rootRef} withBorder radius="md" p="sm" data-testid="builder-workflow-editor">
      <UnstyledButton
        onClick={() => setOpen((v) => !v)}
        w="100%"
        aria-expanded={open}
        data-testid="builder-workflow-editor-toggle"
      >
        <Group gap="xs" wrap="nowrap">
          <Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
          <WorkflowLogo engine={workflow.engine} catalog={workflow.catalog?.name} size={18} />
          <Text fw={600} size="sm" truncate>
            {workflow.name || '(unnamed workflow)'}
          </Text>
          <Badge size="xs" variant="light" color="gray" tt="none">
            {engineLabel(workflow.engine)}
          </Badge>
          {workflow.version && (
            <Badge size="xs" variant="light" color="gray" tt="none">
              v{workflow.version.replace(/^v/i, '')}
            </Badge>
          )}
          {workflow.structure === 'sequencing-runs' && (
            <Badge size="xs" variant="light" color={accent.secondary} tt="none">
              sequencing runs
            </Badge>
          )}
          {(nameClash || nameEmpty) && (
            <Badge size="xs" variant="light" color="red" ml="auto">
              {nameEmpty ? 'needs a name' : 'name in use'}
            </Badge>
          )}
        </Group>
      </UnstyledButton>
      <Collapse in={open}>
        <Stack gap="sm" pt="sm">
          <SectionHead
            icon="mdi:sitemap-outline"
            title="What produced these files"
            hint="A workflow is the pipeline or process behind a set of files. A project can have several; each lists its own collections and labels them."
            kind="required"
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <TextInput
              label="Name"
              withAsterisk
              description="Unique within the project"
              value={workflow.name}
              onChange={(e) => onChange({ name: e.currentTarget.value })}
              error={nameEmpty ? 'Give the workflow a name.' : nameClash ? 'Another workflow already uses this name.' : undefined}
              data-testid="builder-workflow-name"
            />
            <Select
              label="Engine"
              withAsterisk
              description="What produced the data"
              value={workflow.engine}
              data={engineData}
              onChange={(v) => onChange({ engine: v || 'python' })}
              allowDeselect={false}
              searchable
              leftSection={<WorkflowLogo engine={workflow.engine} size={16} />}
              renderOption={({ option }) => (
                <Group gap="xs" wrap="nowrap">
                  <WorkflowLogo engine={option.value} size={16} />
                  <Text size="sm">{option.label}</Text>
                </Group>
              )}
              data-testid="builder-workflow-engine"
            />
          </SimpleGrid>

          <SectionHead
            icon="mdi:folder-network-outline"
            title="How the folders are laid out"
            hint="Flat: every file belongs to one run. Sequencing runs: each folder directly under the data root is a run, and a collection is scanned in each of them."
            kind="required"
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <Select
              label="Structure"
              withAsterisk
              description="Flat, or one level of run folders under the root"
              value={workflow.structure}
              data={[
                { value: 'flat', label: 'Flat' },
                { value: 'sequencing-runs', label: 'Sequencing runs' },
              ]}
              allowDeselect={false}
              onChange={(v) => {
                const runs = v === 'sequencing-runs';
                onChange({ structure: runs ? 'sequencing-runs' : 'flat' });
                // Nothing typed yet: the folders say what a run looks like.
                if (runs && !workflow.runs_regex?.trim()) void detectRuns(true);
              }}
              data-testid="builder-workflow-structure"
            />
            {workflow.structure === 'sequencing-runs' && (
              <TextInput
                label="Runs regex"
              withAsterisk
                description={
                  detected?.regex && detected.regex === workflow.runs_regex
                    ? `Read from the folders: ${detected.runs.length} of ${detected.folders} are runs${
                        detected.skipped.length ? ` (not: ${detected.skipped.join(', ')})` : ''
                      }`
                    : 'Which top-level folders are runs, as a regex on the folder name'
                }
                value={workflow.runs_regex ?? ''}
                onChange={(e) => onChange({ runs_regex: e.currentTarget.value })}
                error={!workflow.runs_regex?.trim() ? 'Say which folders are runs.' : undefined}
                styles={MONO}
                spellCheck={false}
                rightSectionWidth={detecting ? 32 : 92}
                rightSection={
                  detecting ? (
                    <Loader size={14} />
                  ) : (
                    <Button
                      size="compact-xs"
                      variant="light"
                      color={accent.secondary}
                      onClick={() => void detectRuns(true)}
                      leftSection={<Icon icon="mdi:auto-fix" width={13} />}
                      data-testid="builder-workflow-runs-detect"
                    >
                      Detect
                    </Button>
                  )
                }
                data-testid="builder-workflow-runs-regex"
              />
            )}
          </SimpleGrid>
          {workflow.structure === 'sequencing-runs' && <RunsPanel root={root} regex={workflow.runs_regex ?? ''} />}
          <Text size="xs" c="dimmed">
            A data collection&apos;s pattern can include folders (e.g.{' '}
            <Text span ff="monospace" size="xs">
              results/*/quant.sf
            </Text>
            ) to scope it to part of the root.
          </Text>

          <OptionalBlock
            title="More about the workflow"
            hint="Versions, the repository to fetch them from, and where it is published."
            icon="mdi:source-repository"
            initiallyOpen={Boolean(
              workflow.engine_version?.trim() ||
                workflow.version?.trim() ||
                workflow.repository_url?.trim() ||
                workflow.catalog,
            )}
            testId="builder-workflow-optional"
          >
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <TextInput
                label="Engine version"
                placeholder="e.g. 24.04.2"
                value={workflow.engine_version ?? ''}
                onChange={(e) => onChange({ engine_version: e.currentTarget.value })}
              />
              <TextInput
                label="Workflow version"
                placeholder="e.g. 3.14.0"
                value={workflow.version ?? ''}
                onChange={(e) => onChange({ version: e.currentTarget.value })}
              />
            </SimpleGrid>
            <TextInput
              label="Repository URL"
              description="Fetch the name, engine and version from the repository (RO-Crate, Nextflow, GitHub)"
              placeholder="https://github.com/nf-core/rnaseq"
              value={workflow.repository_url ?? ''}
              onChange={(e) => onChange({ repository_url: e.currentTarget.value })}
              leftSection={<Icon icon="mdi:git" width={16} />}
              rightSectionWidth={96}
              rightSection={
                <Button
                  size="compact-xs"
                  variant="light"
                  color={accent.secondary}
                  loading={fetching}
                  disabled={!repoUrl}
                  onClick={fetchMeta}
                  leftSection={<Icon icon="mdi:cloud-download-outline" width={14} />}
                  data-testid="builder-workflow-fetch"
                >
                  Fetch
                </Button>
              }
              data-testid="builder-workflow-repo"
            />
            {workflow.meta && <RepoMetadata meta={workflow.meta} />}

            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              <Select
                label="Catalog"
                description="Where the workflow is published, if anywhere"
                placeholder="None"
                value={workflow.catalog?.name ?? null}
                data={CATALOG_OPTIONS}
                clearable
                onChange={(v) =>
                  onChange({
                    catalog: v ? { name: v as BuilderCatalogName, url: workflow.catalog?.url ?? '' } : null,
                  })
                }
                leftSection={<WorkflowLogo catalog={workflow.catalog?.name} engine={null} size={16} />}
              />
              <TextInput
                label="Catalog page"
                placeholder="https://nf-co.re/rnaseq"
                disabled={!workflow.catalog}
                value={workflow.catalog?.url ?? ''}
                onChange={(e) => {
                  const url = e.currentTarget.value;
                  if (workflow.catalog) onChange({ catalog: { ...workflow.catalog, url } });
                }}
              />
            </SimpleGrid>

          </OptionalBlock>
        </Stack>
      </Collapse>
    </Paper>
  );
};
