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
 * The view itself, full tree or summary by rank, and the summary's top N and
 * sizing, are not here: they are the preview's settings, where the author sees
 * what they do. The preview's controls are seeded once and then hold their own
 * state, so a second writer here would leave the preview showing one value and
 * the save holding another.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Alert, MultiSelect, Select, Stack, Text } from '@mantine/core';

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

/** A cap on the schemas fetched to find a tip-metadata table by its columns. */
const MAX_SCHEMA_PROBES = 40;

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

/**
 * Pre-fill what a tree needs and the author has not chosen, once each: the
 * tree (the component's own DC when it is one), the tip-metadata table (the
 * one the tree names, else the component's own table, else the first table with
 * a tip-label column), and the `taxon` binding (the column the tree declares,
 * else one named like a tip label).
 *
 * The metadata table is pre-filled only while its key is absent: a table the
 * author cleared is an explicit null and stays cleared, and so does the "none"
 * of a saved tree that never had one. Everything resets when the kind does,
 * since picking a kind clears the overrides these write.
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
  // Read at the end of the schema probe, which outlives the render it began in.
  const latest = useRef(merged);
  latest.current = merged;

  useEffect(() => {
    if (!enabled) done.current.clear();
  }, [enabled]);

  const dcs = project?.dcs ?? null;

  useEffect(() => {
    if (!enabled || !dcs || str(merged?.tree_dc_id)) return;
    const tree = treeOf(dcs, merged, dcId);
    if (tree) setVizOverride(phyloSourcePatch('tree', tree, wfId));
  }, [enabled, dcs, merged, dcId, wfId, setVizOverride]);

  useEffect(() => {
    if (!enabled || !dcs || done.current.has('metadata')) return;
    if (merged && merged.metadata_dc_id !== undefined) return;
    done.current.add('metadata');
    const tables = dcs.filter((d) => d.type === 'table');
    const tree = treeOf(dcs, merged, dcId);
    const own = dcs.find((d) => d.dcId === dcId) ?? null;
    const bind = (id: string | null) => {
      const table = tables.find((t) => t.dcId === id);
      if (!table) return;
      // The author may have picked one while the schemas were on their way.
      if (latest.current && latest.current.metadata_dc_id !== undefined) return;
      setVizOverride(phyloSourcePatch('metadata', table, wfId));
    };
    const quick = preferredTipMetadata(tables, { tree, bound: own });
    if (quick) {
      bind(quick);
      return;
    }
    const probed = tables.slice(0, MAX_SCHEMA_PROBES);
    void Promise.allSettled(probed.map((t) => fetchPolarsSchema(t.dcId))).then((results) => {
      const columns: Record<string, string[]> = {};
      results.forEach((r, i) => {
        if (r.status === 'fulfilled') columns[probed[i].dcId] = Object.keys(r.value);
      });
      bind(preferredTipMetadata(probed, { columns }));
    });
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

/** "Tree and tip metadata": the Newick DC, the table joined to its tips, and
 *  the columns of that table the summary may collapse to. */
export const PhyloSourcesSection: React.FC<{
  project: { dcs: PhyloDcRef[]; wfTags: Map<string, string> } | null;
  merged: Preset;
  wfId: string | null;
  setVizOverride: (patch: Patch) => void;
  metadataSchema: Record<string, string> | null;
  taxonCol: string | null;
  /** Shown on the tip-metadata picker: the summary is on and has no table. */
  metadataError?: string;
}> = ({ project, merged, wfId, setVizOverride, metadataSchema, taxonCol, metadataError }) => {
  const dcs = project?.dcs ?? [];
  const wfTags = project?.wfTags ?? new Map<string, string>();
  const trees = dcs.filter((d) => d.type === 'phylogeny');
  const tables = dcs.filter((d) => d.type === 'table');
  const treeId = str(merged?.tree_dc_id);
  const metadataId = str(merged?.metadata_dc_id);
  const ranks = Array.isArray(merged?.extra_color_cols)
    ? (merged!.extra_color_cols as unknown[]).filter((c): c is string => typeof c === 'string')
    : [];
  // A rank is a category of the tips, so a text column; the tip id is not one.
  // Ranks already chosen stay listed even when the table lacks them, so the
  // picker can show (and drop) them.
  const rankOptions = Array.from(
    new Set([
      ...Object.entries(metadataSchema ?? {})
        .filter(([c, t]) => TEXT.has(t) && c !== (taxonCol || 'taxon'))
        .map(([c]) => c),
      ...ranks,
    ]),
  );

  return (
    <BuilderSection
      value="phylo-sources"
      icon="mdi:family-tree"
      title="Tree and tip metadata"
      subtitle="The Newick tree, and the table joined to its tips"
    >
      <Stack gap="sm">
        {project == null ? (
          <Text size="sm" c="dimmed">
            Loading the project’s data collections…
          </Text>
        ) : null}
        <Select
          label="Tree"
          description="A phylogeny data collection (Newick)."
          placeholder="Pick the tree"
          data={dcOptions(trees, wfTags)}
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
        <Select
          label="Tip metadata"
          description="The table joined to the tips on their label: what colours, labels and the summary's ranks are read from."
          placeholder="None: an uncoloured tree"
          data={dcOptions(tables, wfTags)}
          value={metadataId}
          onChange={(v) =>
            setVizOverride(
              phyloSourcePatch('metadata', tables.find((t) => t.dcId === v) ?? null, wfId),
            )
          }
          searchable
          clearable
          error={metadataError}
          data-testid="phylo-metadata-dc"
        />
        <MultiSelect
          label="Rank columns"
          description="Offered as Colour by on the tree and as Collapse to in its summary. List them root to leaf: Kingdom, Phylum, Class…"
          placeholder={metadataId ? 'Pick rank columns' : 'Pick the tip metadata first'}
          data={rankOptions}
          value={ranks}
          onChange={(v) => setVizOverride({ extra_color_cols: v.length ? v : null })}
          disabled={!metadataId}
          searchable
          clearable
          data-testid="phylo-rank-cols"
        />
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
      title="Read shares"
      subtitle="Optional: size the summary's lineages by reads rather than tips"
    >
      <Stack gap="sm">
        <Text size="xs" c="dimmed">
          For the summary view: in the preview’s settings, View → Summary by rank, then Size by →
          Reads. A lineage’s share is then its mean share of a sample’s reads.
        </Text>
        <Select
          label="Abundance table"
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
              description="Each row's relative abundance."
              data={options(NUMERIC)}
              value={valueCol}
              onChange={(v) => v && patchRoles({ abundance: v })}
              allowDeselect={false}
              searchable
              nothingFoundMessage="No numeric column"
            />
            <Select
              label="Sample column"
              description="A share is the mean over samples of each sample's share; without one the value column is summed."
              data={options(TEXT)}
              value={sampleCol}
              onChange={(v) => v && patchRoles({ abundance_sample: v })}
              allowDeselect={false}
              searchable
            />
            <Select
              label="Split by"
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
