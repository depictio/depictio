/**
 * The short type tag an advanced-viz tile shows after its title in a workbench
 * section (compact density), so a reader can tell the linked views of one
 * structure apart at a glance ("3D", "PAE", "Track") without opening each
 * tile's metadata.
 *
 * Pure data keyed by the component's `viz_kind`. A kind with no obvious short
 * name has no entry and its tile shows no tag. Tags are kept to one short word
 * (or an acronym): the compact header is a single line shared with the title,
 * the echo and the status chips.
 */

const VIZ_KIND_TAG: Readonly<Record<string, string>> = {
  // Protein kinds, the workbench's usual contents.
  molecule_3d: '3D',
  hmm_logo: 'HMM',
  msa: 'MSA',
  sequence_track: 'Track',
  pae_matrix: 'PAE',
  secondary_structure: 'SS',
  ramachandran: 'Rama',
  domain_architecture: 'Domains',
  // Everything else a section can hold.
  volcano: 'Volcano',
  ma: 'MA',
  qq: 'QQ',
  manhattan: 'Manhattan',
  embedding: 'Embedding',
  stacked_taxonomy: 'Taxonomy',
  phylogenetic: 'Tree',
  rarefaction: 'Rarefaction',
  da_barplot: 'DA',
  ancombc_differentials: 'DA',
  enrichment: 'Enrichment',
  complex_heatmap: 'Heatmap',
  upset_plot: 'UpSet',
  dot_plot: 'Dot plot',
  lollipop: 'Lollipop',
  sunburst: 'Sunburst',
  oncoplot: 'Oncoplot',
  coverage_track: 'Coverage',
  sankey: 'Sankey',
  pr_benchmark: 'PR',
  roc_pr_curve: 'ROC',
  confusion_matrix: 'Confusion',
  metric_ci_bars: 'Metrics',
  profile: 'Profile',
  signal_matrix: 'Signal',
  fusion_structure: 'Fusion',
  gene_arrow_track: 'Genes',
  gsea_running_score: 'GSEA',
  sashimi: 'Sashimi',
  scatter_xy: 'Scatter',
  contact_map: 'Contacts',
  knee_plot: 'Knee',
  damage_profile: 'Damage',
  genome_view: 'Genome',
  group_compare: 'Compare',
  transcript_structure: 'Transcript',
  cnv_profile: 'CNV',
  genome_chord: 'Chord',
  parallel_coordinates: 'Parallel',
  // `record_card` is a card of fields, not a figure: no tag.
};

/** The tag for a `viz_kind`, or null when the kind has none (or is not a kind). */
export function vizKindTag(kind: unknown): string | null {
  if (typeof kind !== 'string') return null;
  return Object.prototype.hasOwnProperty.call(VIZ_KIND_TAG, kind) ? VIZ_KIND_TAG[kind] : null;
}

/** Every kind that has a tag, for tests and docs that walk the map. */
export function taggedVizKinds(): string[] {
  return Object.keys(VIZ_KIND_TAG);
}
