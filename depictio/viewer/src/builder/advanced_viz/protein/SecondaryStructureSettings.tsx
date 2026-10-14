/**
 * `secondary_structure` settings: what the role mapping above cannot say.
 *
 * The state, residue, source, probability and confidence columns are mapped in
 * the binding table; here they can also be re-pointed or unbound (a probability
 * column the table does not have), and the one value a column cannot be
 * mapped to is chosen: which source the others are compared with. The four
 * switches decide which lanes the tile draws. The tile reads a single
 * per-residue table, so there is no companion collection to pick.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Group, Select, Stack, Switch, Text } from '@mantine/core';
import { fetchUniqueValues } from 'depictio-react-core';
import { str, useDcColumns, type ProteinKindSettingsProps } from './common';

const LANES: { field: string; label: string }[] = [
  { field: 'show_probabilities', label: 'Probability lanes (P of helix, strand and coil)' },
  { field: 'show_agreement', label: 'Agreement lane when several sources are compared' },
  { field: 'show_segments', label: 'Segment list' },
  { field: 'show_composition', label: 'Composition percentages' },
];

/** Most source names offered for the reference; a source column has a handful. */
const MAX_SOURCES = 200;

/** Distinct values of one column of the bound collection, [] while unknown. */
function useUniqueValues(dcId: string | null, column: string | null): string[] {
  const [values, setValues] = useState<string[]>([]);
  useEffect(() => {
    if (!dcId || !column) {
      setValues([]);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(dcId, column)
      .then((v) => {
        if (!cancelled) setValues(v.filter((x) => x != null && x !== '').map(String).slice(0, MAX_SOURCES));
      })
      .catch(() => {
        if (!cancelled) setValues([]);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId, column]);
  return values;
}

/**
 * A column picker that can also say "none": clearing it writes `null` (the
 * column is unbound), which is not the same as leaving the key out (the
 * model's default name). `fallback` is the column the tile reads when the key
 * is absent, shown only when the table has it.
 */
const OptionalColumn: React.FC<{
  label: string;
  field: string;
  fallback: string | null;
  columns: string[];
  config: Record<string, unknown> | null;
  onChange: (patch: Record<string, unknown>) => void;
  description?: string;
}> = ({ label, field, fallback, columns, config, onChange, description }) => {
  const raw = config?.[field];
  const useFallback = fallback != null && (columns.length === 0 || columns.includes(fallback));
  const value = raw === undefined ? (useFallback ? fallback : null) : str(raw);
  const data = value && !columns.includes(value) ? [value, ...columns] : columns;
  return (
    <Select
      label={label}
      description={description}
      data={data}
      value={value}
      onChange={(v) => onChange({ [field]: v })}
      placeholder="None"
      nothingFoundMessage="No such column"
      clearable
      searchable
      size="xs"
    />
  );
};

const SecondaryStructureSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  boundDcId,
}) => {
  const columns = useDcColumns(boundDcId);
  const sourceCol = str(config?.source_col);
  const reference = str(config?.reference_source);
  const sources = useUniqueValues(boundDcId, sourceCol);
  const referenceData = useMemo(
    () => (reference && !sources.includes(reference) ? [reference, ...sources] : sources),
    [sources, reference],
  );

  return (
    <Stack gap="xs">
      <Group grow gap="xs" align="flex-start">
        <OptionalColumn
          label="Source column"
          description="One ribbon per value, compared in the agreement lane"
          field="source_col"
          fallback={null}
          columns={columns}
          config={config}
          // The reference names a value of this column: it goes with it.
          onChange={(patch) => onChange(patch.source_col == null ? { ...patch, reference_source: null } : patch)}
        />
        <Select
          label="Reference source"
          description="The others are compared with it; the first source when unset"
          data={referenceData}
          value={reference}
          onChange={(v) => onChange({ reference_source: v })}
          placeholder={sourceCol ? 'First source' : 'Needs a source column'}
          disabled={!sourceCol}
          nothingFoundMessage="No such source"
          clearable
          searchable
          size="xs"
        />
      </Group>
      <Group grow gap="xs" align="flex-start">
        <OptionalColumn label="P(helix)" field="p_helix_col" fallback="p_helix" columns={columns} config={config} onChange={onChange} />
        <OptionalColumn label="P(strand)" field="p_strand_col" fallback="p_strand" columns={columns} config={config} onChange={onChange} />
        <OptionalColumn label="P(coil)" field="p_coil_col" fallback="p_coil" columns={columns} config={config} onChange={onChange} />
      </Group>
      <OptionalColumn
        label="Confidence column"
        description="Shades each residue from 0 to 1 (a 0 to 100 score is rescaled); the largest probability when unset"
        field="confidence_col"
        fallback={null}
        columns={columns}
        config={config}
        onChange={onChange}
      />
      <Stack gap={6}>
        {LANES.map(({ field, label }) => (
          <Switch
            key={field}
            label={label}
            checked={config?.[field] !== false}
            onChange={(e) => onChange({ [field]: e.currentTarget.checked })}
            size="xs"
          />
        ))}
      </Stack>
      <Text size="xs" c="dimmed">
        The probability lanes need at least one probability column; the agreement lane needs two sources.
      </Text>
    </Stack>
  );
};

export default SecondaryStructureSettings;
