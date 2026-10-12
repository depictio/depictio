/**
 * The collection being added or edited: where it goes (workflow), its tag,
 * type and per-type properties, and which files it reads, a single file or
 * a scan whose glob and regex stay in step, with the files it would ingest
 * listed live below.
 */
import React, { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Collapse,
  Divider,
  Group,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { BUILDER_DC_TYPES, isTagTaken, tableTags, useBrandAccents } from 'depictio-react-core';
import type { BuilderDcType, BuilderState, BuilderSuggestion } from 'depictio-react-core';

import { DisabledReason, GatedButton } from '../../../components/settings/SettingsSections';
import { WorkflowLogo } from '../workflows/WorkflowLogo';
import {
  BuilderDcTypeIcon,
  DC_TYPE_META,
  dcTypeUnavailableReason,
  S3_WALK_REASON,
} from './dcTypes';
import {
  suggestedType,
  suggestionDiffers,
  withGlob,
  withMode,
  withRegex,
  withSuggestedPattern,
  withType,
} from './dcForm';
import type { DcFormState } from './dcForm';
import { PropsForm } from './forms';
import { MatchesPanel } from './MatchesPanel';
import type { MatchState } from './useBuilderMatch';

const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

interface CollectionEditorProps {
  state: BuilderState;
  form: DcFormState;
  onChange: (form: DcFormState) => void;
  onSave: () => void;
  onCancel: () => void;
  /** The file previewed beside the editor. */
  activeFile: string | null;
  suggestion: BuilderSuggestion | null;
  suggesting: boolean;
  match: MatchState;
  onRefreshMatch?: () => void;
  remote: boolean;
  /** The previewed file's columns. */
  columns: string[];
}

/** Why the collection cannot be saved yet; null when it can. */
function saveBlocker(state: BuilderState, form: DcFormState, remote: boolean): string | null {
  const { dc } = form;
  const tag = dc.tag.trim();
  if (!tag) return 'Give the collection a tag.';
  if (isTagTaken(state, tag, form.originalTag)) return 'Another collection already uses this tag.';
  if (dc.mode === 'single' && !dc.path?.trim()) return 'Pick the file it reads.';
  if (dc.mode === 'recursive' && !dc.regex?.trim()) return 'Give the scan a pattern.';
  const unavailable = dcTypeUnavailableReason(dc.type, remote);
  if (unavailable) return unavailable;
  const p = dc.props;
  if (p.kind === 'image' && !p.image_column.trim()) return 'Name the image column.';
  if (p.kind === 'geojson' && !p.feature_id_key.trim()) return 'Name the feature id key.';
  if (p.kind === 'phylogeny' && p.metadata_dc_tag && !tableTags(state).includes(p.metadata_dc_tag)) {
    return 'The metadata table is not a table collection of this project.';
  }
  return null;
}

export const CollectionEditor: React.FC<CollectionEditorProps> = ({
  state,
  form,
  onChange,
  onSave,
  onCancel,
  activeFile,
  suggestion,
  suggesting,
  match,
  onRefreshMatch,
  remote,
  columns,
}) => {
  const accent = useBrandAccents();
  const { dc } = form;
  const editing = form.originalTag !== null;
  const [advancedOpen, setAdvancedOpen] = useState(
    dc.max_depth != null || Boolean(dc.ignore?.length),
  );
  const tagClash = isTagTaken(state, dc.tag, form.originalTag);
  const target = state.workflows.find((w) => w.id === form.workflowId) ?? state.workflows[0];
  const blocker = saveBlocker(state, form, remote);
  const tables = tableTags(state, form.originalTag);

  const typeData = BUILDER_DC_TYPES.map((type) => ({
    value: type,
    label: DC_TYPE_META[type].label,
    disabled: Boolean(dcTypeUnavailableReason(type, remote)) && dc.type !== type,
  }));

  return (
    <Paper withBorder radius="md" p="md" data-testid="builder-dc-editor" data-editing={editing || undefined}>
      <Stack gap="sm">
        <Group gap="xs" wrap="nowrap">
          <BuilderDcTypeIcon type={dc.type} size={18} />
          <Text fw={600} size="sm">
            {editing ? `Edit “${form.originalTag}”` : 'New data collection'}
          </Text>
          {suggesting && (
            <Badge size="xs" variant="light" color="gray">
              reading the file...
            </Badge>
          )}
          {suggestion?.multiqc && (
            <Badge size="xs" variant="light" color="violet">
              MultiQC report
            </Badge>
          )}
        </Group>

        {suggestion && suggestion.catalog.length > 0 && (
          <Group gap={6} wrap="wrap" data-testid="builder-dc-recognized">
            <Icon icon="mdi:check-decagram-outline" width={15} color={`var(--mantine-color-${accent.secondary}-6)`} />
            <Text size="xs" c="dimmed">
              Recognized:
            </Text>
            {suggestion.catalog.map((c) => (
              <Tooltip
                key={`${c.tool_id}/${c.output_id}`}
                label={c.renders.length ? `Renders as ${c.renders.join(', ')}` : 'A known tool output'}
                withArrow
              >
                <Badge size="xs" variant="light" color={accent.secondary} tt="none">
                  {c.tool_id} · {c.output_id}
                </Badge>
              </Tooltip>
            ))}
          </Group>
        )}

        <Group grow align="flex-start">
          <TextInput
            label="Tag"
            description="Unique across the whole project"
            value={dc.tag}
            onChange={(e) =>
              onChange({ ...form, dc: { ...dc, tag: e.currentTarget.value }, touched: { ...form.touched, tag: true } })
            }
            leftSection={<Icon icon="mdi:tag-outline" width={16} />}
            error={tagClash ? 'Another collection already uses this tag.' : !dc.tag.trim() ? 'Required' : undefined}
            spellCheck={false}
            data-testid="builder-dc-tag"
          />
          <Select
            label="Workflow"
            description="Where the collection goes"
            value={target?.id ?? null}
            data={state.workflows.map((w) => ({ value: w.id, label: w.name || '(unnamed)' }))}
            allowDeselect={false}
            onChange={(v) => v && onChange({ ...form, workflowId: v })}
            leftSection={<WorkflowLogo engine={target?.engine} catalog={target?.catalog?.name} size={16} />}
            data-testid="builder-dc-workflow"
          />
        </Group>

        <TextInput
          label="Description"
          placeholder="Optional: what this collection holds"
          value={dc.description ?? ''}
          onChange={(e) => onChange({ ...form, dc: { ...dc, description: e.currentTarget.value } })}
        />

        <Select
          label="Type"
          value={dc.type}
          data={typeData}
          allowDeselect={false}
          onChange={(v) => v && onChange(withType(form, v as BuilderDcType))}
          leftSection={<BuilderDcTypeIcon type={dc.type} size={16} />}
          renderOption={({ option }) => {
            const type = option.value as BuilderDcType;
            const reason = dcTypeUnavailableReason(type, remote);
            const row = (
              <Group gap="xs" wrap="nowrap">
                <BuilderDcTypeIcon type={type} size={16} />
                <Stack gap={0}>
                  <Text size="sm">{DC_TYPE_META[type].label}</Text>
                  <Text size="xs" c="dimmed">
                    {reason ?? DC_TYPE_META[type].description}
                  </Text>
                </Stack>
              </Group>
            );
            return reason ? (
              <Tooltip label={reason} withArrow position="right">
                <div>{row}</div>
              </Tooltip>
            ) : (
              row
            );
          }}
          error={dcTypeUnavailableReason(dc.type, remote) ?? undefined}
          description={
            suggestion && suggestedType(suggestion) !== dc.type
              ? `Suggested: ${DC_TYPE_META[suggestedType(suggestion)].label}`
              : undefined
          }
          data-testid="builder-dc-type"
        />

        <Divider label="Files" labelPosition="left" />

        <Group justify="space-between" align="flex-end">
          <SegmentedControl
            size="xs"
            value={dc.mode}
            data={[
              { value: 'single', label: 'One file' },
              { value: 'recursive', label: 'Scan (pattern)' },
            ]}
            onChange={(v) => onChange(withMode(form, v === 'recursive' ? 'recursive' : 'single', suggestion, activeFile))}
            data-testid="builder-dc-mode"
          />
          <Checkbox
            size="xs"
            label="Optional: skip when nothing matches"
            checked={Boolean(dc.optional)}
            onChange={(e) => onChange({ ...form, dc: { ...dc, optional: e.currentTarget.checked } })}
          />
        </Group>

        {dc.mode === 'single' ? (
          <TextInput
            label="File"
            description="Relative to the root"
            value={dc.path ?? ''}
            onChange={(e) => onChange({ ...form, dc: { ...dc, path: e.currentTarget.value } })}
            leftSection={<Icon icon="mdi:file-outline" width={16} />}
            rightSection={
              activeFile && activeFile !== dc.path ? (
                <Tooltip label="Use the previewed file" withArrow>
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    onClick={() => onChange({ ...form, dc: { ...dc, path: activeFile } })}
                    aria-label="Use the previewed file"
                  >
                    <Icon icon="mdi:file-replace-outline" width={15} />
                  </ActionIcon>
                </Tooltip>
              ) : undefined
            }
            styles={MONO}
            spellCheck={false}
            data-testid="builder-dc-path"
          />
        ) : (
          <>
            <TextInput
              label="Glob"
              description="Files to include, e.g. *_counts.tsv or results/*/quant.sf. Tick sibling files in the tree to generalise it."
              placeholder={dc.regex && !dc.glob ? '(a hand-written regex below)' : '*.tsv'}
              value={dc.glob ?? ''}
              onChange={(e) => onChange(withGlob(form, e.currentTarget.value))}
              leftSection={<Icon icon="mdi:file-search-outline" width={16} />}
              styles={MONO}
              spellCheck={false}
              data-testid="builder-dc-glob"
            />
            <TextInput
              label="Regex"
              description="What ingestion matches: each file's name, or its path from the root when the pattern has a /"
              value={dc.regex ?? ''}
              onChange={(e) => onChange(withRegex(form, e.currentTarget.value))}
              leftSection={<Icon icon="mdi:regex" width={16} />}
              rightSection={
                suggestion && suggestionDiffers(form, suggestion) ? (
                  <Tooltip label={`Use the suggested pattern: ${suggestion.regex}`} withArrow multiline maw={320}>
                    <ActionIcon
                      variant="subtle"
                      color="gray"
                      onClick={() => onChange(withSuggestedPattern(form, suggestion))}
                      aria-label="Use the suggested pattern"
                      data-testid="builder-dc-use-suggestion"
                    >
                      <Icon icon="mdi:auto-fix" width={15} />
                    </ActionIcon>
                  </Tooltip>
                ) : undefined
              }
              error={!dc.regex?.trim() ? 'Required' : undefined}
              styles={MONO}
              spellCheck={false}
              data-testid="builder-dc-regex"
            />
            <Box>
              <Button
                variant="subtle"
                size="compact-sm"
                color="gray"
                leftSection={<Icon icon={advancedOpen ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />}
                onClick={() => setAdvancedOpen((v) => !v)}
              >
                Advanced scan options
              </Button>
              <Collapse in={advancedOpen}>
                <Stack gap={4} pt="xs">
                  <Group grow align="flex-start">
                    <NumberInput
                      label="Max depth"
                      description="Folder levels to descend (blank: no limit)"
                      value={dc.max_depth ?? ''}
                      onChange={(v) => onChange({ ...form, dc: { ...dc, max_depth: typeof v === 'number' ? v : null } })}
                      min={0}
                      allowDecimal={false}
                      disabled={remote}
                    />
                    <TagsInput
                      label="Ignore"
                      description="Globs of paths to skip (Enter to add)"
                      value={dc.ignore ?? []}
                      onChange={(ignore) => onChange({ ...form, dc: { ...dc, ignore } })}
                      placeholder="work/*, *.tmp"
                      disabled={remote}
                    />
                  </Group>
                  {remote && <DisabledReason reason={S3_WALK_REASON} icon="mdi:information-outline" />}
                </Stack>
              </Collapse>
            </Box>
          </>
        )}

        <MatchesPanel state={match} onRefresh={onRefreshMatch} />

        <Divider label={`${DC_TYPE_META[dc.type].label} settings`} labelPosition="left" />
        <PropsForm
          props={dc.props}
          onChange={(props) => onChange({ ...form, dc: { ...dc, props } })}
          columns={columns}
          remote={remote}
          tables={tables}
        />

        <Group justify="flex-end" gap="xs">
          <Button variant="default" onClick={onCancel} data-testid="builder-dc-cancel">
            Cancel
          </Button>
          <GatedButton
            color={accent.secondary}
            leftSection={<Icon icon={editing ? 'mdi:content-save' : 'mdi:plus'} width={16} />}
            onClick={onSave}
            reason={blocker}
            data-testid="builder-add-dc"
          >
            {editing ? 'Save changes' : `Add to ${target?.name || 'workflow'}`}
          </GatedButton>
        </Group>
        <Group justify="flex-end">
          <DisabledReason reason={blocker} icon="mdi:information-outline" testId="builder-add-dc-reason" />
        </Group>
      </Stack>
    </Paper>
  );
};
