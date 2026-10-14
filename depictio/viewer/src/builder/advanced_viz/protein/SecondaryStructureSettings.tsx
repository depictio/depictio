/**
 * `secondary_structure` settings: which lanes the view draws. The columns come
 * from the role mapping and the tile reads a single per-residue table, so there
 * is no companion collection to pick.
 */
import React from 'react';
import { Stack, Switch } from '@mantine/core';
import type { ProteinKindSettingsProps } from './common';

const LANES: { field: string; label: string }[] = [
  { field: 'show_probabilities', label: 'Probability lanes (P of helix, strand and coil)' },
  { field: 'show_agreement', label: 'Agreement lane when several sources are compared' },
  { field: 'show_segments', label: 'Segment list' },
  { field: 'show_composition', label: 'Composition percentages' },
];

const SecondaryStructureSettings: React.FC<ProteinKindSettingsProps> = ({ config, onChange }) => (
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
);

export default SecondaryStructureSettings;
