/**
 * The template choice of the run tab, in two fields:
 *
 *  - Pipeline: one entry per pipeline, grouped by source, with the source's
 *    mark. Empty means "let Depictio recognise it from the folder".
 *  - Template version: the versions of that pipeline the catalog has a
 *    template for, newest first, the latest one and the one matching the run
 *    marked. A segmented control while they fit, a select beyond.
 *
 * Detection fills both and marks each "Detected" until the reader changes it.
 */
import React, { useMemo } from 'react';
import { Box, Group, Input, SegmentedControl, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { formatVersion, sameVersion, Z_LAYERS } from 'depictio-react-core';
import type { RunPipeline, RunPipelineGroup, RunTemplateVersion } from 'depictio-react-core';

import { TemplateSourceLogo } from '../template';
import { FlowBadge } from './FlowBadge';

/** More versions than this switch the control to a select. */
const SEGMENTED_MAX = 4;

interface TemplatePickerProps {
  groups: RunPipelineGroup[];
  pipeline: RunPipeline | null;
  templateId: string | null;
  /** Pipeline version that made the run, when known. */
  runVersion: string | null;
  pipelineDetected: boolean;
  versionDetected: boolean;
  onPipelineChange: (key: string | null) => void;
  onVersionChange: (templateId: string) => void;
  error?: string | null;
}

const FieldLabel: React.FC<{ text: string; detected: boolean; testId: string }> = ({
  text,
  detected,
  testId,
}) => (
  <Group gap={6} wrap="nowrap" component="span" display="inline-flex">
    <span>{text}</span>
    {detected && (
      <FlowBadge
        status="detected"
        tooltip="Filled in from what Depictio read in the folder. Change it if it is wrong."
        testId={testId}
      />
    )}
  </Group>
);

const VersionLabel: React.FC<{ version: RunTemplateVersion; runVersion: string | null }> = ({
  version,
  runVersion,
}) => (
  <Group
    gap={6}
    wrap="nowrap"
    justify="center"
    component="span"
    data-testid={`run-version-option-${version.version ?? version.templateId}`}
  >
    <Text span size="sm" ff="monospace">
      {version.version ? formatVersion(version.version) : 'single version'}
    </Text>
    {version.latest && <FlowBadge status="latest" />}
    {sameVersion(version.version, runVersion) && <FlowBadge status="matches-run" />}
  </Group>
);

export const TemplatePicker: React.FC<TemplatePickerProps> = ({
  groups,
  pipeline,
  templateId,
  runVersion,
  pipelineDetected,
  versionDetected,
  onPipelineChange,
  onVersionChange,
  error,
}) => {
  const byKey = useMemo(() => {
    const map = new Map<string, RunPipeline>();
    for (const group of groups) for (const p of group.pipelines) map.set(p.key, p);
    return map;
  }, [groups]);

  const data = useMemo(
    () =>
      groups.map((group) => ({
        group: group.label,
        items: group.pipelines.map((p) => ({ value: p.key, label: p.title })),
      })),
    [groups],
  );

  const versions = pipeline?.versions ?? [];

  return (
    <Stack gap="md">
      <Select
        label={<FieldLabel text="Pipeline" detected={pipelineDetected} testId="run-pipeline-detected" />}
        description="The pipeline that made the run. Leave it empty and Depictio recognises it from the folder."
        placeholder="Detect from the folder"
        data={data}
        value={pipeline?.key ?? null}
        onChange={onPipelineChange}
        clearable
        searchable
        nothingFoundMessage="No pipeline matches"
        maxDropdownHeight={320}
        comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
        leftSection={
          pipeline ? (
            <TemplateSourceLogo source={pipeline.source} size={18} />
          ) : (
            <Icon icon="mdi:auto-fix" width={16} />
          )
        }
        renderOption={({ option }) => {
          const p = byKey.get(option.value);
          if (!p) return <Text size="sm">{option.label}</Text>;
          const count = p.versions.length;
          return (
            <Group gap="sm" wrap="nowrap" data-testid={`run-pipeline-option-${p.key}`}>
              <TemplateSourceLogo source={p.source} size={22} />
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm">{p.title}</Text>
                <Text size="xs" c="dimmed">
                  {p.variant ? `${p.pipeline}, ${p.variant}` : p.pipeline}
                  {` · ${count} version${count === 1 ? '' : 's'}`}
                </Text>
              </Stack>
            </Group>
          );
        }}
        error={error ?? undefined}
        data-testid="run-pipeline-select"
      />

      <Input.Wrapper
        label={
          <FieldLabel text="Template version" detected={versionDetected} testId="run-version-detected" />
        }
        description="The pipeline version the Depictio template was written for. The run's own version is shown above."
      >
        <Box mt={6}>
          {!pipeline ? (
            <Text size="sm" c="dimmed" data-testid="run-version-empty">
              Pick a pipeline first, or leave both empty and Depictio picks the template that
              matches the folder.
            </Text>
          ) : versions.length <= SEGMENTED_MAX ? (
            <SegmentedControl
              value={templateId ?? versions[0]?.templateId ?? ''}
              onChange={onVersionChange}
              data={versions.map((v) => ({
                value: v.templateId,
                label: <VersionLabel version={v} runVersion={runVersion} />,
              }))}
              size="sm"
              data-testid="run-version-control"
            />
          ) : (
            <Select
              value={templateId}
              onChange={(value) => value && onVersionChange(value)}
              allowDeselect={false}
              data={versions.map((v) => ({
                value: v.templateId,
                label: v.version ? formatVersion(v.version) : v.templateId,
              }))}
              comboboxProps={{ zIndex: Z_LAYERS.tooltip }}
              renderOption={({ option }) => {
                const v = versions.find((x) => x.templateId === option.value);
                return v ? <VersionLabel version={v} runVersion={runVersion} /> : option.label;
              }}
              data-testid="run-version-select"
            />
          )}
        </Box>
      </Input.Wrapper>
    </Stack>
  );
};
