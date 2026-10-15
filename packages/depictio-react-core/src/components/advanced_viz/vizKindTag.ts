/**
 * The short type label an advanced-viz tile shows after its title in a
 * workbench section (compact density), so a reader can tell the linked views
 * of one structure apart at a glance ("3D", "PAE", "Track") without opening
 * each tile's metadata: a word or an acronym, and a small icon for the kind.
 *
 * Pure data keyed by the component's `viz_kind`. A kind with no obvious short
 * name has no entry and its tile shows no label. Tags are kept to one short
 * word (or an acronym): the compact header is a single line shared with the
 * title, the echo and the status chips.
 *
 * The icons are the kind's own in the builder's picker: `KIND_METADATA` in
 * `depictio/models/components/advanced_viz/schemas.py`, which only reaches the
 * browser over the wire, so the ids are repeated here (a test keeps the two in
 * step). A literal icon id in this tree is also what gets the icon bundled
 * (see `scripts/generate-icon-subset.mjs`).
 */

export interface VizKindLabel {
  /** One short word or acronym. */
  tag: string;
  /** Iconify id, the kind's icon in the builder's picker. */
  icon: string;
}

const label = (tag: string, icon: string): VizKindLabel => ({ tag, icon });

const VIZ_KIND: Readonly<Record<string, VizKindLabel>> = {
  // Protein kinds, the workbench's usual contents.
  molecule_3d: label('3D', 'tabler:cube-3d-sphere'),
  hmm_logo: label('HMM', 'tabler:letter-case'),
  msa: label('MSA', 'tabler:align-justified'),
  sequence_track: label('Track', 'tabler:ruler-2'),
  pae_matrix: label('PAE', 'tabler:chart-grid-dots'),
  secondary_structure: label('SS', 'tabler:wave-sine'),
  ramachandran: label('Rama', 'tabler:angle'),
  domain_architecture: label('Domains', 'tabler:timeline'),
  // Everything else a section can hold.
  volcano: label('Volcano', 'tabler:chart-scatter'),
  ma: label('MA', 'tabler:chart-bubble'),
  qq: label('QQ', 'tabler:chart-line'),
  manhattan: label('Manhattan', 'tabler:chart-histogram'),
  embedding: label('Embedding', 'tabler:atom'),
  stacked_taxonomy: label('Taxonomy', 'tabler:chart-pie'),
  phylogenetic: label('Tree', 'tabler:hierarchy-3'),
  rarefaction: label('Rarefaction', 'tabler:chart-line'),
  da_barplot: label('DA', 'tabler:chart-bar-popular'),
  // A legacy kind that became `da_barplot`, so it wears its label.
  ancombc_differentials: label('DA', 'tabler:chart-bar-popular'),
  enrichment: label('Enrichment', 'tabler:chart-dots'),
  complex_heatmap: label('Heatmap', 'tabler:grid-pattern'),
  upset_plot: label('UpSet', 'tabler:chart-bar-popular'),
  dot_plot: label('Dot plot', 'tabler:circle-dot'),
  lollipop: label('Lollipop', 'tabler:chart-arcs'),
  sunburst: label('Sunburst', 'tabler:sun'),
  oncoplot: label('Oncoplot', 'tabler:grid-pattern'),
  coverage_track: label('Coverage', 'tabler:chart-area-line'),
  sankey: label('Sankey', 'tabler:chart-sankey'),
  pr_benchmark: label('PR', 'tabler:target-arrow'),
  roc_pr_curve: label('ROC', 'tabler:chart-line'),
  confusion_matrix: label('Confusion', 'tabler:grid-dots'),
  metric_ci_bars: label('Metrics', 'tabler:chart-bar'),
  profile: label('Profile', 'tabler:chart-line'),
  signal_matrix: label('Signal', 'tabler:grid-pattern'),
  fusion_structure: label('Fusion', 'tabler:arrows-join-2'),
  gene_arrow_track: label('Genes', 'tabler:arrow-big-right-lines'),
  gsea_running_score: label('GSEA', 'tabler:chart-area-line'),
  sashimi: label('Sashimi', 'tabler:chart-arcs'),
  scatter_xy: label('Scatter', 'tabler:chart-dots'),
  contact_map: label('Contacts', 'tabler:layout-grid'),
  knee_plot: label('Knee', 'tabler:trending-down'),
  damage_profile: label('Damage', 'tabler:dna-2'),
  genome_view: label('Genome', 'tabler:dna-2'),
  group_compare: label('Compare', 'tabler:arrows-diff'),
  transcript_structure: label('Transcript', 'tabler:layout-rows'),
  cnv_profile: label('CNV', 'tabler:chart-dots-3'),
  genome_chord: label('Chord', 'tabler:circle-dotted'),
  parallel_coordinates: label('Parallel', 'tabler:chart-line'),
  // `record_card` is a card of fields, not a figure: no label.
};

/** The label for a `viz_kind`, or null when the kind has none (or is not a kind). */
export function vizKindLabel(kind: unknown): VizKindLabel | null {
  if (typeof kind !== 'string') return null;
  return Object.prototype.hasOwnProperty.call(VIZ_KIND, kind) ? VIZ_KIND[kind] : null;
}

/** The tag for a `viz_kind`, or null when the kind has none (or is not a kind). */
export function vizKindTag(kind: unknown): string | null {
  return vizKindLabel(kind)?.tag ?? null;
}

/** Every kind that has a label, for tests and docs that walk the map. */
export function taggedVizKinds(): string[] {
  return Object.keys(VIZ_KIND);
}
