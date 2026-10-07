/**
 * What a phylogenetic viz needs from the builder beyond its column bindings.
 *
 * A tree reads up to three data collections (phylo/sources.ts in
 * depictio-react-core): the Newick tree, the tip-metadata table its roles bind
 * to, and an optional table of per-sample abundance that sizes the summary's
 * lineages by reads. None of them is a column binding, so none of them fits the
 * role table, and until these sections a tree could only be bound by writing
 * YAML: one built here saved without the tree ids its model requires, and
 * nothing could name its metadata table at all.
 *
 * The sources, and the rank columns the summary may collapse to, are config
 * keys rather than roles, so they travel the way the preview's own Tier-2 edits
 * do: as `viz_overrides` on top of whatever the catalog or the last save
 * proposed, which the preview and the save path layer identically
 * (configBlob.ts `mergedPresetConfig`). The keys are the ones a dashboard YAML
 * writes (`tree_dc_tag`, `metadata_dc_tag`, `abundance_dc_tag` and their ids),
 * so a tree bound here and one written by hand are the same config. The
 * abundance table's columns end in `_col` and are roles like any other
 * (`abundance`, `abundance_sample`, `abundance_split`), which is also how a
 * YAML config's keys come back into the mapping when the component is edited
 * (`rolesFromConfigBlob`).
 *
 * The sections read as steps, each saying whether it is required: the tree
 * (required, and all a tree needs to be drawn), then the tip metadata
 * (optional: colours and labels, with the column bindings that only exist once
 * a table is picked), then the view (full tree, or the summary by a rank of
 * that metadata, with its top N, sizing and % labels), then the read shares
 * (optional, and only once there is tip metadata to group by).
 *
 * The view's keys are also the preview's own settings. Both write
 * `viz_overrides`, and the preview's controls follow the config they are handed
 * (usePersistedVizControl), so the form and the preview cannot disagree.
 */
import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Group,
  MultiSelect,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Text,
} from '@mantine/core';

import {
  abundanceRankCoverage,
  fetchPolarsSchema,
  fetchProjectFromDashboard,
  phyloRankChoices,
  phyloSourcePatch,
  preferredTipMetadata,
  tipLabelColumn,
  type PhyloDcRef,
} from 'depictio-react-core';
import { BuilderSection } from '../shared/BuilderSections';

type Preset = Record<string, unknown> | null;
type Patch = Record<string, unknown>;

const NUMERIC = new Set([
  'Int8',
  'Int16',
  'Int32',
  'Int64',
  'UInt8',
  'UInt16',
  'UInt32',
  'UInt64',
  'Float32',
  'Float64',
]);
const TEXT = new Set(['String', 'Utf8', 'Categorical']);

/** The model's defaults for the abundance columns (PhylogeneticConfig). */
const DEFAULT_VALUE_COL = 'rel_abundance';
const DEFAULT_SAMPLE_COL = 'sample';

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** Select options for some DCs: the tag, and the workflow's when a tag repeats. */
function dcOptions(dcs: PhyloDcRef[], wfTags: Map<string, string>) {
  const counts = new Map<string, number>();
  for (const d of dcs) counts.set(d.tag ?? d.dcId, (counts.get(d.tag ?? d.dcId) ?? 0) + 1);
  return dcs.map((d) => {
    const name = d.tag ?? d.dcId;
    return {
      value: d.dcId,
      label: (counts.get(name) ?? 0) > 1 ? `${name} (${wfTags.get(d.wfId) ?? d.wfId})` : name,
    };
  });
}

/** Every DC of the component's project, as phylo refs, plus the workflow tags
 *  for labelling them. Null while loading, or when not a tree. */
export function usePhyloProjectDcs(
  dashboardId: string | null,
  enabled: boolean,
): { dcs: PhyloDcRef[]; wfTags: Map<string, string> } | null {
  const [state, setState] = useState<{ dcs: PhyloDcRef[]; wfTags: Map<string, string> } | null>(
    null,
  );
  useEffect(() => {
    if (!enabled || !dashboardId) {
      setState(null);
      return;
    }
    let cancelled = false;
    fetchProjectFromDashboard(dashboardId)
      .then(({ project }) => {
        if (cancelled) return;
        const dcs: PhyloDcRef[] = [];
        const wfTags = new Map<string, string>();
        for (const wf of project.workflows || []) {
          wfTags.set(wf._id, wf.workflow_tag || wf.name || wf._id);
          for (const dc of wf.data_collections || []) {
            const props = (dc.config?.dc_specific_properties ?? {}) as Record<string, unknown>;
            dcs.push({
              wfId: wf._id,
              dcId: dc._id,
              tag: dc.data_collection_tag ?? null,
              type: typeof dc.config?.type === 'string' ? dc.config.type.toLowerCase() : null,
              metadataTag: str(props.metadata_dc_tag),
              metadataTaxonColumn: str(props.metadata_taxon_column),
            });
          }
        }
        setState({ dcs, wfTags });
      })
      .catch(() => {
        if (!cancelled) setState({ dcs: [], wfTags: new Map() });
      });
    return () => {
      cancelled = true;
    };
  }, [dashboardId, enabled]);
  return state;
}

/** The tree the config binds, else the one it would be pre-filled with: the
 *  component's own DC when that is a tree, else the project's first. */
function treeOf(dcs: PhyloDcRef[], merged: Preset, dcId: string | null): PhyloDcRef | null {
  const bound = str(merged?.tree_dc_id);
  if (bound) return dcs.find((d) => d.dcId === bound) ?? null;
  const own = dcs.find((d) => d.dcId === dcId);
  return own?.type === 'phylogeny' ? own : (dcs.find((d) => d.type === 'phylogeny') ?? null);
}

/** A section title that says whether the step is required, so the one thing a
 *  tree cannot do without is told apart from what only adds to it. */
const StepTitle: React.FC<{ label: string; required: boolean }> = ({ label, required }) => (
  <Group gap={6} wrap="nowrap">
    <span>{label}</span>
    <Badge size="xs" variant="light" color={required ? 'red' : 'gray'}>
      {required ? 'Required' : 'Optional'}
    </Badge>
  </Group>
);

/** A field label that says it can be left empty, the way the role bindings
 *  above it do. */
const optional = (label: string) => (
  <Group gap={4} component="span" wrap="nowrap">
    <span>{label}</span>
    <Text span size="xs" fw={400} c="dimmed">
      optional
    </Text>
  </Group>
);

/**
 * Pre-fill what a tree needs and the author has not chosen: the tree (the
 * component's own DC when it is one), and, once a tip-metadata table is picked,
 * its `taxon` binding (the column the tree declares, else one named like a tip
 * label), once per table.
 *
 * The tip metadata itself is never picked for the author. It is optional, and a
 * table chosen on their behalf read as a requirement; the section suggests one
 * instead (see `PhyloMetadataSection`).
 */
export function usePhyloPrefill(args: {
  enabled: boolean;
  project: { dcs: PhyloDcRef[] } | null;
  dcId: string | null;
  wfId: string | null;
  merged: Preset;
  setVizOverride: (patch: Patch) => void;
  metadataSchema: Record<string, string> | null;
  taxonBound: boolean;
  bindTaxon: (column: string) => void;
}): void {
  const { enabled, project, dcId, wfId, merged, setVizOverride, metadataSchema } = args;
  const done = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!enabled) done.current.clear();
  }, [enabled]);

  const dcs = project?.dcs ?? null;

  useEffect(() => {
    if (!enabled || !dcs || str(merged?.tree_dc_id)) return;
    const tree = treeOf(dcs, merged, dcId);
    if (tree) setVizOverride(phyloSourcePatch('tree', tree, wfId));
  }, [enabled, dcs, merged, dcId, wfId, setVizOverride]);

  const metadataDcId = str(merged?.metadata_dc_id);
  const { taxonBound, bindTaxon } = args;
  useEffect(() => {
    if (!enabled || !dcs || !metadataSchema || !metadataDcId || taxonBound) return;
    const key = `taxon:${metadataDcId}`;
    if (done.current.has(key)) return;
    done.current.add(key);
    const tree = treeOf(dcs, merged, dcId);
    const column = tipLabelColumn(Object.keys(metadataSchema), tree?.metadataTaxonColumn);
    if (column) bindTaxon(column);
  }, [enabled, dcs, metadataSchema, metadataDcId, taxonBound, bindTaxon, merged, dcId]);
}

/** Step 1, "Tree": the Newick data collection. All a tree needs to be drawn. */
export const PhyloTreeSection: React.FC<{
  project: { dcs: PhyloDcRef[]; wfTags: Map<string, string> } | null;
  merged: Preset;
  wfId: string | null;
  setVizOverride: (patch: Patch) => void;
}> = ({ project, merged, wfId, setVizOverride }) => {
  const trees = (project?.dcs ?? []).filter((d) => d.type === 'phylogeny');
  const treeId = str(merged?.tree_dc_id);
  return (
    <BuilderSection
      value="phylo-tree"
      icon="mdi:family-tree"
      title={<StepTitle label="Tree" required />}
      subtitle="The Newick tree to draw"
    >
      <Stack gap="sm">
        {project == null ? (
          <Text size="sm" c="dimmed">
            Loading the project’s data collections…
          </Text>
        ) : null}
        <Select
          label="Tree"
          withAsterisk
          description="A phylogeny data collection (Newick). On its own it draws the full tree, uncoloured."
          placeholder="Pick the tree"
          data={dcOptions(trees, project?.wfTags ?? new Map())}
          value={treeId}
          onChange={(v) => {
            const tree = trees.find((t) => t.dcId === v);
            if (tree) setVizOverride(phyloSourcePatch('tree', tree, wfId));
          }}
          allowDeselect={false}
          searchable
          nothingFoundMessage="No phylogeny data collection in this project"
          error={project != null && !treeId ? 'A tree needs its Newick data collection' : undefined}
          data-testid="phylo-tree-dc"
        />
      </Stack>
    </BuilderSection>
  );
};

/**
 * Step 2, "Tip metadata": the table joined to the tips on their label, and
 * what it is read for. Optional: without it the tree is drawn uncoloured, and
 * the summary by rank is not available.
 *
 * The column bindings (`bindings`, rendered by the builder from the kind's
 * roles) live here because they are columns of this table and mean nothing
 * before it is picked.
 */
export const PhyloMetadataSection: React.FC<{
  project: { dcs: PhyloDcRef[]; wfTags: Map<string, string> } | null;
  merged: Preset;
  dcId: string | null;
  wfId: string | null;
  setVizOverride: (patch: Patch) => void;
  /** The role Selects (tip label, colour, label) and their validation. */
  bindings: React.ReactNode;
}> = ({
  project,
  merged,
  dcId,
  wfId,
  setVizOverride,
  bindings,
}) => {
  const dcs = project?.dcs ?? [];
  const wfTags = project?.wfTags ?? new Map<string, string>();
  const tables = dcs.filter((d) => d.type === 'table');
  const metadataId = str(merged?.metadata_dc_id);
  const pick = (id: string | null) =>
    setVizOverride(phyloSourcePatch('metadata', tables.find((t) => t.dcId === id) ?? null, wfId));
  // The table the tree names as its annotations (or the component's own
  // table), offered as one click rather than chosen for the author.
  const suggestedId = metadataId
    ? null
    : preferredTipMetadata(tables, {
        tree: treeOf(dcs, merged, dcId),
        bound: dcs.find((d) => d.dcId === dcId) ?? null,
      });
  const suggested = tables.find((t) => t.dcId === suggestedId) ?? null;

  return (
    <BuilderSection
      value="phylo-metadata"
      icon="mdi:table-account"
      title={<StepTitle label="Tip metadata" required={false} />}
      subtitle="Colour, label and summarise the tips from a table joined on their name"
    >
      <Stack gap="sm">
        <Select
          label={optional('Tip-metadata table')}
          description="One row per tip, matched on the tip's name. Needed to colour or label the tips, and for the Summary by rank view."
          placeholder="None: an uncoloured tree"
          data={dcOptions(tables, wfTags)}
          value={metadataId}
          onChange={pick}
          searchable
          clearable
          data-testid="phylo-metadata-dc"
        />
        {suggested ? (
          <Text size="xs" c="dimmed">
            Suggested: {suggested.tag ?? suggested.dcId}, the table this tree names for its tips.{' '}
            <Anchor
              component="button"
              type="button"
              size="xs"
              onClick={() => pick(suggested.dcId)}
              data-testid="phylo-metadata-suggested"
            >
              Use it
            </Anchor>
          </Text>
        ) : null}
        {metadataId ? bindings : null}
      </Stack>
    </BuilderSection>
  );
};

/**
 * Step 3, "View": the full tree, or the summary by rank, and the summary's
 * settings. The same keys as the switch and controls in the preview's own
 * settings, which follow what is picked here (and the other way round).
 */
export const PhyloViewSection: React.FC<{
  merged: Preset;
  setVizOverride: (patch: Patch) => void;
  metadataSchema: Record<string, string> | null;
  taxonCol: string | null;
}> = ({ merged, setVizOverride, metadataSchema, taxonCol }) => {
  const hasMetadata = Boolean(merged?.metadata_dc_id || merged?.metadata_dc_tag);
  const hasReads = Boolean(merged?.abundance_dc_id || merged?.abundance_dc_tag);
  const rank = str(merged?.collapse_rank);
  const summary = hasMetadata && rank != null;
  const remembered = useRef<string | null>(rank);
  if (rank) remembered.current = rank;

  // A rank is a category of the tips, so a text column; the tip id is not one.
  const textColumns = Object.entries(metadataSchema ?? {})
    .filter(([c, t]) => TEXT.has(t) && c !== (taxonCol || 'taxon'))
    .map(([c]) => c);
  const offered = Array.isArray(merged?.extra_color_cols)
    ? (merged!.extra_color_cols as unknown[]).filter((c): c is string => typeof c === 'string')
    : [];
  const rankOptions = Array.from(new Set([...textColumns, ...(rank ? [rank] : [])]));
  const firstRank = () =>
    (remembered.current && rankOptions.includes(remembered.current) && remembered.current) ||
    rankOptions.find((c) => c.toLowerCase() === 'phylum') ||
    rankOptions[0] ||
    null;

  const sizeBy = merged?.size_by === 'abundance' && hasReads ? 'abundance' : 'tips';
  const showShares =
    typeof merged?.show_shares === 'boolean' ? merged.show_shares : sizeBy === 'abundance';

  return (
    <BuilderSection
      value="phylo-view"
      icon="mdi:eye-outline"
      title={<StepTitle label="View" required={false} />}
      subtitle="The full tree, or one tip per lineage of a rank"
    >
      <Stack gap="sm">
        <SegmentedControl
          fullWidth
          value={summary ? 'summary' : 'tree'}
          onChange={(v) => setVizOverride({ collapse_rank: v === 'summary' ? firstRank() : null })}
          data={[
            { value: 'tree', label: 'Full tree' },
            { value: 'summary', label: 'Summary by rank', disabled: !hasMetadata },
          ]}
          data-testid="phylo-view"
        />
        {!hasMetadata ? (
          <Text size="xs" c="dimmed">
            Summary by rank groups the tips by a column of the tip metadata: pick that table
            first.
          </Text>
        ) : null}
        {summary ? (
          <>
            <Select
              label="Collapse to"
              withAsterisk
              description="One tip per value of this column, placed where that lineage sits in the tree."
              data={rankOptions}
              value={rank}
              onChange={(v) => v && setVizOverride({ collapse_rank: v })}
              allowDeselect={false}
              searchable
              data-testid="phylo-collapse-rank"
            />
            <NumberInput
              label={optional('Lineages shown')}
              description="The largest ones; the rest are counted under “not shown”. Default 10."
              value={typeof merged?.top_n === 'number' ? merged.top_n : 10}
              onChange={(v) =>
                typeof v === 'number' && setVizOverride({ top_n: Math.min(60, Math.max(1, Math.floor(v))) })
              }
              min={1}
              max={60}
            />
            <Stack gap={4}>
              <Text size="sm" fw={500}>
                Size by
              </Text>
              <SegmentedControl
                fullWidth
                value={sizeBy}
                onChange={(v) => setVizOverride({ size_by: v })}
                data={[
                  { value: 'tips', label: 'ASVs (tips)' },
                  { value: 'abundance', label: 'Reads', disabled: !hasReads },
                ]}
                data-testid="phylo-size-by"
              />
              {!hasReads ? (
                <Text size="xs" c="dimmed">
                  Reads need an abundance table: pick it under Read shares.
                </Text>
              ) : null}
            </Stack>
            <Switch
              label="Show %"
              description={
                typeof merged?.show_shares === 'boolean'
                  ? undefined
                  : 'Default: shown when sized by reads'
              }
              checked={showShares}
              onChange={(e) => setVizOverride({ show_shares: e.currentTarget.checked })}
              data-testid="phylo-show-shares"
            />
          </>
        ) : null}
        {hasMetadata ? (
          <MultiSelect
            label={optional('Columns viewers can switch to')}
            description="Offered in the tile’s settings on the dashboard: Colour by on the full tree, Collapse to on the summary. Nothing changes here until a viewer picks one."
            placeholder="Pick columns"
            data={Array.from(new Set([...textColumns, ...offered]))}
            value={offered}
            onChange={(v) => setVizOverride({ extra_color_cols: v.length ? v : null })}
            searchable
            clearable
            data-testid="phylo-rank-cols"
          />
        ) : null}
      </Stack>
    </BuilderSection>
  );
};

/** "Read shares": the abundance table that sizes the summary's lineages by
 *  reads, its columns, and whether it can be joined to the ranks on offer. */
export const PhyloReadsSection: React.FC<{
  project: { dcs: PhyloDcRef[]; wfTags: Map<string, string> } | null;
  merged: Preset;
  wfId: string | null;
  setVizOverride: (patch: Patch) => void;
  columnMapping: Record<string, string | string[]>;
  /** Set (string) or unbind (null) several roles in one write. */
  patchRoles: (patch: Record<string, string | null>) => void;
}> = ({ project, merged, wfId, setVizOverride, columnMapping, patchRoles }) => {
  const dcs = project?.dcs ?? [];
  const tables = dcs.filter((d) => d.type === 'table');
  const tableId = str(merged?.abundance_dc_id);
  // The reads only size the summary, which needs the tip metadata's ranks; a
  // table already bound stays editable so it can be cleared.
  const hasMetadata = Boolean(merged?.metadata_dc_id || merged?.metadata_dc_tag);

  const [schema, setSchema] = useState<Record<string, string> | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  useEffect(() => {
    setSchema(null);
    setSchemaError(null);
    if (!tableId) return;
    let cancelled = false;
    fetchPolarsSchema(tableId)
      .then((s) => !cancelled && setSchema(s))
      .catch((e: unknown) => !cancelled && setSchemaError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [tableId]);

  const role = (r: string): string | null => str(columnMapping[r]);
  // What the renderer will read: the bound column, else the model's default
  // when the table has a column of that name.
  const effective = (r: string, fallback: string) =>
    role(r) ?? (schema && fallback in schema ? fallback : null);
  const valueCol = effective('abundance', DEFAULT_VALUE_COL);
  const sampleCol = effective('abundance_sample', DEFAULT_SAMPLE_COL);
  const splitCol = role('abundance_split');

  const options = (accept: Set<string>) =>
    Object.entries(schema ?? {})
      .filter(([, t]) => accept.has(t))
      .map(([c, t]) => ({ value: c, label: `${c} : ${t}` }));

  // An optional column of a saved config comes back on save from the preset
  // unless the override says null (configBlob.ts, extractRoleDerivedFallbacks),
  // so unbinding the split writes both.
  const unbindSplit = () => {
    patchRoles({ abundance_split: null });
    setVizOverride({ abundance_split_col: null });
  };

  const onTable = (id: string | null) => {
    const table = tables.find((t) => t.dcId === id) ?? null;
    setVizOverride(phyloSourcePatch('abundance', table, wfId));
    if (!table) {
      patchRoles({ abundance: null, abundance_sample: null, abundance_split: null });
      setVizOverride({ abundance_split_col: null });
    }
  };

  // The ranks the preview's Collapse to offers, which read the colour and tip
  // columns from the bindings rather than from the preset.
  const rank = str(merged?.collapse_rank);
  const ranks = phyloRankChoices(
    {
      ...(merged ?? {}),
      color_col: role('color'),
      taxon_col: role('taxon') ?? undefined,
    } as Parameters<typeof phyloRankChoices>[0],
    rank,
  );
  const coverage = schema ? abundanceRankCoverage(ranks, Object.keys(schema)) : null;

  const warnings: string[] = [];
  if (schema) {
    if (!valueCol) warnings.push(`Pick the column holding each row's abundance (a number).`);
    else if (!(valueCol in schema)) warnings.push(`"${valueCol}" is not a column of this table.`);
    else if (!NUMERIC.has(schema[valueCol]))
      warnings.push(`"${valueCol}" is ${schema[valueCol]}, not a number.`);
    if (splitCol && !(splitCol in schema)) warnings.push(`"${splitCol}" is not a column of this table.`);
  }

  return (
    <BuilderSection
      value="phylo-reads"
      icon="mdi:chart-bubble"
      title={<StepTitle label="Read shares" required={false} />}
      subtitle="Size the summary's lineages by reads rather than tips"
    >
      {!hasMetadata && !tableId ? (
        <Text size="sm" c="dimmed">
          Pick the tip metadata first: the summary groups the tips by its rank columns, and the
          reads are joined on those.
        </Text>
      ) : (
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Used by the summary (View → Summary by rank, Size by → Reads): a lineage’s share is
            then its mean share of a sample’s reads.
          </Text>
          <Select
            label={optional('Abundance table')}
            description="A long table, one row per sample and taxon, with a relative abundance."
            placeholder="None: sized by tips"
            data={dcOptions(tables, project?.wfTags ?? new Map())}
            value={tableId}
            onChange={onTable}
            searchable
            clearable
            data-testid="phylo-abundance-dc"
          />
          {schemaError ? (
            <Alert color="red" title="Failed to load the table's schema">
              <Text size="xs">{schemaError}</Text>
            </Alert>
          ) : null}
          {tableId && schema ? (
            <>
              <Select
                label="Value column"
                withAsterisk
                description="Each row's relative abundance."
                data={options(NUMERIC)}
                value={valueCol}
                onChange={(v) => v && patchRoles({ abundance: v })}
                allowDeselect={false}
                searchable
                nothingFoundMessage="No numeric column"
              />
              <Select
                label={optional('Sample column')}
                description="A share is the mean over samples of each sample's share; without one the value column is summed."
                data={options(TEXT)}
                value={sampleCol}
                onChange={(v) => v && patchRoles({ abundance_sample: v })}
                allowDeselect={false}
                searchable
              />
              <Select
                label={optional('Split by')}
                description="Break each share down by this column (a site, say), drawn as a strip of dots beside the tips."
                placeholder="No strip"
                data={options(TEXT)}
                value={splitCol}
                onChange={(v) => (v ? patchRoles({ abundance_split: v }) : unbindSplit())}
                searchable
                clearable
              />
              <JoinNote rank={rank} coverage={coverage} />
              {warnings.length > 0 ? (
                <Alert color="yellow" variant="light" title="Check the read shares">
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {warnings.map((w) => (
                      <li key={w}>
                        <Text size="xs">{w}</Text>
                      </li>
                    ))}
                  </ul>
                </Alert>
              ) : null}
            </>
          ) : null}
        </Stack>
      )}
    </BuilderSection>
  );
};

/**
 * How the reads reach the tree, said before it matters. The summary groups the
 * abundance table on the column named like the rank it collapses to, so a rank
 * the table lacks is sized by tips instead; flagged in orange when that is the
 * rank currently drawn, listed quietly otherwise.
 */
const JoinNote: React.FC<{
  rank: string | null;
  coverage: { joined: string[]; missing: string[] } | null;
}> = ({ rank, coverage }) => {
  if (!coverage) return null;
  const { joined, missing } = coverage;
  const intro =
    'Joined to the tree by name: the table needs a column called like the rank the summary collapses to.';
  if (rank && missing.includes(rank)) {
    return (
      <Alert color="orange" variant="light" title={`No ${rank} column in this table`}>
        <Text size="xs">
          {intro} Collapsed to {rank}, the summary will be sized by tips.{' '}
          {joined.length > 0
            ? `Ranks it can size by reads: ${joined.join(', ')}.`
            : 'It has none of the rank columns on offer.'}
        </Text>
      </Alert>
    );
  }
  let has = '';
  if (joined.length > 0 && missing.length > 0)
    has = `It has ${joined.join(', ')}; not ${missing.join(', ')}, which would be sized by tips.`;
  else if (joined.length > 0) has = `It has ${joined.join(', ')}.`;
  else if (missing.length > 0)
    has = `It has none of ${missing.join(', ')}, which would be sized by tips.`;
  return (
    <Text size="xs" c="dimmed">
      {intro} {has}
    </Text>
  );
};
