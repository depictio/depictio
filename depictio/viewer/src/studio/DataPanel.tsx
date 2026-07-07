/**
 * Middle column: schema + first rows of the active file, plus recognition info
 * (is it a known tool output? the config-by-example scan glob + match count).
 */
import React from 'react';
import { AgGridReact } from 'ag-grid-react';
import { Badge, Box, Code, Group, Paper, Stack, Text } from '@mantine/core';
import { Icon } from '@iconify/react';
import type { PreviewData, RecognizeResult } from './backend';

interface Props {
  preview: PreviewData | null;
  recognize: RecognizeResult | null;
  theme: 'light' | 'dark';
}

const DataPanel: React.FC<Props> = ({ preview, recognize, theme }) => {
  if (!preview)
    return (
      <Text size="sm" c="dimmed" p="md">
        Pick a file on the left to see its data.
      </Text>
    );

  const columnDefs = preview.columns.map((c) => ({
    field: c,
    headerName: `${c}  ·  ${preview.schema[c]}`,
    sortable: true,
    filter: true,
    resizable: true,
  }));

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

      <div
        className={theme === 'dark' ? 'ag-theme-alpine-dark' : 'ag-theme-alpine'}
        style={{ height: 260, width: '100%' }}
      >
        <AgGridReact
          rowData={preview.rows}
          columnDefs={columnDefs}
          defaultColDef={{ flex: 1, minWidth: 120, resizable: true }}
          suppressFieldDotNotation
        />
      </div>

      <Group gap={6} wrap="wrap">
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          Schema
        </Text>
        {preview.columns.map((c) => (
          <Badge key={c} size="sm" variant="default" radius="sm" tt="none">
            {c}: {preview.schema[c]}
          </Badge>
        ))}
      </Group>

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
