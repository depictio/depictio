import React from 'react';
import {
  ActionIcon,
  Badge,
  Card,
  Code,
  CopyButton,
  Group,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { Icon } from '@iconify/react';

/** One tabular file a composed template left out (`TemplateOrigin.unrecognised_files`). */
interface UnrecognisedFile {
  path: string;
  format: string;
  n_columns?: number;
  columns?: string[];
  sample_column?: string | null;
  proposal?: string[];
}

interface TemplateOriginLike {
  data_root?: string;
  unrecognised_files?: UnrecognisedFile[];
}

/** Single-quote a shell argument so a path with spaces or globs survives a paste. */
function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

const CopyCommand: React.FC<{ command: string; label: string }> = ({ command, label }) => (
  <CopyButton value={command}>
    {({ copied, copy }) => (
      <Tooltip label={copied ? 'Copied' : label} withArrow>
        <ActionIcon
          variant="subtle"
          color={copied ? 'teal' : 'gray'}
          onClick={copy}
          aria-label={label}
        >
          <Icon icon={copied ? 'mdi:check' : 'mdi:content-copy'} width={16} />
        </ActionIcon>
      </Tooltip>
    )}
  </CopyButton>
);

/**
 * The tabular files of a composed run that no catalog output recognised.
 *
 * `depictio run` / `depictio local up` compose a dashboard from what the catalog
 * knows and never add anything else silently: they list the rest here, each
 * with the tiles it would get, and the command that ingests it. The files are
 * on the machine that ran the ingestion, so adding them is that command, not a
 * button here.
 */
export const UnrecognisedFilesPanel: React.FC<{ templateOrigin: unknown }> = ({
  templateOrigin,
}) => {
  const origin = (templateOrigin && typeof templateOrigin === 'object'
    ? templateOrigin
    : {}) as TemplateOriginLike;
  const files = origin.unrecognised_files ?? [];
  if (files.length === 0) return null;
  const dataRoot = origin.data_root ?? '<results directory>';
  const base = `depictio local up --data-root ${shellQuote(dataRoot)} --refresh`;

  return (
    <Card withBorder radius="md" padding="lg" data-testid="unrecognised-files-panel">
      <Stack gap="sm">
        <Group justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Icon icon="mdi:file-question-outline" width={20} />
            <Title order={4}>Files the catalog did not recognise</Title>
            <Badge variant="light" color="gray">
              {files.length}
            </Badge>
          </Group>
          <Group gap={4} wrap="nowrap">
            <Code>--include-unknown</Code>
            <CopyCommand
              command={`${base} --include-unknown`}
              label="Copy the command that adds them all"
            />
          </Group>
        </Group>
        <Text size="sm" c="dimmed">
          These tables were left out of the composed dashboard. Each line shows the tiles it
          would get in an <b>Other data</b> tab. Copy a line&apos;s command to add that file:
          it ingests the directory again and resets the dashboard to the composed one.
        </Text>
        <Table striped highlightOnHover verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>File</Table.Th>
              <Table.Th>Columns</Table.Th>
              <Table.Th>Would show</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {files.map((file) => (
              <Table.Tr key={file.path}>
                <Table.Td>
                  <Text size="sm" ff="monospace">
                    {file.path}
                  </Text>
                  {file.sample_column && (
                    <Text size="xs" c="dimmed">
                      samples in <Code>{file.sample_column}</Code>
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Tooltip
                    label={(file.columns ?? []).join(', ') || file.format}
                    multiline
                    maw={420}
                    withArrow
                  >
                    <Text size="sm">
                      {file.n_columns ?? file.columns?.length ?? 0} ({file.format})
                    </Text>
                  </Tooltip>
                </Table.Td>
                <Table.Td>
                  <Group gap={4}>
                    {(file.proposal ?? []).map((item) => (
                      <Badge key={item} variant="light" size="sm" tt="none">
                        {item}
                      </Badge>
                    ))}
                  </Group>
                </Table.Td>
                <Table.Td>
                  <CopyCommand
                    command={`${base} --include ${shellQuote(file.path)}`}
                    label="Copy the command that adds this file"
                  />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Card>
  );
};
