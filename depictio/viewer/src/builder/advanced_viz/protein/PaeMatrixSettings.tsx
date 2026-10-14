/**
 * `pae_matrix` settings: the collection of predicted-aligned-error files, the
 * residue table's pLDDT and chain columns, how a drag selects, and the colour
 * scale.
 *
 * The bound collection is the residue table; the matrix itself is one file
 * per entity (`indexed_file`, format `pae`), fetched by the browser like a
 * structure file, and its sample id must equal the entity. The table numbers
 * the matrix axes: the entity's residues, positions ascending, chains
 * concatenated in table order when a chain column is bound. When its residue
 * count differs from the matrix the tile numbers the axes 1 to N instead.
 *
 * The pLDDT and chain pickers write the `value` and `chain` roles, the same
 * bindings the role table above shows, so the two never disagree.
 */
import React, { useMemo } from 'react';
import { Group, NumberInput, SegmentedControl, Select, Stack, Switch, Text } from '@mantine/core';
import { useBuilderStore } from '../../store/useBuilderStore';
import { companionOptions } from '../proteinBindings';
import { CompanionPicker, str, useDcColumns, type ProteinKindSettingsProps } from './common';

/** `ColourScale` in depictio/models/components/advanced_viz/configs.py (and
 *  `COLOUR_SCALES` in react-core's colourScales.ts, not exported by the
 *  package index), same names, same order. */
const COLOUR_SCALES = ['Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis', 'RdBu', 'Spectral'];
const THEME_RAMP = 'theme';

type ColumnMapping = Record<string, string | string[]>;

/** One role of the binding table, read and written in the builder store. */
function useRoleBinding(role: string): [string | null, (column: string | null) => void] {
  // A primitive out of the selector: a fresh object per call would re-render
  // on every store write.
  const value = useBuilderStore((s) => {
    const bound = (s.config as { column_mapping?: ColumnMapping }).column_mapping?.[role];
    return typeof bound === 'string' && bound ? bound : null;
  });
  const patchConfig = useBuilderStore((s) => s.patchConfig);
  const set = (column: string | null) => {
    // Read through getState(): the subscribed mapping can be a render behind.
    const current =
      (useBuilderStore.getState().config as { column_mapping?: ColumnMapping }).column_mapping ?? {};
    const next: ColumnMapping = { ...current };
    if (column) next[role] = column;
    else delete next[role];
    patchConfig({ column_mapping: next });
  };
  return [value, set];
}

const PaeMatrixSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  workflows,
  loading,
  boundDcId,
}) => {
  const paeOptions = useMemo(() => companionOptions(workflows ?? [], 'pae'), [workflows]);
  const columns = useDcColumns(boundDcId);
  const [valueColumn, setValueColumn] = useRoleBinding('value');
  const [chainColumn, setChainColumn] = useRoleBinding('chain');
  const columnData = (current: string | null) =>
    current && !columns.includes(current) ? [current, ...columns] : columns;

  const brush = str(config?.brush) ?? 'diagonal';
  const colourScale = str(config?.colour_scale) ?? THEME_RAMP;
  const maxPae = typeof config?.max_pae === 'number' ? config.max_pae : '';
  const showPlddt = config?.show_plddt !== false;

  return (
    <>
      <CompanionPicker
        label="PAE files"
        description="An indexed-file collection of predicted-aligned-error files (format pae), one per entity. The entity the dashboard filters on is the one shown."
        base="pae"
        options={paeOptions}
        config={config}
        onChange={onChange}
        loading={loading}
        emptyMessage="No PAE collection (indexed file, format pae) in this project"
      />

      <Group grow gap="xs" align="flex-start">
        <Select
          label="pLDDT column"
          description="Per-residue confidence, drawn as strips along both axes"
          data={columnData(valueColumn)}
          value={valueColumn}
          onChange={(v) => setValueColumn(v)}
          placeholder="None"
          clearable
          searchable
          size="xs"
        />
        <Select
          label="Chain column"
          description="On a complex: chains concatenated in table order, boundaries marked"
          data={columnData(chainColumn)}
          value={chainColumn}
          onChange={(v) => setChainColumn(v)}
          placeholder="None"
          clearable
          searchable
          size="xs"
        />
      </Group>
      <Switch
        label="Draw the pLDDT strips along the axes"
        checked={showPlddt}
        disabled={!valueColumn}
        onChange={(e) => onChange({ show_plddt: e.currentTarget.checked })}
        size="xs"
      />

      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Brush
        </Text>
        <SegmentedControl
          data={[
            { value: 'diagonal', label: 'Diagonal (a domain)' },
            { value: 'rectangle', label: 'Rectangle' },
          ]}
          value={brush}
          onChange={(v) => onChange({ brush: v })}
          fullWidth
          size="xs"
        />
        <Text size="xs" c="dimmed">
          {brush === 'diagonal'
            ? 'A drag selects the square block on the diagonal it covers and picks its residues. Shift-drag works as a rectangle.'
            : 'A drag picks the scored residues (x) of any block; the aligned residues (y) stay outlined in the tile.'}
        </Text>
      </Stack>

      <Group grow gap="xs" align="flex-start">
        <Select
          label="Colour scale"
          data={[
            { value: THEME_RAMP, label: 'AlphaFold (theme)' },
            ...COLOUR_SCALES.map((s) => ({ value: s, label: s })),
          ]}
          value={colourScale}
          onChange={(v) => onChange({ colour_scale: !v || v === THEME_RAMP ? undefined : v })}
          allowDeselect={false}
          size="xs"
        />
        <NumberInput
          label="Colour maximum (Å)"
          placeholder="File maximum"
          value={maxPae}
          onChange={(v) =>
            onChange({ max_pae: typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : undefined })
          }
          min={0.5}
          step={0.5}
          decimalScale={2}
          size="xs"
        />
      </Group>
    </>
  );
};

export default PaeMatrixSettings;
