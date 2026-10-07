/**
 * The data collections a phylogenetic viz reads, as the builder binds them.
 *
 * A tree is not one table. It is a Newick DC (the tree), a table of tip
 * metadata joined to it on the tip label, and, for the summary sized by reads,
 * a long table of per-sample abundance. Each is named in the config by three
 * keys, `<source>_wf_id`, `<source>_dc_id` and `<source>_dc_tag`, the same keys
 * a dashboard YAML writes, so a tree bound in the builder and one written by
 * hand are the same config (PhylogeneticConfig in configs.py).
 *
 * Pure functions; the builder's React side is
 * depictio/viewer/src/builder/advanced_viz/PhylogeneticSections.tsx.
 */

/** A data collection of the project, as the builder lists it. */
export interface PhyloDcRef {
  wfId: string;
  dcId: string;
  tag?: string | null;
  /** The DC's `config.type`: `phylogeny` for a tree, `table` otherwise. */
  type?: string | null;
  /** A tree DC's own pointer to its tip metadata, by tag
   *  (`dc_specific_properties.metadata_dc_tag`, DCPhylogenyConfig). */
  metadataTag?: string | null;
  /** The column of that table holding the tip labels
   *  (`dc_specific_properties.metadata_taxon_column`). */
  metadataTaxonColumn?: string | null;
}

export type PhyloSource = 'tree' | 'metadata' | 'abundance';

/**
 * The config patch that binds `source` to `dc`, or unbinds it (`dc` null).
 *
 * The tag is written beside the ids only when the import can resolve it: a
 * dashboard import looks a `<source>_dc_tag` up in the component's own
 * workflow and rewrites the ids from it, clearing them when it finds nothing.
 * A tag naming a DC of another workflow would therefore unbind a config that
 * worked, so such a DC is bound by id alone, which is what it was before. And a
 * tag is always written, null included: a stale one left over from a YAML
 * import would otherwise take the binding back to the old table on the next
 * export and import.
 */
export function phyloSourcePatch(
  source: PhyloSource,
  dc: PhyloDcRef | null,
  componentWfId: string | null,
): Record<string, string | null> {
  if (!dc) {
    return { [`${source}_wf_id`]: null, [`${source}_dc_id`]: null, [`${source}_dc_tag`]: null };
  }
  return {
    [`${source}_wf_id`]: dc.wfId,
    [`${source}_dc_id`]: dc.dcId,
    [`${source}_dc_tag`]: componentWfId && dc.wfId === componentWfId ? dc.tag || null : null,
  };
}

/** Names a tip-label column goes by. Mirrors the `taxon` aliases of
 *  `ROLE_NAMES["phylogenetic"]` in depictio/models/components/advanced_viz/schemas.py. */
export const TIP_LABEL_ALIASES: readonly string[] = [
  'taxon',
  'tip',
  'tip_label',
  'label',
  'leaf',
  'name',
];

/** The column of a tip-metadata table that holds the tip labels: the one the
 *  tree declares when the table has it, else the first column named like one
 *  (in alias order, so `taxon` beats a generic `name`), else null. */
export function tipLabelColumn(columns: string[], declared?: string | null): string | null {
  if (declared && columns.includes(declared)) return declared;
  const byLower = new Map(columns.map((c) => [c.toLowerCase(), c] as const));
  for (const alias of TIP_LABEL_ALIASES) {
    const hit = byLower.get(alias);
    if (hit) return hit;
  }
  return null;
}

/**
 * The table to pre-select as a tree's tip metadata, by dc id, or null.
 *
 * In order of how sure it is: the table the tree itself names
 * (`metadata_dc_tag` on the phylogeny DC, which is how an ingested tree says
 * where its annotations are); the component's own DC when that is a table (the
 * author started from the metadata and picked the tree kind); then, when the
 * caller has fetched them, the first table with a tip-label column. A tag can
 * repeat across workflows, so the tree's own workflow is preferred for it.
 */
export function preferredTipMetadata(
  tables: PhyloDcRef[],
  hints: {
    tree?: PhyloDcRef | null;
    bound?: PhyloDcRef | null;
    columns?: Record<string, string[]>;
  },
): string | null {
  const { tree, bound, columns } = hints;
  if (tree?.metadataTag) {
    const tagged = tables.filter((t) => t.tag === tree.metadataTag);
    const hit = tagged.find((t) => t.wfId === tree.wfId) ?? tagged[0];
    if (hit) return hit.dcId;
  }
  if (bound && tables.some((t) => t.dcId === bound.dcId)) return bound.dcId;
  if (columns) {
    const hit = tables.find((t) => tipLabelColumn(columns[t.dcId] ?? []) != null);
    if (hit) return hit.dcId;
  }
  return null;
}

/**
 * Which ranks an abundance table can size the summary by.
 *
 * The summary joins the abundance table to the tree by name: it groups the
 * table on the column called like `collapse_rank` (see `aggregateAbundance`).
 * A rank the table has no column for is not an error, the summary falls back
 * to sizing by tips and says so in its legend, but it is worth knowing before
 * that happens.
 */
export function abundanceRankCoverage(
  ranks: string[],
  columns: string[],
): { joined: string[]; missing: string[] } {
  const have = new Set(columns);
  return {
    joined: ranks.filter((r) => have.has(r)),
    missing: ranks.filter((r) => !have.has(r)),
  };
}
