/**
 * Table properties: the format, the separator of a text table, and an
 * optional description per column (the columns come from the file preview).
 */
import React, { useState } from 'react';
import { Button, Collapse, Group, ScrollArea, Select, Stack, Text, TextInput } from '@mantine/core';
import { Icon } from '@iconify/react';

import type { BuilderTableProps } from 'depictio-react-core';

const FORMATS = ['csv', 'tsv', 'parquet', 'feather', 'xlsx'];

const SEPARATORS = [
  { value: ',', label: 'Comma ( , )' },
  { value: '\t', label: 'Tab' },
  { value: ';', label: 'Semicolon ( ; )' },
  { value: '|', label: 'Pipe ( | )' },
];

const TEXT_FORMATS = new Set(['csv', 'tsv', 'txt']);

/** Format + separator, shared with the image form (an image collection is a
 *  table listing the images). */
export const FormatFields: React.FC<{
  format: string;
  separator: string | null | undefined;
  onChange: (patch: { format?: string; separator?: string | null }) => void;
}> = ({ format, separator, onChange }) => {
  const formats = FORMATS.includes(format) ? FORMATS : [format, ...FORMATS];
  return (
    <Group grow align="flex-start">
      <Select
        label="Format"
        value={format}
        data={formats}
        allowDeselect={false}
        onChange={(v) => {
          const next = v || 'csv';
          onChange({
            format: next,
            separator: next === 'tsv' ? '\t' : next === 'csv' ? ',' : TEXT_FORMATS.has(next) ? separator ?? null : null,
          });
        }}
        data-testid="builder-props-format"
      />
      <Select
        label="Separator"
        placeholder="Detected"
        value={separator ?? null}
        data={SEPARATORS}
        clearable
        disabled={!TEXT_FORMATS.has(format)}
        onChange={(v) => onChange({ separator: v })}
      />
    </Group>
  );
};

export const TableForm: React.FC<{
  props: BuilderTableProps;
  onChange: (props: BuilderTableProps) => void;
  columns: string[];
}> = ({ props, onChange, columns }) => {
  const described = props.columns_description ?? {};
  const [open, setOpen] = useState(Object.keys(described).length > 0);
  return (
    <Stack gap="xs">
      <FormatFields
        format={props.format}
        separator={props.separator}
        onChange={(patch) => onChange({ ...props, ...patch })}
      />
      <div>
        <Button
          variant="subtle"
          size="compact-sm"
          color="gray"
          leftSection={<Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />}
          onClick={() => setOpen((v) => !v)}
        >
          Describe the columns (optional)
        </Button>
        <Collapse in={open}>
          {columns.length === 0 ? (
            <Text size="xs" c="dimmed" pt={4}>
              The columns show here once the file preview has read them.
            </Text>
          ) : (
            <ScrollArea.Autosize mah={240} type="auto" offsetScrollbars>
              <Stack gap={4} pt={4}>
                {columns.map((column) => (
                  <TextInput
                    key={column}
                    size="xs"
                    label={column}
                    styles={{ label: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
                    placeholder="What this column holds"
                    value={described[column] ?? ''}
                    onChange={(e) => {
                      const text = e.currentTarget.value;
                      const next = { ...described };
                      if (text) next[column] = text;
                      else delete next[column];
                      onChange({ ...props, columns_description: next });
                    }}
                  />
                ))}
              </Stack>
            </ScrollArea.Autosize>
          )}
        </Collapse>
      </div>
    </Stack>
  );
};
