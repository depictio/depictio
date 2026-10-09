/**
 * The template choice of the run tab, in two fields:
 *
 *  - Pipeline: one entry per pipeline, grouped by source, with the source's
 *    mark. Empty means "let Depictio recognise it from the folder".
 *  - Template version: a dropdown of the versions of that pipeline the
 *    catalog has a template for, newest first, each with its marks (the one
 *    matching the run, or the closest to it, and the newest) and where it
 *    stands against the run's version; the field shows the chosen one with
 *    its marks.
 *
 * Detection fills both and marks each "Detected" until the reader changes it.
 */
import React, { useMemo } from 'react';
import { Combobox, Group, Input, InputBase, Select, Stack, Text, useCombobox } from '@mantine/core';
import { Icon } from '@iconify/react';

import { compareVersions, formatVersion, sameVersion, Z_LAYERS } from 'depictio-react-core';
import type { RunPipeline, RunPipelineGroup, RunTemplateVersion } from 'depictio-react-core';

import { TemplateSourceLogo } from '../template';
import { FlowBadge } from './FlowBadge';
import { plural } from './plural';

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

/** Where a template version stands against the run's own version, in a few
 *  words; null when the run's version is unknown. */
function relationToRun(version: RunTemplateVersion, runVersion: string | null): string | null {
  if (!runVersion || !version.version) return null;
  const diff = compareVersions(version.version, runVersion);
  if (diff === 0) return "Written for the run's own version";
  return diff > 0
    ? `Written for a newer release than the run (${formatVersion(runVersion)})`
    : `Written for an older release than the run (${formatVersion(runVersion)})`;
}

/** One version, as the field shows it and as each option of its list does:
 *  the version and how it relates to the run, then, in the list, where it
 *  stands against the run's own version. */
const VersionLine: React.FC<{
  version: RunTemplateVersion;
  runVersion: string | null;
  closestTemplateId: string | null;
  withRelation?: boolean;
}> = ({ version, runVersion, closestTemplateId, withRelation = false }) => {
  const relation = withRelation ? relationToRun(version, runVersion) : null;
  return (
    <Stack gap={2} style={{ minWidth: 0 }}>
      <Group gap={6} wrap="wrap" component="span">
        <Text span size="sm" fw={600} ff="monospace">
          {versionText(version)}
        </Text>
        <VersionMarks version={version} runVersion={runVersion} closestTemplateId={closestTemplateId} />
      </Group>
      {relation && (
        <Text size="xs" c="dimmed">
          {relation}
        </Text>
      )}
    </Stack>
  );
};

interface VersionFieldProps {
  pipeline: RunPipeline | null;
  templateId: string | null;
  runVersion: string | null;
  closestTemplateId: string | null;
  versionDetected: boolean;
  onVersionChange: (templateId: string) => void;
}

/** The Template version field: a hint until a pipeline is picked, then a
 *  dropdown of its versions, newest first, each with its marks (the one
 *  matching the run, or the closest to it, and the newest) and where it
 *  stands against the run, the selected one shown with its marks in the
 *  field. */
const VersionField: React.FC<VersionFieldProps> = ({
  pipeline,
  templateId,
  runVersion,
  closestTemplateId,
  versionDetected,
  onVersionChange,
}) => {
  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
    onDropdownOpen: () => combobox.updateSelectedOptionIndex('active'),
  });
  const label = (
    <FieldLabel text="Template version" detected={versionDetected} testId="run-version-detected" />
  );

  if (!pipeline) {
    return (
      <Input.Wrapper label={label} description={VERSION_DESCRIPTION}>
        <Text size="sm" c="dimmed" mt={6} data-testid="run-version-empty">
          Pick a pipeline first, or leave both empty and Depictio picks the template that
          matches the folder.
        </Text>
      </Input.Wrapper>
    );
  }

  const { versions } = pipeline;
  const selected = versions.find((v) => v.templateId === templateId) ?? versions[0] ?? null;
  return (
    <Combobox
      store={combobox}
      withinPortal
      zIndex={Z_LAYERS.tooltip}
      onOptionSubmit={(value) => {
        onVersionChange(value);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target>
        <InputBase
          component="button"
          type="button"
          pointer
          label={label}
          description={VERSION_DESCRIPTION}
          rightSection={<Combobox.Chevron />}
          rightSectionPointerEvents="none"
          onClick={() => combobox.toggleDropdown()}
          multiline
          styles={{ input: { minHeight: 44, paddingTop: 6, paddingBottom: 6 } }}
          aria-haspopup="listbox"
          aria-expanded={combobox.dropdownOpened}
          data-testid="run-version-control"
          data-template-id={selected?.templateId}
        >
          {selected ? (
            <VersionLine
              version={selected}
              runVersion={runVersion}
              closestTemplateId={closestTemplateId}
            />
          ) : (
            <Input.Placeholder>Pick a version</Input.Placeholder>
          )}
        </InputBase>
      </Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Options mah={340} style={{ overflowY: 'auto' }} aria-label="Template versions">
          {versions.map((v) => {
            const active = v.templateId === selected?.templateId;
            return (
              <Combobox.Option
                key={v.templateId}
                value={v.templateId}
                active={active}
                data-testid={`run-version-option-${v.version ?? v.templateId}`}
                data-template-id={v.templateId}
              >
                <Group gap="sm" wrap="nowrap" align="flex-start">
                  <Icon
                    icon="mdi:check"
                    width={16}
                    style={{ flexShrink: 0, marginTop: 2, visibility: active ? 'visible' : 'hidden' }}
                  />
                  <VersionLine
                    version={v}
                    runVersion={runVersion}
                    closestTemplateId={closestTemplateId}
                    withRelation
                  />
                </Group>
              </Combobox.Option>
            );
          })}
        </Combobox.Options>
        <Combobox.Footer>
          <Text size="xs" c="dimmed">
            {plural(versions.length, 'template version')} of {pipeline.title}, newest first.
          </Text>
        </Combobox.Footer>
      </Combobox.Dropdown>
    </Combobox>
  );
};

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
          return (
            <Group gap="sm" wrap="nowrap" data-testid={`run-pipeline-option-${p.key}`}>
              <TemplateSourceLogo source={p.source} size={22} />
              <Stack gap={0} style={{ minWidth: 0 }}>
                <Text size="sm">{p.title}</Text>
                <Text size="xs" c="dimmed">
                  {p.variant ? `${p.pipeline}, ${p.variant}` : p.pipeline}
                  {` · ${plural(p.versions.length, 'version')}`}
                </Text>
              </Stack>
            </Group>
          );
        }}
        error={error ?? undefined}
        data-testid="run-pipeline-select"
      />

      <VersionField
        pipeline={pipeline}
        templateId={templateId}
        runVersion={runVersion}
        closestTemplateId={closestTemplateId}
        versionDetected={versionDetected}
        onVersionChange={onVersionChange}
      />
    </Stack>
  );
};
