/**
 * Shared column-picker primitive for builder forms. Reads the resolved column
 * list from the builder store; optionally filters by column type. Mirrors the
 * `dmc.Select` used across all Dash design forms.
 */
import React, { useMemo } from 'react';
import { Select } from '@mantine/core';
import { Icon } from '@iconify/react';
import { useBuilderStore } from '../store/useBuilderStore';

export interface ColumnSelectProps {
  label: string;
  placeholder?: string;
  value: string | undefined | null;
  onChange: (val: string | null, type: string | null) => void;
  /** Filter to numeric-only columns (e.g. for size/lat/lon). */
  numericOnly?: boolean;
  /** Filter to categorical columns. */
  categoricalOnly?: boolean;
  required?: boolean;
  clearable?: boolean;
  searchable?: boolean;
  description?: string;
  disabled?: boolean;
}

const NUMERIC_TYPES = new Set([
  'int64',
  'int32',
  'float64',
  'float32',
  'number',
  'numeric',
]);

const CATEGORICAL_TYPES = new Set([
  'object',
  'string',
  'category',
  'bool',
]);

const ColumnSelect: React.FC<ColumnSelectProps> = ({
  label,
  placeholder,
  value,
  onChange,
  numericOnly,
  categoricalOnly,
  required,
  clearable = true,
  searchable = true,
  description,
  disabled,
}) => {
  const cols = useBuilderStore((s) => s.cols);
  const data = useMemo(() => {
    return cols
      .filter((c) => {
        if (numericOnly) return NUMERIC_TYPES.has(c.type);
        if (categoricalOnly) return CATEGORICAL_TYPES.has(c.type);
        return true;
      })
      .map((c) => ({ value: c.name, label: `${c.name} (${c.type})` }));
  }, [cols, numericOnly, categoricalOnly]);

  return (
    <Select
      label={label}
      description={description}
      placeholder={placeholder ?? 'Pick a column'}
      data={data}
      value={value ?? null}
      onChange={(val) => {
        const c = cols.find((c) => c.name === val);
        onChange(val, c?.type ?? null);
      }}
      searchable={searchable}
      clearable={clearable}
      required={required}
      disabled={disabled}
      leftSection={<Icon icon="mdi:table-column" width={14} />}
    />
  );
};

export default ColumnSelect;
