/**
 * The short type label an advanced-viz tile shows after its title in a
 * linked view section (compact density), so a reader can tell the linked views
 * of one structure apart at a glance ("3D", "PAE", "Track") without opening
 * each tile's metadata: a word or an acronym, and a small icon for the kind.
 *
 * Pure data keyed by the component's `viz_kind`. A kind with no obvious short
 * name has no entry and its tile shows no label. Tags are kept to one short
 * word (or an acronym): the compact header is a single line shared with the
 * title, the echo and the status chips. The acronym is cryptic on its own, so
 * each label also carries a one-line description, shown as the badge's tooltip.
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
  /** What the view shows, in one plain-English line (about 90 characters at
   *  most, no jargon the tag does not already carry), for the badge's tooltip.
   *  A label without one falls back to the tag as a native title. */
  description?: string;
}

const label = (tag: string, icon: string, description?: string): VizKindLabel =>
  description ? { tag, icon, description } : { tag, icon };

const VIZ_KIND: Readonly<Record<string, VizKindLabel>> = {
  // Protein kinds, the linked view's usual contents.
  molecule_3d: label(
    '3D',
    'tabler:cube-3d-sphere',
    '3D structure, coloured by confidence, chain or a per-residue value',
  ),
  hmm_logo: label('HMM', 'tabler:letter-case', 'Profile HMM logo: residue conservation per match state'),
  msa: label(
    'MSA',
    'tabler:align-justified',
    'Multiple sequence alignment, one row per sequence, with consensus and conservation',
  ),
  sequence_track: label(
    'Track',
    'tabler:ruler-2',
    'Per-residue tracks along the sequence (confidence, conservation, domains)',
  ),
  pae_matrix: label(
    'PAE',
    'tabler:chart-grid-dots',
    'Predicted aligned error between residue pairs (AlphaFold PAE)',
  ),
  secondary_structure: label(
    'SS',
    'tabler:wave-sine',
    'Secondary structure per residue (helix, strand, coil)',
  ),
  ramachandran: label('Rama', 'tabler:angle', 'Ramachandran plot of backbone dihedral angles (phi/psi)'),
  domain_architecture: label(
    'Domains',
    'tabler:timeline',
    'Domain architecture: domain hits along each protein',
  ),
  // Everything else a section can hold.
  volcano: label(
    'Volcano',
    'tabler:chart-scatter',
    'Effect size against significance, with threshold lines and top hits labelled',
  ),
  ma: label(
    'MA',
    'tabler:chart-bubble',
    'Mean intensity against log2 fold change, the same hits as a volcano plot',
  ),
  qq: label(
    'QQ',
    'tabler:chart-line',
    'Observed against expected -log10(p), a check on the p-value distribution',
  ),
  manhattan: label(
    'Manhattan',
    'tabler:chart-histogram',
    'Association score along the genome, by chromosome and position',
  ),
  embedding: label('Embedding', 'tabler:atom', '2D or 3D sample embedding (PCA, UMAP, t-SNE or PCoA)'),
  stacked_taxonomy: label(
    'Taxonomy',
    'tabler:chart-pie',
    'Relative abundance of taxa per sample, stacked, at a chosen rank',
  ),
  phylogenetic: label(
    'Tree',
    'tabler:hierarchy-3',
    'Phylogenetic tree with tip metadata, several layouts and subtree highlight',
  ),
  rarefaction: label(
    'Rarefaction',
    'tabler:chart-line',
    'Alpha diversity against sequencing depth, one curve per sample',
  ),
  da_barplot: label(
    'DA',
    'tabler:chart-bar-popular',
    'Differential abundance: top features ranked by signed log fold change',
  ),
  // A legacy kind that became `da_barplot`, so it wears its label.
  ancombc_differentials: label(
    'DA',
    'tabler:chart-bar-popular',
    'Differential abundance: top features ranked by signed log fold change',
  ),
  enrichment: label(
    'Enrichment',
    'tabler:chart-dots',
    'Pathway enrichment: terms by NES, sized by gene-set size, coloured by adjusted p',
  ),
  complex_heatmap: label(
    'Heatmap',
    'tabler:grid-pattern',
    'Clustered heatmap with dendrograms and annotation tracks',
  ),
  upset_plot: label(
    'UpSet',
    'tabler:chart-bar-popular',
    'Set intersections as a matrix with size bars, an alternative to Venn diagrams',
  ),
  dot_plot: label(
    'Dot plot',
    'tabler:circle-dot',
    'Marker dot plot: size is the fraction expressing, colour the mean expression',
  ),
  lollipop: label('Lollipop', 'tabler:chart-arcs', 'Variants along a gene as stems, coloured by consequence'),
  sunburst: label('Sunburst', 'tabler:sun', 'Hierarchy as concentric rings, from root to leaf'),
  oncoplot: label(
    'Oncoplot',
    'tabler:grid-pattern',
    'Sample by gene mutation matrix, coloured by mutation type',
  ),
  coverage_track: label('Coverage', 'tabler:chart-area-line', 'Read depth or signal along a coordinate axis'),
  sankey: label('Sankey', 'tabler:chart-sankey', 'Flow between ordered categorical levels'),
  pr_benchmark: label(
    'PR',
    'tabler:target-arrow',
    'Recall against precision per callset, with F1 iso-contours',
  ),
  roc_pr_curve: label(
    'ROC',
    'tabler:chart-line',
    'Precision-recall curve over thresholds with AUC, one line per tool',
  ),
  confusion_matrix: label(
    'Confusion',
    'tabler:grid-dots',
    'True and false positive and negative counts per callset, as a heatmap',
  ),
  metric_ci_bars: label(
    'Metrics',
    'tabler:chart-bar',
    'Precision, recall and F1 bars with 95% confidence intervals',
  ),
  profile: label(
    'Profile',
    'tabler:chart-line',
    'Curves over a shared axis, such as metagene or fragment-length profiles',
  ),
  signal_matrix: label(
    'Signal',
    'tabler:grid-pattern',
    'One row per region, one column per offset: the heatmap half of a metagene plot',
  ),
  fusion_structure: label(
    'Fusion',
    'tabler:arrows-join-2',
    'Gene fusion: both partners end to end, with protein domains and the breakpoint',
  ),
  gene_arrow_track: label(
    'Genes',
    'tabler:arrow-big-right-lines',
    'Strand-aware gene arrows on a base-pair axis, one lane per contig',
  ),
  gsea_running_score: label(
    'GSEA',
    'tabler:chart-area-line',
    'GSEA enrichment-score curve over the ranked list, with its hits',
  ),
  sashimi: label(
    'Sashimi',
    'tabler:chart-arcs',
    'Splice junction arcs on a base-pair axis, wider with more supporting reads',
  ),
  scatter_xy: label(
    'Scatter',
    'tabler:chart-dots',
    'Numeric against numeric, with optional colour, size and labels',
  ),
  contact_map: label(
    'Contacts',
    'tabler:layout-grid',
    'Hi-C style contact matrix between binned genomic regions',
  ),
  knee_plot: label(
    'Knee',
    'tabler:trending-down',
    'Barcode-rank curve: UMI count against rank, with the cell-calling cutoff',
  ),
  damage_profile: label(
    'Damage',
    'tabler:dna-2',
    'Ancient-DNA damage: substitution frequency by position from the read end',
  ),
  genome_view: label(
    'Genome',
    'tabler:dna-2',
    'Scores along the chromosomes on a zoomable genome axis, with a region brush',
  ),
  group_compare: label(
    'Compare',
    'tabler:arrows-diff',
    'Differential test between two saved selection groups',
  ),
  transcript_structure: label(
    'Transcript',
    'tabler:layout-rows',
    'Isoforms of one gene stacked on a base-pair axis, exons as blocks',
  ),
  cnv_profile: label(
    'CNV',
    'tabler:chart-dots-3',
    'Copy-number log2 ratio along the genome, with the called segments',
  ),
  genome_chord: label(
    'Chord',
    'tabler:circle-dotted',
    'Links between genomic loci, drawn as chords on a chromosome ring',
  ),
  parallel_coordinates: label(
    'Parallel',
    'tabler:chart-line',
    'One line per sample across several metric axes, each one brushable',
  ),
  ranked_distribution: label(
    'Ranked',
    'tabler:chart-candle',
    'Top features ranked by a score, each with its distribution across samples',
  ),
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
