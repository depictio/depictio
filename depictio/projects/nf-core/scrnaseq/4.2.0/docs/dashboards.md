# nf-core/scrnaseq 4.2.0 reference dashboard

Validated against the nf-core/scrnaseq 4.2.0 AWS megatest (one 10x v2 sample,
see `megatest.yaml`). `DATA_ROOT` is the results root, holding one directory
per `--aligner` route: `aligner_cellranger/` (required, the pipeline default,
the only route with matrices, secondary analysis and a MultiQC report),
`aligner_simpleaf/` and `aligner_kallisto/` (optional, tables-and-JSON only,
feed the Aligner concordance tab). `aligner_star/` publishes nothing this
dashboard reads.

## Template variables

| Variable | Required | What it does |
| --- | --- | --- |
| `DATA_ROOT` | yes | results root, one directory per `--aligner` route |
| `MARKER_PANEL` | no | comma-separated gene symbols the per-cell marker tiles always carry (Markers violin, gene UMAP Colour by menu) |

`MARKER_PANEL` replaces the PBMC panel earlier versions hardcoded. It is
forwarded to `cellranger/cell_expression.py` and
`cellranger/cell_expression_long.py` as their `marker_panel` transform param
(see `depictio/recipes/lib/scrnaseq_panels.py`). Without it, or when none of
its genes is in the reference (a mouse run typed with human symbols, for
example), the recipes fall back to the top markers of every graph-based
cluster from `cellranger_diffexp`: 5 per cluster in the wide matrix, 2 per
cluster (at most 24 genes) in the long table the violin reads. Neither recipe
raises on an empty intersection any more. A blood run would pass the lineage
markers it wants to see, for example
`--var MARKER_PANEL=CD3D,CD8A,MS4A1,CD14,LYZ,FCGR3A,NKG7,FCER1A,PPBP`.

Two readings stay human-specific and are documented rather than hidden: the
mitochondrial fraction and the MAD mito rule read gene symbols starting with
`MT-` (they read 0 on another organism, or on a reference without
mitochondrial genes, as the megatest's bundled GRCh38 is), and the cell-cycle
scores read the human Tirosh gene sets (the phase degrades to NA elsewhere).

## Funnel

1. **MultiQC** (landing tab): FastQC on the raw reads, then Cell Ranger
   count's own summary stats and its median-genes and saturation curves.
2. **Library QC**: five Cell Ranger metrics against 10x's own cut-offs,
   depth per cell, the mapping breakdown, and the full metrics table.
3. **Cell calling**: the filtering funnel, the barcode-rank ("knee") curve
   computed straight off the raw matrix, and CellBender's ambient-RNA
   accounting.
4. **Cell QC**: the MAD-based flag every other tab can filter on, rule by
   rule, including the mitochondrial rule.
5. **Embeddings**: UMAP and t-SNE by cluster, the UMAP coloured by any panel
   gene, gene dispersion and the PCA scree.
6. **Clusters**: cluster sizes, QC medians, composition per sample,
   cell-cycle phase, and stability across k-means resolutions.
7. **Markers**: marker dot plot, the markers cell by cell, and
   differential expression at any clustering resolution, with a gene
   record at the end of the tab.
8. **Compare selections**: lasso two groups of cells on the UMAP and test
   every panel gene between them.
9. **Aligner concordance** (optional): Cell Ranger against simpleaf/alevin-fry
   and kallisto|bustools, when the run used several routes.

Pinned on every tab: the "Run at a glance" strip (four cards: cells called,
median genes per cell, lowest sequencing saturation, lowest reads-in-cells
fraction), the collapsed sample sheet, the sample filter and the cell-level
QC filters (cluster, QC status, UMI counts, genes detected). The cluster
picked there narrows the cluster summary, marker expression, marker gene,
per-cell expression and cell-cycle tables through the `cluster_label`
cross-DC links. Every tab except MultiQC also carries its own open filter
section for the question that tab asks. Every tab sets
`advanced_viz_controls: header`, so colour-by and sort controls sit as chips
under each tile title.

Cell Ranger clusters each sample on its own, so `cluster_label` ("C1
top1/top2") names a population within its own sample. The Clusters and
Markers intros say so; on a multi-sample run, a label or a colour shared by
two samples is not the same population.

## Selection

Every scatter and embedding of cells selects on `barcode`, and the tables select
on their entity column (`sample_id` in the sample hub, `barcode` for cells,
`gene` for markers, `aligner` for routes, `barcode_core` for the cell-call
overlap). A pick narrows the other tiles on the same collection or linked to it;
the sample hub, pinned on every tab, narrows every collection through the
sample links. The Cell QC and Markers tabs each carry a record card beside the
table that drives it (`linked_component`): the card stays a thin rail until a
row or cell is picked, then shows that record. Tables whose collection nothing
else on the tab reads (library metrics, Cell Ranger metrics, calling funnel,
CellBender), the gene-coloured UMAP, the dispersion scatter, the volcano and
the knee plots do not select.

## Tab by tab

### MultiQC
MultiQC panels only, outside the pinned strip. Cell Ranger's own barcode-rank
panel is not shown: the Cell calling tab draws the same curve with the cell
and background barcodes coloured and the cutoff marked.

### Library QC
One section: five threshold cards (sequencing saturation, reads in cells,
valid barcodes, Q30 RNA, confidently mapped to the transcriptome), each the
lowest library against 10x's cut-off, then mean reads and median UMI per
cell as box plots, a count of the metric checks per QC band, and the
thresholded table. `Cells called` on the glance strip should track
`expected_cells` on the pinned sample sheet. The mapping breakdown is
grouped, not stacked, because `antisense` overlaps `exonic`/`intronic` by
Cell Ranger's own definition. Cell Ranger's full metrics table sits
collapsed at the end of the tab; it is no longer pinned on every tab.

The glance strip and the threshold cards read the same `_frac` columns on
the same 0 to 1 scale, and show the lowest library rather than a mean of
fractions.

### Cell calling
The funnel opens the tab: every barcode observed, called a cell, kept by
CellBender, passing the per-cell QC, each a subset of the one before. The
knee curve follows. The Ambient section keeps four CellBender cards (cells
found, fraction of counts removed, counts removed, found over expected) and
its metrics table. The found over expected ratio carries no verdict: a
ratio far above 1 is as much a warning as one below it, so the card shows
the per-library spread instead of a one-sided threshold.

### Cell QC
Rule cards first (low UMI, low genes, high top-20 share, high mito), then
the flagged share and the UMI, gene and mitochondrial distributions, then
the UMI vs genes scatter and the mito and depth box plots by cluster. The
MAD rules (sc-best-practices convention, per sample, on log1p values): 5 MAD
below the median for UMIs and genes, 5 MAD above for the top-20 share, and
median plus 3 MAD or 8% for the mitochondrial fraction.

### Embeddings
The cluster UMAP and the t-SNE side by side, under two PCA cards (the top
component's variance and the number of components reported). Depth and QC
status are one Colour by pick away on either tile, so they no longer get
tiles of their own. "Gene expression on the map" is the same UMAP bound to
`cellranger_cell_expression`, where every panel gene is a column of the
searchable Colour by menu; it opens coloured by cluster, no gene is
hardcoded.

"Feature selection" keeps the mean expression against normalised dispersion
scatter, coloured by detection rate. Cell Ranger's `features_selected.csv`
lists every gene with a finite dispersion, so it separates the genes Cell
Ranger could normalise from those it could not (undetected or constant), not
variable from non-variable genes; the old "kept for the PCA" filter was a
NaN toggle and is gone. The dispersion slider stays.

### Clusters
Four cards first (cells by cluster, flagged share and CellBender agreement
per cluster as box plots, median depth), then the QC-status bar per cluster
(its height is the cluster size), the cluster QC heatmap, the composition
per sample and the cluster table. The heatmap is column-z-scored: each
metric (median UMIs, median genes, flagged share, CellBender share) is
centred across clusters, so mixed units no longer make every row read "UMI
high". The stability sankey reads graphclust, kmeans_6 and kmeans_10, the
resolutions Cell Ranger computes by default.

"Cell cycle": S and G2/M scores from the Tirosh gene sets, each the cell's
mean log1p(CP10k) over the set minus its mean over every measured gene; the
larger positive score wins, otherwise G1. The "Cycling cells" card counts
cells whose G2/M score is at least 0.05 (a documented default, a little
above the 0 the phase call uses), broken down by cluster.

### Markers
The Clustering resolution filter opens on `graphclust`. "Marker
expression": two cards (mean expression and detection rate of the markers,
as box plots), the dot plot and its table. "Per-cell marker spread": the
violin is faceted by gene, one panel per marker gene of the long table, so
it reads without a gene picked; the Gene filter narrows it to one panel.
The box per gene sits below it.

"Differential expression": four cards (significant markers, adjusted p-value
below 0.05, counted per cluster; log2 fold change; adjusted p-value; mean
counts) and the volcano. The volcano keeps the volcano
view only: these are Cell Ranger's top-ranked markers per cluster, not a
genome-wide test, so a QQ plot has no null to compare against. "Gene
detail" closes the tab: the marker table with a record card beside it (no
hardcoded default). Ticking a row of the table fills the card with
that gene, one row per clustering where it ranks as a marker. Its Ensembl link uses the species-agnostic
`https://www.ensembl.org/Multi/Search/Results?q={gene_id}` search.

### Compare selections
Lasso a set of cells on the UMAP, save it as group A, lasso a second set as
group B, and read the volcano. With no groups saved, the comparison opens on
the two largest clusters (the renderer's automatic pair; the template no
longer names cluster labels). Each gene is tested with a Wilcoxon rank-sum
on the log1p(CP10k) values, FDR-corrected across genes, and the result is
cached server-side. The guard cards say what the comparison is run over:
cells on the map, their QC status (narrow to `pass` first), their depth
(two groups of very different depth differ on almost every gene for the
wrong reason), and the marker panel size.

### Aligner concordance (optional)
A Cell Ranger-only run (the pipeline default) leaves every tile on this tab
empty; every collection feeding it is optional. When simpleaf and/or
kallisto were also run, the cards compare cells called, CellBender cells,
median UMI per cell and mapping rate per route; the UpSet plot shows how
the routes' cell calls (plus CellBender on each) agree on the same physical
barcode, normalised to the bare 16-mer; the two knee curves share log-log
axes.

`simpleaf_cellbender_metrics` and `kallisto_cellbender_metrics` now run
pipeline-local recipes (`nf-core/scrnaseq/simpleaf_cellbender_metrics.py`,
`nf-core/scrnaseq/kallisto_cellbender_metrics.py`) that reuse the catalog
`cellbender/metrics.py` transform on the route's own raw scan. The catalog
recipe's fixed `dc_ref` made both collections copies of the Cell Ranger
route's CellBender numbers, which is why the three routes showed the same
CellBender cell count.

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
| `cellranger_cell_expression` | 8 767 x 102 | one row per cell, one Float64 column per panel gene (`MARKER_PANEL`, the top 5 markers per cluster and the most dispersed genes; 96 here without `MARKER_PANEL`), plus the UMAP coordinates, cluster and QC status |
| `cellranger_cell_expression_long` | 49 896 | the marker-panel slice (`MARKER_PANEL`, else the top 2 markers per cluster, at most 24 genes), melted to one row per (cell, gene), capped per cluster so a violin stays drawable |
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
