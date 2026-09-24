# nf-core/differentialabundance 2.0.0: Depictio dashboards

This template turns the output of
[nf-core/differentialabundance](https://nf-co.re/differentialabundance) 2.0.0 into one
interactive Depictio dashboard with four tabs: Samples, Differential expression, Genome
view and Enrichment. The pipeline runs DESeq2 over a count
matrix and a contrast sheet; the template surfaces the per-contrast statistics, the gene
annotation joined onto them, and the variance-stabilised sample space the pipeline uses
for its own exploratory plots.

Scope: the DESeq2 route (`--differential_method deseq2`, the pipeline default). The
limma / propd / dream routes write differently named tables and are not bound.

## No MultiQC tab

differentialabundance runs no MultiQC. Its reporting is an R/shinyngs application, which
is not parquet-backed and therefore has nothing Depictio can read. There is no
`multiqc_data` data collection and no QC tab; the **Samples** tab carries the run-level
quality read instead (cohort size, group balance, library-size normalisation, and the
sample-distance matrix that exposes an outlier).

## Data source (AWS megatest)

```
s3://nf-core-awsmegatests/differentialabundance/results-30ed7741fc392127156c2fb10cfa3d69d216b54b
```

24 mouse RNA-seq samples (featureCounts matrix), two contrasts:

| Contrast | Comparison | Blocking | Significant calls (padj < 0.05, abs log2FC >= 1) |
|---|---|---|---|
| `Condition_genotype_WT_KO_study` | Condition genotype, WT vs KO | `batch` | 520 of 31,317 |
| `Condition_treatment_Control_Treated_study` | Condition treatment, Control vs Treated | none | 0 of 31,317 |

**The second contrast is deliberately kept.** A real analysis often returns nothing, and a
dashboard has to say so rather than look broken. Its volcano is a symmetric cloud with no
labelled points, its DA-barplot panel is empty, and its `_filtered` table on disk is a
header with no rows. The barplot description on the Differential expression tab says what an
empty panel means.

This run was launched with two parameter sets at once, so every table sits one directory
deeper than a normal run
(`tables/differential/deseq2_rnaseq_gsea,deseq2_rnaseq_gprofiler2/…`, comma included). The
template absorbs the difference: its scans match on file name and its recipe globs use
`**`, so a plain run and this one bind identically.

## Tabs

### 1. Samples

Is the experiment sound before any contrast is read?

* **Run at a glance** (pinned, every tab): samples split by group (donut), contrasts,
  features tested and the DESeq2 size-factor distribution (median with a Tukey box plot).
* **Sample space**: the sample PCA on the 500 most variable features, coloured by the
  sheet's leading factor with group centroids, then the Euclidean sample-to-sample
  distance matrix with dendrograms on both axes, then the per-sample expression
  distributions. Lassoing the PCA carries those samples to the distance matrix, the
  variance-stabilised heatmap and the distributions, through the PCA's own outgoing links.

  The distribution panel is the one a PCA cannot replace. A PCA says which libraries
  differ; a density curve says whether a library is *shaped* like the others at all, which
  is the question behind a normalisation problem. Features at the matrix floor are
  excluded from the shared grid and published as a share on their own.
* **Top variable features**: the 500 most variable features, row z-scored, clustered on
  both axes. It moved here from the former Expression tab. The matrix has no contrast
  column, so the pinned `Contrast scope` does not reach it.

#### Filtering by more than one factor

The ingest recipe publishes the next three factor-like columns of the sheet under stable
names (`factor_2`, `factor_3`, `factor_4`), so the persistent `Sample scope` can carry a
control for each without the template knowing what a given run's sheet calls them. All
three columns are always present: a sheet with fewer factors gets null values and the name
`none` in `factor_n_name`, so a one-factor study ingests against the same schema. Each alias
carries its source column name alongside it, and every column also keeps its own sanitised
name in the sheet.

![Samples](screenshots/samples.png)

### 2. Differential expression

All tab-local controls sit in one `Call scope` section (direction, biotype, thresholds).

* **Calls at a glance**: the up/down/not-significant split per contrast, the log2
  fold-change spread, the call composition, the median significance with a Tukey box plot
  and the best adjusted p-value against 0.05 (warning at 0.1).
* **Volcano, MA and QQ**: one `deseq2/volcano` tile with a view switch in its header
  (`views: [volcano, ma, qq]`, `p_value_col: pvalue`), cut at the pipeline's own thresholds
  (padj 0.05, two-fold change). The MA view reads `log2_base_mean` on x; the QQ view draws
  the raw p-values against the uniform null with a confidence band and the identity line.
  The separate QQ tile is gone.
* **Test diagnostics**: the raw p-value histogram, one panel per contrast (flat with a
  spike at zero is a well-specified test), and a code-mode scatter that pairs the first two
  contrasts gene by gene. Selecting a point carries its `gene_id` to the annotated table
  and to the pinned results table.
* **Effect by biotype** (moved from the former Expression tab): the biotype intro,
  `deseq2/annotated_da_barplot` (the largest effect sizes per contrast, one panel per
  contrast, so a null contrast reads as an empty panel) and a box plot of effect size
  within each biotype.
* **Gene detail**: the annotated calls with row selection on `gene_id` and, beside them, a gene
  record (`record_card`, `linked_component` on the table) that stays a thin rail until a row
  is picked, then follows the selection. The Ensembl identifier links
  out through `https://www.ensembl.org/id/`.

![Differential expression](screenshots/differential-expression.png)

### 3. Genome view

`Region scope` and `Signal scope` are open by default.

* **Calls on the genome**: genes placed by direction, the chromosome census, the
  significance spread and the best adjusted p-value against a 0.05 cut-off.
* **Signal along the genome**: the Manhattan plot, height `-log10(padj)`, threshold line
  at padj 0.05, selectable by `gene_id`.
* **Per-chromosome detail**: the lollipop panel gives each contrast a lane and each gene a
  head at its start coordinate, coloured by direction and sized by significance (pick a
  chromosome first, since coordinates from different contigs otherwise share one axis).
  The annotated volcano that used to sit below it duplicated the DE volcano and is gone.

![Genome view](screenshots/genome-view.png)

### 4. Enrichment

Which gene sets moved, and how much of each set carries the movement.

GSEA runs pre-ranked over the DESeq2 statistics and publishes one report per **pole** of
each contrast. Neither the contrast nor the pole is a column of any report: both live only
in the file name, so the recipe recovers them from the path and stacks every report into
one frame. That is why each panel splits on `phenotype` as well as on `contrast`.

* **Enrichment at a glance**: sets reported with their split by pole, the strongest
  absolute normalised enrichment score (the recipe adds an `abs_nes` column, so a strongly
  negative set counts as strong), the median FDR against a 0.05 cut-off, and the leading-edge
  share as a median with a Tukey box plot.
* **Enriched sets**: one dot per set on its normalised enrichment score, sized by how many
  of its genes were found in the ranked list and coloured by significance.
* **Scores side by side**: the same scores as bars grouped by contrast, which answers
  whether a set moved in both comparisons or only one.
* **Set table** (collapsed): one row per set and pole, selectable.

Read the **normalised** enrichment score, not the raw one: normalising for set size is what
makes a set of twenty comparable with a set of two hundred. An FDR q-value of zero is what
GSEA writes for anything below its own resolution, so the significance axis is clipped at
the smallest q-value the run actually resolved.

### Sample sheet (pinned, every tab)

Formerly `Observation sheet`. Every column of the pipeline's `--input` sheet with the DESeq2
size factor joined on, collapsed by default, persistent and pinned to every tab. The
template binds `sample_id`, `group` and `size_factor` by name and keeps whatever else the
sheet carried.

### Reference tables (pinned, every tab)

The full DESeq2 result set, collapsed by default and pinned to the bottom of every tab. The
results table carries row selection on `gene_id`.

## Cross-selection

A picked row or point becomes a dashboard filter that narrows the other tiles of its
collection and follows the project links to the collections they reach. The pinned sample
sheet selects on `sample_id` and so narrows the PCA, the distance matrix and the VST
panels; the PCA selects on `sample_id` too. The results tables, the contrast-against-contrast
scatter and the manhattan panel select on `gene_id`, and the GSEA table on `term`. The VST
distribution profile does not select: its collection has no outgoing link.

## Reading notes

* **`-log10(padj)` is capped at 300.** Five genes in the WT/KO contrast have a padj that
  underflowed to exactly 0 in the DESeq2 output; `-log10(0)` is infinite and no axis can
  place it. Those rows are drawn at 300, just short of the double-underflow limit, so they
  stay visible above every finite value (the largest of which is about 265). Points sitting
  exactly on 300 are "beyond measurement", not "measured at 300".
* **`padj` is null for about a third of the features.** That is DESeq2's independent
  filtering, not a defect: those features never reached the multiple-testing correction.
  They count as not significant and have no Manhattan or volcano height.
* **The annotated collections are shorter than the raw ones** (27,743 against 31,317 rows
  per contrast). Features the GTF did not place on the genome are dropped, since there is
  no coordinate to draw them at. Eleven of the 520 significant WT/KO calls are lost this
  way.
* **The sample filter stops at the sample-space collections.** A contrast pools its
  samples, so the differential tables have no sample column and nothing to filter on.
* **The contrast is a second pinned scope.** `Contrast scope` is sourced on
  `deseq2_results.contrast` and persistent, so one pick narrows the Differential expression,
  Genome view and Enrichment tabs at once: the template carries it onto the
  annotated table (`deseq2_results -> deseq2_results_annotated` on `contrast`) and onto the
  GSEA report. The tabs keep only their own local controls (direction, biotype, chromosome,
  pole, thresholds).

## Reproducing

```bash
bash depictio/projects/nf-core/differentialabundance/2.0.0/download_test_data.sh
# then follow post_fetch_help in megatest.yaml for the samplesheet and contrasts curls
depictio-cli run --template nf-core/differentialabundance/2.0.0 \
  --data-root ~/Data/depictio-nfcore/differentialabundance/2.0.0/megatest
```

`--project-name` is safe for `run` itself, but leave it off anyway. The dashboard carries
`project_tag: Differential Abundance Analysis`, and the standalone `depictio dashboard
import` resolves that tag by name, so a renamed project cannot take a re-imported
dashboard later.
