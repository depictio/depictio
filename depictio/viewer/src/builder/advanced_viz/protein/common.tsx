/**
 * What the protein kinds' settings panels share: the props each per-kind panel
 * receives, the companion-collection and column pickers, and the hook that
 * lists a companion table's columns.
 *
 * Kept apart from `ProteinBindingSettings.tsx` (which dispatches to the panels)
 * so a panel imports its helpers without importing the module that imports it.
 */
import React, { useEffect, useState } from 'react';
import { Select } from '@mantine/core';
import { fetchSpecs } from 'depictio-react-core';
import type { WorkflowEntry } from 'depictio-react-core';
import {
  type CompanionBase,
  type CompanionOption,
  companionPatch,
  specColumns,
} from '../proteinBindings';

/** What `ProteinBindingSettings` hands every per-kind panel. */
export interface ProteinKindSettingsProps {
  /** The config the tile renders with (saved or catalog blob plus overrides). */
  config: Record<string, unknown> | null;
  /** Writes config fields; `undefined` drops a key the saved config never had. */
  onChange: (patch: Record<string, unknown>) => void;
  /** The project's workflows, null while they load (or when they failed to). */
  workflows: readonly WorkflowEntry[] | null;
  loading: boolean;
  /** The tile's own bound collection, which is never its own companion. */
  boundDcId: string | null;
}

export const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** Columns of one companion DC, for its column pickers. */
export function useDcColumns(dcId: string | null): string[] {
  const [columns, setColumns] = useState<string[]>([]);
  useEffect(() => {
    if (!dcId) {
      setColumns([]);
      return;
    }
    let cancelled = false;
    fetchSpecs(dcId)
      .then((specs) => {
        if (!cancelled) setColumns(specColumns(specs));
      })
      .catch(() => {
        if (!cancelled) setColumns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);
  return columns;
}

export const CompanionPicker: React.FC<{
  label: string;
  description: string;
  base: CompanionBase;
  options: CompanionOption[];
  config: Record<string, unknown> | null;
  onChange: (patch: Record<string, unknown>) => void;
  loading: boolean;
  emptyMessage: string;
}> = ({ label, description, base, options, config, onChange, loading, emptyMessage }) => {
  const current = str(config?.[`${base}_dc_id`]);
  const tag = str(config?.[`${base}_dc_tag`]);
  return (
    <Select
      label={label}
      description={description}
      placeholder={loading ? 'Loading collections…' : tag ? `Template tag: ${tag}` : 'None'}
      data={options.map((o) => ({ value: o.value, label: o.label }))}
      value={current && options.some((o) => o.value === current) ? current : null}
      onChange={(v) => onChange(companionPatch(base, v, options))}
      clearable
      searchable
      nothingFoundMessage={emptyMessage}
    />
  );
};

export const ColumnPicker: React.FC<{
  label: string;
  field: string;
  fallback: string;
  columns: string[];
  config: Record<string, unknown> | null;
  onChange: (patch: Record<string, unknown>) => void;
}> = ({ label, field, fallback, columns, config, onChange }) => {
  const value = str(config?.[field]) ?? fallback;
  const data = columns.includes(value) || !value ? columns : [value, ...columns];
  return (
    <Select
      label={label}
      data={data}
      value={value || null}
      onChange={(v) => onChange({ [field]: v ?? undefined })}
      searchable
      size="xs"
    />
  );
};
