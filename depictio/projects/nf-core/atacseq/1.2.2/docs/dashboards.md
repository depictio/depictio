# nf-core/atacseq 1.2.2: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
library quality to the regions that change accessibility between design groups. The
template follows the family rules in `depictio/projects/nf-core/RULES.md`; its sibling
`nf-core/chipseq 1.2.0` shares the same groups, tab names and key-figure logic.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did sequencing, alignment and filtering work for every library? |
| Data & QC | ATAC quality | Did transposition work, library by library? |
| Data & QC | Signal | How enriched and how complex is each library? |
| Peak calls | Peaks | How many peaks did each library yield, and how strong? |
| Peak calls | Annotation | Where do the peaks fall relative to genes? |
| Peak calls | Locus | What do the libraries call at one genomic region? |
| Comparison | Consensus | Which peaks do the libraries agree on? |
| Comparison | Differential accessibility | Which regions change accessibility between groups? |

The design comes from the pipeline's own design sheet (`pipeline_info/design_reads.csv`),
which becomes the `sample_design` hub: one row per sample with its group, replicate and
merged-library name. atacseq has no metadata file and so no `GROUP_COL`: every grouped
tile and the group filters read the hub's `group` column. `GENOME` (default `hg38`) is the
only other variable; it feeds the assembly of the Locus tracks and the run card.

> **This template reads a REPROCESSED MultiQC report.** atacseq 1.2.2 is a DSL1 pipeline
> and the run published MultiQC 1.9, which writes no parquet. The MultiQC tab is bound to a
> report regenerated with the pinned MultiQC 1.35 over the run's raw tool outputs, which
> also adds the `ataqv` module 1.9 did not have. Read a `selected_plot` from
> `multiqc.list_plots()` on the regenerated parquet, never from the published HTML.

> **This is the broad-peak route.** The peak files are `*_peaks.broadPeak` (no summit
> column), read by the catalog's `macs2/broad_peaks`. There is no narrowPeak route variant:
> broad calls carry a `midpoint` where narrow ones carry a `summit`, and the dashboard binds
> the broad renders (AT-D15).

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters. DSL1 wrote no
  `params.json`, so the dialog lists the software versions the run recorded.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples and groups, the
  sequenced libraries, the genome build and the peaks called, read from the run's tables.
- **Pipeline**: six steps (trim, align, call, annotate, merge, test). Each step opens the
  version of the tool that ran it and the tab that shows its output.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by group), peaks called (the box shows the spread per library), the significant
  differential calls (split by direction) and the median FRiP score, its strip counting the
  libraries at the ENCODE target (30%), in the acceptable band (20%) and below it. A group
  and a sample filter above them narrow these four only.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  median fold enrichment of the peaks, the most common HOMER feature class and its share,
  the consensus intervals called by more than one library, and the interval tests DESeq2
  calls significant (one test per interval and contrast). Below them, four figures in two
  rows: the peak significance along the genome beside the peaks around the nearest start
  site, then a summary of the consensus beside the volcano. The summary counts the consensus
  intervals by how many libraries call them and links to the Consensus tab: the UpSet there
  draws one set per library, too many for a third of the row. Peak and interval ids are not
  drawn as point labels, and the two per-library highlights hide their legends. The bar of
  this section filters by group and chromosome.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, sample, replicate) sit in the collapsed left panel
and narrow every tab; `QC thresholds` (TSS enrichment, FRiP, peak count) sit collapsed under
them. The `Sample sheet` and `Reference tables` (the per-library peak QC rows) sections are
pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables and details follow,
collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics, FastQC sequence counts beside
samtools percent mapped (before and after filtering: `mLb.mkD` is duplicate-marked,
`mLb.clN` is what the peak caller sees), then the deepTools fingerprint, FRiP scores, peaks
per library and featureCounts assignments. Collapsed `QC details`: per-base quality,
Trim Galore kept reads, Picard insert sizes and duplicates, mapped reads per contig and the
ataqv mapping quality. Its own `Library scope` filter narrows the panels by sequencing
library.

**ATAC quality.** Strip: TSS enrichment (box plot), the lowest share of reads in peaks
(threshold at 20%), the mitochondrial fraction (box plot) and the duplicate fraction
(distribution). Then the coverage around start sites beside the signal against specificity
scatter (a lasso selects libraries), the fragment ladder with its own four cards (fragment
length, reads by nucleosome window, the sub- to mononucleosomal ratio, properly paired
reads as a box plot), the fragment ladder curve with the nucleosome-free (NFR) and
mono-nucleosome windows shaded, and the reads per fragment class, and the read
distribution matrix over the reference sequences. The ataqv table is collapsed. Filters:
fragment class, fragment length and reference sequence.

**Signal.** Strip: coverage concentration (the fingerprint area ratio, box plot), the
divergence from a uniform library (distribution), the distinct fragments preseq expects at a
billion reads (box plot) and the metagene signal at the start site (distribution). Then the
fingerprint scatter (the legend names the libraries; no point labels), the preseq
complexity curves with their 95% band and the deepTools metagene profile with the start site
marked and the gene body shaded. Filters: coverage concentration and extrapolated depth.

**Peaks.** Strip: peaks in view (the chromosomes with the most), peak width (box plot), fold
enrichment (distribution) and the median -log10 q-value (threshold at 1.3, q 0.05). Then the
genome-wide significance panel, without point labels, and the width distribution on a log
axis. The MACS2 table is
collapsed. Filters: significance, width and chromosome.

**Annotation.** Strip: annotated peaks (a ring by feature class), genes reached (by feature
class), the distance to the nearest start site (box plot) and the peak score. Then the
feature classes per library as 100% bars and the peaks around the nearest start site, with
the promoter window shaded. The collapsed `Peak annotation` holds the HOMER table with the
peak record card beside it: the card waits for a picked row. Filters: feature class and
distance to the start site.

**Locus.** Three collections on one genome axis. Strip: calls in the region (split by
library), libraries per consensus interval, feature classes and nearest genes; the
cards follow the region like the tracks. Then the navigator, a `genome_view` on the broad
calls with one lane per library and `assembly: {GENOME}`, and two follower tracks: the
consensus intervals as high as their support, and the HOMER annotation coloured by feature
class (it stands in for a gene lane, which is bundled for hg38 and mm10 only). Filters:
significance, libraries per interval and feature class.

**Consensus.** Strip: consensus intervals (by chromosome), libraries per interval (box
plot), peaks merged and the support of the strongest intervals (a ring). Then the UpSet of
the libraries calling each interval. The fold-enrichment heatmap over the strongest
intervals, clustered, sits folded below it: it grows to one row per interval and would take
the tab past its height. Both tables are collapsed. Filters: libraries per interval, peaks
merged and support.

**Differential accessibility.** Pick a contrast first. Strip: intervals tested (one test per
interval and contrast, split by outcome), significant calls (a ring by direction), the
effect size of the calls (box plot) and the strongest significance (threshold at 1.3). Then
the volcano, without point labels (the ids are interval ids), whose View switch reads the
same rows as an MA plot (`log2_base_mean`) or a QQ plot of the raw p-values, the ten largest
effects per contrast beside the calls per contrast, and the sample space: the pipeline's PCA on the
consensus counts beside the library distance heatmap (`ward`, `Blues`). The three tables
are collapsed. The `Contrast` filter is a single `Select`: the interval ids repeat in every
contrast, so a row is an interval only together with its contrast.

## Routes and pruning

A single route is bound (broad peaks, merged-library level). The DESeq2 QC tables are
optional:

| Route | What changes |
|---|---|
| No replicated groups | No PCA or distance heatmap; the Sample space section and its two tables drop. |

The import re-packs a grid after a drop, so a lone tile takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the `group`
column is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a
re-import), and the HOMER feature classes, the DESeq2 directions and the ataqv fragment
classes are written out. Code figures read the same map and follow Analysis mode's groups
when it has some.

## Cross-selection

Tables select rows; the signal against specificity scatter, the fingerprint scatter, the
complexity and metagene curves select libraries; the genome-wide panel and the Locus tracks
select peaks. A pick becomes a dashboard filter that narrows the other tiles of the same
collection and, through the project links, the collections downstream of it. The design
hub carries both spellings of a library (`sample` and `<sample>.mLb.clN`), so one sample
pick reaches the MultiQC panels, the ataqv, deepTools and preseq tables, the peak calls, the
HOMER annotation and, through a prefix link on the group, the DESeq2 contrasts. The
consensus matrices have the libraries as columns, so the sample filters do not narrow them.

The value link from the broad calls to the HOMER annotation on `peak_id` is disabled in
`template.yaml`: a range filter on the calls resolves through it as a handful of ids and
empties the HOMER tiles. A lasso on the Peaks tab therefore narrows the MACS2 tiles only;
the reverse link (HOMER to MACS2) still works. On the Locus tab, two region links rename
the navigator's chromosome and position filters onto the consensus and HOMER tracks, and
the navigator's own read is capped at about 10k rows ranked by q-value.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

The megatest `post_fetch_help` names the genome build the reference run was aligned to;
pass it as `GENOME`.

```bash
bash depictio/projects/nf-core/atacseq/1.2.2/download_test_data.sh <DATA_ROOT>
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/atacseq/1.2.2 --data-root <DATA_ROOT> --var GENOME=<build>
```

The reprocess step is mandatory: without it `multiqc_data` finds no parquet and the MultiQC
tab is empty. It is not idempotent for its provenance record, so keep the first
`REPROCESSED.json` or delete `multiqc/multiqc_data/` before re-running (AT-D7).
