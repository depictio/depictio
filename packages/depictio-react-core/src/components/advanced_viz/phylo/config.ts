import type { Layout } from './layout';

/**
 * The phylogenetic viz's config, as the renderers read it. Mirrors
 * `PhylogeneticConfig` in depictio/models/components/advanced_viz/configs.py.
 */
export interface PhylogeneticConfig {
  tree_wf_id: string;
  tree_dc_id: string;
  /** Each source's portable name, resolved to its ids at import (see
   *  phylo/sources.ts for when the builder writes one). */
  tree_dc_tag?: string | null;
  metadata_wf_id?: string | null;
  metadata_dc_id?: string | null;
  metadata_dc_tag?: string | null;
  taxon_col?: string;
  color_col?: string | null;
  label_col?: string | null;
  /** Extra metadata columns to fetch alongside color_col / label_col, so
   *  they show up in the "Colour by" Select. Use for taxonomic ranks on
   *  ASV trees (Kingdom / Phylum / Class / Order / Family / Genus / Species). */
  extra_color_cols?: string[] | null;
  /** Per-column palette overrides for the "Colour by" selector. Shape:
   *  ``{column_name: {category_value: hex}}``. Lets dashboards pin domain
   *  palettes (e.g. dominant_habitat → Set1) consistently across tiles. */
  category_palettes?: Record<string, Record<string, string>> | null;
  default_layout?: Layout;
  ladderize?: boolean;
  show_metadata_strip?: boolean;
  show_branch_lengths?: boolean;
  show_internal_labels?: boolean;

  // ---- Summary view (PhyloSummaryRenderer) --------------------------------
  /** Metadata column to collapse the tree to, one tip per value. Set, the
   *  component draws the summary instead of the full tree. */
  collapse_rank?: string | null;
  /** How many lineages get a tip; the rest are counted under "not shown". */
  top_n?: number;
  /** What a lineage is sized and ranked by: its tips, or its reads in the
   *  abundance table. */
  size_by?: 'tips' | 'abundance';
  /** The % beside each lineage. Unset, shown only when sized by reads. */
  show_shares?: boolean | null;
  /** Long table of per-sample abundance per lineage (e.g.
   *  `taxonomy_rel_abundance`), with a column named like `collapse_rank`. */
  abundance_wf_id?: string | null;
  abundance_dc_id?: string | null;
  abundance_dc_tag?: string | null;
  abundance_col?: string;
  /** Sample column: a share is the mean over samples; a table without it is
   *  summed instead. */
  abundance_sample_col?: string;
  /** Column of the abundance table to split each lineage's share by (a site),
   *  drawn as a strip of dots beside the tips. */
  abundance_split_col?: string | null;
  /** Draw that strip. Unset, drawn whenever `abundance_split_col` is set. */
  show_split?: boolean | null;
}
