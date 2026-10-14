/**
 * Protein kinds (molecule_3d, msa, sequence_track and the five newer ones):
 * what the role mapping cannot say.
 *
 * The bound collection's columns go through the usual role mapping. What is
 * left is where the other data lives (the structure files, the alignment
 * beside the structure, the domain spans and variants under the sequence, a
 * profile's hits, the PAE files), how a structure is found (a file per entity,
 * or resolved from an accession or a sequence), and whether the tile picks
 * residues and follows the picks of the others. All of it is plain config,
 * written as viz overrides like the record card's link settings.
 *
 * The newer kinds each keep their own panel under `./protein/`; this module
 * owns the frame around them (the selection switches, the project's
 * collections, the load error) and the three older kinds' panels.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Alert, Group, Paper, Select, Stack, Switch, Text, TextInput } from '@mantine/core';
import { fetchProjectFromDashboard } from 'depictio-react-core';
import type { WorkflowEntry } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import { companionOptions } from './proteinBindings';
import { ColumnPicker, CompanionPicker, str, useDcColumns } from './protein/common';
import DomainArchitectureSettings from './protein/DomainArchitectureSettings';
import HmmLogoSettings from './protein/HmmLogoSettings';
import PaeMatrixSettings from './protein/PaeMatrixSettings';
import RamachandranSettings from './protein/RamachandranSettings';
import SecondaryStructureSettings from './protein/SecondaryStructureSettings';
import StructureSourceSettings from './protein/StructureSourceSettings';

type ProteinKind =
  | 'molecule_3d'
  | 'msa'
  | 'sequence_track'
  | 'hmm_logo'
  | 'secondary_structure'
  | 'domain_architecture'
  | 'pae_matrix'
  | 'ramachandran';

/** Panel heading per kind. */
const PANEL_TITLE: Record<ProteinKind, string> = {
  molecule_3d: 'Structure',
  msa: 'Alignment',
  sequence_track: 'Sequence lanes',
  hmm_logo: 'HMM logo',
  secondary_structure: 'Secondary structure',
  domain_architecture: 'Domain architecture',
  pae_matrix: 'Predicted aligned error',
  ramachandran: 'Ramachandran plot',
};

const PROTEIN_KINDS: ReadonlySet<string> = new Set<ProteinKind>(
  Object.keys(PANEL_TITLE) as ProteinKind[],
);

export function isProteinKind(kind: string): kind is ProteinKind {
  return PROTEIN_KINDS.has(kind);
}

export interface ProteinBindingSettingsProps {
  vizKind: ProteinKind;
  /** What Save will write: the role bindings, the saved or catalog blob and
   *  the overrides, merged. */
  config: Record<string, unknown> | null;
  /** Writes config fields; `undefined` drops a key the saved config never had. */
  onChange: (patch: Record<string, unknown>) => void;
}

const ProteinBindingSettings: React.FC<ProteinBindingSettingsProps> = ({
  vizKind,
  config,
  onChange,
}) => {
  const dashboardId = useBuilderStore((s) => s.dashboardId);
  const boundDcId = useBuilderStore((s) => s.dcId);
  const [workflows, setWorkflows] = useState<WorkflowEntry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!dashboardId) return;
    let cancelled = false;
    fetchProjectFromDashboard(dashboardId)
      .then(({ project }) => {
        if (!cancelled) setWorkflows(project.workflows ?? []);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId]);

  const loading = workflows == null && !loadError;
  // The alignment, domain and variant pickers all offer the project's other tables.
  const tableOptions = useMemo(
    () => companionOptions(workflows ?? [], 'msa', boundDcId),
    [workflows, boundDcId],
  );

  const domainsColumns = useDcColumns(str(config?.domains_dc_id));
  const variantsColumns = useDcColumns(str(config?.variants_dc_id));

  const selectionEnabled = config?.selection_enabled !== false;
  const followSelection = config?.follow_selection !== false;
  const layout = str(config?.layout) ?? 'structure';
  // What each newer kind's own panel receives.
  const kindProps = { config, onChange, workflows, loading, boundDcId };

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Text fw={600} size="sm">
          {PANEL_TITLE[vizKind]}
        </Text>

        {vizKind === 'molecule_3d' ? (
          <>
            <StructureSourceSettings
              config={config}
              onChange={onChange}
              workflows={workflows}
              loading={loading}
            />
            <Select
              label="Layout"
              data={[
                { value: 'structure', label: 'Structure only' },
                { value: 'structure_sequence', label: 'Structure and sequence' },
                { value: 'structure_text', label: 'Structure and written sequence' },
                { value: 'structure_msa', label: 'Structure and alignment' },
              ]}
              value={layout}
              onChange={(v) => v && onChange({ layout: v })}
              allowDeselect={false}
              size="xs"
            />
            {layout === 'structure_msa' ? (
              <CompanionPicker
                label="Alignment"
                description="The MSA table shown beside the structure"
                base="msa"
                options={tableOptions}
                config={config}
                onChange={onChange}
                loading={loading}
                emptyMessage="No other table in this project"
              />
            ) : null}
          </>
        ) : null}

        {vizKind === 'sequence_track' ? (
          <>
            <CompanionPicker
              label="Domains"
              description="Optional table of spans (start, end, label) drawn as a lane"
              base="domains"
              options={tableOptions}
              config={config}
              onChange={onChange}
              loading={loading}
              emptyMessage="No other table in this project"
            />
            {config?.domains_dc_id ? (
              <Group grow gap="xs">
                <ColumnPicker label="Start" field="domain_start_col" fallback="start" columns={domainsColumns} config={config} onChange={onChange} />
                <ColumnPicker label="End" field="domain_end_col" fallback="end" columns={domainsColumns} config={config} onChange={onChange} />
                <ColumnPicker label="Label" field="domain_label_col" fallback="label" columns={domainsColumns} config={config} onChange={onChange} />
              </Group>
            ) : null}
            <CompanionPicker
              label="Variants"
              description="Optional variant table drawn as mini lollipops"
              base="variants"
              options={tableOptions}
              config={config}
              onChange={onChange}
              loading={loading}
              emptyMessage="No other table in this project"
            />
            {config?.variants_dc_id ? (
              <Group grow gap="xs">
                <ColumnPicker label="Position" field="variant_position_col" fallback="position" columns={variantsColumns} config={config} onChange={onChange} />
                <ColumnPicker label="Label" field="variant_label_col" fallback="label" columns={variantsColumns} config={config} onChange={onChange} />
                <ColumnPicker label="Category" field="variant_category_col" fallback="category" columns={variantsColumns} config={config} onChange={onChange} />
              </Group>
            ) : null}
          </>
        ) : null}

        {vizKind === 'msa' ? (
          <>
            <Text size="xs" c="dimmed">
              A column brush picks residues in reference coordinates. Name the entity and
              position columns of the residue and variant tables it should narrow.
            </Text>
            <Group grow gap="xs">
              <TextInput
                label="Entity column"
                value={str(config?.entity_col_for_selection) ?? 'entity'}
                // Emptied, the name falls back to its default: unsetting a
                // saved key writes null, which the model refuses.
                onChange={(e) =>
                  onChange({ entity_col_for_selection: e.currentTarget.value || 'entity' })
                }
                size="xs"
              />
              <TextInput
                label="Position column"
                value={str(config?.position_col_for_selection) ?? 'position'}
                onChange={(e) =>
                  onChange({ position_col_for_selection: e.currentTarget.value || 'position' })
                }
                size="xs"
              />
            </Group>
          </>
        ) : null}

        {vizKind === 'hmm_logo' ? <HmmLogoSettings {...kindProps} /> : null}
        {vizKind === 'secondary_structure' ? <SecondaryStructureSettings {...kindProps} /> : null}
        {vizKind === 'domain_architecture' ? <DomainArchitectureSettings {...kindProps} /> : null}
        {vizKind === 'pae_matrix' ? <PaeMatrixSettings {...kindProps} /> : null}
        {vizKind === 'ramachandran' ? <RamachandranSettings {...kindProps} /> : null}

        <Stack gap={6}>
          <Switch
            label="Pick residues (emits a residue selection the other protein tiles follow)"
            checked={selectionEnabled}
            onChange={(e) => onChange({ selection_enabled: e.currentTarget.checked })}
            size="xs"
          />
          <Switch
            label="Follow residue picks and hovers from the other tiles"
            checked={followSelection}
            onChange={(e) => onChange({ follow_selection: e.currentTarget.checked })}
            size="xs"
          />
          <Text size="xs" c="dimmed">
            Tiles move together when their collections share the entity and position column
            names.
          </Text>
        </Stack>

        {loadError ? (
          <Alert color="yellow" variant="light">
            <Text size="xs">Could not list this project's collections: {loadError}</Text>
          </Alert>
        ) : null}
      </Stack>
    </Paper>
  );
};

export default ProteinBindingSettings;
