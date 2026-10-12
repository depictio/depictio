/**
 * The selected workflow: name, engine, versions, catalog, repository (with a
 * metadata fetch) and structure (flat, or one level of run folders). Edits
 * go straight to the draft; a name another workflow uses is shown, not
 * refused, so typing through a clash is never blocked.
 */
import React, { useCallback, useState } from 'react';
import {
  Badge,
  Button,
  Collapse,
  Group,
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

import { builderMetadata, BUILDER_CATALOGS, isWorkflowNameTaken, useBrandAccents } from 'depictio-react-core';
import type {
  BuilderCatalogName,
  BuilderState,
  BuilderWorkflowPatch,
  BuilderWorkflowState,
} from 'depictio-react-core';

import { RepoMetadata } from './RepoMetadata';
import { CATALOG_OPTIONS, ENGINE_OPTIONS, engineLabel, WorkflowLogo } from './WorkflowLogo';

const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

interface WorkflowEditorProps {
  state: BuilderState;
  workflow: BuilderWorkflowState;
  onChange: (patch: BuilderWorkflowPatch) => void;
}

export const WorkflowEditor: React.FC<WorkflowEditorProps> = ({ state, workflow, onChange }) => {
  const accent = useBrandAccents();
  // Folded for the lone default workflow: a single-workflow project never
  // has to look at it.
  const [open, setOpen] = useState(state.workflows.length > 1);
  const [fetching, setFetching] = useState(false);
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

  const engineData = ENGINE_OPTIONS.some((o) => o.value === workflow.engine)
    ? ENGINE_OPTIONS
    : [{ value: workflow.engine, label: engineLabel(workflow.engine) }, ...ENGINE_OPTIONS];

  return (
    <Paper withBorder radius="md" p="sm" data-testid="builder-workflow-editor">
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
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <TextInput
              label="Name"
              description="Unique within the project"
              value={workflow.name}
              onChange={(e) => onChange({ name: e.currentTarget.value })}
              error={nameEmpty ? 'Give the workflow a name.' : nameClash ? 'Another workflow already uses this name.' : undefined}
              data-testid="builder-workflow-name"
            />
            <Select
              label="Engine"
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
            description="Optional: fetch the name, engine and version from the repository (RO-Crate, Nextflow, GitHub)"
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

          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            <Select
              label="Structure"
              description="Flat, or one level of run folders under the root"
              value={workflow.structure}
              data={[
                { value: 'flat', label: 'Flat' },
                { value: 'sequencing-runs', label: 'Sequencing runs' },
              ]}
              allowDeselect={false}
              onChange={(v) => onChange({ structure: v === 'sequencing-runs' ? 'sequencing-runs' : 'flat' })}
              data-testid="builder-workflow-structure"
            />
            {workflow.structure === 'sequencing-runs' && (
              <TextInput
                label="Runs regex"
                description="Which top-level folders are runs"
                value={workflow.runs_regex ?? ''}
                onChange={(e) => onChange({ runs_regex: e.currentTarget.value })}
                error={!workflow.runs_regex?.trim() ? 'Say which folders are runs.' : undefined}
                styles={MONO}
                spellCheck={false}
                data-testid="builder-workflow-runs-regex"
              />
            )}
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            A data collection&apos;s pattern can include folders (e.g.{' '}
            <Text span ff="monospace" size="xs">
              results/*/quant.sf
            </Text>
            ) to scope it to part of the root.
          </Text>
        </Stack>
      </Collapse>
    </Paper>
  );
};
