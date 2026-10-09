# nf-core/scrnaseq 4.2.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
reads to the cells, their clusters and the genes that mark them. It follows the family rules
in `depictio/projects/nf-core/RULES.md`, with nf-core/ampliseq 2.18.0 as the reference.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the reads and Cell Ranger's own QC hold for every sample? |
| Data & QC | Library QC | Do the libraries meet 10x Genomics' own QC guidance? |
| Cells | Cell Calling | How many barcodes are cells, and how much ambient RNA was removed? |
| Cells | Aligner Concordance | Do Cell Ranger, simpleaf and kallisto call the same cells? |
| Cells | Cell QC | Which called cells do the MAD rules flag, and why? |
| Cells | Embeddings | Do the cells separate into groups on the UMAP and t-SNE? |
| Cells | Clusters | Which clusters are large and clean, and which are cycling? |
| Genes | Markers | Which genes mark each cluster? |
| Genes | Compare Selections | Which genes separate two groups of cells you lasso? |

[nf-core/scrnaseq](https://nf-co.re/scrnaseq) quantifies droplet single-cell RNA-seq with
Cell Ranger (and, with `--aligner`, simpleaf or kallisto | bustools) and removes ambient RNA
with CellBender. `DATA_ROOT` is the results root, holding one directory per `--aligner`
route: `aligner_cellranger/` (required, the pipeline default, the only route with matrices,
secondary analysis and a MultiQC report), `aligner_simpleaf/` and `aligner_kallisto/`
(optional, tables and JSON only, read by the Aligner Concordance tab). `aligner_star/`
publishes nothing this dashboard reads.

## Template variables

| Variable | Required | What it does |
| --- | --- | --- |
| `DATA_ROOT` | yes | results root, one directory per `--aligner` route |
| `MARKER_PANEL` | no | comma-separated gene symbols the per-cell marker tiles always carry (the Markers violins, the gene UMAP's colour menu) |

`MARKER_PANEL` replaces the fixed panel earlier versions hardcoded. It is forwarded to
`cellranger/cell_expression.py` and `cellranger/cell_expression_long.py` as their
`marker_panel` transform param (see `depictio/recipes/lib/scrnaseq_panels.py`). Without it,
or when none of its genes is in the reference (a mouse run typed with human symbols, for
example), the recipes fall back to the top markers of every graph-based cluster from
`cellranger_diffexp`: 5 per cluster in the wide matrix, 2 per cluster (at most 24 genes) in
the long table the violins read. Neither recipe raises on an empty intersection. A run
passes the lineage markers it wants to see as `--var MARKER_PANEL=<GENE>,<GENE>,...`.

Two readings stay human-specific and are documented rather than hidden: the mitochondrial
share and the MAD mitochondrial rule read gene symbols starting with `MT-` (they read 0 on
another organism, or on a reference without mitochondrial genes, as the megatest's bundled
reference is), and the cell-cycle scores read the human Tirosh gene sets (the phase degrades
to NA elsewhere). The dashboard therefore leads with the top-20 gene share and the ribosomal
share, and drops a QC measure that is constant over the clusters from the cluster profile.

Cell Ranger clusters each sample on its own, so a cluster id (`C1`) or a `cluster_label`
(`C1` followed by its two top markers) names a population within its own sample. On a
multi-sample run, a label or a colour shared by two samples is not the same population; the
cluster-size bars draw one panel per sample for that reason.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples from
  the sample hub; the aligner, the protocol and the genome from the run parameters).
- **Pipeline**: five steps (reads, count, call, flag, cluster). Each step opens the
  parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Cells called
  (split into passing and flagged), the median genes per cell (with the spread over cells),
  the graph-based clusters (with the share the five largest hold) and the marker genes
  (up-regulated in a graph-based cluster at adjusted p below 0.05, with how many mark more
  than one cluster). A QC status and a sample filter above them narrow these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the cells called out of the barcodes observed, the share of called cells flagged
  and the most common rule, the largest cluster's share of the cells, and the number of
  marker genes. Below them, four figures in two rows, each linking its tab: the UMAP by
  cluster beside the barcode-rank curve, then the cells per cluster (flagged stacked on top)
  beside the strongest marker of each cluster. The bar of this section filters by sample and
  cluster.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (the sample hub's `sample_id`) sit in the collapsed left
panel and narrow every tab through the sample links. The persistent `Cell filters` (cluster,
QC status, UMIs and genes per cell, on the per-cell QC table) sit collapsed at the bottom of
the panel on the tabs that draw cells (Cell QC, Embeddings, Clusters, Markers); the cluster
picked there narrows the cluster summary, marker, expression and cell-cycle tables through
the `cluster_label` links. The `Sample sheet` section is pinned to the bottom of every child
tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to read
the tab), then a strip of key numbers, each card with its own colour and a secondary that
reads it, then at most three open sections; tables and details follow, collapsed. The
left-panel filters of a tab narrow its strip too.

**MultiQC.** MultiQC panels only. Open: the general statistics and Cell Ranger count's
summary table, then its median-genes and saturation curves, then the FastQC sequence counts
and per-sequence quality. Collapsed: GC content and duplication, which runs high by design.
Cell Ranger's own barcode-rank panel is left out: the Cell Calling tab draws the same curve
with the called cells marked.

**Library QC.** Strip: reads in cells, sequencing saturation and reads on the transcriptome
as levels out of 100 (a one-sample run still reads them), and reads per cell with the samples
counted against the 20,000 10x recommends. Then each library metric (saturation, reads in
cells, valid barcodes, Q30 on the RNA read, mapped to the transcriptome) as a dot coloured by
its verdict beside the 10x cut-off (a grey tick, its colour declared in `category_colors`
under `status`), and the mapping breakdown by region, grouped rather than
stacked because `antisense` overlaps `exonic` and `intronic` by Cell Ranger's own definition.
Collapsed: the checks table and every column of Cell Ranger's metrics summary. Filters: the
check verdict and the mapping region.

**Cell Calling.** Strip: the barcodes observed, followed down to the cells called, the cells
CellBender keeps and the cells that pass QC (each stage a subset of the one before), and the
UMI counts CellBender keeps out of the raw counts. Then the barcode-rank ("knee") curve,
computed off the raw matrix, called cells marked. Collapsed: the funnel table and CellBender's
metrics. Filter: UMIs per barcode.

**Aligner Concordance.** Strip: cells called per route and the barcodes any method calls,
split by how many methods agree. Then each route's own call against CellBender's on it (the
diagonal is agreement) beside its mapping rate, and the UpSet of the five cell calls (three
routes, CellBender on two of them) on the bare 16-base barcode. Collapsed: simpleaf's knee
curve and both tables. Filters: aligner route and methods agreeing.

**Cell QC.** Strip: called cells as a ring by the rule that flags them, UMIs per cell (with
their distribution), genes per cell (with their spread) and the top-20 gene share. Then UMIs
against genes per cell on log axes, coloured by QC status, and per cluster the UMIs and the
top-20 share as boxes. Collapsed: the per-cell table with a record card beside it. The MAD
rules (sc-best-practices convention, per sample, on log1p values): 5 MAD below the median for
UMIs and genes, 5 MAD above for the top-20 share, and median plus 3 MAD or 8% for the
mitochondrial share. Filters: failing rule and top-20 gene share.

**Embeddings.** Strip: cells on the map (with the share the five largest clusters hold), the
genes scored for dispersion as a ring of those selected for the PCA, the first principal
component's share of the variance (the line follows the next ones) and the genes whose
normalised dispersion passes 0.5 (the Seurat and Scanpy default; the dispersion is centred
per expression bin, so its median is 0 on every run), with their dispersions as a histogram.
Then the UMAP by cluster, and the same UMAP bound to
`cellranger_cell_expression`, where every panel gene is a column of the colour menu (it opens
coloured by cluster; no gene is hardcoded). Collapsed: the t-SNE, the mean expression against
dispersion scatter and the variance per component. Cell Ranger's `features_selected.csv`
lists every gene with a finite dispersion, so the selection separates the genes Cell Ranger
could normalise from the others, not variable from non-variable genes. Filters: ribosomal
share and normalised dispersion.

**Clusters.** Strip: cells (with the share the five largest clusters hold), the flagged share
of the highest cluster with every cluster counted against 5% and 10%, cells by cell-cycle
phase, and the share of the lowest cluster's cells CellBender also calls, with every cluster
counted against 95% and 90%. Most clusters flag no cell and CellBender keeps nearly every
cell, so a median would sit at 0 and 100 on every run. Then the cells per cluster with the flagged ones stacked on top, the cluster QC
profile (median UMIs, median genes, mitochondrial, flagged and CellBender shares, each row
coloured by its z-score across clusters and printed with the cluster's own value), and the
cell cycle: S against G2/M score per cell beside the phase mix of each cluster. Collapsed: the
stability Sankey (graph-based, then k-means with 6 and 10 clusters, the resolutions Cell
Ranger computes by default) and the cluster table. The cell-cycle scores come from the Tirosh
gene sets, each the cell's mean log1p(CP10k) over the set minus its mean over every measured
gene; the larger positive score wins, otherwise G1. Filters: cells per cluster and phase.

**Markers.** Strip: the marker genes up-regulated at adjusted p below 0.05 (with how many
recur across clusters) and their median log2 fold change, up-regulated markers only. Then the
dot plot (dot size the share of the cluster's cells expressing the gene, colour its mean),
and the volcano (volcano view only: these are Cell Ranger's top-ranked markers per cluster,
not a genome-wide test, so a QQ plot has no null to compare against; the five strongest
genes are named) beside the strongest marker of each cluster. Collapsed: the markers cell by cell as violins (one panel per gene;
the gene filter narrows them to one), the marker table with a gene record beside it, and the
marker expression table. The record's Ensembl link uses the species-agnostic
`https://www.ensembl.org/Multi/Search/Results?q={gene_id}` search. Filters: the clustering
(opens on `graphclust`) and the gene shown cell by cell.

**Compare Selections.** Strip: cells on the map, as a ring by QC status, and the clusters on
it. Then the UMAP with lasso on: save a set as group A, a second as group B, and every gene
of the marker panel is tested between them (Wilcoxon rank-sum on the log1p(CP10k) values,
FDR-corrected across genes, cached server-side). With no groups saved it compares the two
largest clusters. Narrow to `pass` cells first: two groups of very different depth differ on
almost every gene for the wrong reason. Filters: clusters on the map and QC status.

## Routes and pruning

Every Key figure, Findings row and highlight reads the Cell Ranger route, which every run
writes. The optional collections prune only what reads them:

| Route | What changes |
|---|---|
| `--skip_cellbender` | No CellBender card or table on Cell Calling (the funnel card widens). The funnel's CellBender stage and the CellBender shares on Clusters read empty. |
| Cell Ranger only (the default `--aligner`) | No Aligner Concordance tab: every collection it reads is optional. |
| simpleaf or kallisto alongside Cell Ranger | The Aligner Concordance tab fills; simpleaf's knee sits collapsed on it. |

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: QC status (green
pass, red flagged), the failing rule, the library check verdict, the cell-cycle phase, the
gene selection, the aligner route and the mapping region are written out, and samples are
coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a re-import).
Clusters keep the default palette: their labels carry the run's own marker genes, so no
template can name them.

## Cross-selection

Every scatter and embedding of cells selects on `barcode` (the UMI against genes scatter, the
UMAP and t-SNE, the phase scatter, the lasso UMAP), the aligner scatter on `aligner`, and the
tables on their entity column (`sample_id` in the sample hub, `sample` in the metrics and
funnel tables, `barcode` for cells, `cluster_label` for clusters, `gene` for markers,
`aligner` for routes, `barcode_core` for the cell-call overlap). A pick narrows the other tiles
on the same collection or linked to it. The Cell QC and Markers tabs each carry a record card
beside the table that drives it (`linked_component`): the card stays a thin rail until a row
or cell is picked, then shows that record.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of a
narrower one. Nothing is set per tab or per tile.

## Data not fetched (see `megatest.yaml` for the full rationale)

`possorted_genome_bam.bam`, `output*.bus` (tens of GB, any route), the `.h5` / `.h5ad` /
`.cloupe` / `.rds` / molecule_info binaries, the `mkref/` reference index, the alevin-fry
`map.rad` / `map.collated.rad` and kallisto `matrix.ec` / `transcripts.txt` intermediates,
CellBender's checkpoint and posterior `.h5`. The `analysis/` tables are a few MB in total, so
the clustering, differential-expression and PCA keys are wildcarded over the resolution
directory rather than pinned to the graph-based one: the dashboard offers every resolution
Cell Ranger ran as a filter, and reads `dispersion.csv` and `features_selected.csv` for the
feature selection.

## Data collections added in the lot 2 pass

Six transformed collections and two raw scans were added, all of them catalog outputs under
`depictio/catalog/cellranger/` so another Cell Ranger-based template can reuse them:

| Collection | What it carries |
| --- | --- |
| `cellranger_cell_expression` | one row per cell, one Float64 column per panel gene (`MARKER_PANEL`, the top 5 markers per cluster and the most dispersed genes), plus the UMAP coordinates, cluster and QC status |
| `cellranger_cell_expression_long` | the marker-panel slice (`MARKER_PANEL`, else the top 2 markers per cluster, at most 24 genes), melted to one row per (cell, gene), capped per cluster so a violin stays drawable |
| `cellranger_hvg_dispersion` | mean expression, normalised dispersion, detection rate and whether the PCA used the gene |
| `cellranger_cell_cycle` | S and G2/M scores per cell and the phase call |
| `cellranger_cell_funnel` | the four nested stage counts of the calling funnel, one row per sample |
| `cellranger_diffexp` | marker genes for every clustering resolution, not only the graph-based one |

The two raw scans are `cellranger_dispersion_raw` (`analysis/pca/*/dispersion.csv`) and
`cellranger_features_selected_raw` (`analysis/pca/*/features_selected.csv`, whose header
names one column while its rows carry two, so it is scanned headerless past the first line).

`cell_calls_by_method` and `aligner_summary` live in the catalog as well, so every tile on
the Aligner Concordance tab carries a `use:` handle. `simpleaf_cellbender_metrics` and
`kallisto_cellbender_metrics` run pipeline-local recipes
(`nf-core/scrnaseq/simpleaf_cellbender_metrics.py`,
`nf-core/scrnaseq/kallisto_cellbender_metrics.py`) that reuse the catalog
`cellbender/metrics.py` transform on the route's own raw scan, so each route reports its own
CellBender numbers.

## Portability

Every scan regex in `template.yaml` is anchored with `(?:.*/)?` rather than on the
megatest-only `aligner_cellranger/` prefix, so a run whose results root is a single aligner's
output directory (the ordinary case: the pipeline default writes one route) scans
identically. The route stays disambiguated by the tool directory name in the path
(`cellranger/`, `simpleaf/`, `kallisto/`), which is what actually separates the three
CellBender scans.

## Barcode collisions

Cell Ranger writes identically named files (`matrix.mtx.gz`, `barcodes.tsv.gz`,
`features.tsv.gz`) under both `raw_feature_bc_matrix/` and `filtered_feature_bc_matrix/`; the
scan regexes for these match on the parent directory as well as the file name. CellBender
writes identically named files (`*_metrics.csv`, `*_cell_barcodes.csv`) under all three
aligner routes' `cellbender_removebackground/` directories; every CellBender scan is
qualified with its route (`aligner_cellranger/cellranger/...`, `aligner_simpleaf/simpleaf/...`,
`aligner_kallisto/kallisto/...`) so a route's own hub or the concordance table never silently
pulls in another route's rows.

## MultiQC module

`cellranger` is a MultiQC module for this catalog (`depictio/catalog/multiqc/cellranger.yaml`).
`plots:` / `selected_plot:` in `template.yaml` / `dashboards/base.yaml` are the bare MultiQC
**section** names (`Section.name`), not the plot's internal title:

- `Count - Summary stats`
- `Count - BC rank plot`
- `Count - Median genes`
- `Count - Saturation plot`

## Reproducing

```bash
python scripts/nfcore_megatest.py fetch --pipeline scrnaseq --version 4.2.0 --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/scrnaseq/4.2.0 --data-root <DATA_ROOT>
```
