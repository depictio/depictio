/**
 * Pieces the table-like forms share (table, image, genomic tracks manifest):
 * the format and separator, the csv/tsv reader options, the per-column
 * descriptions, and a folding section.
 */
import React, { useState } from 'react';
import {
  Button,
  Collapse,
  Group,
  NumberInput,
  ScrollArea,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
} from '@mantine/core';
import { Icon } from '@iconify/react';

import { READER_FORMATS } from 'depictio-react-core';
import type { BuilderReaderOptions } from 'depictio-react-core';

import { OptionalBlock } from '../../Requirement';

const SEPARATORS = [
  { value: ',', label: 'Comma ( , )' },
  { value: '\t', label: 'Tab' },
  { value: ';', label: 'Semicolon ( ; )' },
  { value: '|', label: 'Pipe ( | )' },
];

const TEXT_FORMATS = new Set(['csv', 'tsv', 'txt']);

export const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

/** The optional settings of a collection, together in one folded block, so they
 *  read as "more, if you need it" and not as part of what must be filled in.
 *  Each child is a `FoldSection` that says in a few words what it is for. */
export const OptionsSection: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <OptionalBlock
    title="Additional options"
    hint="The defaults suit most files. Open a section only if you need it."
    testId="builder-props-options"
  >
    <Stack gap={2}>{children}</Stack>
  </OptionalBlock>
);

/** A section that folds, opened at first when it holds something. `description`
 *  says what it is for, beside its title. */
export const FoldSection: React.FC<{
  label: string;
  description?: string;
  initiallyOpen?: boolean;
  testId?: string;
  children: React.ReactNode;
}> = ({ label, description, initiallyOpen = false, testId, children }) => {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <div data-testid={testId}>
      <Button
        variant="subtle"
        size="compact-md"
        color="gray"
        fullWidth
        justify="flex-start"
        leftSection={<Icon icon={open ? 'mdi:chevron-down' : 'mdi:chevron-right'} width={16} />}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid={testId ? `${testId}-toggle` : undefined}
      >
        <Group gap={8} wrap="nowrap" component="span">
          <Text span size="sm" fw={600} inherit>
            {label}
          </Text>
          {description && (
            <Text span size="xs" c="dimmed" fw={400} truncate>
              {description}
            </Text>
          )}
        </Group>
      </Button>
      <Collapse in={open}>
        <Stack gap="xs" pt={4}>
          {children}
        </Stack>
      </Collapse>
    </div>
  );
};

/** Format + separator. `formats` are the ones offered; the current one is
 *  kept even when it is not among them. `disabled` maps a format to why it
 *  cannot be picked. */
export const FormatFields: React.FC<{
  format: string;
  separator: string | null | undefined;
  formats: readonly string[];
  disabled?: Record<string, string>;
  label?: string;
  onChange: (patch: { format?: string; separator?: string | null }) => void;
}> = ({ format, separator, formats, disabled = {}, label = 'Format', onChange }) => {
  const values = formats.includes(format) ? [...formats] : [format, ...formats];
  return (
    <Group grow align="flex-start">
      <Select
        label={label}
        value={format}
        data={values.map((value) => ({
          value,
          label: disabled[value] ? `${value} (${disabled[value]})` : value,
          disabled: Boolean(disabled[value]) && value !== format,
        }))}
        allowDeselect={false}
        onChange={(v) => {
          const next = v || 'csv';
          onChange({
            format: next,
            separator:
              next === 'tsv' ? '\t' : next === 'csv' ? ',' : TEXT_FORMATS.has(next) ? separator ?? null : null,
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

/** How a csv/tsv file is read (polars options), limited to the options the
 *  server allows. Nothing for other formats. */
export const ReaderOptionsFields: React.FC<{
  format: string;
  reader: BuilderReaderOptions | null | undefined;
  allowed: readonly string[];
  onChange: (reader: BuilderReaderOptions) => void;
}> = ({ format, reader, allowed, onChange }) => {
  const options = allowed.filter((k) => k !== 'separator');
  if (!READER_FORMATS.has(format) || options.length === 0) return null;
  const r = reader ?? {};
  const has = (key: keyof BuilderReaderOptions) => options.includes(key);
  const set = (patch: Partial<BuilderReaderOptions>) => onChange({ ...r, ...patch });
  const touched = Object.values(r).some((v) => v !== undefined && v !== null && v !== '');
  return (
    <FoldSection
      label="How the file is read"
      description="header, skipped lines, decimal comma, missing values"
      initiallyOpen={touched}
      testId="builder-props-reader"
    >
      <Group grow align="flex-start">
        {has('has_header') && (
          <Switch
            label="First row is the header"
            checked={r.has_header ?? true}
            onChange={(e) => set({ has_header: e.currentTarget.checked })}
            mt={8}
            data-testid="builder-props-reader-has-header"
          />
        )}
        {has('decimal_comma') && (
          <Switch
            label="Decimal comma (3,14)"
            checked={r.decimal_comma ?? false}
            onChange={(e) => set({ decimal_comma: e.currentTarget.checked })}
            mt={8}
          />
        )}
      </Group>
      <Group grow align="flex-start">
        {has('skip_rows') && (
          <NumberInput
            label="Skip rows"
            description="Lines to skip before the header"
            min={0}
            allowDecimal={false}
            value={r.skip_rows ?? ''}
            onChange={(v) => set({ skip_rows: typeof v === 'number' ? v : undefined })}
            data-testid="builder-props-reader-skip-rows"
          />
        )}
        {has('comment_prefix') && (
          <TextInput
            label="Comment prefix"
            description="Lines starting with it are skipped"
            placeholder="#"
            value={r.comment_prefix ?? ''}
            onChange={(e) => set({ comment_prefix: e.currentTarget.value })}
            styles={MONO}
          />
        )}
        {has('quote_char') && (
          <TextInput
            label="Quote character"
            placeholder={'"'}
            maxLength={1}
            value={r.quote_char ?? ''}
            onChange={(e) => set({ quote_char: e.currentTarget.value })}
            styles={MONO}
          />
        )}
      </Group>
      {has('null_values') && (
        <TagsInput
          label="Null values"
          description="Values read as missing (Enter to add)"
          placeholder="NA, ., -"
          value={r.null_values ?? []}
          onChange={(null_values) => set({ null_values })}
          data-testid="builder-props-reader-null-values"
        />
      )}
    </FoldSection>
  );
};

/** An optional description per column; the columns come from the preview. */
export const ColumnsDescription: React.FC<{
  columns: string[];
  value: Record<string, string> | undefined;
  onChange: (value: Record<string, string>) => void;
}> = ({ columns, value, onChange }) => {
  const described = value ?? {};
  return (
    <FoldSection
      label="Describe the columns"
      description="a note per column, shown in dashboards"
      initiallyOpen={Object.keys(described).length > 0}
    >
      {columns.length === 0 ? (
        <Text size="xs" c="dimmed">
          The columns show here once the file preview has read them.
        </Text>
      ) : (
        <ScrollArea.Autosize mah={240} type="auto" offsetScrollbars>
          <Stack gap={4}>
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
                  onChange(next);
                }}
              />
            ))}
          </Stack>
        </ScrollArea.Autosize>
      )}
    </FoldSection>
  );
};

/** A column picked among the previewed ones, typed in when there are none. */
export const ColumnField: React.FC<{
  label: string;
  description?: string;
  value: string | null | undefined;
  columns: string[];
  placeholder?: string;
  required?: boolean;
  clearable?: boolean;
  error?: string;
  testId?: string;
  onChange: (value: string | null) => void;
}> = ({ label, description, value, columns, placeholder, required, clearable = true, error, testId, onChange }) => {
  const current = value ?? '';
  const shownError = error ?? (required && !current.trim() ? 'Required' : undefined);
  if (columns.length === 0) {
    return (
      <TextInput
        label={label}
        description={description}
        placeholder={placeholder}
        value={current}
        onChange={(e) => onChange(e.currentTarget.value)}
        error={shownError}
        withAsterisk={required}
        spellCheck={false}
        data-testid={testId}
      />
    );
  }
  const data = !current || columns.includes(current) ? columns : [current, ...columns];
  return (
    <Select
      label={label}
      description={description}
      placeholder={placeholder ?? 'Pick a column'}
      value={current || null}
      data={data}
      searchable
      clearable={clearable && !required}
      withAsterisk={required}
      onChange={(v) => onChange(v)}
      error={shownError}
      data-testid={testId}
    />
  );
};
