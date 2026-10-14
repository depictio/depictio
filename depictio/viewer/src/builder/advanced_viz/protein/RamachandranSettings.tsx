/**
 * `ramachandran` settings: phi and psi come from the backbone of the structure,
 * so the tile finds its structure exactly as molecule_3d does (a file per
 * entity, or a model resolved from an accession, a gene or a sequence), then
 * how the points are coloured, whether the approximate favoured regions are
 * drawn, which residue classes are plotted and how large the markers are.
 *
 * The value, category and chain columns go through the role mapping above (the
 * colour modes that read them are greyed out until they are bound).
 */
import React from 'react';
import { MultiSelect, NumberInput, Select, Stack, Switch, Text } from '@mantine/core';
import { str, type ProteinKindSettingsProps } from './common';
import StructureSourceSettings from './StructureSourceSettings';

const COLOUR_MODES: { value: string; label: string; needs?: 'value' | 'category' | 'chain' }[] = [
  { value: 'plddt', label: 'pLDDT (confidence bands)' },
  { value: 'residue_class', label: 'Residue class' },
  { value: 'secondary_structure', label: 'Secondary structure' },
  { value: 'value', label: 'Value column', needs: 'value' },
  { value: 'category', label: 'Category column', needs: 'category' },
  { value: 'chain', label: 'Chain' },
];

const RESIDUE_CLASSES: { value: string; label: string }[] = [
  { value: 'general', label: 'General' },
  { value: 'glycine', label: 'Glycine' },
  { value: 'proline', label: 'Proline' },
  { value: 'pre_proline', label: 'Pre-proline' },
];

/** RamachandranConfig's `marker_size` default. The field takes no null, so a
 *  cleared input writes it back rather than unsetting the key (which nulls a
 *  saved value, and the save is refused). */
const DEFAULT_MARKER_SIZE = 6;

const RamachandranSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  workflows,
  loading,
}) => {
  // `config` carries the role bindings (the role table's included), so a column
  // counts as bound the moment it is bound, saved or not.
  const bound = (role: 'value' | 'category' | 'chain'): boolean =>
    str(config?.[`${role}_col`]) !== null;

  const colourMode = str(config?.color_mode) ?? 'plddt';
  const classes = Array.isArray(config?.residue_classes)
    ? (config.residue_classes as string[])
    : RESIDUE_CLASSES.map((c) => c.value);
  const markerSize =
    typeof config?.marker_size === 'number' ? config.marker_size : DEFAULT_MARKER_SIZE;
  const showRegions = config?.show_regions !== false;

  const missing = COLOUR_MODES.find((m) => m.value === colourMode && m.needs && !bound(m.needs));

  return (
    <>
      <StructureSourceSettings
        config={config}
        onChange={onChange}
        workflows={workflows}
        loading={loading}
      />
      <Stack gap={4}>
        <Select
          label="Colour points by"
          description="pLDDT reads the structure's B-factor column. Secondary structure uses the category column when it holds helix and strand states, else the phi/psi regions."
          data={COLOUR_MODES.map((m) => ({
            value: m.value,
            label: m.label,
            disabled: m.needs !== undefined && !bound(m.needs),
          }))}
          value={colourMode}
          onChange={(v) => v && onChange({ color_mode: v })}
          allowDeselect={false}
          size="xs"
        />
        {missing ? (
          <Text size="xs" c="orange">
            Bind a {missing.needs} column in the role mapping above to colour by it.
          </Text>
        ) : (
          <Text size="xs" c="dimmed">
            The value, category and chain columns are bound in the role mapping above; the
            entity column lists the proteins to pick.
          </Text>
        )}
      </Stack>
      <Switch
        label="Draw the approximate favoured regions"
        description="Hand-drawn from textbook boundaries and labelled as approximate regions, not MolProbity contours. Glycine and proline get their own when the plot is filtered to them."
        checked={showRegions}
        onChange={(e) => onChange({ show_regions: e.currentTarget.checked })}
        size="xs"
      />
      <MultiSelect
        label="Residue classes"
        description="Glycine, proline and pre-proline residues have their own marker symbols. All four are plotted unless you narrow them."
        data={RESIDUE_CLASSES}
        value={classes}
        onChange={(v) =>
          // Nothing selected is not a plot, and all four is the unfiltered default.
          onChange({
            residue_classes: v.length === 0 || v.length === RESIDUE_CLASSES.length ? undefined : v,
          })
        }
        size="xs"
      />
      <NumberInput
        label="Marker size"
        description="Point diameter in pixels"
        value={markerSize}
        onChange={(v) => onChange({ marker_size: typeof v === 'number' ? v : DEFAULT_MARKER_SIZE })}
        min={2}
        max={20}
        allowDecimal={false}
        size="xs"
      />
    </>
  );
};

export default RamachandranSettings;
