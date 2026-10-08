# nf-core/chipseq 1.2.0: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
library quality to the regions bound differently between conditions. The template follows
the family rules in `depictio/projects/nf-core/RULES.md`; its sibling `nf-core/atacseq
1.2.2` shares the same groups, tab names and key-figure logic.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did sequencing, alignment and filtering work for every library? |
| Data & QC | Signal | How enriched and how complex is each library? |
| Peak calls | Peaks | How many peaks did each library yield, and how strong? |
| Peak calls | Annotation | Where do the peaks fall relative to genes? |
| Peak calls | Locus | What do the libraries call at one genomic region? |
| Comparison | Consensus | Which peaks do the libraries agree on? |
| Comparison | Differential binding | Which regions change binding between conditions? |

The `design` hub is a recipe (`nf-core/chipseq/design_factors.py`): one row per library,
the ChIPs and their input controls, with `role`, `antibody`, `replicate` and `condition`.
`condition` is the `GROUP_COL` column of the optional design table (`METADATA_FILE`) and,
without one, the design sheet group; the hub column is always called `condition`, so the
dashboard reads it literally and works with or without the table. `GENOME` (default `hg38`)
feeds the assembly of the Locus tracks and the run card.

> **This template reads a REPROCESSED MultiQC report.** chipseq 1.2.0 is a DSL1 pipeline
> and the run published MultiQC 1.9, which writes no parquet. The MultiQC tab is bound to a
> report regenerated with the pinned MultiQC 1.35 over the run's raw tool outputs. Read a
> `selected_plot` from `multiqc.list_plots()` on the regenerated parquet, never from the
> published HTML.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters. DSL1 wrote no
  `params.json`, so the dialog lists the software versions the run recorded.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the libraries and ChIPs, the
  antibodies and conditions, the genome build and the peaks called, read from the run's
  tables.
- **Pipeline**: six steps (trim, align, call, annotate, merge, test). Each step opens the
  version of the tool that ran it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Libraries
  (split by condition), peaks called (the box shows the spread per ChIP), the significant
  differential calls (split by direction) and the median FRiP score, its strip counting the
  ChIPs at or above the ENCODE floor of 1%. A condition and a library filter above them
  narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  median fold enrichment at the summits, the most common HOMER feature class and its share,
  the consensus intervals called by more than one library, and the interval tests DESeq2
  calls significant (one test per interval and contrast). Below them, four figures in two
  rows: the peak significance along the genome beside the peaks around the nearest start
  site, then a summary of the consensus beside the volcano. The summary counts each
  antibody's consensus intervals by how many of its libraries call them and links to the
  Consensus tab: the UpSet there draws the libraries of every antibody, too many sets for a
  third of the row. Peak and interval ids are not drawn as point labels, and the two
  per-library highlights hide their legends. The bar of this section filters by condition
  and antibody.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (condition, antibody, library, replicate, role) sit in the
collapsed left panel and narrow every tab; `QC thresholds` (FRiP, peak count) sit collapsed
under them. The `Sample sheet` and `Reference tables` (the per-ChIP peak QC rows) sections
are pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables and details follow,
collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, FastQC sequence counts beside
samtools percent mapped, then the deepTools fingerprint, FRiP scores and the NSC and RSC
strand coefficients. Collapsed `QC details`: per-base quality, Trim Galore kept reads, Picard
duplicates, featureCounts assignments and the strand shift correlation curve. Its own
`Library scope` filter narrows the panels by sequencing library (`<sample>_T<n>`).

**Signal.** Strip: coverage concentration (the fingerprint area ratio, box plot), the
divergence from the input (distribution), the share of the genome called enriched
(distribution) and the distinct fragments preseq expects at a billion reads (box plot). Then
the fingerprint scatter (only the ChIPs carry a point: both axes are measured against the
input; the legend names them, with no point labels), then, one per row so their legends of
every ChIP and input wrap under the plot, the preseq complexity curves with their 95% band
and the deepTools metagene profile with the start site marked and the gene body shaded. Filters: genome called enriched and extrapolated
depth.

**Peaks.** Strip: peaks in view (the chromosomes with the most), peak width (box plot), fold
enrichment (distribution) and the median -log10 q-value (box plot: MACS2 calls at q 0.05, so
every call passes that line). Then the genome-wide significance panel, without point labels, the width distribution on a log axis, and the two summit
profiles: the other libraries' summits around each summit (replicates of a sharp factor
pile up) beside the average footprint of a call. Neither profile is a read coverage: the
recipe aggregates the calls themselves. The MACS2 table is collapsed. Filters: significance,
fold enrichment, width and chromosome.

**Annotation.** Strip: annotated peaks (a ring by feature class), genes reached (by feature
class), the distance to the nearest start site (box plot) and the peak score. Then the
feature classes per library as 100% bars and the peaks around the nearest start site, with
the promoter window shaded. The collapsed `Peak annotation` holds the HOMER table with the
peak record card beside it: the card waits for a picked row. Filters: feature class and
distance to the start site.

**Locus.** Three collections on one genome axis. Strip: calls in the region (split by
library), libraries per consensus interval, feature classes and nearest genes; the
cards follow the region like the tracks. Then the navigator (`macs2/peak_genome_view`, one
lane per library, `assembly: {GENOME}`), a coverage track of the consensus intervals with
one lane per consensus set, and the HOMER annotation coloured by feature class (it stands in
for a gene lane, which is bundled for hg38 and mm10 only, so the locus field takes
coordinates, not gene symbols). Filters: significance, libraries per interval and feature
class.

**Consensus.** Pick one consensus set first: the libraries of two antibodies never meet.
Strip: consensus intervals (by consensus set), libraries per interval (box plot), peaks
merged and the support of the strongest intervals (a ring). Then the UpSet of the libraries
calling each interval. The fold-enrichment heatmap over the 250 strongest intervals of each
set, clustered, rows annotated by set and support, sits folded below it: it grows to one row
per interval and would take the tab past its height. Both tables are collapsed. Filters:
consensus set, libraries per interval and chromosome.

**Differential binding.** Pick a contrast first. Strip: intervals tested (one test per
interval and contrast, split by outcome), significant calls (a ring by direction), the
effect size of the calls (box plot) and the strongest significance (threshold at 1.3). Then
the volcano, without point labels (the ids are interval ids), whose View switch reads the
same rows as an MA plot (`log2_base_mean`) or a QQ plot of the raw p-values, the ten largest
effects per contrast beside the calls per contrast, and the sample space:
the pipeline's PCA, coloured by consensus set, beside the library distance heatmap (`ward`,
`Blues`). The three tables are collapsed. The `Contrast` filter is a single `Select`: DESeq2
numbers the intervals afresh in each consensus set, so a row is an interval only together
with its contrast.

chipseq writes one count matrix, and so one PCA and one distance matrix, per antibody. The
distance matrix is block diagonal, and the PCA uses a pipeline-local recipe
(`nf-core/chipseq/deseq2_qc_pca.py`) that resolves the components per matrix while keeping
the catalog output's columns.

## Routes and pruning

| Route | What changes |
|---|---|
| No `METADATA_FILE` | The `metadata` collection is pruned; `condition` falls back to the design sheet group. No tile changes. |

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: `condition` and
`antibody` are coloured `auto` (each value takes a colour-blind-safe colour at import, kept
on a re-import), and the library roles, the HOMER feature classes and the DESeq2 directions
are written out. Code figures read the same map and follow Analysis mode's groups when it
has some.

## Cross-selection

Tables select rows; the fingerprint scatter, the complexity, metagene and summit curves
select libraries; the genome-wide panel and the Locus tracks select peaks. A pick becomes a
dashboard filter that narrows the other tiles of the same collection and, through the
project links, the collections downstream of it. The hub reaches the MultiQC panels, the
peak calls and summary, the HOMER annotation and the signal tables on the library id; the
consensus sets, the DESeq2 contrasts and the PCA have no library column, so the antibody
reaches them through a prefix (`wildcard`) link on the set or contrast name. The MACS2 and
HOMER peak tables are linked both ways on `peak_id`, and a consensus interval links to its
DESeq2 rows on `interval_id`. On the Locus tab, two region links rename the navigator's
chromosome and position filters onto the consensus and HOMER tracks.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

The megatest `post_fetch_help` names the genome build and the design table of the reference
run; the vendored table is `input/sample_metadata.tsv`.

```bash
bash depictio/projects/nf-core/chipseq/1.2.0/download_test_data.sh
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
mkdir -p <DATA_ROOT>/input
cp depictio/projects/nf-core/chipseq/1.2.0/input/sample_metadata.tsv <DATA_ROOT>/input/
depictio-cli ingest --template nf-core/chipseq/1.2.0 --data-root <DATA_ROOT> \
  --var GENOME=<build> --var METADATA_FILE=<DATA_ROOT>/input/sample_metadata.tsv
```

The reprocess step is mandatory: without it `multiqc_data` finds no parquet and the MultiQC
tab is empty. Do not re-run it over a directory that already holds the regenerated parquet.
Do not pass `--project-name`: the dashboard's `project_tag` is resolved by project name, so
a renamed project breaks a later `depictio dashboard import`.
