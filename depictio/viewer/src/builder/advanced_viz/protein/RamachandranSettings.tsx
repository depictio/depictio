/**
 * `ramachandran` settings: phi and psi come from the backbone of the structure,
 * so the tile finds its structure exactly as molecule_3d does (a file per
 * entity, or a model resolved from an accession, a gene or a sequence).
 */
import React from 'react';
import StructureSourceSettings from './StructureSourceSettings';
import type { ProteinKindSettingsProps } from './common';

const RamachandranSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  workflows,
  loading,
}) => (
  <StructureSourceSettings
    config={config}
    onChange={onChange}
    workflows={workflows}
    loading={loading}
  />
);

export default RamachandranSettings;
