/**
 * Where a tile finds its structure: a pdb or mmcif file per entity in an
 * indexed-file collection, or a model resolved from a UniProt accession, a gene
 * symbol or a sequence.
 *
 * Shared by the kinds that read a structure (molecule_3d, ramachandran): both
 * take the same `structure_*` fields and the same resolve inputs, so the pick
 * is one component rather than a copy per kind.
 */
import React, { useMemo } from 'react';
import { NumberInput, SegmentedControl, Stack, Text } from '@mantine/core';
import { companionOptions } from '../proteinBindings';
import { CompanionPicker, type ProteinKindSettingsProps } from './common';

const StructureSourceSettings: React.FC<
  Pick<ProteinKindSettingsProps, 'config' | 'onChange' | 'workflows' | 'loading'>
> = ({ config, onChange, workflows, loading }) => {
  const structureOptions = useMemo(
    () => companionOptions(workflows ?? [], 'structure'),
    [workflows],
  );
  const structureSource =
    typeof config?.structure_source === 'string' && config.structure_source
      ? config.structure_source
      : 'file';

  return (
    <>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Structure source
        </Text>
        <SegmentedControl
          data={[
            { value: 'file', label: 'Structure files' },
            { value: 'resolve', label: 'Predicted (resolved)' },
          ]}
          value={structureSource}
          onChange={(v) => onChange({ structure_source: v })}
          fullWidth
          size="xs"
        />
      </Stack>
      {structureSource === 'file' ? (
        <CompanionPicker
          label="Structure files"
          description="An indexed-file collection of pdb or mmcif files, one per entity. The entity the dashboard filters on is the one shown."
          base="structure"
          options={structureOptions}
          config={config}
          onChange={onChange}
          loading={loading}
          emptyMessage="No pdb or mmcif collection in this project"
        />
      ) : (
        <>
          <Text size="xs" c="dimmed">
            Bind a UniProt, gene or sequence column in the role mapping above: the structure is
            fetched from the AlphaFold database, or folded from the sequence when no accession
            resolves.
          </Text>
          <NumberInput
            label="Taxon"
            description="NCBI taxonomy id used to resolve gene symbols"
            value={typeof config?.taxon === 'number' ? config.taxon : 9606}
            onChange={(v) => onChange({ taxon: typeof v === 'number' ? v : undefined })}
            min={1}
            size="xs"
          />
        </>
      )}
    </>
  );
};

export default StructureSourceSettings;
