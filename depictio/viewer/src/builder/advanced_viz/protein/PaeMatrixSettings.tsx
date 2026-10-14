/**
 * `pae_matrix` settings: the collection of predicted-aligned-error files. The
 * bound collection is the residue table; the matrix itself is one file per
 * entity (`indexed_file`, format `pae`), fetched by the browser like a
 * structure file, and its sample id must equal the entity.
 */
import React, { useMemo } from 'react';
import { companionOptions } from '../proteinBindings';
import { CompanionPicker, type ProteinKindSettingsProps } from './common';

const PaeMatrixSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  workflows,
  loading,
}) => {
  const paeOptions = useMemo(() => companionOptions(workflows ?? [], 'pae'), [workflows]);
  return (
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
  );
};

export default PaeMatrixSettings;
