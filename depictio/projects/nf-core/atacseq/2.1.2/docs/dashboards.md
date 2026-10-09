# nf-core/atacseq 2.1.2: Depictio dashboards

One dashboard: an **Overview**, then child tabs in three groups, read as a funnel from
library quality to the peaks the libraries agree on. The template follows the family rules
in `depictio/projects/nf-core/RULES.md` and is rebuilt from the nf-core/atacseq 1.2.2
dashboard: same groups, tab names and key-figure logic wherever the 2.x outputs allow.
What 2.x lost is the differential analysis: nf-core/atacseq 2.0 removed the DESeq2
contrasts, so there is no Differential accessibility tab and the PCA and distances of the
consensus counts move to the Consensus tab.

| Group | Tab | The question it answers |
|---|---|---|
| Data & QC | MultiQC | Did sequencing, alignment and filtering work for every library? |
| Data & QC | ATAC quality | Did transposition work, library by library? |
| Data & QC | Signal | How enriched and how complex is each library? |
| Peak calls | Peaks | How many peaks did each library yield, and how strong? |
| Peak calls | Annotation | Where do the peaks fall relative to genes? |
| Peak calls | Locus | What do the libraries call at one genomic region? |
| Comparison | Consensus | Which peaks do the libraries agree on? |

The design comes from the samplesheet the pipeline validated
(`pipeline_info/samplesheet.valid.csv`), which becomes the `sample_design` hub: one row per
merged library with its group, replicate, read type, control and merged-library name.
atacseq has no metadata file and so no `GROUP_COL`: every grouped tile and the group
filters read the hub's `group` column. `GENOME` (default `hg38`) is the only other
variable; it feeds the assembly of the Locus tracks and the run card.

> **Two MultiQC reports.** The release pins MultiQC 1.13, which writes no parquet. The
> collection binds the pipeline's own report when the run had MultiQC 1.31 or later swapped
> in (`multiqc/broad_peak/multiqc_data/`), or one regenerated with
> `python -m depictio.dev_scripts.multiqc_reprocess` (`multiqc/multiqc_data/`). Keep exactly
> one: the CLI ingests every parquet it finds as its own report. The two name their modules
> differently (the pipeline's report numbers a tool run at several levels: `picard-1`,
> `mlib_deeptools`; a reprocessed one keeps the plain ids), so the MultiQC tab binds the
> tiles both carry under one id, gives the fingerprint and the insert sizes one tile per
> report on the same slot, and keeps three tiles only a reprocessed report carries. The
> import prunes the tiles a report lacks.

> **This is the broad-peak route.** The peak files are `*_peaks.broadPeak` (no summit
> column), read by the catalog's `macs2/broad_peaks`. A `--narrow_peak` run is not bound,
> for the reason the nf-core/atacseq 1.2.2 template records: the dashboard binds the broad
> renders.

## Overview

The landing page, at compact width with the filter panel collapsed:

- **Hero**: what the run is, and a link to the run parameters. 2.x writes no
  `params.json`, so the dialog lists the software versions the run recorded.
- **About this dashboard** and **The run**: two cards side by side. The first says what the
  dashboard shows and how to move through it; the second lists the samples and groups, the
  sequenced libraries, the genome build and the peaks called, read from the run's tables.
- **Pipeline**: five steps (trim, align, call, annotate, merge). Each step opens the
  version of the tool that ran it and the tab that shows its output. The align step names
  Picard, which marks duplicates whatever the aligner.
- **Key figures**: four headline cards, each opening the tab that explains it. Samples
  (split by group), peaks called (the box shows the spread per library), the consensus
  intervals (the strip counts those that two libraries or more call against the rest) and
  the median FRiP score, its strip counting the libraries at the ENCODE target (30%), in the
  acceptable band (20%) and below it. A group and a sample filter above them narrow these
  four only; the consensus card reads a table with the libraries as columns, which they do
  not reach.
- **Findings**: result rows computed under the filters, each with a link to its tab: the
  fragment window most reads fall in and its share, the median fold enrichment of the
  peaks, the most common HOMER feature class and its share, and the consensus intervals
  called by more than one library. Below them, four figures in two rows, in the order of
  the rows: the fragment ladder beside the peak significance along the genome, then the
  peaks around the nearest start site beside a summary of the consensus. The ladder takes
  the place the volcano had in 1.2.2: it is the ATAC-specific check a reader looks at
  first. The summary counts the consensus intervals by how many libraries call them: the
  UpSet on the Consensus tab draws one set per library, too many for a third of the row.
  The three per-library highlights hide their legends. The bar of this section filters by
  group and chromosome.
- **How to read this dashboard**: one tile per tab, by group, each showing its question.

The persistent `Sample filters` (group, sample, replicate) sit in the collapsed left panel
and narrow every tab; `QC thresholds` (TSS enrichment, FRiP, peak count) sit collapsed under
them. The `Sample sheet` and `Reference tables` (the per-library peak QC rows) sections are
pinned to the bottom of every child tab, collapsed, and absent from the Overview.

## Child tabs

Each child tab opens with a short intro (the method, with a link to its tool, and how to
read the tab), then a strip of four key numbers, each card with its own colour and a
secondary that reads it, then at most three open sections; tables, details and alternate
routes follow, collapsed.

**MultiQC.** MultiQC panels only. Open: general statistics (reprocessed report), FastQC
sequence counts beside samtools percent mapped, then the deepTools fingerprint (one tile
per report on one slot), FRiP scores, peaks per library and featureCounts assignments
(reprocessed report). Collapsed `QC details`: per-base quality, Trim Galore kept reads,
Picard insert sizes (one tile per report on one slot) and duplicates, mapped reads per
contig and the ataqv mapping quality (reprocessed report). Its own `Library scope` filter
narrows the panels by sequencing library, read from the validated samplesheet.

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
divergence from a uniform library (distribution), the library size Picard estimates (box
plot) and the metagene signal at the start site (distribution). Then the fingerprint
scatter (the legend names the libraries; no point labels), Picard's duplication against
the reads left after it beside the deepTools metagene profile with the start site marked
and the gene body shaded. Picard makes no size estimate for single-end reads, so the
library-size card is the median of the paired-end libraries. The preseq complexity curve
with its 95% band sits in a collapsed section that only a run made with
`--skip_preseq false` keeps (2.x skips preseq by default). Filters: coverage concentration,
duplication rate and, with preseq, extrapolated depth.

**Peaks.** Strip: peaks in view (the chromosomes with the most), peak width (box plot), fold
enrichment (distribution) and the median -log10 q-value (threshold at 1.3, q 0.05). Then the
genome-wide significance panel, without point labels, and the width distribution on a log
axis. The MACS2 table is collapsed. Filters: significance, width and chromosome.

**Annotation.** Strip: annotated peaks (a ring by feature class), genes reached (by feature
class), the distance to the nearest start site (box plot) and the peak score. Then the
feature classes per library as 100% bars and the peaks around the nearest start site, with
the promoter window shaded. The collapsed `Peak annotation` holds the HOMER table with the
peak record card beside it: the card waits for a picked row. Filters: feature class and
distance to the start site.

**Locus.** Three collections on one genome axis. Strip: calls in the region (split by
library), libraries per consensus interval, feature classes and nearest genes; the cards
follow the region like the tracks. Then the navigator, a `genome_view` on the broad calls
with one lane per library and `assembly: {GENOME}`, opening on the first chromosome the
calls carry, and two follower tracks: the consensus intervals as high as their support,
and the HOMER annotation coloured by feature class (it stands in for a gene lane, which is
bundled for hg38 and mm10 only). Filters: significance, libraries per interval and feature
class.

**Consensus.** Strip: consensus intervals (by chromosome), libraries per interval (box
plot), peaks merged and the support of the strongest intervals (a ring). Then the UpSet of
the libraries calling each interval, and the sample space: the pipeline's DESeq2 PCA of the
consensus counts (coloured by group) and the library distance heatmap (`ward`, `Blues`), each full width. The
fold-enrichment heatmap over the strongest intervals, clustered, sits folded below them: it
grows to one row per interval. The four tables (intervals, fold enrichment, principal
components, distances) are collapsed. Filters: libraries per interval, peaks merged and
support.

## Routes and pruning

One peak route is bound (broad peaks, merged-library level). Optional collections and
report-specific tiles:

| Route | What changes |
|---|---|
| Default run (`--skip_preseq` true) | No preseq curve: the Complexity curve section and the extrapolated depth filter drop. |
| Run with `--skip_preseq false` | The Complexity curve section is kept, collapsed. |
| No replicated groups, or `--skip_deseq2_qc` | No PCA or distance heatmap; the Sample space section and its two tables drop. |
| Pipeline-written MultiQC report | The general statistics, featureCounts and ataqv mapping quality tiles drop; the fingerprint and insert sizes read `mlib_deeptools` and `picard-1`. |
| Reprocessed MultiQC report | The `mlib_deeptools` and `picard-1` tiles drop. |
| Control route (`control` in the samplesheet) | No change of layout: the controls are merged libraries of their own, marked `role: control` in the hub and the sample sheet. |

The import re-packs a section after a drop, so a lone tile takes the full row.

## Colours

`category_colors` is declared once, on the Overview, and read by every tab: the `group`
column is coloured `auto` (each value takes a colour-blind-safe colour at import, kept on a
re-import), and the HOMER feature classes and the ataqv fragment classes are written out.
Code figures read the same map and follow Analysis mode's groups when it has some.

## Cross-selection

Tables select rows; the signal against specificity scatter, the fingerprint scatter, the
duplication scatter and the metagene curves select libraries; the genome-wide panel and the
Locus tracks select peaks. A pick becomes a dashboard filter that narrows the other tiles of
the same collection and, through the project links, the collections downstream of it. The
design hub carries both spellings of a library (`sample` and `<sample>.mLb.clN`), so one
sample pick reaches the MultiQC panels, the ataqv, deepTools, Picard, preseq and peak QC
tables, the peak calls, the HOMER annotation and the DESeq2 QC tables. Picard names a
library after its duplicate-marked BAM, so the hub reaches it through a pattern link
(`{sample}.mLb.mkD.sorted`). The consensus matrices have the libraries as columns, so the
sample filters do not narrow them.

The link from the broad calls to the HOMER annotation on `peak_id` carries range filters as
a span, so the q-value and width sliders and a lasso on the Peaks tab narrow the HOMER tiles
too. On the Locus tab, two region links rename the navigator's chromosome and position
filters onto the consensus and HOMER tracks.

## Controls

Advanced visualisation controls dock by width: to the right of a full-width tile, on top
of a narrower one. Nothing is set per tab or per tile.

## Reproducing

No usable S3 megatest exists for 2.x (see `megatest.yaml`); the template was validated on
EMBL HPC runs of the `test`, `test_controls` and `test_full` profiles. For a run of your
own, point `--data-root` at its `--outdir` and pass the genome build it was aligned to:

```bash
# Only for a run made with the release's MultiQC 1.13:
python -m depictio.dev_scripts.multiqc_reprocess --src <DATA_ROOT> --dest <DATA_ROOT>
depictio-cli ingest --template nf-core/atacseq/2.1.2 --data-root <DATA_ROOT> --var GENOME=<build>
```

Without a MultiQC 1.31 or later parquet, `multiqc_data` finds nothing and the MultiQC tab is
empty. Never reprocess a run that already published one.
