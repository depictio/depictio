# nf-core/smrnaseq 2.4.1: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from the
libraries to the miRNAs they hold and the new ones they suggest. The layout follows the
family rules in `depictio/projects/nf-core/RULES.md`, with `ampliseq/2.18.0` as the
reference.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did the adapter come off and the reads map? |
| Data & QC | Library QC | Is each library a small RNA library, and a clean one? |
| Expression | miRNA Expression | Which miRNAs does each library express, and how much? |
| Expression | Group Comparison | Which libraries look alike, and which miRNAs separate two groups? |
| Sequences | isomiRs | How far do the reads stray from the reference sequence? |
| Sequences | Novel miRNAs | Which new miRNAs does miRDeep2 propose, and how credible are they? |

The library is the unit of QC and the miRNA the unit of analysis. `samples`, one row per
library, is the hub: it is always present, carries the miRNA depth, the miRTrace composition
and the miRDeep2 call counts of each library, and links on `sample` to every sample-keyed
collection. The pipeline samplesheet has no design column, so the design comes from an
optional table (`METADATA_FILE`, the ampliseq convention): when given, it sends the same
links and lends its factors to the hub, and `GROUP_COL` (its first factor by default) colours
and splits the figures. The per-miRNA and per-precursor collections (`mirtop_mirna_summary`,
`mirtop_isomir_landscape`, `mirdeep2_novel_precursors`) aggregate over libraries, so the
sample filters do not reach them.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the run's facts (samples,
  genome, miRTrace species, the read length window, the miRNAs with reads), read from the run
  parameters and the collections.
- **Pipeline**: six steps (trim, profile, count, compare, annotate, discover). Each step opens
  the parameters that drive it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples (split
  by the design group), the median miRNAs detected per library (with its spread), the median
  share of miRNA reads on the reference sequence and the novel precursors miRDeep2 proposes
  (split by whether the star arm has reads). A group and a sample filter above them narrow
  these four only.
- **Findings**: result rows whose values are computed under the filters, each with a link to
  its tab: the miRNA share of the median library, the share of miRNA reads the leading miRNA
  takes, the share of miRNA reads trimmed short of the reference 3' end, and the novel
  precursors with star-arm reads. Below them, four figures in two rows, each linking its tab:
  the top miRNAs by group beside the library PCA, then the novel precursor plane beside the
  isomiR composition. The bar of this section filters by group and sample.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (the design group, then the sample) sit in the collapsed left
panel and narrow every tab. The group filter reads the design table and is pruned with it;
the sample filter reads the hub. The `Sample sheet` section, with the design table and the
library summary, is pinned to the bottom of every child tab, collapsed, and absent from the
Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of key numbers, each card with its own colour and a secondary
that reads it (a box plot, a distribution, a bar out of 100, a ranking or a share), then at
most three open sections; tables and details follow, collapsed.

**MultiQC.** MultiQC panels only. Open: fastp's filtered reads beside the trimmed read
length, miRTrace's read QC beside mirtop's isomiR read counts, then samtools' mapping rate at
full width. Collapsed: the distinct isomiR sequences, the raw FastQC counts and adapter
content, fastp's base quality, the post-trim FastQC status (MultiQC anchors the second FastQC
pass as `fastqc-1`), the mean isomiR read counts and samtools' alignment statistics, one
violin row per metric and too dense for a half-width tile. Its own sample filter reads the
MultiQC report.

**Library QC.** miRTrace's view of every library. Strip: the median miRNA share of a library
(a bar out of 100), the median rRNA share (a box), the reads on miRNAs (the deepest libraries ranked)
and the most miRNAs a library reaches at full depth (the libraries ranked). Then the read
length profile, the miRNA window shaded, beside the complexity curves; the composition bars
(RNA type, read QC outcome, organism clade); and the parallel coordinates of the
per-library measures (the miRDeep2 counts stay on the record card: a null axis would drop
every line on a run without miRDeep2). Collapsed: depth against miRNA share, one point per library coloured by
its main clade, beside the record of the picked library. Filters: miRNA depth, miRNAs
detected, and the miRNA, rRNA, tRNA and main-clade shares.

**miRNA Expression.** mirtop's counts, scaled to counts per million miRNA reads. Strip: the
miRNAs with reads (spread by their mean expression), the miRNA reads (split by group), the
median miRNAs at 10 CPM or more per library (a box) and the median number of libraries
detecting a miRNA (its distribution). Then the clustered heatmap of the most variable
miRNAs, the boxes of the twelve most expressed miRNAs by group, and the mean-variance plane,
unlabelled, beside the record of the picked miRNA, linked to miRBase. Collapsed: the
miRNA table. Filters: miRNA, mean expression and detection breadth.

**Group Comparison.** Two cards rather than four: the libraries compared (split by group)
and their miRNA depth (a box), the two things to check before trusting a separation. Then
the library PCA, coloured by group, where a lasso saves a set of points as a group, and the
volcano of a Wilcoxon rank-sum test between two groups, corrected for multiple testing. The
volcano opens on the first two groups of the design column and runs at once. The pipeline
publishes no model-based test in this release, so the tab presents the volcano as a
screen. Filters: miRNAs at 10 CPM or more, and the first component.

**isomiRs.** mirtop's isomiR classes. Strip: the median share of a library's miRNA reads on
the reference sequence (a box), the median isomiRs of an expressed miRNA in a library (its
distribution), the miRNA reads by 3' end (a ring) and the reads with a non-templated 3'
addition (the added bases ranked). Then the isomiR composition of each library, opening on the 3' end with the
other partitions a switch away, and the landscape of isomiR classes over the 40 most
expressed miRNAs. Collapsed: the landscape table. Filters: isomiR class and reference share.

**Novel miRNAs.** miRDeep2's predictions. Strip: the novel precursors merged across libraries
(a ring by star-arm reads), the median libraries reporting one (a box), the median
true-positive estimate (its distribution) and every call (split into novel and known). Then
miRDeep2's signal-to-noise curve beside its known-precursor recovery curve, both by score
cutoff, and the plane of recurrence against the true-positive estimate beside the record of
the picked precursor, linked to the UCSC browser on `{GENOME}`. The plane and the strip read
the estimate rather than the raw score, which is unbounded: one hairpin far above the rest
flattens every other point. Collapsed: the precursor table and every per-library call.
Filters: libraries reporting, true-positive estimate and star-arm reads.

## Routes and pruning

| Route | What changes |
|---|---|
| no `METADATA_FILE` | No design table, group filters or design colours; the figures draw one colour and the group splits fall away. |
| `SKIP_MULTIQC` | No MultiQC tab, miRTrace cards, length, complexity or composition figures, nor the miRNA share row. |
| `SKIP_MIRDEEP` | No Novel miRNAs tab, novel key figure, novel row or highlight; the Key figures keep three cards. |

The import re-packs the Overview grid after a drop, so a lone highlight takes the full row.
The cards and figures on the hub keep working on every route.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab. The design group
is coloured `auto`. miRTrace's RNA types (miRNA, rRNA, tRNA, artifact, unknown), the
precursor arm, the reference isoform, star-arm support and miRDeep2's novel and known calls
are written out; the read QC outcomes, clades and isomiR classes share the `taxon` column and
take the palette by abundance. The code figure of the top miRNAs reads the same map and
follows Analysis mode's groups when it has some.

## Cross-selection

Tables select rows and the planes and curves select points; a pick becomes a dashboard filter
that narrows the other tiles of the same collection and, through the project links, the
collections downstream of it. Selection is on `sample` in the sample sheet, the length and
complexity curves, the PCA and the library plane, on `mirna` in the miRNA and landscape
tables and the mean-variance plane, and on `precursor_id` in the precursor table and plane. A
miRNA picked on the plane narrows the per-library counts behind the boxes and the isomiR
landscape; each record card follows the plane beside it and waits for a pick.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top of
a narrower one. Nothing is set per tab or per tile.

## Catalog modules

| Tool | Output | Read by |
|---|---|---|
| `multiqc` | `mirtrace_composition`, `mirtrace_length`, `mirtrace_complexity` | Library QC, Overview |
| `mirtop` | `mirna_counts`, `mirna_summary`, `top_variable_heatmap` | miRNA Expression, Overview |
| `mirtop` | `sample_pca`, `sample_matrix` | Group Comparison, Overview |
| `mirtop` | `isomir_composition`, `isomir_landscape` | isomiRs, Overview |
| `mirdeep2` | `predictions`, `novel_precursors`, `score_summary` | Novel miRNAs, Overview |

The MultiQC panels use the shared `multiqc/fastp`, `fastqc`, `mirtrace`, `mirtop` and
`samtools` entries; the hub is the template recipe `nf-core/smrnaseq/samples.py`.

## Reproducing

The megatest publishes no design table. The one bundled as `input/sample_metadata.tsv` was
built once from the test-datasets samplesheet (vendored as `input/samplesheet.csv`), and the
template's reference variables point at it.

```bash
python scripts/nfcore_megatest.py fetch --pipeline smrnaseq --version 2.4.1 --dest <DATA_ROOT>
mkdir -p <DATA_ROOT>/input && cp depictio/projects/nf-core/smrnaseq/2.4.1/input/* <DATA_ROOT>/input/
depictio-cli ingest --template nf-core/smrnaseq/2.4.1 --data-root <DATA_ROOT> \
  --var METADATA_FILE=<DATA_ROOT>/input/sample_metadata.tsv
```

A run that skipped a step adds the matching variable, for example `--var SKIP_MIRDEEP=true`.
The megatest publishes no mature or hairpin count matrices and no edgeR tables, so expression
is aggregated from the mirtop joined isomiR table, and miRTrace's numbers are read back from
the MultiQC plot input. `VALIDATION_REPORT.md` next to this file records the ingestion numbers
and the discrepancies found while validating.
