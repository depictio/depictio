/**
 * A workflow of the shipped template the draft edits: its settings (name,
 * versions, catalog, repository, all editable), the template's variables, and each of its
 * collections, which may be removed (what is built from it follows),
 * restored, or repointed (a file's path, a scan's pattern, a recipe's
 * input). Everything else of the template, dashboards and recipes included,
 * stays as shipped; the reader's own collections are added from the tree.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Collapse,
  Group,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  baseDependants,
  baseIssues,
  baseRemoved,
  collectionFolderStatus,
  folderStatusOf,
  scopeRemovals,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  BuilderAction,
  BuilderRootSpec,
  BuilderBaseCollection,
  BuilderBaseCollectionKind,
  BuilderBaseSource,
  BuilderBaseState,
  BuilderBaseWorkflow,
  BuilderIssue,
  BuilderState,
  BuilderWorkflowState,
  CollectionFolderStatus,
  WorkflowEditKey,
} from 'depictio-react-core';

import { FactBadge, StatusBadge } from '../../badges';
import { DcTypeIcon } from '../../dcTypeIcon';
import { useRunPlan } from '../../fromRun/runPlan';
import { useBuilderFolder } from '../FolderRunsContext';
import { RunsBadge } from './RunsBadge';
import { DcCard } from '../collections/DcCard';
import { SectionHead } from '../Requirement';
import { CATALOG_OPTIONS, engineLabel, WorkflowLogo } from './WorkflowLogo';
import { MONO } from '../styles';

const KIND_LABELS: Record<BuilderBaseCollectionKind, { label: string; hint: string }> = {
  file: { label: 'file', hint: 'One file, relative to the data folder' },
  scan: { label: 'scan', hint: 'Every file whose path matches the pattern' },
  recipe: { label: 'recipe', hint: 'Built by a recipe from the files it reads' },
  derived: { label: 'derived', hint: 'Built from other collections of the template' },
  other: { label: 'other', hint: 'Read as the template says' },
};

/** The location field of a collection: what the reader set, else the template's. */
function scanValue(base: BuilderBaseState, c: BuilderBaseCollection): { value: string; edited: boolean } {
  const edit = base.scans[c.tag];
  if (!edit) return { value: c.location ?? '', edited: false };
  return { value: edit.path ?? edit.regex ?? '', edited: true };
}

function sourceValue(base: BuilderBaseState, tag: string, s: BuilderBaseSource): { value: string; edited: boolean } {
  const edit = base.sources[tag]?.[s.ref];
  const shipped = s.path ?? s.glob_pattern ?? '';
  if (!edit) return { value: shipped, edited: false };
  return { value: edit.path ?? edit.glob_pattern ?? '', edited: true };
}

const ResetButton: React.FC<{ onClick: () => void; label: string }> = ({ onClick, label }) => (
  <Tooltip label={label} withArrow>
    <ActionIcon variant="subtle" color="gray" size="sm" onClick={onClick} aria-label={label}>
      <Icon icon="mdi:backup-restore" width={15} />
    </ActionIcon>
  </Tooltip>
);

/** What the data folder holds for a template collection (its dry run). */
const FOLDER_STATUS: Record<CollectionFolderStatus, { label: string; color: string; hint: string }> = {
  found: { label: 'found', color: 'green', hint: 'The data folder has files for it' },
  empty: {
    label: 'empty for now',
    color: 'yellow',
    hint: 'No files in the data folder yet: created empty, filled at the next refresh',
  },
  absent: {
    label: 'not in this run',
    color: 'gray',
    hint: 'Optional or conditional, and this run did not produce it: the template leaves it out here',
  },
};

const CollectionRow: React.FC<{
  base: BuilderBaseState;
  collection: BuilderBaseCollection;
  /** Null while the folder is being read, or for a collection it says nothing of. */
  folder: CollectionFolderStatus | null;
  removedWhy: string | undefined;
  issues: BuilderIssue[];
  open: boolean;
  onToggle: () => void;
  dispatch: React.Dispatch<BuilderAction>;
  rowRef?: (el: HTMLDivElement | null) => void;
}> = ({ base, collection: c, folder, removedWhy, issues, open, onToggle, dispatch, rowRef }) => {
  const accent = useBrandAccents();
  const removed = removedWhy !== undefined;
  // Removed by the reader (restorable here) or by what it is built from.
  const ownRemoval = base.remove.includes(c.tag);
  const dependants = removed ? [] : baseDependants(base, c.tag);
  const editableSources = c.sources.filter((s) => s.editable);
  const editable = Boolean(c.edit) || editableSources.length > 0;
  const scan = scanValue(base, c);
  const sourcesEdited = Object.keys(base.sources[c.tag] ?? {}).length > 0;
  const edited = scan.edited || sourcesEdited;
  const kind = KIND_LABELS[c.kind];
  const shown = c.kind === 'recipe' ? c.recipe : c.location;

  const removeLabel = dependants.length
    ? `Remove; also removes what is built from it: ${dependants.join(', ')}`
    : 'Remove from the project';

  return (
    <Paper
      ref={rowRef}
      withBorder
      radius="sm"
      px="sm"
      py={6}
      style={{
        opacity: removed ? 0.6 : undefined,
        borderColor: open && !removed ? `var(--mantine-color-${accent.secondary}-5)` : undefined,
      }}
      data-testid="builder-base-collection"
      data-tag={c.tag}
      data-removed={removed || undefined}
    >
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap" gap={4}>
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <DcTypeIcon type={c.type} size={16} withTooltip={false} />
            <Text
              size="sm"
              fw={600}
              ff="monospace"
              truncate
              td={removed ? 'line-through' : undefined}
            >
              {c.tag}
            </Text>
            <Tooltip label={kind.hint} withArrow>
              <FactBadge size="xs">{kind.label}</FactBadge>
            </Tooltip>
            {c.optional && <FactBadge size="xs">optional</FactBadge>}
            {edited && !removed && (
              <Badge size="xs" variant="light" color={accent.secondary} tt="none" style={{ flexShrink: 0 }}>
                edited
              </Badge>
            )}
            {folder && (
              <Tooltip label={FOLDER_STATUS[folder].hint} withArrow multiline maw={280}>
                <StatusBadge
                  size="xs"
                  color={FOLDER_STATUS[folder].color}
                  data-testid="builder-base-folder-status"
                  data-status={folder}
                >
                  {FOLDER_STATUS[folder].label}
                </StatusBadge>
              </Tooltip>
            )}
          </Group>
          <Group gap={2} wrap="nowrap" style={{ flexShrink: 0 }}>
            {editable && !removed && (
              <Tooltip label={open ? 'Close' : 'Change where it is read from'} withArrow>
                <ActionIcon
                  variant={open ? 'light' : 'subtle'}
                  color={accent.secondary}
                  size="sm"
                  onClick={onToggle}
                  aria-label={`Change where ${c.tag} is read from`}
                  aria-expanded={open}
                  data-testid="builder-base-edit"
                >
                  <Icon icon="mdi:pencil-outline" width={14} />
                </ActionIcon>
              </Tooltip>
            )}
            {removed ? (
              ownRemoval ? (
                <Button
                  size="compact-xs"
                  variant="subtle"
                  color={accent.secondary}
                  leftSection={<Icon icon="mdi:undo" width={13} />}
                  onClick={() => dispatch({ type: 'base/restore', tag: c.tag })}
                  data-testid="builder-base-restore"
                >
                  Restore
                </Button>
              ) : null
            ) : (
              <Tooltip label={removeLabel} withArrow multiline maw={320}>
                <ActionIcon
                  variant="subtle"
                  color="red"
                  size="sm"
                  onClick={() => dispatch({ type: 'base/remove', tag: c.tag })}
                  aria-label={`Remove ${c.tag}`}
                  data-testid="builder-base-remove"
                >
                  <Icon icon="mdi:close" width={14} />
                </ActionIcon>
              </Tooltip>
            )}
          </Group>
        </Group>
        {removed ? (
          <Text size="xs" c="dimmed" data-testid="builder-base-removed-why">
            {removedWhy === 'Removed' ? 'Removed: not in the project.' : `${removedWhy}: removed with it.`}
          </Text>
        ) : (
          <>
            {shown && !open && (
              <Tooltip label={shown} withArrow multiline maw={480} openDelay={400}>
                <Text size="xs" c="dimmed" ff="monospace" truncate>
                  {c.kind === 'recipe' ? `recipe: ${shown}` : scan.value || shown}
                </Text>
              </Tooltip>
            )}
            {c.description && !open && (
              <Text size="xs" c="dimmed" lineClamp={1}>
                {c.description}
              </Text>
            )}
          </>
        )}
        <Collapse in={open && !removed}>
          <Stack gap="xs" pt={4}>
            {c.edit && (
              <Group gap={4} wrap="nowrap" align="flex-end">
                <TextInput
                  style={{ flex: 1 }}
                  size="xs"
                  label={c.edit === 'regex' ? 'Pattern (regex on the path)' : 'File (relative to the data folder)'}
                  description={
                    c.edit === 'regex' && c.wildcards.length
                      ? `Keep ${c.wildcards.map((w) => `{${w}}`).join(', ')}: a column is read from each.`
                      : undefined
                  }
                  value={scan.value}
                  onChange={(e) => {
                    const v = e.currentTarget.value;
                    // Typed back to the template's: no edit left.
                    const edit = v === (c.location ?? '') ? null : c.edit === 'regex' ? { regex: v } : { path: v };
                    dispatch({ type: 'base/scan', tag: c.tag, edit });
                  }}
                  error={
                    issues
                      .filter((i) => i.code.startsWith('base_location') || i.code === 'base_wildcard_lost')
                      .map((i) => i.message)
                      .join(' ') || undefined
                  }
                  styles={MONO}
                  spellCheck={false}
                  data-testid="builder-base-location"
                />
                {scan.edited && (
                  <ResetButton
                    label="Back to the template's"
                    onClick={() => dispatch({ type: 'base/scan', tag: c.tag, edit: null })}
                  />
                )}
              </Group>
            )}
            {editableSources.map((s) => {
              const v = sourceValue(base, c.tag, s);
              const glob = s.path === null && s.glob_pattern !== null;
              return (
                <Group key={s.ref} gap={4} wrap="nowrap" align="flex-end">
                  <TextInput
                    style={{ flex: 1 }}
                    size="xs"
                    label={`Input “${s.ref}”${s.optional ? ' (optional)' : ''}`}
                    description={glob ? 'A glob, relative to the data folder' : 'A file, relative to the data folder'}
                    value={v.value}
                    onChange={(e) => {
                      const typed = e.currentTarget.value;
                      const edit =
                        typed === (s.path ?? s.glob_pattern ?? '')
                          ? null
                          : glob
                            ? { glob_pattern: typed }
                            : { path: typed };
                      dispatch({ type: 'base/source', tag: c.tag, ref: s.ref, edit });
                    }}
                    error={v.edited && !v.value.trim() ? 'Give it a location, or reset it.' : undefined}
                    styles={MONO}
                    spellCheck={false}
                    data-testid="builder-base-source"
                    data-ref={s.ref}
                  />
                  {v.edited && (
                    <ResetButton
                      label="Back to the template's"
                      onClick={() => dispatch({ type: 'base/source', tag: c.tag, ref: s.ref, edit: null })}
                    />
                  )}
                </Group>
              );
            })}
            {c.needs.length > 0 && (
              <Text size="xs" c="dimmed">
                Built from {c.needs.join(', ')}.
              </Text>
            )}
          </Stack>
        </Collapse>
      </Stack>
    </Paper>
  );
};

const CATALOG_URLS: Record<string, string> = {
  'nf-core': 'https://nf-co.re',
  workflowhub: 'https://workflowhub.eu',
  'smk-wf-catalog': 'https://snakemake.github.io/snakemake-workflow-catalog',
};
const NO_CATALOG = '__none__';

/** One setting of the template's workflow: the reader's value, else the
 *  template's, with a way back to the template's. */
const SettingField: React.FC<{
  label: string;
  description?: string;
  value: string;
  shipped: string;
  edited: boolean;
  error?: string;
  placeholder?: string;
  testId: string;
  onChange: (value: string | null) => void;
}> = ({ label, description, value, shipped, edited, error, placeholder, testId, onChange }) => (
  <Group gap={4} wrap="nowrap" align="flex-start" style={{ flex: 1, minWidth: 200 }}>
    <TextInput
      style={{ flex: 1 }}
      size="xs"
      label={label}
      description={description}
      value={value}
      placeholder={placeholder}
      onChange={(e) => {
        const v = e.currentTarget.value;
        onChange(v === shipped ? null : v);
      }}
      error={error}
      styles={MONO}
      spellCheck={false}
      data-testid={testId}
    />
    {edited && (
      <Box pt={description ? 38 : 22}>
        <ResetButton label={`Back to the template's (${shipped || 'none'})`} onClick={() => onChange(null)} />
      </Box>
    )}
  </Group>
);

/** Every setting of the template's workflow, editable: its name (the
 *  template's dashboards follow it), the pipeline version, catalog,
 *  repository and engine version. */
const WorkflowSettings: React.FC<{
  base: BuilderBaseState;
  workflow: BuilderBaseWorkflow | null;
  issues: BuilderIssue[];
  dispatch: React.Dispatch<BuilderAction>;
}> = ({ base, workflow, issues, dispatch }) => {
  if (!workflow) return null;
  const edit = base.workflows?.[workflow.name] ?? {};
  const set = (patch: Partial<Record<WorkflowEditKey, string | null>>) =>
    dispatch({ type: 'base/workflow', name: workflow.name, patch });
  const errorOf = (code: string) =>
    issues
      .filter((i) => i.code === code && i.message.includes(`“${workflow.name}”`))
      .map((i) => i.message.replace(`Workflow “${workflow.name}”: `, ''))
      .join(' ') || undefined;
  const shippedCatalog = workflow.catalog?.name ?? '';
  const catalog = edit.catalog_name !== undefined ? edit.catalog_name : shippedCatalog;
  const catalogOptions = [
    ...CATALOG_OPTIONS.map((o) => ({ value: o.value, label: o.label })),
    ...(shippedCatalog && !CATALOG_OPTIONS.some((o) => o.value === shippedCatalog)
      ? [{ value: shippedCatalog, label: shippedCatalog }]
      : []),
    { value: NO_CATALOG, label: 'None (your own pipeline or fork)' },
  ];
  const nameTaken = issues.some((i) => i.code === 'base_workflow_name_taken');
  return (
    <Stack gap="xs" data-testid="builder-template-fork">
      <Group gap="sm" align="flex-start" wrap="wrap">
        <SettingField
          label="Name"
          description="The template's dashboards follow the new name"
          value={edit.name ?? workflow.name}
          shipped={workflow.name}
          edited={edit.name !== undefined}
          error={errorOf('base_workflow_name_invalid') ?? (nameTaken ? 'Another workflow has this name' : undefined)}
          testId="builder-template-name"
          onChange={(v) => set({ name: v })}
        />
        <SettingField
          label="Pipeline version"
          description="The version that made the run"
          value={edit.version ?? workflow.version ?? ''}
          shipped={workflow.version ?? ''}
          edited={edit.version !== undefined}
          error={errorOf('base_workflow_version_empty')}
          testId="builder-template-version"
          onChange={(v) => set({ version: v })}
        />
      </Group>
      <Group gap="sm" align="flex-start" wrap="wrap">
        <Group gap={4} wrap="nowrap" align="flex-start" style={{ flex: 1, minWidth: 200 }}>
          <Select
            style={{ flex: 1 }}
            size="xs"
            label="Catalog"
            description="Where the pipeline is published"
            data={catalogOptions}
            value={catalog || NO_CATALOG}
            allowDeselect={false}
            onChange={(value) => {
              const next = !value || value === NO_CATALOG ? '' : value;
              if (next === shippedCatalog) set({ catalog_name: null, catalog_url: null });
              else set({ catalog_name: next, catalog_url: CATALOG_URLS[next] ?? '' });
            }}
            leftSection={catalog ? <WorkflowLogo catalog={catalog} size={14} /> : undefined}
            data-testid="builder-template-catalog"
          />
          {edit.catalog_name !== undefined && (
            <Box pt={38}>
              <ResetButton
                label={`Back to the template's (${shippedCatalog || 'none'})`}
                onClick={() => set({ catalog_name: null, catalog_url: null })}
              />
            </Box>
          )}
        </Group>
        <SettingField
          label={`${engineLabel(workflow.engine ?? '') || 'Engine'} version`}
          description="The engine version the run used"
          value={edit.engine_version ?? workflow.engine_version ?? ''}
          shipped={workflow.engine_version ?? ''}
          edited={edit.engine_version !== undefined}
          placeholder="As the run used"
          testId="builder-template-engine-version"
          onChange={(v) => set({ engine_version: v })}
        />
      </Group>
      <SettingField
        label="Repository"
        description="Where the code that ran comes from, e.g. your fork"
        value={edit.repository_url ?? workflow.repository_url ?? ''}
        shipped={workflow.repository_url ?? ''}
        edited={edit.repository_url !== undefined}
        error={errorOf('base_repository_invalid')}
        testId="builder-template-repository"
        onChange={(v) => set({ repository_url: v })}
      />
      {edit.version !== undefined && (
        <Text size="xs" c="dimmed">
          The template&apos;s recipes stay the ones for {workflow.version}: a recipe written for another version of the
          pipeline is looked for under {edit.version.trim() || 'the new version'}, then among the shared ones.
        </Text>
      )}
    </Stack>
  );
};

interface TemplateBasePanelProps {
  state: BuilderState;
  workflow: BuilderWorkflowState;
  dispatch: React.Dispatch<BuilderAction>;
  /** Open this collection and bring it into view (from the workflows panel). */
  focus?: { tag: string; nonce: number } | null;
  /** The reader's own collections: open one in the collection editor. */
  onEditDc: (tag: string) => void;
  onRemoveDc: (tag: string) => void;
  /** Bring the files panel into view, to pick a file for a new collection. */
  onPickFile: () => void;
  /** How to start a collection from a file, shown under the reader's own. */
  filePane?: React.ReactNode;
  /** The data folder: each template collection says whether it has files there. */
  root?: BuilderRootSpec | null;
}

export const TemplateBasePanel: React.FC<TemplateBasePanelProps> = ({
  state,
  workflow,
  dispatch,
  focus = null,
  onEditDc,
  onRemoveDc,
  onPickFile,
  filePane = null,
  root = null,
}) => {
  const accent = useBrandAccents();
  const base = state.base;
  const [open, setOpen] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  // Folded: a template may carry a dozen, most of them optional.
  const [showVariables, setShowVariables] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);
  const rows = useRef<Map<string, HTMLDivElement>>(new Map());

  const shipped = base?.template.workflows.find((w) => w.name === workflow.name) ?? null;
  const removed = useMemo(() => baseRemoved(base), [base]);
  const issues = useMemo(() => baseIssues(state), [state]);
  // The shipped template's dry run on the data folder (cached, shared with
  // the New project dialog): which of its collections have files there.
  // Asked once the folder's inspection settled: before, a folder of runs
  // would be read as one run and every collection found empty.
  const folder = useBuilderFolder();
  const runs = folder.runs;
  const plan = useRunPlan(
    folder.settled ? (folder.location ?? root?.data_root ?? null) : null,
    base?.template.template_id ?? null,
    root?.storage ?? null,
    runs,
  );
  const folderStatus = useMemo(
    () =>
      plan?.status === 'ready'
        ? collectionFolderStatus(plan.report.data_collections)
        : new Map<string, CollectionFolderStatus>(),
    [plan],
  );
  // "Only the found", by the rule the New project dialog applies.
  const foundRemovals = useMemo(
    () => (base && folderStatus.size ? scopeRemovals(base.template, folderStatus) : []),
    [base, folderStatus],
  );

  const focusNonce = focus?.nonce ?? null;
  useEffect(() => {
    if (!focus) return;
    setQuery('');
    setOpen(focus.tag);
    if (removed.has(focus.tag)) setShowRemoved(true);
    // After the row is drawn (the filter cleared).
    requestAnimationFrame(() =>
      rows.current.get(focus.tag)?.scrollIntoView({ block: 'center', behavior: 'smooth' }),
    );
    // A new request is a new nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNonce]);

  if (!base || !shipped) return null;
  const { template } = base;
  const collections = shipped.collections;
  const wanted = query.trim().toLowerCase();
  const listed = wanted
    ? collections.filter((c) => c.tag.toLowerCase().includes(wanted) || (c.location ?? '').toLowerCase().includes(wanted))
    : collections;
  const removedHere = collections.filter((c) => removed.has(c.tag)).length;
  const keptListed = listed.filter((c) => !removed.has(c.tag));
  const removedListed = listed.filter((c) => removed.has(c.tag));
  // A filter that finds a removed collection shows it.
  const removedOpen = showRemoved || (Boolean(wanted) && removedListed.length > 0);
  const row = (c: BuilderBaseCollection) => (
    <CollectionRow
      key={c.tag}
      base={base}
      collection={c}
      folder={folderStatusOf(folderStatus, c.tag)}
      removedWhy={removed.get(c.tag)}
      issues={issues.filter((i) => i.tag === c.tag)}
      open={open === c.tag}
      onToggle={() => setOpen((t) => (t === c.tag ? null : c.tag))}
      dispatch={dispatch}
      rowRef={(el) => {
        if (el) rows.current.set(c.tag, el);
        else rows.current.delete(c.tag);
      }}
    />
  );
  // "Only the found" / "Whole template": the dialog's choice, again here, by
  // the same rule (`scopeRemovals`).
  const foundCount = collections.filter((c) => folderStatus.get(c.tag) === 'found').length;
  // Once the plan is read, every collection has a status: one it does not
  // name is left out for this folder.
  const named = folderStatus.size ? collections.map((c) => c.tag) : [];
  const toRemove = new Set(foundRemovals);
  const scopeOffered = foundCount > 0 && named.some((t) => toRemove.has(t));
  const atFound = named.every((t) => base.remove.includes(t) === toRemove.has(t));
  const atWhole = named.every((t) => !base.remove.includes(t));
  const scopeValue = atFound ? 'found' : atWhole ? 'whole' : '';
  const setScope = (value: string) => {
    for (const tag of named) {
      const own = base.remove.includes(tag);
      const out = value === 'found' && toRemove.has(tag);
      if (out && !own) dispatch({ type: 'base/remove', tag });
      if (!out && own) dispatch({ type: 'base/restore', tag });
    }
    if (value === 'found') setShowRemoved(false);
  };
  const counts = { found: 0, empty: 0, absent: 0 };
  for (const c of collections) {
    const s = folderStatusOf(folderStatus, c.tag);
    if (s) counts[s] += 1;
  }
  const variables = template.variables;
  const wfEdit = base.workflows?.[shipped.name] ?? {};
  const shownName = wfEdit.name?.trim() || shipped.name;
  const shownVersion = wfEdit.version?.trim() || shipped.version;
  const shownEngineVersion = wfEdit.engine_version?.trim() || shipped.engine_version;
  const shownCatalog = wfEdit.catalog_name !== undefined ? wfEdit.catalog_name || null : shipped.catalog?.name;

  return (
    <Stack gap="md" data-testid="builder-template-workflow">
      <Paper withBorder radius="md" p="md">
        <Stack gap="xs">
          <Group gap="xs" wrap="nowrap">
            <WorkflowLogo engine={workflow.engine} catalog={shownCatalog} size={22} />
            <Text fw={700} size="lg" truncate data-testid="builder-template-workflow-name">
              {shownName}
            </Text>
            {workflow.engine && (
              <FactBadge
                icon={<WorkflowLogo engine={workflow.engine} size={12} />}
                data-testid="builder-template-engine"
              >
                {engineLabel(workflow.engine)}
                {shownEngineVersion ? ` ${shownEngineVersion}` : ''}
              </FactBadge>
            )}
            {shownVersion && <FactBadge icon="mdi:tag-outline">v{shownVersion.replace(/^v/, '')}</FactBadge>}
            {/* A template that refused the runs reads one: the badge says so. */}
            <RunsBadge workflow={workflow} runs={plan?.status === 'error' ? null : runs} />
          </Group>
          {plan?.status === 'error' && (
            <Alert
              color="yellow"
              variant="light"
              icon={<Icon icon="mdi:folder-alert-outline" width={16} />}
              data-testid="builder-template-folder-error"
            >
              The data folder could not be checked against this template: {plan.error}
            </Alert>
          )}
          <Text size="sm" c="dimmed">
            From the template{' '}
            <Text span fw={600} c="var(--mantine-color-text)">
              {template.title ?? template.template_id}
            </Text>
            . Change any of its settings below, remove what this project does not need, change where a file
            is read from, or add your own collections. The template&apos;s recipes and dashboards come along.
          </Text>
          <WorkflowSettings base={base} workflow={shipped} issues={issues} dispatch={dispatch} />
        </Stack>
      </Paper>

      <Paper withBorder radius="md" p="md" data-testid="builder-template-own">
        <Stack gap="sm">
          <Group justify="space-between" wrap="nowrap" align="flex-start">
            <SectionHead
              icon="mdi:database-plus-outline"
              title="Your data collections"
              hint={
                workflow.data_collections.length
                  ? `Added to ${shownName}, next to the template's`
                  : 'Files of this run the template does not read: click one in the files on the left'
              }
            />
            <Tooltip
              label="A collection of your own cannot be read across several runs yet: open one run folder to add it."
              disabled={!runs}
              withArrow
              multiline
              maw={300}
            >
              {/* A span keeps the tooltip on a disabled button. */}
              <span style={{ flexShrink: 0 }}>
                <Button
                  size="xs"
                  variant="light"
                  color={accent.secondary}
                  leftSection={<Icon icon="mdi:plus" width={14} />}
                  onClick={onPickFile}
                  disabled={Boolean(runs)}
                  data-testid="builder-template-add-dc"
                >
                  Add a collection
                </Button>
              </span>
            </Tooltip>
          </Group>
          {workflow.data_collections.length > 0 && (
            <Stack gap={6}>
              {workflow.data_collections.map((dc) => (
                <DcCard
                  key={dc.tag}
                  dc={dc}
                  files={state.claimed[dc.tag]}
                  onEdit={() => onEditDc(dc.tag)}
                  onRemove={() => onRemoveDc(dc.tag)}
                />
              ))}
            </Stack>
          )}
        </Stack>
      </Paper>

      {/* Where a new collection starts, right under the reader's own. */}
      {filePane}

      {variables.length > 0 && (
        <Paper withBorder radius="md" p="md" data-testid="builder-template-variables">
          <UnstyledButton onClick={() => setShowVariables((v) => !v)} style={{ width: '100%' }}>
            <Group justify="space-between" wrap="nowrap">
              <SectionHead
                icon="mdi:variable"
                title="Template variables"
                hint="Values the template reads: left blank, its default is used"
              />
              <Icon icon={showVariables ? 'mdi:chevron-up' : 'mdi:chevron-down'} width={18} />
            </Group>
          </UnstyledButton>
          <Collapse in={showVariables}>
            <Stack gap="xs" pt="sm">
              {variables.map((v) => (
                <TextInput
                  key={v.name}
                  size="xs"
                  label={v.name}
                  description={v.description ?? undefined}
                  withAsterisk={v.required}
                  placeholder={v.default ?? (v.required ? 'Required' : '')}
                  value={base.variables[v.name] ?? ''}
                  onChange={(e) => dispatch({ type: 'base/variable', name: v.name, value: e.currentTarget.value })}
                  styles={MONO}
                  spellCheck={false}
                  data-testid="builder-template-variable"
                  data-name={v.name}
                />
              ))}
            </Stack>
          </Collapse>
        </Paper>
      )}

      <Paper withBorder radius="md" p="md" data-testid="builder-template-collections">
        <Stack gap="sm">
          <Group justify="space-between" wrap="nowrap" align="flex-end">
            <SectionHead
              icon="mdi:database-outline"
              title="The template's data collections"
              hint={`${collections.length - removedHere} of ${collections.length} kept${
                removedHere ? `, ${removedHere} removed` : ''
              }`}
            />
            {collections.length > 8 && (
              <TextInput
                size="xs"
                placeholder="Filter"
                leftSection={<Icon icon="mdi:magnify" width={14} />}
                value={query}
                onChange={(e) => setQuery(e.currentTarget.value)}
                w={180}
                aria-label="Filter the template's collections"
                data-testid="builder-template-filter"
              />
            )}
          </Group>
          {scopeOffered && (
            <Group gap="sm" wrap="wrap" data-testid="builder-template-scope">
              <SegmentedControl
                size="xs"
                color={accent.secondary}
                value={scopeValue}
                onChange={setScope}
                data={[
                  { value: 'found', label: `Only the ${foundCount} found` },
                  { value: 'whole', label: 'Whole template' },
                ]}
                aria-label="Which of the template's collections the project keeps"
                data-testid="builder-template-scope-control"
                data-value={scopeValue || 'custom'}
              />
              <Text size="xs" c="dimmed">
                In the data folder: {counts.found} found
                {counts.empty ? `, ${counts.empty} empty for now` : ''}
                {counts.absent ? `, ${counts.absent} not in this run` : ''}
                {scopeValue ? '' : '. Your own selection'}
              </Text>
            </Group>
          )}
          <Stack gap={6}>
            {keptListed.map(row)}
            {listed.length === 0 && (
              <Text size="xs" c="dimmed">
                No collection matches “{query}”.
              </Text>
            )}
          </Stack>
          {removedListed.length > 0 && (
            <Stack gap={6}>
              {/* Folded: what was taken out is there to restore, not to read. */}
              <UnstyledButton
                onClick={() => setShowRemoved((v) => !v)}
                aria-expanded={removedOpen}
                data-testid="builder-template-removed-toggle"
              >
                <Group gap={6} wrap="nowrap">
                  <Icon icon={removedOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />
                  <Text size="sm" fw={600} c="dimmed">
                    Removed ({removedListed.length})
                  </Text>
                  <Text size="xs" c="dimmed">
                    not in the project; restore one to bring it back
                  </Text>
                </Group>
              </UnstyledButton>
              <Collapse in={removedOpen}>
                <Stack gap={6} data-testid="builder-template-removed">
                  {removedListed.map(row)}
                </Stack>
              </Collapse>
            </Stack>
          )}
        </Stack>
      </Paper>
    </Stack>
  );
};
