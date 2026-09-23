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
   flag and depth, the same UMAP coloured by any gene of the marker panel,
   the feature selection behind the PCA, and the PCA scree.
6. **Clusters**: cluster sizes, composition per sample, QC medians (as a
   heatmap), cell-cycle phase, and how stable the clusters are across
   k-means resolutions.
7. **Markers**: per-cluster marker gene expression (dot plot, heatmap), the
   same markers cell by cell, and differential expression at any clustering
   resolution (volcano, bar plot, table).
8. **Compare selections**: lasso two groups of cells on the UMAP and test
   every panel gene between them.
9. **Aligner concordance** (optional): Cell Ranger against simpleaf/alevin-fry
   and kallisto|bustools, when the megatest fetched all three routes.

The sample hub (`samples`) and the cell-level QC filters (cluster, QC
status, UMI counts, genes detected) are pinned on every tab; the cluster
picked on any of them narrows the cluster summary, marker expression,
marker gene, per-cell expression and cell-cycle tables through the
`cluster_label` cross-DC links, without leaving the tab. Every tab also
carries its own non-persistent filter section for the question that tab
asks: QC band and metric on Library QC, UMIs per barcode on Cell calling,
failing rule and top-20 share on Cell QC, feature selection on Embeddings,
cluster size and cell-cycle phase on Clusters, clustering resolution and
gene on Markers, cluster and QC status on Compare selections, aligner route
and caller agreement on Aligner concordance. The MultiQC tab is the
exception: its only collection is the MultiQC report, which is filtered by
sample mapping rather than by column.

## Tab by tab

### MultiQC
Opens with a pinned "Run at a glance" strip that rides every tab: cells
called, median genes per cell, sequencing saturation and reads in cells, from
Cell Ranger's metrics summary, with a tab-local "Glance scope" slider on the
cells-called count. Then "MultiQC general statistics", "Read quality"
(FastQC), "Cell Ranger summary" (Cell Ranger's own stats + 3 curves). Outside
the pinned strip it holds MultiQC panels only, no pipeline-computed tile
lives here.

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
drew the cell-calling threshold. The "Calling funnel" strip that opens the tab
reads the same filtering as four nested counts (every barcode observed,
called a cell, kept by CellBender, passing the per-cell QC), each a subset
of the one before, so the drop between two stages is the cost of that step
and nothing else. CellBender's cards show how much
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
structure, laid out two by two. A cluster that is uniformly low-depth is a
candidate low-quality population rather than a real cell type; QC-flagged
cells clustering together (rather than scattering) is the same signal from
the other side. Lasso-select on the cluster UMAP feeds the Analysis panel.

"Gene expression on the map" is the same UMAP bound to
`cellranger_cell_expression`, where every panel gene is its own column, so
the tile's Colour-by menu lists them all: type a gene and see where it is
expressed. The panel is the top markers of every graph-based cluster, a
curated PBMC panel and the most dispersed genes, log1p(CP10k) normalised, a
cell with no UMI of the gene reading 0 rather than missing.

"Feature selection" is the step between the count matrix and the PCA that
no dashboard showed: mean expression against normalised dispersion for
every gene Cell Ranger measured, coloured by whether it kept the gene for
the PCA. A gene missing from the embedding is a gene in the grey cloud.
Genes Cell Ranger could not normalise carry no dispersion, and those are
exactly the ones it dropped. The PCA scree then shows how much the first 3
components (used everywhere else) actually explain.

Every scatter and embedding on this tab draws its colour-by and axis
controls as chips under the title (`controls_placement: header`), so
switching the UMAP from cluster to depth to a gene is one click, not a
settings popover.

### Clusters
What to look for: cluster sizes, then the same cluster's QC medians as a
row-z-scored heatmap (`median_pct_mito` dropped: constant 0 on this
reference, which a z-score cannot normalise) and its QC-status split as a
grouped bar, a cluster with a high flagged share is a candidate QC
artefact rather than a cell type. The stability sankey (graphclust ->
kmeans_6 -> kmeans_10) shows whether a graph-based cluster stays a single
ribbon as k grows (stable) or fans out across several k-means clusters
(candidate for further splitting).

The parallel coordinates under the heatmap draw the same cluster summary
as one line per cluster across six axes (cells, share of cells, median
UMIs, median genes, flagged share, CellBender share), each rescaled to its
own range. A small, shallow, heavily flagged cluster bends away from the
rest on several axes at once, which a single bar never shows. Brushing an
axis becomes a range filter on the cluster summary. The Cells per cluster
slider draws its distribution above the handle, like every QC threshold
slider of this template.

"Cell cycle" answers a question Cell Ranger does not: is this cluster a
distinct cell type, or the same type cycling? The S and G2/M scores are
computed from the Tirosh gene sets, each the cell's mean log1p(CP10k) over
the set minus its mean over every measured gene, and the larger score wins
when it is positive, otherwise the cell is G1. A cluster that is mostly S
or G2M next to a G1 cluster with the same markers is one population in two
phases. The composition bar reads each sample's cells as percentages per
cluster, so two samples of different depth stay comparable; this megatest
has one sample, so it draws one bar.

### Markers
What to look for: `cluster_label` names each cluster generically by its top
2 markers, there is no hardcoded tissue panel. The dot plot and heatmap
show which genes are specific to which cluster (large dot / bright cell);
the volcano and bar plot show the same markers by effect size and
significance. Picking a cluster on the pinned Cell QC filters narrows every
tile on this tab through the `cluster_label` link, and the Clustering
resolution filter swaps the graph-based clustering for any of the k-means
ones (Cell Ranger writes a differential-expression table per resolution and
all of them are read, not just the graph-based one).

"Per-cell marker spread" draws the same markers cell by cell rather than as
one number per (cluster, gene). A cluster whose marker is bimodal, high in
half its cells and absent in the other half, is indistinguishable from a
uniform one on a dot plot. Cells are capped per cluster there so the box
stays drawable; the wide matrix behind the Compare selections tab keeps
every cell.
The per-cluster tile is a violin (with its box inside), so a bimodal
marker shows as two bulges.

"Differential expression" pairs the volcano (volcano view only: these are
the markers Cell Ranger kept per cluster, already filtered on
significance, so a QQ view has no null to read against) with a gene
record card. The card opens on FCER1A, the top marker of the
dendritic-cell cluster, and shows one card per (resolution, cluster) row
where the gene ranks as a marker; ticking a gene in the marker table swaps
it, clearing the tick brings FCER1A back. The dot plot's gene sort and
cap sit as chips under its title.

### Compare selections
What to look for: lasso a set of cells on the UMAP, save it as group A,
lasso a second set and save it as group B, then run the comparison: every
gene of the panel is tested between the two groups and drawn as a volcano,
effect size against significance. With no groups saved the tab opens on
the B-cell cluster (C1) against the classical monocytes (C2), already
compared (`auto_run`), so the tile shows a result before you touch it;
the group pickers sit as chips under the title. The values are already log1p(CP10k), so no further
transform is applied, and the test is a Wilcoxon rank-sum. Two caveats:
narrow to `qc_status: pass` first, since a comparison run over flagged
cells is a comparison of QC artefacts, and check that the two groups have
comparable depth, since groups of very different depth differ on almost
every gene for the wrong reason.

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
posterior `.h5`. The `analysis/` tables are a few MB in total, so the
clustering, differential-expression and PCA keys are wildcarded over the
resolution directory rather than pinned to the graph-based one: the
dashboard offers every resolution Cell Ranger ran as a filter, and reads
`dispersion.csv` and `features_selected.csv` for the feature-selection
section.

## Data collections added in the lot 2 pass

Six transformed collections and two raw scans were added, all of them
catalog outputs under `depictio/catalog/cellranger/` so another
Cell-Ranger-based template can reuse them:

| Collection | Rows (pbmc8k) | What it carries |
| --- | --- | --- |
| `cellranger_cell_expression` | 8 767 x 127 | one row per cell, one Float64 column per panel gene (121 here), plus the UMAP coordinates, cluster and QC status |
| `cellranger_cell_expression_long` | 70 686 | the curated panel half, melted to one row per (cell, gene), capped per cluster so a box plot stays drawable |
| `cellranger_hvg_dispersion` | 22 835 | mean expression, normalised dispersion, detection rate and whether the PCA used the gene |
| `cellranger_cell_cycle` | 8 767 | S and G2/M scores per cell and the phase call (G1 5 290 / G2M 1 867 / S 1 610) |
| `cellranger_cell_funnel` | 1 per sample | the four nested stage counts of the filtering waterfall |
| `cellranger_diffexp` | 6 800 | marker genes for every clustering resolution, not only the graph-based one |

The two new raw scans are `cellranger_dispersion_raw`
(`analysis/pca/*/dispersion.csv`) and `cellranger_features_selected_raw`
(`analysis/pca/*/features_selected.csv`, whose header names one column
while its rows carry two, so it is scanned headerless past the first line).

`cell_calls_by_method` and `aligner_summary` moved from pipeline-local
recipes into the catalog as well, so every tile on the Aligner concordance
tab now carries a `use:` handle.

## Portability

Every scan regex in `template.yaml` is anchored with `(?:.*/)?` rather than
on the megatest-only `aligner_cellranger/` prefix, so a run whose results
root is a single aligner's output directory (the ordinary case: the
pipeline default writes one route) scans identically. The route stays
disambiguated by the tool directory name in the path (`cellranger/`,
`simpleaf/`, `kallisto/`), which is what actually separates the three
CellBender scans.

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
