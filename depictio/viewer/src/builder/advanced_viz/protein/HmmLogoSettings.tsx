/**
 * `hmm_logo` settings: where the logo comes from (a profile HMM's long table or
 * an alignment), how its letters are sized and coloured, which rows sit under
 * it, and the optional hits table drawn as a coverage lane.
 *
 * The source switch also decides which roles the binding table asks for (see
 * `kindModes.ts`), so flipping it here changes the required columns above.
 * The height mode, colour scheme, row switches and hit limits are also tile
 * controls; what is set here is what the tile opens with.
 */
import React, { useMemo } from 'react';
import { Group, NumberInput, SegmentedControl, Select, Stack, Switch, Text } from '@mantine/core';
import { companionOptions } from '../proteinBindings';
import {
  ColumnPicker,
  CompanionPicker,
  str,
  useDcColumns,
  type ProteinKindSettingsProps,
} from './common';

const HEIGHT_MODES = [
  { value: 'relent_abovebg', label: 'Relative entropy, letters above background (hmmlogo --height_relent_abovebg)' },
  { value: 'relent_all', label: 'Relative entropy, every letter (hmmlogo default)' },
  { value: 'probability', label: 'Emission probability (stacks of 1)' },
];

const COLOUR_SCHEMES = [
  { value: 'clustal', label: 'Clustal X' },
  { value: 'zappo', label: 'Zappo' },
  { value: 'hydrophobicity', label: 'Hydrophobicity' },
  { value: 'identity', label: 'Percent identity' },
  { value: 'none', label: 'None' },
];

const DEFAULT_EVALUE_MAX = 0.01;
const EVALUE_PRESETS = [1, 0.1, 0.01, 1e-3, 1e-5, 1e-10, 1e-20];

const evalueLabel = (v: number): string => (v < 0.001 ? v.toExponential(0) : String(v));

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
  const heightMode = str(config?.height_mode) ?? 'relent_abovebg';
  const colourScheme = str(config?.color_scheme) ?? 'clustal';
  // `null` is "every hit"; a missing key is the model's default.
  const evalueMax =
    config?.hits_evalue_max === null
      ? null
      : typeof config?.hits_evalue_max === 'number'
        ? config.hits_evalue_max
        : DEFAULT_EVALUE_MAX;
  const evalueOptions = useMemo(() => {
    const values = new Set(EVALUE_PRESETS);
    if (evalueMax != null) values.add(evalueMax);
    return [
      { value: 'any', label: 'Any (draw every hit)' },
      ...Array.from(values)
        .sort((a, b) => b - a)
        .map((v) => ({ value: String(v), label: `At most ${evalueLabel(v)}` })),
    ];
  }, [evalueMax]);
  const maxHits = typeof config?.max_hits === 'number' ? config.max_hits : 200;

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
            ? 'The logo is computed from an alignment table: bind its id, sequence id and aligned sequence. The match states are the reference row’s residues (rank 0).'
            : 'The logo is drawn from the long emission table of a parsed profile HMM.'}
        </Text>
      </Stack>
      <Group grow gap="xs" align="flex-start">
        <Select
          label="Letter heights"
          description="Recomputed in the browser from the emission probabilities"
          data={HEIGHT_MODES}
          value={heightMode}
          onChange={(v) => v && onChange({ height_mode: v })}
          allowDeselect={false}
          size="xs"
        />
        <Select
          label="Colour scheme"
          description="The alignment tile's residue colours"
          data={COLOUR_SCHEMES}
          value={colourScheme}
          onChange={(v) => v && onChange({ color_scheme: v })}
          allowDeselect={false}
          size="xs"
        />
      </Group>
      <Stack gap={6}>
        <Switch
          label="Consensus rows (consensus, RF and CS annotation lines when the model has them)"
          checked={config?.show_consensus !== false}
          onChange={(e) => onChange({ show_consensus: e.currentTarget.checked })}
          size="xs"
        />
        <Switch
          label="Insert and occupancy rows (insert probability, expected insert length, match occupancy)"
          checked={config?.show_indel_rows !== false}
          onChange={(e) => onChange({ show_indel_rows: e.currentTarget.checked })}
          size="xs"
        />
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
        <>
          <Group grow gap="xs">
            <ColumnPicker label="Model" field="hits_model_col" fallback="label" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="Entity" field="hits_entity_col" fallback="entity" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="HMM from" field="hits_from_col" fallback="hmm_from" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="HMM to" field="hits_to_col" fallback="hmm_to" columns={hitsColumns} config={config} onChange={onChange} />
          </Group>
          <Group grow gap="xs">
            <ColumnPicker label="Residue from" field="hits_ali_from_col" fallback="ali_from" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="Residue to" field="hits_ali_to_col" fallback="ali_to" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="E-value" field="hits_evalue_col" fallback="i_evalue" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="Score" field="hits_score_col" fallback="dom_score" columns={hitsColumns} config={config} onChange={onChange} />
            <ColumnPicker label="HMM length" field="hits_length_col" fallback="hmm_length" columns={hitsColumns} config={config} onChange={onChange} />
          </Group>
          <Group grow gap="xs" align="flex-start">
            <Select
              label="E-value threshold"
              description="Hits above it are left out of the lane"
              data={evalueOptions}
              value={evalueMax == null ? 'any' : String(evalueMax)}
              onChange={(v) => onChange({ hits_evalue_max: !v || v === 'any' ? null : Number(v) })}
              allowDeselect={false}
              size="xs"
            />
            <NumberInput
              label="Hits drawn"
              description="Best score first; coverage counts every hit under the threshold"
              value={maxHits}
              onChange={(v) =>
                onChange({ max_hits: Math.max(1, Math.min(2000, Math.round(Number(v)) || 200)) })
              }
              min={1}
              max={2000}
              size="xs"
            />
          </Group>
          <Text size="xs" c="dimmed">
            The hits of the model shown are drawn, matched on the model column. A click on a hit
            picks its aligned residues on its own protein.
          </Text>
        </>
      ) : null}
    </>
  );
};

export default HmmLogoSettings;
