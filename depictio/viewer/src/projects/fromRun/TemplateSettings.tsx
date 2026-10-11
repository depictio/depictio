/**
 * Template settings (the template's variables other than DATA_ROOT) in the
 * run tab, both folded by default since the server works them out from the
 * run folder:
 *
 *  - on the Source step, the fields that override them;
 *  - on the Preview step, what the server resolved, as a table.
 *
 * Each setting reads as a label ("Group column") with its raw name
 * (`GROUP_COL`) beside it, the name the template and `--var` use.
 */
import React from 'react';
import { Accordion, Code, Group, Stack, Table, Text, TextInput, Tooltip } from '@mantine/core';

import { humanizeVariableName, templateSettingValue, Z_LAYERS } from 'depictio-react-core';
import type { TemplateVariable } from 'depictio-react-core';

import { FolderPath } from './FolderPath';
import { SectionHeader } from './SectionHeader';

/** "Group column" and, beside it, `GROUP_COL`. */
const SettingName: React.FC<{ name: string }> = ({ name }) => (
  <Group gap={6} wrap="wrap" component="span" display="inline-flex" style={{ rowGap: 0 }}>
    <span>{humanizeVariableName(name)}</span>
    <Text span size="xs" ff="monospace" c="dimmed" fw={400}>
      {name}
    </Text>
  </Group>
);

interface TemplateSettingsSectionProps {
  variables: TemplateVariable[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
}

/** The Source step's override fields, folded under one header. */
export const TemplateSettingsSection: React.FC<TemplateSettingsSectionProps> = ({
  variables,
  values,
  onChange,
}) => {
  const overridden = variables.filter((v) => (values[v.name] ?? '').trim()).length;
  return (
    <Accordion variant="separated" radius="md" chevronPosition="right">
      <Accordion.Item value="settings" data-testid="run-template-settings">
        <Accordion.Control data-testid="run-template-settings-toggle">
          <SectionHeader
            icon="mdi:tune-variant"
            color="gray"
            title="Advanced: template settings"
            count={variables.length}
            note={overridden > 0 ? `${overridden} overridden` : undefined}
            description="Depictio works these out from the run folder. Give one a value only to override it."
          />
        </Accordion.Control>
        <Accordion.Panel>
          <Stack gap="sm">
            {variables.map((v) => (
              <TextInput
                key={v.name}
                label={<SettingName name={v.name} />}
                description={v.description ?? undefined}
                placeholder={v.default ?? ''}
                value={values[v.name] ?? ''}
                onChange={(e) => onChange(v.name, e.currentTarget.value)}
                spellCheck={false}
                data-testid={`run-variable-input-${v.name}`}
              />
            ))}
          </Stack>
        </Accordion.Panel>
      </Accordion.Item>
    </Accordion>
  );
};

/** One resolved value: a location under the run folder relative to it, a
 *  long list cut short, anything else as it is. */
const SettingValue: React.FC<{ value: string; dataRoot: string; testId: string }> = ({
  value,
  dataRoot,
  testId,
}) => {
  const shown = templateSettingValue(value, dataRoot);
  switch (shown.kind) {
    case 'empty':
      return (
        <Text size="sm" c="dimmed" fs="italic" data-testid={testId}>
          Not set
        </Text>
      );
    case 'run-folder':
      return (
        <Text size="sm" c="dimmed" title={shown.full} data-testid={testId}>
          The run folder
        </Text>
      );
    case 'run-path':
      return (
        <Tooltip label={shown.full} withArrow multiline maw={480} zIndex={Z_LAYERS.tooltip}>
          <Code data-testid={testId} data-full-path={shown.full} style={{ wordBreak: 'break-all' }}>
            {shown.relative}
          </Code>
        </Tooltip>
      );
    case 'path':
      return <FolderPath location={shown.full} maxLength={48} testId={testId} />;
    case 'list':
      return (
        <Group gap={6} wrap="wrap" data-testid={testId}>
          <Text size="sm" ff="monospace" style={{ wordBreak: 'break-word' }}>
            {shown.shown.join(', ')}
          </Text>
          {shown.more > 0 && (
            <Tooltip
              label={shown.items.join(', ')}
              withArrow
              multiline
              maw={360}
              zIndex={Z_LAYERS.tooltip}
              events={{ hover: true, focus: true, touch: true }}
            >
              <Text
                span
                size="xs"
                c="dimmed"
                td="underline"
                tabIndex={0}
                style={{ textDecorationStyle: 'dotted', cursor: 'help' }}
              >
                and {shown.more} more
              </Text>
            </Tooltip>
          )}
        </Group>
      );
    case 'text':
      return (
        <Text size="sm" ff="monospace" style={{ wordBreak: 'break-word' }} data-testid={testId}>
          {shown.text}
        </Text>
      );
  }
};

/** The Preview step's resolved settings, folded under one header. */
export const ResolvedSettings: React.FC<{ settings: Array<[string, string]>; dataRoot: string }> = ({
  settings,
  dataRoot,
}) => (
  <Accordion variant="separated" radius="md" chevronPosition="right">
    <Accordion.Item value="settings" data-testid="run-resolved-variables">
      <Accordion.Control data-testid="run-resolved-variables-toggle">
        <SectionHeader
          icon="mdi:tune-variant"
          color="gray"
          title="Template settings"
          count={settings.length}
          description="What the template resolved for this run folder. Override one in Advanced: template settings, on the Source step."
        />
      </Accordion.Control>
      <Accordion.Panel>
        <Table.ScrollContainer minWidth={420}>
          <Table verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th w="40%">Setting</Table.Th>
                <Table.Th>Value</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {settings.map(([key, value]) => (
                <Table.Tr key={key} data-testid={`run-resolved-variable-${key}`}>
                  <Table.Td style={{ verticalAlign: 'top' }}>
                    <Text size="sm" fw={500}>
                      {humanizeVariableName(key)}
                    </Text>
                    <Text size="xs" ff="monospace" c="dimmed" style={{ wordBreak: 'break-all' }}>
                      {key}
                    </Text>
                  </Table.Td>
                  <Table.Td style={{ verticalAlign: 'top' }}>
                    <SettingValue value={value} dataRoot={dataRoot} testId={`run-resolved-value-${key}`} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Accordion.Panel>
    </Accordion.Item>
  </Accordion>
);
