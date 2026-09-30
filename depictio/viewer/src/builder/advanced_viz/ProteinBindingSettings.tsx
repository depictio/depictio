/**
 * Protein kinds (molecule_3d, msa, sequence_track): what the role mapping
 * cannot say.
 *
 * The bound collection's columns go through the usual role mapping. What is
 * left is where the other data lives (the structure files, the alignment
 * beside the structure, the domain spans and variants under the sequence),
 * how a structure is found (a file per entity, or resolved from an accession
 * or a sequence), and whether the tile picks residues and follows the picks
 * of the others. All of it is plain config, written as viz overrides like the
 * record card's link settings.
 */
import React, { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Group,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { fetchProjectFromDashboard, fetchSpecs } from 'depictio-react-core';
import type { WorkflowEntry } from 'depictio-react-core';
import { useBuilderStore } from '../store/useBuilderStore';
import {
  type CompanionBase,
  type CompanionOption,
  companionOptions,
  companionPatch,
  specColumns,
} from './proteinBindings';

type ProteinKind = 'molecule_3d' | 'msa' | 'sequence_track';

/** Panel heading per kind. */
const PANEL_TITLE: Record<ProteinKind, string> = {
  molecule_3d: 'Structure',
  msa: 'Alignment',
  sequence_track: 'Sequence lanes',
};

const PROTEIN_KINDS: ReadonlySet<string> = new Set<ProteinKind>(['molecule_3d', 'msa', 'sequence_track']);

export function isProteinKind(kind: string): kind is ProteinKind {
  return PROTEIN_KINDS.has(kind);
}

export interface ProteinBindingSettingsProps {
  vizKind: ProteinKind;
  /** The config the tile renders with (saved or catalog blob plus overrides). */
  config: Record<string, unknown> | null;
  /** Writes config fields; `undefined` drops a key the saved config never had. */
  onChange: (patch: Record<string, unknown>) => void;
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** Columns of one companion DC, for its column pickers. */
function useDcColumns(dcId: string | null): string[] {
  const [columns, setColumns] = useState<string[]>([]);
  useEffect(() => {
    if (!dcId) {
      setColumns([]);
      return;
    }
    let cancelled = false;
    fetchSpecs(dcId)
      .then((specs) => {
        if (!cancelled) setColumns(specColumns(specs));
      })
      .catch(() => {
        if (!cancelled) setColumns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [dcId]);
  return columns;
}

const CompanionPicker: React.FC<{
  label: string;
  description: string;
  base: CompanionBase;
  options: CompanionOption[];
  config: Record<string, unknown> | null;
  onChange: (patch: Record<string, unknown>) => void;
  loading: boolean;
  emptyMessage: string;
}> = ({ label, description, base, options, config, onChange, loading, emptyMessage }) => {
  const current = str(config?.[`${base}_dc_id`]);
  const tag = str(config?.[`${base}_dc_tag`]);
  return (
    <Select
      label={label}
      description={description}
      placeholder={loading ? 'Loading collections…' : tag ? `Template tag: ${tag}` : 'None'}
      data={options.map((o) => ({ value: o.value, label: o.label }))}
      value={current && options.some((o) => o.value === current) ? current : null}
      onChange={(v) => onChange(companionPatch(base, v, options))}
      clearable
      searchable
      nothingFoundMessage={emptyMessage}
    />
  );
};

const ColumnPicker: React.FC<{
  label: string;
  field: string;
  fallback: string;
  columns: string[];
  config: Record<string, unknown> | null;
  onChange: (patch: Record<string, unknown>) => void;
}> = ({ label, field, fallback, columns, config, onChange }) => {
  const value = str(config?.[field]) ?? fallback;
  const data = columns.includes(value) || !value ? columns : [value, ...columns];
  return (
    <Select
      label={label}
      data={data}
      value={value || null}
      onChange={(v) => onChange({ [field]: v ?? undefined })}
      searchable
      size="xs"
    />
  );
};

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
  const structureOptions = useMemo(
    () => companionOptions(workflows ?? [], 'structure'),
    [workflows],
  );
  // The alignment, domain and variant pickers all offer the project's other tables.
  const tableOptions = useMemo(
    () => companionOptions(workflows ?? [], 'msa', boundDcId),
    [workflows, boundDcId],
  );

  const domainsColumns = useDcColumns(str(config?.domains_dc_id));
  const variantsColumns = useDcColumns(str(config?.variants_dc_id));

  const selectionEnabled = config?.selection_enabled !== false;
  const followSelection = config?.follow_selection !== false;
  const structureSource = str(config?.structure_source) ?? 'file';
  const layout = str(config?.layout) ?? 'structure';

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Text fw={600} size="sm">
          {PANEL_TITLE[vizKind]}
        </Text>

        {vizKind === 'molecule_3d' ? (
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
                  Bind a UniProt, gene or sequence column in the role mapping above: the
                  structure is fetched from the AlphaFold database, or folded from the sequence
                  when no accession resolves.
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
            <Select
              label="Layout"
              data={[
                { value: 'structure', label: 'Structure only' },
                { value: 'structure_sequence', label: 'Structure and sequence' },
                { value: 'structure_msa', label: 'Structure and alignment' },
              ]}
              value={layout}
              onChange={(v) => onChange({ layout: v ?? undefined })}
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
                onChange={(e) =>
                  onChange({ entity_col_for_selection: e.currentTarget.value || undefined })
                }
                size="xs"
              />
              <TextInput
                label="Position column"
                value={str(config?.position_col_for_selection) ?? 'position'}
                onChange={(e) =>
                  onChange({ position_col_for_selection: e.currentTarget.value || undefined })
                }
                size="xs"
              />
            </Group>
          </>
        ) : null}

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
