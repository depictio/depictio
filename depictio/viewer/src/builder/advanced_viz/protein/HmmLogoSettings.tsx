/**
 * `hmm_logo` settings: where the logo comes from (a profile HMM's long table or
 * an alignment) and the optional hits table drawn as a coverage lane under it.
 *
 * The source switch also decides which roles the binding table asks for (see
 * `kindModes.ts`), so flipping it here changes the required columns above.
 */
import React, { useMemo } from 'react';
import { Group, SegmentedControl, Stack, Text } from '@mantine/core';
import { companionOptions } from '../proteinBindings';
import {
  ColumnPicker,
  CompanionPicker,
  str,
  useDcColumns,
  type ProteinKindSettingsProps,
} from './common';

const HmmLogoSettings: React.FC<ProteinKindSettingsProps> = ({
  config,
  onChange,
  workflows,
  loading,
  boundDcId,
}) => {
  const hitsOptions = useMemo(
    () => companionOptions(workflows ?? [], 'hits', boundDcId),
    [workflows, boundDcId],
  );
  const hitsColumns = useDcColumns(str(config?.hits_dc_id));
  const profileSource = str(config?.profile_source) ?? 'hmm';

  return (
    <>
      <Stack gap={4}>
        <Text size="sm" fw={500}>
          Profile source
        </Text>
        <SegmentedControl
          data={[
            { value: 'hmm', label: 'Profile HMM' },
            { value: 'msa', label: 'Alignment (MSA)' },
          ]}
          value={profileSource}
          onChange={(v) => onChange({ profile_source: v })}
          fullWidth
          size="xs"
        />
        <Text size="xs" c="dimmed">
          {profileSource === 'msa'
            ? 'The logo is computed from an alignment table: bind its id, sequence id and aligned sequence.'
            : 'The logo is drawn from the long emission table of a parsed profile HMM.'}
        </Text>
      </Stack>
      <CompanionPicker
        label="Hits"
        description="Optional domain-hit table (model, entity, HMM start and end) drawn as a coverage lane under the logo"
        base="hits"
        options={hitsOptions}
        config={config}
        onChange={onChange}
        loading={loading}
        emptyMessage="No other table in this project"
      />
      {config?.hits_dc_id ? (
        <Group grow gap="xs">
          <ColumnPicker label="Model" field="hits_model_col" fallback="label" columns={hitsColumns} config={config} onChange={onChange} />
          <ColumnPicker label="Entity" field="hits_entity_col" fallback="entity" columns={hitsColumns} config={config} onChange={onChange} />
          <ColumnPicker label="HMM from" field="hits_from_col" fallback="hmm_from" columns={hitsColumns} config={config} onChange={onChange} />
          <ColumnPicker label="HMM to" field="hits_to_col" fallback="hmm_to" columns={hitsColumns} config={config} onChange={onChange} />
        </Group>
      ) : null}
    </>
  );
};

export default HmmLogoSettings;
