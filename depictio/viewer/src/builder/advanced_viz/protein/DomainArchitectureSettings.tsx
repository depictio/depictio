/**
 * `domain_architecture` settings: one row per protein, or proteins grouped by
 * their architecture. The hits are the bound collection itself, so there is no
 * companion collection to pick; its columns (the HMM span and length, the
 * coverage, the E-value, the source...) are bound in the column mapping above.
 * What is left here is how the tile draws and filters them, and where a
 * domain pick lands on the other tables.
 */
import React, { useEffect, useState } from 'react';
import {
  Group,
  NumberInput,
  SegmentedControl,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
} from '@mantine/core';
import { fetchUniqueValues } from 'depictio-react-core';
import { str, type ProteinKindSettingsProps } from './common';

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** DomainArchitectureConfig's defaults for the fields below that do not take
 *  null. A cleared input writes the default back: unsetting a saved key
 *  writes null (`patchOverrides` in configBlob.ts), which the model refuses. */
const DEFAULT_PARTIAL_COVERAGE = 0.9;
const DEFAULT_MAX_ARCHITECTURES = 15;
const DEFAULT_MAX_PROTEINS = 2000;
const DEFAULT_POSITION_COLUMN = 'position';

/** The values of the bound table's source column, as suggestions for the
 *  source filter (none when the column is missing). */
function useSourceValues(dcId: string | null, column: string | null): string[] {
  const [values, setValues] = useState<string[]>([]);
  useEffect(() => {
    if (!dcId || !column) {
      setValues([]);
      return;
    }
    let cancelled = false;
    fetchUniqueValues(dcId, column)
      .then((v) => {
        if (!cancelled) setValues(v.map(String).filter(Boolean).sort());
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

/** An E-value typed as people write them (`1e-5`, `0.001`); empty clears. */
const EvalueInput: React.FC<{
  value: number | null;
  onChange: (v: number | null) => void;
}> = ({ value, onChange }) => {
  const [text, setText] = useState(value == null ? '' : String(value));
  useEffect(() => {
    setText(value == null ? '' : String(value));
  }, [value]);
  const parsed = text.trim() === '' ? null : Number(text);
  const invalid = parsed != null && !(Number.isFinite(parsed) && parsed > 0);
  return (
    <TextInput
      label="E-value threshold"
      description="Draw only the domains at or below it; empty draws every hit"
      placeholder="Any (for example 1e-5)"
      value={text}
      onChange={(e) => setText(e.currentTarget.value)}
      onBlur={() => {
        if (!invalid) onChange(parsed);
      }}
      error={invalid ? 'A positive number' : undefined}
      size="xs"
    />
  );
};

const DomainArchitectureSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  boundDcId,
}) => {
  const view = str(config?.view) ?? 'proteins';
  const sourceColumn = config?.source_col === null ? null : (str(config?.source_col) ?? 'source');
  const sourceValues = useSourceValues(boundDcId, sourceColumn);
  const sources = Array.isArray(config?.sources) ? (config?.sources as unknown[]).map(String) : [];

  return (
    <>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          View
        </Text>
        <SegmentedControl
          data={[
            { value: 'proteins', label: 'Proteins' },
            { value: 'architectures', label: 'Architectures' },
          ]}
          value={view}
          onChange={(v) => onChange({ view: v })}
          fullWidth
          size="xs"
        />
        <Text size="xs" c="dimmed">
          {view === 'architectures'
            ? 'Proteins grouped by their ordered domain labels, the most frequent first, each drawn with its median-length protein and a count.'
            : 'One row per protein: a backbone of its length, its domains in their colours, overlapping hits in sub-lanes.'}
        </Text>
      </Stack>

      <Group grow gap="xs" align="flex-start">
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Scale
          </Text>
          <SegmentedControl
            data={[
              { value: 'shared', label: 'Shared' },
              { value: 'per_protein', label: 'Per protein' },
            ]}
            value={str(config?.scale) ?? 'shared'}
            onChange={(v) => onChange({ scale: v })}
            fullWidth
            size="xs"
          />
        </Stack>
        <Stack gap={4}>
          <Text size="xs" fw={500}>
            Colour by
          </Text>
          <SegmentedControl
            data={[
              { value: 'label', label: 'Domain' },
              { value: 'source', label: 'Source' },
            ]}
            value={str(config?.color_by) ?? 'label'}
            onChange={(v) => onChange({ color_by: v })}
            fullWidth
            size="xs"
          />
        </Stack>
      </Group>

      <Group grow gap="xs" align="flex-start">
        <EvalueInput
          value={num(config?.evalue_threshold)}
          onChange={(v) => onChange({ evalue_threshold: v })}
        />
        <NumberInput
          label="Partial below coverage"
          description="Without HMM states, a lower coverage is drawn partial"
          value={num(config?.partial_coverage) ?? DEFAULT_PARTIAL_COVERAGE}
          onChange={(v) =>
            onChange({ partial_coverage: typeof v === 'number' ? v : DEFAULT_PARTIAL_COVERAGE })
          }
          min={0}
          max={1}
          step={0.05}
          decimalScale={2}
          size="xs"
        />
      </Group>

      <TagsInput
        label="Sources"
        description="Annotation databases to keep (Pfam, SMART...); empty keeps them all"
        data={sourceValues}
        value={sources}
        onChange={(v) => onChange({ sources: v.length ? v : null })}
        placeholder={sources.length ? undefined : 'All sources'}
        clearable
        size="xs"
      />

      <Group grow gap="xs" align="flex-start">
        <NumberInput
          label="Architectures"
          description="Most frequent ones drawn"
          value={num(config?.max_architectures) ?? DEFAULT_MAX_ARCHITECTURES}
          onChange={(v) =>
            onChange({ max_architectures: typeof v === 'number' ? v : DEFAULT_MAX_ARCHITECTURES })
          }
          min={1}
          max={100}
          allowDecimal={false}
          size="xs"
        />
        <NumberInput
          label="Max proteins"
          description="Rows drawn at most"
          value={num(config?.max_proteins) ?? DEFAULT_MAX_PROTEINS}
          onChange={(v) =>
            onChange({ max_proteins: typeof v === 'number' ? v : DEFAULT_MAX_PROTEINS })
          }
          min={1}
          max={20000}
          allowDecimal={false}
          size="xs"
        />
      </Group>

      <Stack gap={6}>
        <TextInput
          label="Position column of the pick"
          description="A domain click picks its span on this column (with the entity column) of the residue tables"
          value={str(config?.position_col_for_selection) ?? DEFAULT_POSITION_COLUMN}
          onChange={(e) =>
            onChange({ position_col_for_selection: e.currentTarget.value || DEFAULT_POSITION_COLUMN })
          }
          size="xs"
        />
        <Switch
          label="A domain click also selects its label"
          checked={config?.label_selection !== false}
          onChange={(e) => onChange({ label_selection: e.currentTarget.checked })}
          size="xs"
        />
      </Stack>
    </>
  );
};

export default DomainArchitectureSettings;
