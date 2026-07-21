/**
 * Middle column: schema + first rows of the active file, plus recognition info
 * (is it a known tool output? the config-by-example scan glob + match count).
 */
import React from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  Badge,
  Center,
  Code,
  Group,
  Paper,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
} from '@mantine/core';
import { Icon } from '@iconify/react';
import type { PreviewData, RecognizeResult } from './backend';

interface Props {
  preview: PreviewData | null;
  recognize: RecognizeResult | null;
  theme: 'light' | 'dark';
}

/** ag-grid table of a preview's rows + column·dtype headers. Shared by the source
 *  preview and the per-DC review preview. */
export const PreviewGrid: React.FC<{
  preview: PreviewData;
  theme: 'light' | 'dark';
  height?: number;
}> = ({ preview, theme, height = 260 }) => {
  const columnDefs = preview.columns.map((c) => ({
    field: c,
    headerName: `${c}  ·  ${preview.schema[c]}`,
    sortable: true,
    filter: true,
    resizable: true,
  }));
  return (
    <div
      className={theme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
      style={{ height, width: '100%' }}
    >
      <AgGridReact
        rowData={preview.rows}
        columnDefs={columnDefs}
        defaultColDef={{ flex: 1, minWidth: 120, resizable: true }}
        suppressFieldDotNotation
      />
    </div>
  );
};

const DataPanel: React.FC<Props> = ({ preview, recognize, theme }) => {
  if (!preview)
    return (
      <Center mih={340} p="xl">
        <Paper
          withBorder
          radius="lg"
          p={40}
          maw={460}
          style={{ borderStyle: 'dashed', textAlign: 'center' }}
        >
          <Stack gap="md" align="center">
            <ThemeIcon variant="light" color="teal" size={72} radius="xl">
              <Icon icon="mdi:table-search" width={40} />
            </ThemeIcon>
            <Text fw={700} fz={26} lh={1.2}>
              Pick a file to preview it
            </Text>
            <Text c="dimmed" fz="lg" maw={360}>
              Click any file in the <b>Files</b> panel to see its first rows and inferred schema.
            </Text>
          </Stack>
        </Paper>
      </Center>
    );

  return (
    <Stack gap="sm" p="md">
      <Group justify="space-between">
        <Text fw={600} size="sm">
          <Icon icon="mdi:table" width={16} style={{ verticalAlign: -3 }} /> {preview.path}
        </Text>
        <Badge variant="light" size="sm">
          {preview.format.toUpperCase()} · {preview.columns.length} cols
        </Badge>
      </Group>

      <PreviewGrid preview={preview} theme={theme} />

      <SchemaList schema={preview.schema} columns={preview.columns} />

      {recognize ? (
        <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-default-hover)">
          <Stack gap={4}>
            <Group gap="xs">
              <Icon
                icon={recognize.recognized ? 'mdi:check-circle' : 'mdi:help-circle-outline'}
                width={16}
                color={
                  recognize.recognized
                    ? 'var(--mantine-color-teal-6)'
                    : 'var(--mantine-color-dimmed)'
                }
              />
              <Text size="sm">
                {recognize.recognized ? (
                  <>
                    Recognized:{' '}
                    <Text span fw={600}>
                      {recognize.matches.map((m) => m.tool_id).join(', ')}
                    </Text>
                  </>
                ) : (
                  'Unknown tool — using config-by-example'
                )}
              </Text>
            </Group>
            <Group gap="xs">
              <Text size="xs" fw={600} c="dimmed" style={{ minWidth: 84 }}>
                Scan glob
              </Text>
              <Code fz="xs">{recognize.config_by_example.path_glob}</Code>
              <Badge size="xs" variant="light">
                {recognize.config_by_example.match_count} match
                {recognize.config_by_example.match_count === 1 ? '' : 'es'}
              </Badge>
            </Group>
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );
};

export default DataPanel;

/** Scrollable column→dtype list — scales to wide tables where inline badges wrap
 *  into an unreadable blob. Reused by the Data-collections step. */
export const SchemaList: React.FC<{
  schema: Record<string, string>;
  columns?: string[];
  maxHeight?: number;
}> = ({ schema, columns, maxHeight = 180 }) => {
  const cols = columns ?? Object.keys(schema);
  return (
    <Stack gap={4}>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase">
        Schema · {cols.length} col{cols.length === 1 ? '' : 's'}
      </Text>
      <Paper withBorder radius="sm">
        <ScrollArea.Autosize mah={maxHeight} type="auto">
          <Stack gap={0}>
            {cols.map((c, i) => (
              <Group
                key={c}
                justify="space-between"
                wrap="nowrap"
                px="sm"
                py={4}
                style={{
                  borderTop: i === 0 ? undefined : '1px solid var(--mantine-color-default-border)',
                }}
              >
                <Text size="xs" style={{ fontFamily: 'var(--mantine-font-family-monospace)' }} lineClamp={1}>
                  {c}
                </Text>
                <Badge size="xs" variant="light" color="gray" radius="sm" tt="none">
                  {schema[c]}
                </Badge>
              </Group>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </Paper>
    </Stack>
  );
};
