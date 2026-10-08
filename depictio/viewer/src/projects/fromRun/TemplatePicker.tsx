/**
 * The template choice of the run tab, in two fields:
 *
 *  - Pipeline: one entry per pipeline, grouped by source, with the source's
 *    mark. Empty means "let Depictio recognise it from the folder".
 *  - Template version: the versions of that pipeline the catalog has a
 *    template for, newest first, each a card that wraps onto the next line
 *    with its own marks (the one matching the run, or the closest to it, and
 *    the newest). A select beyond `CARDS_MAX` versions. Arrow keys move
 *    between the cards and pick, Tab enters and leaves them as one stop.
 *
 * Detection fills both and marks each "Detected" until the reader changes it.
 */
import React, { useMemo } from 'react';
import { Group, Input, Radio, Select, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';

import { formatVersion, sameVersion, Z_LAYERS } from 'depictio-react-core';
import type { RunPipeline, RunPipelineGroup, RunTemplateVersion } from 'depictio-react-core';

import { TemplateSourceLogo } from '../template';
import { FlowBadge } from './FlowBadge';

/** More versions than this switch the cards to a select. */
const CARDS_MAX = 8;

const VERSION_DESCRIPTION =
  "The pipeline version the Depictio template was written for. The run's own version is shown above.";

interface TemplatePickerProps {
  groups: RunPipelineGroup[];
  pipeline: RunPipeline | null;
  templateId: string | null;
  /** Pipeline version that made the run, when known. */
  runVersion: string | null;
  /** The template detection chose because no version matches the run. */
  closestTemplateId?: string | null;
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

const versionText = (version: RunTemplateVersion): string =>
  version.version ? formatVersion(version.version) : 'single version';

/** How a version relates to the run, then whether it is the newest. */
const VersionMarks: React.FC<{
  version: RunTemplateVersion;
  runVersion: string | null;
  closestTemplateId: string | null;
}> = ({ version, runVersion, closestTemplateId }) => {
  const matches = sameVersion(version.version, runVersion);
  return (
    <>
      {matches && <FlowBadge status="matches-run" />}
      {!matches && closestTemplateId === version.templateId && (
        <FlowBadge
          status="closest-to-run"
          tooltip="No template exists for the run's own version: this one is the nearest."
        />
      )}
      {version.latest && <FlowBadge status="latest" />}
    </>
  );
};

/** A version in the select's list. */
const VersionOption: React.FC<{
  version: RunTemplateVersion;
  runVersion: string | null;
  closestTemplateId: string | null;
}> = ({ version, runVersion, closestTemplateId }) => (
  <Group
    gap={6}
    wrap="wrap"
    component="span"
    data-testid={`run-version-option-${version.version ?? version.templateId}`}
  >
    <Text span size="sm" ff="monospace">
      {versionText(version)}
    </Text>
    <VersionMarks version={version} runVersion={runVersion} closestTemplateId={closestTemplateId} />
  </Group>
);

export const TemplatePicker: React.FC<TemplatePickerProps> = ({
  groups,
  pipeline,
  templateId,
  runVersion,
  closestTemplateId = null,
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
  const selected = templateId ?? versions[0]?.templateId ?? null;
  const selectedListed = versions.some((v) => v.templateId === selected);
  const versionLabel = (
    <FieldLabel text="Template version" detected={versionDetected} testId="run-version-detected" />
  );

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

      {!pipeline ? (
        <Input.Wrapper label={versionLabel} description={VERSION_DESCRIPTION}>
          <Text size="sm" c="dimmed" mt={6} data-testid="run-version-empty">
            Pick a pipeline first, or leave both empty and Depictio picks the template that
            matches the folder.
          </Text>
        </Input.Wrapper>
      ) : versions.length <= CARDS_MAX ? (
        <Radio.Group
          label={versionLabel}
          description={VERSION_DESCRIPTION}
          value={selected}
          onChange={onVersionChange}
          data-testid="run-version-control"
        >
          <Group gap="xs" wrap="wrap" mt={6}>
            {versions.map((v) => {
              const checked = v.templateId === selected;
              return (
                <Radio.Card
                  key={v.templateId}
                  value={v.templateId}
                  radius="md"
                  w="auto"
                  px="sm"
                  py={6}
                  // One Tab stop for the whole set, as native radios have;
                  // the arrow keys move between the cards.
                  tabIndex={checked || (!selectedListed && v === versions[0]) ? 0 : -1}
                  bg={checked ? 'var(--mantine-primary-color-light)' : undefined}
                  style={{
                    maxWidth: '100%',
                    borderColor: checked ? 'var(--mantine-primary-color-filled)' : undefined,
                  }}
                  data-testid={`run-version-option-${v.version ?? v.templateId}`}
                  data-template-id={v.templateId}
                >
                  <Group gap={8} wrap="wrap">
                    <Radio.Indicator size="xs" />
                    <Text span size="sm" fw={600} ff="monospace">
                      {versionText(v)}
                    </Text>
                    <VersionMarks
                      version={v}
                      runVersion={runVersion}
                      closestTemplateId={closestTemplateId}
                    />
                  </Group>
                </Radio.Card>
              );
            })}
          </Group>
        </Radio.Group>
      ) : (
        <Select
          label={versionLabel}
          description={VERSION_DESCRIPTION}
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
            return v ? (
              <VersionOption version={v} runVersion={runVersion} closestTemplateId={closestTemplateId} />
            ) : (
              option.label
            );
          }}
          data-testid="run-version-select"
        />
      )}
    </Stack>
  );
};
