# nf-core/scrnaseq 4.2.0 reference dashboard

Built against the nf-core/scrnaseq 4.2.0 AWS megatest, one sample (`pbmc8k`,
10x Genomics v2 chemistry, GRCh38). `DATA_ROOT` is now the megatest RESULTS
ROOT, holding one directory per `--aligner` route: `aligner_cellranger/`
(required, the pipeline default, the only route with matrices, secondary
analysis and a MultiQC report), `aligner_simpleaf/` and `aligner_kallisto/`
(optional, tables-and-JSON only, feed the Aligner concordance tab).
`aligner_star/` publishes nothing this dashboard reads.

## Funnel

1. **MultiQC** (landing tab): FastQC on the raw reads, then Cell Ranger
   count's own summary stats table and its three QC curves (barcode-rank,
   median genes per cell, sequencing saturation), read from the Cell Ranger
   route's MultiQC 1.35 parquet.
2. **Library QC**: Cell Ranger's headline library metrics against 10x's own
   pass/warn/fail bands, and where confidently-mapped reads land in the
   genome.
3. **Cell calling**: the barcode-rank ("knee") curve computed independently
   of MultiQC straight off the raw feature-barcode matrix, and CellBender's
   ambient-RNA removal accounting.
4. **Cell QC**: the MAD-based flag every other tab can filter on, and the
   distributions behind it.
5. **Embeddings**: UMAP and t-SNE against the graph-based clusters, the QC
   flag and depth, plus the PCA scree behind them.
6. **Clusters**: cluster sizes, QC medians (as a heatmap) and how stable
   they are across k-means resolutions.
7. **Markers**: per-cluster marker gene expression (dot plot, heatmap) and
   differential expression (volcano, bar plot, table).
8. **Aligner concordance** (optional): Cell Ranger against simpleaf/alevin-fry
   and kallisto|bustools, when the megatest fetched all three routes.

The sample hub (`samples`) and the cell-level QC filters (cluster, QC
status, mito %, genes detected) are pinned on every tab; the cluster picked
on any of them narrows the cluster summary, marker expression and marker
gene tables through the `cluster_label` cross-DC links, without leaving the
tab.

## Tab by tab

### MultiQC
Unchanged in shape: "Run at a glance" (general stats), "Read quality"
(FastQC), "Cell Ranger summary" (Cell Ranger's own stats + 3 curves). Holds
MultiQC panels only, no pipeline-computed tile lives here.

### Library QC
What to look for: `Cells called` against `expected_cells` on the pinned
sample sheet, a large gap is worth a second look before trusting anything
downstream. The 5 thresholded metrics (sequencing saturation, fraction
reads in cells, valid barcodes, Q30 RNA, confidently-mapped-to-transcriptome)
each carry a pass/warn/fail band in the table; the mapping breakdown is
grouped, not stacked, because `antisense` overlaps `exonic`/`intronic` by
Cell Ranger's own definition and a 100%-stacked bar would misread as a
partition. The MultiQC saturation curve is intentionally not repeated here
(MultiQC-only rule), the card and table give the same reading as a number.

### Cell calling
What to look for: the knee in the barcode-rank curve is where Cell Ranger
drew the cell-calling threshold; the histogram below shows the same UMI
totals as a distribution instead of a rank order, the "cells" and
"background" colours should barely overlap. CellBender's cards show how much
of the raw signal it called ambient and how many barcodes it kept as cells;
the agreement card counts how many of Cell Ranger's own called cells
CellBender's independent model also keeps, a large gap flags a dataset
where the two cell-calling strategies disagree.

### Cell QC
What to look for: the MAD rules (sc-best-practices convention, computed
per sample on log1p values) flag a cell as a low-UMI, low-gene, high-top20
or high-mito outlier. **This reference has no mitochondrial genes** (the
bundled pbmc8k GRCh38 carries zero `MT-*` features), so `pct_mito` and
`mad_high_mito` read 0 / false for every cell on this megatest; the rule is
unchanged and will activate against a reference that does carry them. The
reading here leads with UMI / gene counts, the top-20 share and the
ribosomal fraction instead. The scatter (UMI vs genes, coloured by QC
status) and the two box plots (ribosomal fraction, log10 UMI, both by
cluster) show whether flagged cells sit apart from the main cloud or are
concentrated in a specific cluster, the latter is a candidate real cell
type, not noise.

### Embeddings
What to look for: the same UMAP read three ways, by cluster, by depth
(log10 genes detected, since the mito-based reading is empty here) and by
QC status, then t-SNE by cluster as a second projection of the same
structure. A cluster that is uniformly low-depth is a candidate low-quality
population rather than a real cell type; QC-flagged cells clustering
together (rather than scattering) is the same signal from the other side.
Lasso-select on the cluster UMAP feeds the Analysis panel. The PCA scree
shows how much of the first 3 components (used everywhere else) actually
explain.

### Clusters
What to look for: cluster sizes, then the same cluster's QC medians as a
row-z-scored heatmap (`median_pct_mito` dropped: constant 0 on this
reference, which a z-score cannot normalise) and its QC-status split as a
grouped bar, a cluster with a high flagged share is a candidate QC
artefact rather than a cell type. The stability sankey (graphclust ->
kmeans_6 -> kmeans_10) shows whether a graph-based cluster stays a single
ribbon as k grows (stable) or fans out across several k-means clusters
(candidate for further splitting).

### Markers
What to look for: `cluster_label` names each cluster generically by its top
2 markers, there is no hardcoded tissue panel. The dot plot and heatmap
show which genes are specific to which cluster (large dot / bright cell);
the volcano and bar plot show the same markers by effect size and
significance. Picking a cluster on the pinned Cell QC filters narrows every
tile on this tab through the `cluster_label` link.

### Aligner concordance (optional)
What to look for: **a Cell Ranger-only run (the pipeline default) leaves
every tile on this tab empty**, every collection feeding it is optional.
When simpleaf and/or kallisto were also run, the cards compare cells
called, CellBender cells and mapping rate per route; the UpSet plot shows
how the routes' cell calls (plus CellBender on each) agree on the same
physical barcode, normalised to the bare 16-mer since Cell Ranger's own
barcodes carry a `-1` GEM-well suffix the other routes do not; the two knee
curves (Cell Ranger, simpleaf) are drawn on the same log-log axes and are
directly comparable side by side.

## Data not fetched (see `megatest.yaml` for the full rationale)

`possorted_genome_bam.bam`, `output*.bus` (tens of GB, any route), the
`.h5` / `.h5ad` / `.cloupe` / `.rds` / molecule_info binaries, the `mkref/`
reference index, the alevin-fry `map.rad` / `map.collated.rad` and kallisto
`matrix.ec` / `transcripts.txt` intermediates, CellBender's checkpoint and
posterior `.h5`, and the k-means clusterings beyond what `cellranger_cell_qc`
needs (the graph-based clustering is what Cell Ranger reports on and what
the marker-gene tabs use).

## Barcode collisions

Cell Ranger writes identically-named files (`matrix.mtx.gz`,
`barcodes.tsv.gz`, `features.tsv.gz`) under both `raw_feature_bc_matrix/`
and `filtered_feature_bc_matrix/`; the scan regexes for these match on the
parent directory as well as the file name. CellBender writes identically
named files (`*_metrics.csv`, `*_cell_barcodes.csv`) under all three
aligner routes' `cellbender_removebackground/` dirs; every CellBender scan
is qualified with its route (`aligner_cellranger/cellranger/...`,
`aligner_simpleaf/simpleaf/...`, `aligner_kallisto/kallisto/...`) so a
route's own hub or the concordance table never silently pulls in another
route's rows.

## MultiQC module

`cellranger` is a MultiQC module for this catalog
(`depictio/catalog/multiqc/cellranger.yaml`). `plots:` / `selected_plot:`
in `template.yaml` / `dashboards/base.yaml` are the bare MultiQC **section**
names (`Section.name`), not the plot's internal title:

- `Count - Summary stats`
- `Count - BC rank plot`
- `Count - Median genes`
- `Count - Saturation plot`
