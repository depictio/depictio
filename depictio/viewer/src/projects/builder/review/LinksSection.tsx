/**
 * The project's links, on the review step: each filters one collection (the
 * target) from a column of another (the source: a table, an image or genomic
 * tracks) on a dashboard. The targets offered are the collections whose type
 * the server takes as a link target (`capabilities.link_target_types`).
 *
 * The column pickers read each collection's schema as it was matched when
 * saved (`state.schemas`); a collection saved without one (an older draft)
 * is matched once more for it.
 */
import React, { useEffect, useRef } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Paper,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import {
  BUILDER_LINK_RESOLVERS,
  builderDcColumns,
  builderMatch,
  defaultLinkResolver,
  defaultLinkTargetField,
  findBuilderDc,
  linkIssues,
  linkSourceTags,
  linkTargetTags,
  newLinkDraft,
  normalizeDcDraft,
  useBrandAccents,
} from 'depictio-react-core';
import type {
  BuilderAction,
  BuilderCapabilities,
  BuilderLinkDraft,
  BuilderLinkResolver,
  BuilderRootSpec,
  BuilderState,
} from 'depictio-react-core';

import { DisabledReason } from '../../../components/settings/SettingsSections';
import { BuilderDcTypeIcon, DC_TYPE_META } from '../collections/dcTypes';
import { ColumnField, MONO } from '../collections/forms/shared';

const RESOLVER_LABELS: Record<BuilderLinkResolver, string> = {
  direct: 'Direct: the same values',
  sample_mapping: 'Sample mapping: MultiQC sample names',
  pattern: 'Pattern: a template holding {sample}',
  regex: 'Regex: values matched as regexes',
  wildcard: 'Wildcard: values matched as globs',
};

/** Types whose target field is one of their columns. */
const COLUMN_TARGETS = new Set(['table', 'image']);

/** Matches, once each, the collections the links read that have no schema
 *  kept yet, and keeps what comes back in the draft. */
function useMissingSchemas(
  root: BuilderRootSpec,
  remote: boolean,
  state: BuilderState,
  capabilities: BuilderCapabilities,
  dispatch: React.Dispatch<BuilderAction>,
): void {
  const asked = useRef<Set<string>>(new Set());
  const tags = [...new Set(state.links.flatMap((l) => [l.source_tag, l.target_tag]))]
    .filter((tag) => tag && !state.schemas[tag] && !asked.current.has(tag))
    .sort();
  const key = tags.join('\n');
  useEffect(() => {
    for (const tag of tags) {
      const located = findBuilderDc(state, tag);
      if (!located || (!COLUMN_TARGETS.has(located.dc.type) && located.dc.type !== 'genomic_tracks')) continue;
      asked.current.add(tag);
      const workflow = state.workflows.find((w) => w.id === located.workflowId);
      if (!workflow) continue;
      builderMatch(
        root,
        { structure: workflow.structure, runs_regex: workflow.runs_regex },
        normalizeDcDraft(located.dc, { remote, capabilities }),
      )
        .then((result) => {
          const columns = result.schema ?? Object.fromEntries((result.tracks?.columns ?? []).map((c) => [c, '']));
          if (Object.keys(columns).length) dispatch({ type: 'dc/schema', tag, schema: columns });
        })
        .catch(() => undefined);
    }
    // The key stands for the tags still to ask for.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

const LinkRow: React.FC<{
  index: number;
  link: BuilderLinkDraft;
  state: BuilderState;
  capabilities: BuilderCapabilities;
  issues: string[];
  onPatch: (patch: Partial<BuilderLinkDraft>) => void;
  onRemove: () => void;
}> = ({ index, link, state, capabilities, issues, onPatch, onRemove }) => {
  const columnsOf = (tag: string) =>
    builderDcColumns(tag ? findBuilderDc(state, tag)?.dc : null, state.schemas[tag]);
  const source = link.source_tag ? findBuilderDc(state, link.source_tag)?.dc ?? null : null;
  const target = link.target_tag ? findBuilderDc(state, link.target_tag)?.dc ?? null : null;
  const sourceTags = linkSourceTags(state);
  const targetTags = linkTargetTags(state, capabilities, link.source_tag || null);
  const withCurrent = (tags: string[], current: string) =>
    current && !tags.includes(current) ? [current, ...tags] : tags;
  const option = (tag: string) => {
    const dc = findBuilderDc(state, tag)?.dc;
    return { value: tag, label: dc ? `${tag} (${DC_TYPE_META[dc.type].label})` : tag };
  };
  const sourceColumns = columnsOf(link.source_tag);
  const targetColumns = columnsOf(link.target_tag);

  const pickTarget = (tag: string | null) => {
    const next = tag ? findBuilderDc(state, tag)?.dc ?? null : null;
    onPatch({
      target_tag: tag ?? '',
      resolver: defaultLinkResolver(next?.type),
      target_field: defaultLinkTargetField(next, link.source_column, tag ? columnsOf(tag) : []),
      pattern: null,
    });
  };

  const pickSourceColumn = (column: string | null) => {
    const patch: Partial<BuilderLinkDraft> = { source_column: column ?? '' };
    if (target && COLUMN_TARGETS.has(target.type) && !link.target_field?.trim()) {
      patch.target_field = defaultLinkTargetField(target, column ?? '', targetColumns);
    }
    onPatch(patch);
  };

  return (
    <Paper withBorder radius="sm" p="sm" data-testid="builder-link" data-index={index}>
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <Group gap={6} wrap="nowrap" style={{ minWidth: 0 }}>
            <Badge size="sm" variant="default" radius="sm">
              Link {index + 1}
            </Badge>
            {source && <BuilderDcTypeIcon type={source.type} size={14} />}
            <Text size="sm" ff="monospace" truncate>
              {link.source_tag || '?'}
              {link.source_column ? `.${link.source_column}` : ''}
            </Text>
            <Icon icon="mdi:arrow-right" width={14} style={{ flexShrink: 0 }} />
            {target && <BuilderDcTypeIcon type={target.type} size={14} />}
            <Text size="sm" ff="monospace" truncate>
              {link.target_tag || '?'}
            </Text>
          </Group>
          <Tooltip label="Remove the link" withArrow>
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              onClick={onRemove}
              aria-label={`Remove link ${index + 1}`}
              data-testid="builder-link-remove"
            >
              <Icon icon="mdi:close" width={14} />
            </ActionIcon>
          </Tooltip>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
          <Select
            label="From collection"
            description="Its filter drives the other"
            placeholder="Pick a collection"
            value={link.source_tag || null}
            data={withCurrent(sourceTags, link.source_tag).map(option)}
            allowDeselect={false}
            onChange={(v) => {
              const patch: Partial<BuilderLinkDraft> = { source_tag: v ?? '', source_column: '' };
              if (v && v === link.target_tag) {
                patch.target_tag = '';
                patch.target_field = null;
              }
              onPatch(patch);
            }}
            data-testid="builder-link-source"
          />
          <ColumnField
            label="Column"
            description="The values that filter"
            value={link.source_column}
            columns={sourceColumns}
            required
            testId="builder-link-source-column"
            onChange={pickSourceColumn}
          />
          <Select
            label="Filters collection"
            description="Follows the column's filter"
            placeholder={targetTags.length ? 'Pick a collection' : 'No collection can be a target'}
            value={link.target_tag || null}
            data={withCurrent(targetTags, link.target_tag).map(option)}
            allowDeselect={false}
            onChange={pickTarget}
            data-testid="builder-link-target"
          />
          <Select
            label="Resolver"
            description="How the values map onto the target"
            value={link.resolver ?? defaultLinkResolver(target?.type)}
            data={BUILDER_LINK_RESOLVERS.map((r) => ({ value: r, label: RESOLVER_LABELS[r] }))}
            allowDeselect={false}
            onChange={(v) => v && onPatch({ resolver: v as BuilderLinkResolver })}
            data-testid="builder-link-resolver"
          />
          {target && COLUMN_TARGETS.has(target.type) ? (
            <ColumnField
              label="Target column"
              description="The target's column holding the same values"
              value={link.target_field}
              columns={targetColumns}
              testId="builder-link-target-field"
              onChange={(v) => onPatch({ target_field: v })}
            />
          ) : (
            <TextInput
              label="Target field"
              description={
                target?.type === 'multiqc'
                  ? 'MultiQC: sample_name'
                  : target?.type === 'genomic_tracks'
                    ? "The manifest's sample column"
                    : 'Optional'
              }
              placeholder={target ? defaultLinkTargetField(target, link.source_column) ?? '' : ''}
              value={link.target_field ?? ''}
              onChange={(e) => onPatch({ target_field: e.currentTarget.value })}
              styles={MONO}
              data-testid="builder-link-target-field"
            />
          )}
          {link.resolver === 'pattern' && (
            <TextInput
              label="Pattern"
              description="Must hold {sample}"
              placeholder="{sample}_R1"
              value={link.pattern ?? ''}
              onChange={(e) => onPatch({ pattern: e.currentTarget.value })}
              styles={MONO}
              data-testid="builder-link-pattern"
            />
          )}
        </SimpleGrid>
        <TextInput
          size="xs"
          placeholder="Optional: what the link is for"
          aria-label="Link description"
          value={link.description ?? ''}
          onChange={(e) => onPatch({ description: e.currentTarget.value })}
        />
        {issues.map((message) => (
          <Text key={message} size="xs" c="red" data-testid="builder-link-error">
            {message}
          </Text>
        ))}
      </Stack>
    </Paper>
  );
};

/** Why no link can be added yet; null when one can. */
function addBlocker(state: BuilderState, capabilities: BuilderCapabilities): string | null {
  if (capabilities.link_target_types.length === 0) return 'This server does not take links from the builder.';
  if (linkSourceTags(state).length === 0) return 'Links read from a table, image or genomic tracks collection: add one first.';
  const anyTarget = linkSourceTags(state).some((tag) => linkTargetTags(state, capabilities, tag).length > 0);
  if (!anyTarget) return 'No other collection can be filtered by a link.';
  return null;
}

export const LinksSection: React.FC<{
  state: BuilderState;
  dispatch: React.Dispatch<BuilderAction>;
  root: BuilderRootSpec;
  remote: boolean;
  capabilities: BuilderCapabilities;
}> = ({ state, dispatch, root, remote, capabilities }) => {
  const accent = useBrandAccents();
  useMissingSchemas(root, remote, state, capabilities, dispatch);
  const issues = linkIssues(state, capabilities);
  const blocker = addBlocker(state, capabilities);
  return (
    <Paper withBorder radius="md" p="md" data-testid="builder-links">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Icon icon="mdi:link-variant" width={18} color={`var(--mantine-color-${accent.secondary}-6)`} />
              <Text fw={600}>Links</Text>
              {state.links.length > 0 && (
                <Badge size="sm" variant="light" color={accent.secondary}>
                  {state.links.length}
                </Badge>
              )}
            </Group>
            <Text size="xs" c="dimmed">
              Links filter one collection from another on a dashboard; you can also add them later on the
              project page.
            </Text>
          </Stack>
          <Button
            size="xs"
            variant="light"
            color={accent.secondary}
            leftSection={<Icon icon="mdi:plus" width={14} />}
            onClick={() => dispatch({ type: 'link/add', link: newLinkDraft(state, capabilities) })}
            disabled={Boolean(blocker)}
            style={{ flexShrink: 0 }}
            data-testid="builder-link-add"
          >
            Add link
          </Button>
        </Group>
        <DisabledReason reason={blocker} icon="mdi:information-outline" testId="builder-link-add-reason" />
        {state.links.map((link, index) => (
          <LinkRow
            // eslint-disable-next-line react/no-array-index-key
            key={index}
            index={index}
            link={link}
            state={state}
            capabilities={capabilities}
            issues={issues.filter((i) => i.linkIndex === index).map((i) => i.message)}
            onPatch={(patch) => dispatch({ type: 'link/patch', index, patch })}
            onRemove={() => dispatch({ type: 'link/remove', index })}
          />
        ))}
        <Text size="xs" c="dimmed">
          Joins and recipes are not available here: add them later via the project YAML and{' '}
          <Text span ff="monospace" size="xs">
            depictio ingest
          </Text>
          .
        </Text>
      </Stack>
    </Paper>
  );
};
